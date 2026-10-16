import logging
import sqlite3
from concurrent.futures import Future

import pytest

from clipvault.core.limits import Limits
from clipvault.core.model import Representation, Snapshot
from clipvault.core.ports import ClipboardUnavailable, ItemTooLarge
from clipvault.engine import capture
from clipvault.engine.capture import CaptureController, CaptureResult
from clipvault.engine.dedupe import blob_hash
from clipvault.storage.db import Database, StorageError

from conftest import INLINE_MAX, png_rep, query, snap, text_rep

SECRET = "mat-khau-bi-mat-12345"


def _files(root):
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


# --- text / ảnh mới ------------------------------------------------------------------------


def test_new_text_is_stored_byte_exact(service, db):
    rep = text_rep("héllo 😀")
    result = service.process(snap(rep))
    assert result.status == "saved"
    items = db.list_items()
    assert len(items) == 1 and items[0].kind == "text" and items[0].copy_count == 1
    assert items[0].preview == "héllo 😀"
    assert db.representations(result.item_id) == [rep]  # kể cả NUL cuối


def test_small_image_is_inline(service, db):
    rep = png_rep(4096)
    result = service.process(snap(rep))
    ((external, data),) = query(db, "SELECT external, data FROM blobs")
    assert external == 0 and bytes(data) == rep.data
    assert db.list_items()[0].kind == "image"
    assert db.representations(result.item_id) == [rep]
    assert _files(db.blobs.root) == []


def test_large_image_is_external_file(service, db):
    rep = png_rep(INLINE_MAX + 1000)
    result = service.process(snap(rep))
    ((h, external, data),) = query(db, "SELECT hash, external, data FROM blobs")
    assert external == 1 and data is None
    path = db.blobs.root / bytes(h).hex()[:2] / bytes(h).hex()
    assert path.is_file() and path.read_bytes() == rep.data
    assert db.representations(result.item_id) == [rep]
    assert not list((db.blobs.root / "tmp").glob("*"))


def test_image_at_exact_inline_limit_stays_inline(service, db):
    service.process(snap(png_rep(INLINE_MAX)))
    assert query(db, "SELECT external FROM blobs") == [(0,)]


def test_duplicate_formats_in_snapshot_keep_first(service, db):
    first, second = text_rep("one"), text_rep("two")
    result = service.process(snap(first, second))
    assert db.representations(result.item_id) == [first]


# --- copy lặp ------------------------------------------------------------------------------


def test_repeated_copy_updates_existing_item(service, db):
    first = service.process(snap(text_rep("lặp")))
    created = db.list_items()[0]
    second = service.process(snap(text_rep("lặp")))
    assert (first.status, second.status) == ("saved", "duplicate")
    assert second.item_id == first.item_id
    (item,) = db.list_items()
    assert item.copy_count == 2 and item.last_seen_at > created.last_seen_at
    assert item.created_at == created.created_at


def test_repeated_copy_floats_item_to_top(service, db):
    a = service.process(snap(text_rep("a")))
    service.process(snap(text_rep("b")))
    service.process(snap(text_rep("a")))
    assert db.list_items()[0].id == a.item_id


def test_same_image_in_two_items_shares_one_blob(service, db):
    img = png_rep(INLINE_MAX + 10)
    service.process(snap(img, text_rep("a")))
    service.process(snap(img, text_rep("b")))
    assert len(db.list_items()) == 2
    assert query(db, "SELECT COUNT(*) FROM blobs WHERE hash = ?", (blob_hash(img.data),)) == [(1,)]
    assert len(_files(db.blobs.root)) == 1


def test_same_text_with_extra_format_is_a_different_item(service, db):
    service.process(snap(text_rep("x")))
    service.process(snap(text_rep("x"), Representation("PNG", "image/png", b"\x89PNG1")))
    assert len(db.list_items()) == 2


# --- khởi động lại ---------------------------------------------------------------------------


class FakeReader:
    def __init__(self):
        self.snapshot = None
        self.seq = 1
        self.error = None
        self.reads = 0

    def sequence_number(self):
        return self.seq

    def read_snapshot(self, max_item_bytes):
        self.reads += 1
        if self.error:
            raise self.error
        return self.snapshot


