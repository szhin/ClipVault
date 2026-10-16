import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest

from clipvault.engine.history import HistoryError
from clipvault.ui.images import ImageProvider
from clipvault.ui.main_window import MainWindow
from clipvault.ui.models import HistoryModel
from clipvault.ui.preview import PAGE_EMPTY, PAGE_IMAGE, PAGE_MESSAGE, PAGE_TEXT

from conftest import INLINE_MAX, png_rep, snap, text_rep, wait_until
from test_ui_basics import _qt_image_bytes

CODE = "def f(x):\n    return x\n"


def _real_png(w=64, h=32):
    from clipvault.core.model import Representation

    return Representation("PNG", "image/png", _qt_image_bytes("PNG", w, h))


@pytest.fixture
def ids(service):
    def add(*reps):
        return service.process(snap(*reps)).item_id

    return {
        "text": add(text_rep("Xin chào thế giới")),
        "link": add(text_rep("https://example.com/path?q=1")),
        "code": add(text_rep(CODE)),
        "image": add(_real_png()),
        "other": add(text_rep("#ff8800")),
    }


@pytest.fixture
def window(qapp, history, ids):
    images = ImageProvider(history.image)
    model = HistoryModel(history, page_size=3)
    win = MainWindow(history, model, images)
    win.show()
    qapp.processEvents()
    yield win
    win.hide()
    images.shutdown()
    win.deleteLater()
    qapp.processEvents()


def _select(win, item_id):
    assert win.select_item(item_id), "mục không có trong danh sách"
    return win.current_item()


def _go_view(win, view):
    for row in range(win.sidebar.count()):
        if win.sidebar.item(row).data(Qt.ItemDataRole.UserRole) == view:
            win.sidebar.setCurrentRow(row)
            return
    raise AssertionError(view)


def _rows(win):
    return [win.model.item_at(r).id for r in range(win.model.rowCount())]


def _load_all(win):
    while win.model.canFetchMore():
        win.model.fetchMore()


# --- sidebar + danh sách ---------------------------------------------------------------------------


def test_sidebar_has_all_entries_in_order(window):
    labels = [window.sidebar.item(i).text() for i in range(window.sidebar.count())]
    assert labels == ["All", "Images", "Text", "Links", "Code", "Other", "Pinned"]


def test_model_pages_on_demand(qapp, history, ids):
    model = HistoryModel(history, page_size=3)  # không gắn view: không có fetchMore tự động
    model.reload()
    assert model.rowCount() == 3 and model.canFetchMore()
    model.fetchMore()
    assert model.rowCount() == 5 and not model.canFetchMore()
    assert [model.item_at(r).id for r in range(5)] == sorted(ids.values(), reverse=True)


def test_model_pages_exactly_full_last_page(qapp, history, service):
    for i in range(6):
        service.process(snap(text_rep(f"n{i}")))
    model = HistoryModel(history, page_size=3)
    model.reload()
    model.fetchMore()
    assert model.rowCount() == 6 and model.canFetchMore()  # trang đầy: chưa biết đã hết
    model.fetchMore()
    assert model.rowCount() == 6 and not model.canFetchMore()


def test_view_fetches_more_rows_to_fill_itself(window, ids):
    _load_all(window)
    assert _rows(window) == sorted(ids.values(), reverse=True)
    assert not window.model.canFetchMore()


@pytest.mark.parametrize("view,key", [("image", "image"), ("text", "text"), ("link", "link"),
                                      ("code", "code"), ("other", "other")])
def test_each_sidebar_view_filters(window, ids, view, key):
    _go_view(window, view)
    assert _rows(window) == [ids[key]]
    assert window.current_item().id == ids[key]  # dòng đầu tự được chọn


def test_pinned_view_empty_state(window):
    _go_view(window, "pinned")
    assert window.model.rowCount() == 0
    assert window.list_stack.currentWidget() is window.empty_label
    assert "pin" in window.empty_label.text().lower()
    assert window.preview.stack.currentIndex() == PAGE_EMPTY
    assert not window.preview.copy_button.isEnabled()


