import logging

import pytest

from clipvault.core.model import Representation
from clipvault.core.ports import ClipboardUnavailable, ClipboardWriteError
from clipvault.engine.capture import CaptureController
from clipvault.engine.history import HistoryError, allowed_categories
from clipvault.storage.db import StorageError

from conftest import INLINE_MAX, png_rep, query, snap, text_rep

SECRET = "mat-khau-bi-mat-98765"


def _add(service, *reps):
    return service.process(snap(*reps)).item_id


@pytest.fixture
def populated(service):
    ids = {
        "text": _add(service, text_rep("Xin chào thế giới")),
        "link": _add(service, text_rep("https://example.com/a")),
        "code": _add(service, text_rep("def f(x):\n    return x\n")),
        "image": _add(service, png_rep(2000)),
        "other": _add(service, text_rep("#ff8800")),
    }
    return ids


def _ids(items):
    return [i.id for i in items]


# --- views ---------------------------------------------------------------------------------------


def test_all_view_newest_first(history, populated):
    assert _ids(history.query("all")) == sorted(populated.values(), reverse=True)


@pytest.mark.parametrize("view", ["image", "text", "link", "code", "other"])
def test_category_views_each_return_only_their_items(history, populated, view):
    assert _ids(history.query(view)) == [populated[view]]


def test_pinned_view_and_ordering(history, populated):
    history.set_pinned(populated["text"], True)
    assert _ids(history.query("pinned")) == [populated["text"]]
    assert history.query("all")[0].id == populated["text"]  # ghim luôn nằm đầu
    history.set_pinned(populated["text"], False)
    assert history.query("pinned") == []


def test_paging_with_offset(history, service):
    ids = [_add(service, text_rep(f"item {i}")) for i in range(25)]
    page1 = history.query("all", limit=10)
    page2 = history.query("all", limit=10, offset=10)
    page3 = history.query("all", limit=10, offset=20)
    assert [len(page1), len(page2), len(page3)] == [10, 10, 5]
    assert _ids(page1 + page2 + page3) == sorted(ids, reverse=True)


# --- tìm kiếm ----------------------------------------------------------------------------------


def test_search_is_case_and_unicode_insensitive(history, populated):
    assert _ids(history.query("all", "XIN CHÀO")) == [populated["text"]]
    assert _ids(history.query("all", "chào thế")) == [populated["text"]]


def test_search_combines_with_view(history, populated):
    assert history.query("link", "example") != []
    assert history.query("text", "example") == []


def test_search_treats_wildcards_literally(history, service):
    _add(service, text_rep("100% sure"))
    _add(service, text_rep("under_score"))
    _add(service, text_rep("plain"))
    assert len(history.query("all", "%")) == 1
    assert len(history.query("all", "_")) == 1
    assert len(history.query("all", "\\")) == 0


def test_search_blank_returns_everything(history, populated):
    assert len(history.query("all", "   ")) == 5


# --- ghim / xóa -------------------------------------------------------------------------------


def test_delete_removes_item_and_unreferenced_files(history, service, db):
    big = _add(service, png_rep(INLINE_MAX + 100))
    assert [p for p in db.blobs.root.rglob("*") if p.is_file()]
    history.delete(big)
    assert history.get(big) is None
    assert not [p for p in db.blobs.root.rglob("*") if p.is_file()]
    assert query(db, "SELECT COUNT(*) FROM blobs") == [(0,)]


def test_delete_missing_item_raises_history_error(history):
    with pytest.raises(HistoryError):
        history.delete(999)


# --- change type ------------------------------------------------------------------------------


def test_change_type_moves_item_between_views(history, populated):
    history.change_category(populated["text"], "code")
    assert populated["text"] in _ids(history.query("code"))
    assert populated["text"] not in _ids(history.query("text"))
    item = history.get(populated["text"])
    assert item.category == "code" and "manual" in item.tags


def test_change_type_does_not_alter_payload(history, populated, db):
    before = db.representations(populated["text"])
    history.change_category(populated["text"], "other")
    assert db.representations(populated["text"]) == before


def test_change_type_rules(history, populated):
    assert allowed_categories(history.get(populated["image"])) == ("image", "other")
    assert allowed_categories(history.get(populated["text"])) == ("text", "link", "code", "other")
    with pytest.raises(HistoryError):
        history.change_category(populated["image"], "code")
    with pytest.raises(HistoryError):
        history.change_category(populated["text"], "image")
    with pytest.raises(HistoryError):
        history.change_category(populated["text"], "bogus")
    with pytest.raises(HistoryError):
        history.change_category(12345, "text")


