"""Phase 3c (engine): xóa theo phạm vi, tự xóa theo ngày, cài đặt, tạm dừng ghi."""

import pytest

from clipvault.engine import retention
from clipvault.engine.capture import CaptureController
from clipvault.engine.history import DELETE_SCOPES, HistoryError
from clipvault.engine.settings import AppSettings, SettingsError, SettingsStore, parse_int, validate

from conftest import INLINE_MAX, png_rep, query, snap, text_rep
from test_capture import FakeNotifier, FakeReader

DAY_MS = 86_400_000


@pytest.fixture
def seeded(service, db):
    """Mỗi loại một mục thường + một mục ghim; ảnh lớn để có blob file ngoài."""
    def add(*reps):
        return service.process(snap(*reps)).item_id

    ids = {
        "text": add(text_rep("plain words here")),
        "link": add(text_rep("https://example.com/a")),
        "code": add(text_rep("def f(x):\n    return x\n")),
        "other": add(text_rep("#ff8800")),
        "image": add(png_rep(INLINE_MAX + 100, seed=1)),
        "text_pinned": add(text_rep("pinned plain words")),
        "image_pinned": add(png_rep(INLINE_MAX + 100, seed=2)),
    }
    db.set_pinned(ids["text_pinned"], True)
    db.set_pinned(ids["image_pinned"], True)
    return ids


def _remaining(db):
    return set(db.all_item_ids())


def _consistent(db, data_dir):
    """Không còn blob/representation/tag mồ côi và file ngoài khớp đúng bảng blobs."""
    assert query(db, "SELECT COUNT(*) FROM representations WHERE item_id NOT IN (SELECT id FROM items)")[0][0] == 0
    assert query(db, "SELECT COUNT(*) FROM tags WHERE item_id NOT IN (SELECT id FROM items)")[0][0] == 0
    assert query(db, "SELECT COUNT(*) FROM blobs WHERE hash NOT IN (SELECT blob_hash FROM representations)")[0][0] == 0
    files = {p.name for p in (data_dir / "blobs").rglob("*") if p.is_file()}
    assert files == db.external_hashes()


@pytest.mark.parametrize("scope", ["text", "image", "link", "code", "other"])
def test_scope_deletes_only_that_category_and_keeps_pinned(history, seeded, db, data_dir, scope):
    cat_ids = {i.id for i in db.query_items(category=scope, limit=100)}
    pinned = {seeded["text_pinned"], seeded["image_pinned"]}
    before = _remaining(db)
    deleted = history.delete_scope(scope, include_pinned=False)
    assert deleted == len(cat_ids - pinned)
    assert _remaining(db) == before - (cat_ids - pinned)
    assert pinned <= _remaining(db)  # mục ghim còn nguyên
    _consistent(db, data_dir)


@pytest.mark.parametrize("scope", ["text", "image"])
def test_scope_with_include_pinned_removes_pinned_too(history, seeded, db, data_dir, scope):
    cat_ids = {i.id for i in db.query_items(category=scope, limit=100)}
    history.delete_scope(scope, include_pinned=True)
    assert not (cat_ids & _remaining(db))
    _consistent(db, data_dir)


def test_delete_all_keeps_pinned_by_default_and_all_when_included(history, seeded, db, data_dir):
    history.delete_scope("all", include_pinned=False)
    assert _remaining(db) == {seeded["text_pinned"], seeded["image_pinned"]}
    _consistent(db, data_dir)
    history.delete_scope("all", include_pinned=True)
    assert _remaining(db) == set() and db.stats().blob_bytes == 0
    assert list((data_dir / "blobs").rglob("*.*")) == []
    _consistent(db, data_dir)


def test_deleting_image_removes_its_blob_file(history, seeded, db, data_dir):
    h = query(db, "SELECT blob_hash FROM representations WHERE item_id = ?", (seeded["image"],))[0][0]
    path = db.blobs.path_for(bytes(h).hex())
    assert path.is_file()
    history.delete_scope("image", include_pinned=False)
    assert not path.exists()


def test_shared_blob_survives_when_another_item_uses_it(history, service, db):
    shared = png_rep(INLINE_MAX + 50, seed=9)
    a = service.process(snap(shared)).item_id
    b = service.process(snap(shared, text_rep("extra"))).item_id  # mục khác, cùng blob ảnh
    db.change_category(b, "other")
    history.delete_scope("image", include_pinned=False)
    assert a not in _remaining(db) and b in _remaining(db)
    assert db.representations(b, "PNG")[0] == shared  # file blob vẫn còn đọc được


def test_scope_summary_matches_what_gets_deleted(history, seeded, db):
    count, size = history.scope_summary("all", include_pinned=False)
    assert count == 5 and size > 0
    assert history.scope_summary("all", include_pinned=True)[0] == 7
    assert history.delete_scope("all", include_pinned=False) == count


def test_summary_alone_deletes_nothing_and_bad_scope_rejected(history, seeded, db):
    before = _remaining(db)
    history.scope_summary("all", True)  # "hủy xác nhận" chỉ dừng ở bước xem trước
    assert _remaining(db) == before
    with pytest.raises(HistoryError):
        history.delete_scope("bogus", True)
    assert set(DELETE_SCOPES) == {"text", "image", "link", "code", "other", "all"}