# --- tìm kiếm ----------------------------------------------------------------------------------------


def test_search_filters_and_clears(window, qapp, ids):
    window.search.setText("CHÀO")  # áp dụng qua timer debounce
    assert wait_until(qapp, lambda: _rows(window) == [ids["text"]])
    window.search.setText("không có gì khớp")
    window._apply_query()
    assert window.model.rowCount() == 0 and "No matches" in window.empty_label.text()
    window.escape()  # Esc xóa tìm kiếm trước, chưa ẩn cửa sổ
    assert window.search.text() == "" and window.isVisible()
    assert window.model.rowCount() == 3


def test_search_applies_within_selected_view(window, ids):
    _go_view(window, "link")
    window.search.setText("example")
    window._apply_query()
    assert _rows(window) == [ids["link"]]
    window.search.setText("chào")
    window._apply_query()
    assert _rows(window) == []


# --- preview theo loại -------------------------------------------------------------------------------


def test_text_preview(window, ids):
    _select(window, ids["text"])
    p = window.preview
    assert p.stack.currentIndex() == PAGE_TEXT
    assert p.text_view.toPlainText() == "Xin chào thế giới"
    assert p.title.text() == "Text"


def test_link_preview_shows_original_url(window, ids):
    _select(window, ids["link"])
    p = window.preview
    assert p.title.text() == "Link"
    assert p.text_view.toPlainText() == "https://example.com/path?q=1"


def test_code_preview_shows_language_name(window, ids):
    _select(window, ids["code"])
    p = window.preview
    assert p.title.text() == "Code — Python"
    assert p.text_view.toPlainText() == CODE


def test_image_preview_is_a_real_thumbnail(window, qapp, ids):
    _select(window, ids["image"])
    p = window.preview
    assert wait_until(qapp, lambda: p.stack.currentIndex() == PAGE_IMAGE)
    assert p.image_view.source().width() == 64 and p.image_view.source().height() == 32
    assert "64 × 32" in p.meta.text()


def test_undecodable_image_shows_message_not_crash(window, qapp, service):
    from clipvault.core.model import Representation

    bad = service.process(snap(Representation("PNG", "image/png", b"\x89PNG not really"))).item_id
    window.refresh()
    _select(window, bad)
    assert wait_until(qapp, lambda: window.preview.stack.currentIndex() == PAGE_MESSAGE
                      and "can't be previewed" in window.preview.message.text())


def test_other_preview_for_unknown_format(window, qapp, service):
    from clipvault.core.model import Representation

    odd = service.process(snap(Representation("Weird", "application/x-weird", b"\x00\x01"))).item_id
    window.refresh()
    _select(window, odd)
    assert window.preview.stack.currentIndex() == PAGE_MESSAGE
    assert "Weird" in window.preview.message.text()


# --- nút Copy -----------------------------------------------------------------------------------------


def test_copy_button_restores_original_formats(window, writer, db, ids):
    _select(window, ids["code"])
    window.preview.copy_button.click()
    assert writer.writes == [db.representations(ids["code"])]
    assert "Copied" in window.statusBar().currentMessage()
    assert window.current_item().id == ids["code"]  # lựa chọn đi theo mục, dù mục nổi lên đầu
    assert window.model.item_at(0).id == ids["code"]


def test_copy_error_is_shown_not_raised(window, writer, ids):
    from clipvault.core.ports import ClipboardUnavailable

    writer.error = ClipboardUnavailable("busy")
    _select(window, ids["text"])
    assert window.copy_current() is False
    assert "busy" in window.statusBar().currentMessage()


# --- nút Pin / Unpin ----------------------------------------------------------------------------------


