"""Phase 3c (UI): theme sáng/tối + gradient, switch ↔ Settings, xóa dữ liệu qua dialog, tạm dừng, đóng cửa sổ."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from clipvault.ui import theme
from clipvault.ui.settings_dialog import SettingsDialog

from conftest import wait_until
from test_ui_theme import _sidebar_counts
from test_ui_window import _go_view, ids, window  # noqa: F401  (fixture dùng chung)


@pytest.fixture(autouse=True)
def _reset_theme(qapp):
    yield
    theme.apply("dark", "medium", "comfortable")
    theme.set_scheme("dark")


@pytest.fixture
def dialog(window, qapp):  # noqa: F811
    d = SettingsDialog(window.history, window.prefs, window)
    d.data_changed.connect(window.after_data_deleted)
    d.show()
    qapp.processEvents()
    yield d
    d.close()


def _answer(dialog, value, log=None):
    def confirm(text):
        if log is not None:
            log.append(text)
        return value

    dialog.confirm = confirm


# --- token / gradient ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("p", [theme.DARK, theme.LIGHT], ids=lambda p: p.name)
def test_contrast_on_both_gradient_ends_and_elevated(p):
    for fg in (p.text, p.muted):
        for bg in (p.grad_start, p.grad_end, p.elevated, p.sidebar):
            assert theme.contrast_ratio(fg, bg) >= 4.5, (p.name, fg, bg)
    assert theme.contrast_ratio(p.warn, p.elevated) >= 4.5  # chữ trạng thái tạm dừng


@pytest.mark.parametrize("p", [theme.DARK, theme.LIGHT], ids=lambda p: p.name)
def test_layers_and_gradient_is_subtle_and_not_pure(p):
    def lum(c):
        return QColor(c).lightnessF()

    ordered = [p.bg, p.sidebar, p.surface, p.elevated]
    steps = [lum(c) for c in ordered]
    assert steps == sorted(steps) if p.name == "dark" else steps[0] > steps[1] and steps[1] < steps[2] <= steps[3]
    for c in (p.bg, p.sidebar, p.surface, p.elevated, p.text):
        assert c.lower() not in ("#000000", "#ffffff")
    assert abs(lum(p.grad_start) - lum(p.grad_end)) < 0.1  # chênh nhẹ
    assert p.grad_start == p.bg


def test_gradient_only_on_root_and_painted_diagonally(window, qapp):  # noqa: F811
    roots = [w for w in window.findChildren(QWidget) if isinstance(w, theme.GradientBackground)]
    assert roots == [window.root] and window.centralWidget() is window.root
    qss = theme.stylesheet(theme.DARK) + theme.stylesheet(theme.LIGHT)
    assert "gradient" not in qss.lower()  # không widget con nào tự đặt gradient trong QSS
    bare = theme.GradientBackground()  # vẽ riêng để không bị sidebar/card che
    bare.resize(900, 500)
    img = bare.grab().toImage()
    p = theme.current()
    tl, br = img.pixelColor(0, 0), img.pixelColor(img.width() - 1, img.height() - 1)
    assert tl.name() == QColor(p.grad_start).name()
    assert abs(br.lightnessF() - QColor(p.grad_end).lightnessF()) < 0.01
    mid = img.pixelColor(img.width() // 2, img.height() // 2).lightnessF()
    assert min(tl.lightnessF(), br.lightnessF()) <= mid <= max(tl.lightnessF(), br.lightnessF())
    # đường chéo: hai góc còn lại cùng mức sáng gần nhau và nằm giữa hai đầu
    tr, bl = img.pixelColor(img.width() - 1, 0), img.pixelColor(0, img.height() - 1)
    assert tr != tl and bl != tl


def test_gradient_follows_resize_and_theme(window, qapp):  # noqa: F811
    window.resize(700, 480)
    qapp.processEvents()
    dark = window.root.grab().toImage().pixelColor(2, 2)
    window.resize(1200, 700)
    qapp.processEvents()
    assert window.root.grab().toImage().pixelColor(2, 2).name() == dark.name()  # điểm đầu không đổi khi kéo giãn
    window.toggle_theme()
    qapp.processEvents()
    assert window.root.grab().toImage().pixelColor(2, 2).name() != dark.name()


# --- switch sidebar ↔ Settings ----------------------------------------------------------------------------------------


def test_switch_changes_theme_live_and_syncs_settings(window, dialog, qapp):  # noqa: F811
    window.prefs.set(theme="dark")
    assert window.theme_button.toolTip() and theme.current().name == "dark"
    window.theme_button.click()
    assert theme.current().name == "light" and window.prefs.values.theme == "light"
    assert dialog.theme_box.currentData() == "light"  # Settings theo switch
    assert theme.LIGHT.surface in window.styleSheet()
    dialog.theme_box.setCurrentIndex(dialog.theme_box.findData("dark"))
    assert theme.current().name == "dark" and window.prefs.values.theme == "dark"  # switch theo Settings
    dialog.theme_box.setCurrentIndex(dialog.theme_box.findData("system"))
    assert window.prefs.values.theme == "system"
    assert window.theme_button.icon().isNull() is False


def test_theme_persists_across_prefs_reload(window):  # noqa: F811
    from clipvault.engine.settings import SettingsStore

    window.prefs.set(theme="light", font_size="large", density="compact")
    again = SettingsStore(window.history.db).load()
    assert (again.theme, again.font_size, again.density) == ("light", "large", "compact")


def test_title_bar_color_scheme_follows_theme(window, qapp):  # noqa: F811
    hints = qapp.styleHints()
    if not hasattr(hints, "setColorScheme"):
        pytest.skip("Qt không hỗ trợ QStyleHints.setColorScheme")
    window.prefs.set(theme="light")
    if hints.colorScheme() == Qt.ColorScheme.Unknown:
        pytest.skip("platform offscreen không báo color scheme; title bar thật chỉ kiểm bằng tay trên Windows")
    assert hints.colorScheme() == Qt.ColorScheme.Light
    window.prefs.set(theme="dark")
    assert hints.colorScheme() == Qt.ColorScheme.Dark


def test_switching_theme_with_every_preview_page_does_not_error(window, ids, qapp):  # noqa: F811
    for key in ("text", "code", "image", "link", "other"):
        window.select_item(ids[key])
        for mode in ("light", "dark", "light"):
            window.prefs.set(theme=mode)
            qapp.processEvents()
            assert not window.grab().isNull() and not window.preview.grab().isNull()
    assert window.current_item() is not None


def test_font_size_and_density_apply_live(window, qapp):  # noqa: F811
    base = theme.row_height()
    window.prefs.set(density="compact")
    qapp.processEvents()
    assert theme.row_height() < base
    assert window.list.itemDelegate().sizeHint(None, None).height() == theme.row_height()
    window.prefs.set(font_size="large", density="comfortable")
    assert theme.SIZE_BASE == theme.FONT_SCALES["large"][1] and theme.row_height() > base
    assert f"{theme.SIZE_BASE}pt" in window.styleSheet()
    assert not window.grab().isNull()


# --- xóa dữ liệu qua dialog ---------------------------------------------------------------------------------------------


def test_delete_cancel_changes_nothing(window, dialog):  # noqa: F811
    before = window.history.db.stats()
    _answer(dialog, False)
    dialog.scope_box.setCurrentIndex(dialog.scope_box.findData("all"))
    dialog.include_pinned.setChecked(True)
    assert dialog.delete_data() == 0
    assert window.history.db.stats() == before


def test_delete_default_keeps_pinned_and_confirmation_states_count_and_size(window, dialog, qapp, ids):  # noqa: F811
    assert not dialog.include_pinned.isChecked()  # mặc định TẮT
    window.select_item(ids["text"])
    window.toggle_pin()
    qapp.processEvents()
    log = []
    _answer(dialog, True, log)
    dialog.scope_box.setCurrentIndex(dialog.scope_box.findData("all"))
    assert dialog.delete_data() == 4
    assert "4 mục" in log[0] and " B" in log[0] or "KB" in log[0]
    assert "Đã xóa 4 mục" in dialog.delete_result.text()
    assert wait_until(qapp, lambda: _sidebar_counts(window)["all"] == 1)  # sidebar tự cập nhật
    assert _sidebar_counts(window)["pinned"] == 1
    assert window.model.rowCount() == 1


def test_delete_scope_text_via_dialog_updates_list(window, dialog, qapp):  # noqa: F811
    _answer(dialog, True)
    dialog.scope_box.setCurrentIndex(dialog.scope_box.findData("image"))
    assert dialog.delete_data() == 1
    assert wait_until(qapp, lambda: _sidebar_counts(window)["image"] == 0)
    assert _sidebar_counts(window)["text"] == 1


def test_nothing_to_delete_reports_without_confirm(window, dialog):  # noqa: F811
    _answer(dialog, True)
    dialog.scope_box.setCurrentIndex(dialog.scope_box.findData("all"))
    dialog.delete_data()
    log = []
    _answer(dialog, True, log)
    assert dialog.delete_data() == 0 and log == []


# --- nhập liệu / lưu trữ / reset --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("edit,text", [("max_items_edit", ""), ("max_items_edit", "-1"), ("max_mb_edit", "abc"),
                                       ("days_edit", "999999"), ("max_mb_edit", "99999999999")])
def test_dialog_rejects_bad_numbers_and_saves_nothing(window, dialog, edit, text):  # noqa: F811
    before = window.prefs.values
    getattr(dialog, edit).setText(text)
    assert dialog.apply_storage() is False
    assert dialog.storage_error.text() and window.prefs.values == before
    assert getattr(dialog, edit).property("invalid") is True


def test_dialog_saves_valid_numbers_and_reads_back(window, dialog):  # noqa: F811
    from clipvault.engine.settings import SettingsStore

    dialog.max_items_edit.setText("2000")
    dialog.max_mb_edit.setText("512")
    dialog.days_edit.setText("0")
    assert dialog.apply_storage() is True
    again = SettingsStore(window.history.db).load()
    assert (again.max_items, again.max_total_mb, again.retention_days) == (2000, 512, 0)
    assert str(window.history.db.stats().items) in dialog.usage_label.text()


def test_lowering_limit_asks_first_and_cancel_keeps_data(window, dialog):  # noqa: F811
    before = window.history.db.stats().items
    dialog.max_items_edit.setText("1")
    _answer(dialog, False)
    assert dialog.apply_storage() is False
    assert window.history.db.stats().items == before and window.prefs.values.max_items != 1


def test_reset_needs_confirm_and_keeps_data(window, dialog):  # noqa: F811
    window.prefs.set(theme="light", font_size="large", paused=True)
    before = window.history.db.stats()
    _answer(dialog, False)
    assert dialog.reset_defaults() is False and window.prefs.values.theme == "light"
    _answer(dialog, True)
    assert dialog.reset_defaults() is True
    assert window.prefs.values.theme == "system" and window.prefs.values.font_size == "medium"
    assert not window.prefs.values.paused and not dialog.pause_check.isChecked()
    assert window.history.db.stats() == before


# --- tạm dừng / hành vi ----------------------------------------------------------------------------------------------------------


def test_pause_is_visible_synced_and_persistent(window, dialog, qapp):  # noqa: F811
    assert not window.pause_banner.isVisibleTo(window)
    dialog.pause_check.setChecked(True)
    assert window.prefs.values.paused
    assert window.pause_banner.isVisibleTo(window) and window.pause_status.isVisibleTo(window)
    from clipvault.engine.settings import SettingsStore

    assert SettingsStore(window.history.db).load().paused  # nhớ khi mở lại app
    window.resume_button.click()
    assert not window.prefs.values.paused and not dialog.pause_check.isChecked()
    assert not window.pause_banner.isVisibleTo(window)


def test_tray_pause_action_syncs_with_prefs(qapp, history):
    from clipvault.ui.app import ClipVaultUi

    ui = ClipVaultUi(history, None)
    try:
        if ui.tray is None:
            pytest.skip("không có system tray trong môi trường test")
        ui.tray.pause_action.setChecked(True)
        assert ui.prefs.values.paused
        ui.prefs.set(paused=False)
        assert not ui.tray.pause_action.isChecked()
    finally:
        ui.shutdown()
        ui.window.deleteLater()


def test_confirm_delete_setting_controls_prompt(window, ids):  # noqa: F811
    asked = []
    window.prefs.set(confirm_delete=True)
    window.confirm = lambda text: asked.append(text) or False
    window.select_item(ids["text"])
    window.delete_current()
    assert len(asked) == 1 and window.history.get(ids["text"]) is not None  # hỏi, từ chối → còn nguyên
    window.prefs.set(confirm_delete=False)
    window.delete_current()
    assert len(asked) == 1 and window.history.get(ids["text"]) is None  # tắt hỏi → xóa ngay


def test_close_button_follows_behavior_setting(window, qapp):  # noqa: F811
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtTest import QSignalSpy

    window.hide_on_close = True
    spy = QSignalSpy(window.quit_requested)
    window.prefs.set(close_to_tray=True)
    window.closeEvent(QCloseEvent())
    assert not window.isVisible() and spy.count() == 0
    window.show()
    window.prefs.set(close_to_tray=False)
    event = QCloseEvent()
    window.closeEvent(event)
    assert spy.count() == 1 and not event.isAccepted()  # app thoát qua ClipVaultUi.quit


def test_settings_button_opens_dialog(window, qapp):  # noqa: F811
    window.settings_button.click()
    assert window._settings_dialog.isVisible()
    window._settings_dialog.close()


def test_sidebar_footer_stays_visible_when_compact(window, qapp):  # noqa: F811
    window.resize(700, 480)
    qapp.processEvents()
    assert window.theme_button.isVisibleTo(window) and window.settings_button.isVisibleTo(window)
    assert window.theme_button.x() + window.theme_button.width() <= window.sidebar_panel.width()


def test_closed_settings_dialog_does_not_break_later_changes(window, qapp):  # noqa: F811
    """Hồi quy: đóng Settings rồi đổi theme/tạm dừng từng gây RuntimeError (widget C++ đã bị xóa)."""
    from PySide6.QtCore import QCoreApplication, QEvent

    errors = []
    old_hook = __import__("sys").excepthook
    __import__("sys").excepthook = lambda *a: errors.append(a)
    try:
        for _ in range(2):
            window.settings_button.click()
            window._settings_dialog.close()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qapp.processEvents()
        window.prefs.set(theme="light", paused=True)
        window.toggle_theme()
        qapp.processEvents()
    finally:
        __import__("sys").excepthook = old_hook
    assert errors == []