class FakeNotifier:
    def __init__(self):
        self.callback = None

    def start(self, on_change):
        self.callback = on_change

    def stop(self):
        self.callback = None


@pytest.fixture
def controller_factory(data_dir, clock):
    made = []

    def factory(reader=None, **kw):
        c = CaptureController(reader or FakeReader(), FakeNotifier(), data_dir, clock=clock, **kw)
        made.append(c)
        return c

    yield factory
    for c in made:
        try:
            c.shutdown()
        except Exception:
            pass


def test_history_survives_restart(data_dir, clock):
    text, img = text_rep("còn đây"), png_rep(INLINE_MAX + 5000, seed=3)
    c1 = CaptureController(FakeReader(), FakeNotifier(), data_dir, clock=clock)
    c1.submit(snap(text)).result(timeout=5)
    c1.submit(snap(img)).result(timeout=5)
    c1.shutdown()

    db = Database(data_dir)
    try:
        items = db.list_items()
        assert [i.kind for i in items] == ["image", "text"]
        assert db.representations(items[0].id) == [img]
        assert db.representations(items[1].id) == [text]
    finally:
        db.close()
    c2 = CaptureController(FakeReader(), FakeNotifier(), data_dir, clock=clock)
    try:
        assert len(c2.db.list_items()) == 2
        assert c2.db.representations(c2.db.list_items()[0].id) == [img]  # file ngoài còn nguyên sau sweep
    finally:
        c2.shutdown()


def test_startup_sweeps_orphans_and_tmp(data_dir, clock):
    c1 = CaptureController(FakeReader(), FakeNotifier(), data_dir, clock=clock)
    c1.submit(snap(png_rep(INLINE_MAX + 1))).result(timeout=5)
    c1.shutdown()
    blobs = data_dir / "blobs"
    (blobs / "tmp").mkdir(exist_ok=True)
    (blobs / "tmp" / "leftover").write_bytes(b"x")
    (blobs / "ab").mkdir(exist_ok=True)
    (blobs / "ab" / ("ab" + "0" * 62)).write_bytes(b"orphan")
    c2 = CaptureController(FakeReader(), FakeNotifier(), data_dir, clock=clock)
    try:
        left = [p.name for p in _files(blobs)]
        assert len(left) == 1 and "leftover" not in left
        assert c2.db.representations(c2.db.list_items()[0].id)
    finally:
        c2.shutdown()


# --- clipboard rỗng / định dạng lạ -----------------------------------------------------------


def test_snapshot_without_representations_is_skipped(service, db):
    assert service.process(snap()).status == "skipped"
    assert db.list_items() == []


def test_controller_ignores_empty_clipboard(controller_factory):
    reader = FakeReader()
    c = controller_factory(reader)
    assert c._on_change() is None
    assert reader.reads == 1 and c.db.list_items() == []


def test_oversized_item_is_skipped_and_log_has_no_content(service, db, caplog):
    limits = Limits(max_item_bytes=100)
    svc = capture.CaptureService(db, limits)
    big = Representation("CF_UNICODETEXT", "text/plain", (SECRET * 20).encode("utf-16-le"))
    with caplog.at_level(logging.DEBUG):
        assert svc.process(snap(big)).status == "skipped"
    assert db.list_items() == []
    assert str(len(big.data)) in caplog.text and "CF_UNICODETEXT" in caplog.text
    assert SECRET not in caplog.text


def test_controller_item_too_large_from_reader(controller_factory, caplog):
    reader = FakeReader()
    reader.error = ItemTooLarge(99_000_000, ["PNG"])
    c = controller_factory(reader)
    with caplog.at_level(logging.DEBUG):
        assert c._on_change() is None
    assert "99000000" in caplog.text and "PNG" in caplog.text
    assert c.db.list_items() == []


def test_unavailable_clipboard_is_retried_on_next_event(controller_factory):
    reader = FakeReader()
    reader.error = ClipboardUnavailable("busy")
    c = controller_factory(reader)
    assert c._on_change() is None
    reader.error, reader.snapshot = None, snap(text_rep("ok"))
    future = c._on_change()  # cùng sequence number nhưng lần trước chưa đọc được
    assert isinstance(future, Future) and future.result(timeout=5).status == "saved"