def test_failed_delete_rolls_back_everything(history, seeded, db, monkeypatch):
    before = _remaining(db)
    orig = db._conn

    class Boom:
        def execute(self, sql, *a):
            if sql.startswith("DELETE FROM blobs"):
                raise __import__("sqlite3").OperationalError("boom")
            return orig.execute(sql, *a)

    monkeypatch.setattr(db, "_conn", Boom())
    with pytest.raises(HistoryError):
        history.delete_scope("all", include_pinned=True)
    monkeypatch.setattr(db, "_conn", orig)
    assert _remaining(db) == before


# --- tự xóa theo ngày -------------------------------------------------------------------------------------


def test_age_purge_skips_pinned_and_recent(service, db, history):
    old_clock = [1_000]
    service.clock = lambda: old_clock[0]
    old = service.process(snap(text_rep("old one"))).item_id
    old_pinned = service.process(snap(text_rep("old pinned"))).item_id
    db.set_pinned(old_pinned, True)
    now = 100 * DAY_MS
    old_clock[0] = now - 2 * DAY_MS
    recent = service.process(snap(text_rep("recent"))).item_id
    assert history.count_expired(30, now) == 1
    assert history.purge_expired(30, now) == 1
    assert _remaining(db) == {old_pinned, recent} and old not in _remaining(db)
    assert retention.purge_older_than(db, 0, now) == 0  # 0 = tắt


# --- cài đặt: lưu, đọc lại, kiểm tra hợp lệ, reset ------------------------------------------------------------


def test_settings_roundtrip(db):
    store = SettingsStore(db)
    assert store.load() == AppSettings()  # lần đầu: mặc định, theme theo hệ thống
    assert store.load().theme == "system"
    saved = store.save(theme="light", font_size="large", density="compact", max_items=123, max_total_mb=64,
                       retention_days=7, close_to_tray=False, confirm_delete=True, paused=True)
    assert SettingsStore(db).load() == saved
    assert db.settings()["limits.max_total_bytes"] == str(64 * 1024 * 1024)  # cùng khóa Limits.from_settings


@pytest.mark.parametrize("field,value", [
    ("max_items", ""), ("max_items", "   "), ("max_items", "-5"), ("max_items", "0"), ("max_items", "abc"),
    ("max_items", "1e3"), ("max_items", "10_000"), ("max_items", "99999999999"), ("max_items", "1.5"),
    ("max_total_mb", "-1"), ("max_total_mb", "99999999999999"), ("retention_days", "-1"),
    ("retention_days", "100000"), ("retention_days", ""), ("theme", "neon"), ("font_size", "huge"),
    ("density", "x"), ("paused", "yes"), ("nonexistent", 1),
])
def test_invalid_values_rejected_and_nothing_written(db, field, value):
    store = SettingsStore(db)
    with pytest.raises(SettingsError):
        store.save(**{"density": "compact", **{field: value}})  # giá trị đúng đi kèm cũng không được ghi
    assert store.load() == AppSettings()


def test_valid_edge_values(db):
    assert parse_int("0", "retention_days") == 0
    assert parse_int(" 5000 ", "max_items") == 5000
    assert validate("paused", True) is True


def test_corrupt_stored_values_fall_back_to_defaults(db):
    for k, v in (("ui.theme", "???"), ("limits.max_items", "-3"), ("privacy.paused", "maybe"),
                 ("retention.days", "abc")):
        db.set_setting(k, v)
    assert SettingsStore(db).load() == AppSettings()


def test_reset_restores_defaults_without_touching_clipboard_data(history, seeded, db, data_dir):
    store = SettingsStore(db)
    store.save(theme="dark", max_items=10, paused=True)
    before_items, before_blobs = _remaining(db), db.stats().blob_bytes
    assert store.reset() == AppSettings() and store.load() == AppSettings()
    assert _remaining(db) == before_items and db.stats().blob_bytes == before_blobs
    _consistent(db, data_dir)


def test_new_limits_trim_through_existing_retention(history, seeded, db):
    limits = SettingsStore.limits(AppSettings(max_items=3))
    assert history.would_trim(limits)
    history.apply_limits(limits)
    assert db.stats().items <= 3 or db.stats().items == db.stats().pinned_items
    assert {seeded["text_pinned"], seeded["image_pinned"]} <= _remaining(db)


# --- tạm dừng ghi ------------------------------------------------------------------------------------------------


def test_pause_stops_saving_and_resume_saves_again(data_dir, clock):
    reader, notifier = FakeReader(), FakeNotifier()
    c = CaptureController(reader, notifier, data_dir, clock=clock)
    try:
        c.start()
        reader.snapshot, reader.seq = snap(text_rep("before")), 1
        notifier.callback().result(timeout=5)
        c.set_paused(True)
        reader.snapshot, reader.seq = snap(text_rep("while paused")), 2
        assert notifier.callback() is None
        assert reader.reads == 1  # tạm dừng thì thậm chí không đọc clipboard
        assert len(c.db.list_items()) == 1
        c.set_paused(False)
        reader.snapshot, reader.seq = snap(text_rep("after")), 3
        notifier.callback().result(timeout=5)
        previews = {i.preview for i in c.db.list_items()}
        assert previews == {"before", "after"}  # nội dung lúc tạm dừng không bao giờ được lưu
    finally:
        c.shutdown()