def test_manual_type_survives_reclassification(history, populated, db):
    from clipvault.engine import reclassify

    history.change_category(populated["link"], "text")
    reclassify.reclassify_item(db, populated["link"])
    assert history.get(populated["link"]).category == "text"


# --- đọc dữ liệu cho preview -----------------------------------------------------------------------


def test_text_and_image_accessors(history, populated):
    assert history.text(populated["link"]) == "https://example.com/a"  # đúng chuỗi gốc
    assert history.text(populated["image"]) is None
    rep = history.image(populated["image"])
    assert rep.mime == "image/png" and rep.native_format == "PNG"
    assert history.image(populated["text"]) is None
    assert history.format_names(populated["image"]) == ["PNG"]


def test_text_is_truncated_for_display_only(history, service, db):
    item = _add(service, text_rep("x" * 5000))
    assert len(history.text(item, max_chars=100)) == 100
    assert len(db.representations(item)[0].data) == (5000 + 1) * 2  # dữ liệu gốc nguyên vẹn


def test_image_prefers_png_over_dib(history, service):
    dib = Representation("CF_DIBV5", "image/bmp", b"\x00" * 200)
    item = _add(service, dib, png_rep(300))
    assert history.image(item).native_format == "PNG"


# --- Copy: khôi phục đúng định dạng gốc --------------------------------------------------------------


def test_copy_restores_every_representation_in_original_order(history, service, writer, db):
    reps = [
        png_rep(INLINE_MAX + 50),  # ảnh lớn lưu ngoài file
        text_rep("kèm text"),
        Representation("CF_DIBV5", "image/bmp", b"\x7c\x00\x00\x00" + b"\x01" * 200),
    ]
    item = _add(service, *reps)
    assert history.copy(item) == 3
    assert writer.writes == [reps]  # đúng bytes, đúng native_format, đúng thứ tự


def test_copy_reports_sequence_so_capture_skips_own_change(history, populated, written_sequences, writer):
    history.copy(populated["text"])
    assert written_sequences == [writer.sequence]


def test_copy_bumps_item_to_top_and_counts(history, populated):
    history.copy(populated["text"])
    top = history.query("all")[0]
    assert top.id == populated["text"] and top.copy_count == 2


@pytest.mark.parametrize(
    "error", [ClipboardUnavailable("busy"), ClipboardWriteError("SetClipboardData failed: PNG")]
)
def test_copy_failures_become_history_errors(history, populated, writer, error):
    writer.error = error
    with pytest.raises(HistoryError):
        history.copy(populated["text"])


def test_copy_failure_does_not_touch_item(history, populated, writer):
    writer.error = ClipboardUnavailable("busy")
    with pytest.raises(HistoryError):
        history.copy(populated["text"])
    assert history.get(populated["text"]).copy_count == 1


def test_copy_missing_item(history):
    with pytest.raises(HistoryError):
        history.copy(424242)


def test_history_error_messages_never_contain_content(history, populated, writer, caplog):
    writer.error = ClipboardWriteError(SECRET)
    with caplog.at_level(logging.DEBUG), pytest.raises(HistoryError) as exc:
        history.copy(populated["text"])
    assert SECRET not in str(exc.value) and exc.value.__cause__ is None


def test_storage_error_is_wrapped(history, db, monkeypatch):
    monkeypatch.setattr(db, "query_items", lambda *a, **k: (_ for _ in ()).throw(StorageError("x")))
    with pytest.raises(HistoryError):
        history.query("all")


# --- capture bỏ qua lần đổi do chính mình ----------------------------------------------------------------


class _Reader:
    def __init__(self):
        self.reads = 0

    def sequence_number(self):
        return 7

    def read_snapshot(self, max_item_bytes):
        self.reads += 1
        return snap(text_rep("x"))


class _Notifier:
    def start(self, cb): ...
    def stop(self): ...


def test_controller_ignores_sequence_after_copy(data_dir, clock):
    reader = _Reader()
    c = CaptureController(reader, _Notifier(), data_dir, clock=clock)
    try:
        c.ignore_sequence(7)
        assert c._on_change() is None and reader.reads == 0
        c.ignore_sequence(None)  # không có sequence: không đổi gì
        assert c._on_change() is None and reader.reads == 0
    finally:
        c.shutdown()