def test_same_sequence_number_is_read_once(controller_factory):
    reader = FakeReader()
    reader.snapshot = snap(text_rep("a"))
    c = controller_factory(reader)
    c._on_change().result(timeout=5)
    assert c._on_change() is None and reader.reads == 1
    reader.seq = 2
    assert c._on_change().result(timeout=5).status == "duplicate"


def test_on_result_callback_receives_result(controller_factory):
    got = []
    c = controller_factory(on_result=got.append)
    c.submit(snap(text_rep("cb"))).result(timeout=5)
    assert got == [CaptureResult("saved", got[0].item_id)]


# --- lỗi ghi file / DB -----------------------------------------------------------------------


def test_file_write_failure_leaves_no_item_and_next_capture_works(service, db, monkeypatch, caplog):
    rep = Representation("PNG", "image/png", b"\x89PNG" + SECRET.encode() * 20000)
    import clipvault.storage.blobstore as bs

    original = bs.os.replace

    def boom(*a, **k):
        raise OSError(SECRET)

    monkeypatch.setattr(bs.os, "replace", boom)
    with caplog.at_level(logging.DEBUG):
        assert service.process(snap(rep)).status == "failed"
    assert db.list_items() == [] and query(db, "SELECT COUNT(*) FROM blobs") == [(0,)]
    assert _files(db.blobs.root) == []  # không còn file tmp
    assert SECRET not in caplog.text and "OSError" in caplog.text

    monkeypatch.setattr(bs.os, "replace", original)
    assert service.process(snap(rep)).status == "saved"
    assert db.representations(db.list_items()[0].id) == [rep]


def test_db_failure_cleans_new_file_and_next_capture_works(service, db, caplog):
    rep = png_rep(INLINE_MAX + 100)
    db._conn.execute(
        f"CREATE TRIGGER boom BEFORE INSERT ON items BEGIN SELECT RAISE(ABORT, '{SECRET}'); END"
    )
    with caplog.at_level(logging.DEBUG):
        assert service.process(snap(rep)).status == "failed"
    assert db.list_items() == [] and query(db, "SELECT COUNT(*) FROM blobs") == [(0,)]
    assert _files(db.blobs.root) == []
    assert SECRET not in caplog.text

    db._conn.execute("DROP TRIGGER boom")
    assert service.process(snap(rep)).status == "saved"


def test_failed_save_does_not_leave_open_transaction(service, db):
    db._conn.execute(
        "CREATE TRIGGER boom BEFORE INSERT ON representations BEGIN SELECT RAISE(ABORT, 'x'); END"
    )
    assert service.process(snap(text_rep("a"))).status == "failed"
    assert not db._conn.in_transaction
    assert query(db, "SELECT COUNT(*) FROM items") == [(0,)]


def test_storage_error_message_has_no_content(db):
    db._conn.execute(
        f"CREATE TRIGGER boom BEFORE INSERT ON items BEGIN SELECT RAISE(ABORT, '{SECRET}'); END"
    )
    with pytest.raises(StorageError) as exc:
        db.save(snap(text_rep(SECRET)), b"\x00" * 32, [b"\x01" * 32], "text", SECRET, SECRET, 1, 10)
    assert SECRET not in str(exc.value)


def test_corrupt_database_file_raises_storage_error(data_dir):
    data_dir.mkdir(parents=True)
    (data_dir / "clipvault.db").write_bytes(b"this is not a sqlite database" * 100)
    with pytest.raises(StorageError):
        Database(data_dir)


def test_unknown_schema_version_raises_storage_error(data_dir):
    data_dir.mkdir(parents=True)
    conn = sqlite3.connect(data_dir / "clipvault.db")
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(StorageError):
        Database(data_dir)


def test_unexpected_exception_in_worker_does_not_kill_it(controller_factory, monkeypatch):
    c = controller_factory()
    monkeypatch.setattr(c.service, "process", lambda s: (_ for _ in ()).throw(RuntimeError(SECRET)))
    assert c.submit(snap(text_rep("a"))).result(timeout=5).status == "failed"
    monkeypatch.undo()
    assert c.submit(snap(text_rep("b"))).result(timeout=5).status == "saved"