def test_pin_button_toggles_and_updates_views(window, ids):
    _select(window, ids["text"])
    p = window.preview
    assert p.pin_button.text() == "Pin"
    p.pin_button.click()
    assert p.pin_button.text() == "Unpin"
    assert window.history.get(ids["text"]).pinned
    assert window.model.item_at(0).id == ids["text"]  # ghim nằm đầu
    _go_view(window, "pinned")
    assert _rows(window) == [ids["text"]]
    window.preview.pin_button.click()  # Unpin ngay trong view Pinned
    assert not window.history.get(ids["text"]).pinned
    assert window.model.rowCount() == 0 and window.list_stack.currentWidget() is window.empty_label


# --- nút Delete -----------------------------------------------------------------------------------------


def test_delete_button_removes_item_and_selects_neighbour(window, ids, db):
    _go_view(window, "all")
    _load_all(window)
    first = window.model.item_at(0).id
    second = window.model.item_at(1).id
    _select(window, first)
    window.preview.delete_button.click()
    assert window.history.get(first) is None
    assert first not in _rows(window)
    assert window.current_item().id == second  # dòng kế tiếp được chọn


def test_delete_pinned_item_requires_confirmation(window, ids, monkeypatch):
    _select(window, ids["text"])
    window.toggle_pin()
    asked = []
    monkeypatch.setattr(window, "confirm", lambda text: asked.append(text) or False)
    window.preview.delete_button.click()
    assert asked and window.history.get(ids["text"]) is not None
    monkeypatch.setattr(window, "confirm", lambda text: True)
    window.preview.delete_button.click()
    assert window.history.get(ids["text"]) is None


def test_delete_last_item_shows_empty_state(window, ids):
    for item_id in ids.values():
        _select(window, item_id) if window.select_item(item_id) else None
        window.delete_current()
    window.model.reload()
    window._after_reload()
    assert window.model.rowCount() == 0
    assert "Nothing copied yet" in window.empty_label.text()
    assert not window.preview.delete_button.isEnabled()


# --- Change Type -----------------------------------------------------------------------------------------


def _type_actions(win):
    return {a.data(): a for a in win.preview.type_menu.actions()}


def test_change_type_menu_changes_category_for_real(window, ids):
    _select(window, ids["text"])
    actions = _type_actions(window)
    assert list(actions) == ["text", "link", "code", "other"]
    assert actions["text"].isChecked() and not actions["code"].isChecked()
    actions["code"].trigger()
    assert window.history.get(ids["text"]).category == "code"
    assert window.preview.title.text() == "Code"  # chưa có ngôn ngữ vì người dùng tự đặt
    _go_view(window, "code")
    assert ids["text"] in _rows(window)
    assert _type_actions(window)["code"].isChecked()


def test_change_type_for_image_offers_only_image_and_other(window, ids):
    _select(window, ids["image"])
    assert list(_type_actions(window)) == ["image", "other"]
    _type_actions(window)["other"].trigger()
    assert window.history.get(ids["image"]).category == "other"
    _go_view(window, "other")
    assert ids["image"] in _rows(window)


# --- phím tắt + điều hướng bàn phím ------------------------------------------------------------------------


def test_arrow_keys_in_search_box_move_selection(window, ids):
    _go_view(window, "all")
    window.search.setFocus()
    first = window.current_item().id
    QTest.keyClick(window.search, Qt.Key.Key_Down)
    assert window.current_item().id == window.model.item_at(1).id != first
    QTest.keyClick(window.search, Qt.Key.Key_Up)
    assert window.current_item().id == first
    QTest.keyClick(window.search, Qt.Key.Key_Up)  # không vượt đầu danh sách
    assert window.current_item().id == first


def test_enter_in_search_copies_selected_and_hides_window(window, writer, db, ids):
    window.search.setFocus()
    QTest.keyClicks(window.search, "example")
    QTest.keyClick(window.search, Qt.Key.Key_Return)  # áp dụng truy vấn đang chờ rồi copy
    assert writer.writes == [db.representations(ids["link"])]
    assert not window.isVisible()


def test_enter_on_list_copies_and_hides(window, writer, db, ids):
    _select(window, ids["code"])
    window.list.setFocus()
    window.activateWindow()
    QTest.keyClick(window.list, Qt.Key.Key_Return)
    assert writer.writes == [db.representations(ids["code"])]
    assert not window.isVisible()


def test_delete_key_on_list_deletes_item(window, ids):
    _select(window, ids["code"])
    window.list.setFocus()
    window.activateWindow()
    QTest.keyClick(window.list, Qt.Key.Key_Delete)
    assert window.history.get(ids["code"]) is None


def test_delete_key_in_search_box_edits_text_only(window, ids):
    window.search.setText("abc")
    window.search.setFocus()
    window.search.setCursorPosition(0)
    QTest.keyClick(window.search, Qt.Key.Key_Delete)
    assert window.search.text() == "bc"
    assert all(window.history.get(i) is not None for i in ids.values())


def test_ctrl_p_toggles_pin(window, ids):
    _select(window, ids["code"])
    window.activateWindow()
    QTest.keyClick(window, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier)
    assert window.history.get(ids["code"]).pinned


def test_ctrl_number_switches_views(window, ids):
    window.activateWindow()
    QTest.keyClick(window, Qt.Key.Key_4, Qt.KeyboardModifier.ControlModifier)  # Links
    assert window.model.view == "link"
    QTest.keyClick(window, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)  # All
    assert window.model.view == "all"


def test_ctrl_f_focuses_search(window):
    window.list.setFocus()
    window.activateWindow()
    QTest.keyClick(window, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert window.search.hasFocus()


def test_escape_hides_window(window):
    window.activateWindow()
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert not window.isVisible()


def test_double_click_copies_and_hides(window, writer, db, ids):
    _select(window, ids["text"])
    window.list.doubleClicked.emit(window.list.currentIndex())
    assert writer.writes == [db.representations(ids["text"])]
    assert not window.isVisible()


# --- vòng đời / refresh ------------------------------------------------------------------------------------------


def test_close_hides_to_tray_but_quit_really_closes(window, qapp):
    window.hide_on_close = True
    window.close()
    assert not window.isVisible()
    window.show()
    window.request_quit()
    assert not window.isVisible()


def test_close_without_tray_really_closes(window):
    window.hide_on_close = False
    window.close()
    assert not window.isVisible()


def test_refresh_after_new_capture_keeps_selection(window, service, ids):
    _select(window, ids["code"])
    new = service.process(snap(text_rep("mới nhất"))).item_id
    window.refresh()
    assert window.model.item_at(0).id == new
    assert window.current_item().id == ids["code"]


def test_refresh_without_changes_does_not_reset_model(window):
    spy = QSignalSpy(window.model.modelReset)
    window.refresh()
    assert spy.count() == 0


def test_model_error_is_reported_in_status_bar(window, monkeypatch):
    def boom(*a, **k):
        raise HistoryError("load history failed (StorageError)")

    monkeypatch.setattr(window.history, "query", boom)
    window.model.reload()
    assert "load history failed" in window.statusBar().currentMessage()
    assert window.model.rowCount() == 0


def test_show_and_focus_focuses_search(window):
    window.hide()
    window.show_and_focus()
    assert window.isVisible()
    assert window.search.hasFocus() or window.focusWidget() is window.search


def test_toggle_visibility_hides_visible_active_window(window, qapp):
    window.show_and_focus()
    qapp.processEvents()
    if window.isActiveWindow():
        window.toggle_visibility()
        assert not window.isVisible()
    window.toggle_visibility()
    assert window.isVisible()


def test_thumbnails_never_block_painting_of_large_list(window, service, qapp):
    for i in range(30):
        service.process(snap(_real_png(16 + i, 16)))
    window.model.reload()
    _load_all(window)
    window.list.viewport().repaint()  # phải trả về ngay; thumbnail điền dần ở nền
    assert wait_until(qapp, lambda: window.images.get(window.model.item_at(0).id, 96) is not None
                      or window.model.item_at(0).category != "image")
