import pytest
from PySide6.QtCore import QModelIndex
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QStyleOptionViewItem

from clipvault.core.model import StoredItem
from clipvault.engine.capture import CaptureResult
from clipvault.ui.app import ClipVaultUi
from clipvault.ui.delegate import ItemDelegate, meta_text, primary_text

from conftest import png_rep, snap, text_rep, wait_until


class FakeHotkey:
    def __init__(self, ok=True):
        self.ok = ok
        self.spec = None
        self.callback = None
        self.unregistered = 0

    def register(self, spec, on_triggered):
        self.spec, self.callback = spec, on_triggered
        return self.ok

    def unregister(self):
        self.unregistered += 1


@pytest.fixture
def ui(qapp, history):
    hotkey = FakeHotkey()
    app_ui = ClipVaultUi(history, hotkey, "Ctrl+Alt+K")
    app_ui.hotkey_fake = hotkey
    yield app_ui
    app_ui.shutdown()
    app_ui.window.hide()
    app_ui.window.deleteLater()
    qapp.processEvents()


def test_hotkey_is_registered_and_toggles_window(ui, qapp):
    assert ui.hotkey_fake.spec == "Ctrl+Alt+K" and ui.hotkey_ok
    ui.window.hide()
    ui.hotkey_fake.callback()  # phím tắt → mở cửa sổ
    assert ui.window.isVisible() and ui.window.search.hasFocus() or ui.window.focusWidget() is ui.window.search
    qapp.processEvents()
    if ui.window.isActiveWindow():
        ui.hotkey_fake.callback()  # bấm lần nữa → ẩn
        assert not ui.window.isVisible()


def test_failed_hotkey_is_reported_and_app_still_usable(qapp, history):
    ui = ClipVaultUi(history, FakeHotkey(ok=False), "Ctrl+Alt+K")
    try:
        assert not ui.hotkey_ok
        ui.start(show_window=False)
        assert ui.window.isVisible() or ui.tray is not None  # không có tray → cửa sổ phải hiện
        if ui.tray is None:
            assert "unavailable" in ui.window.statusBar().currentMessage()
    finally:
        ui.shutdown()
        ui.window.hide()


def test_shutdown_unregisters_hotkey(ui):
    ui.shutdown()
    assert ui.hotkey_fake.unregistered >= 1


def test_capture_bridge_refreshes_window_from_worker_thread(ui, qapp, service):
    import threading

    ui.window.show()
    service.process(snap(text_rep("vừa copy")))
    t = threading.Thread(target=lambda: ui.bridge.notify(CaptureResult("saved", 1)))
    t.start()
    t.join()
    assert wait_until(qapp, lambda: ui.window.model.rowCount() == 1)
    assert ui.window.model.item_at(0).preview == "vừa copy"


@pytest.mark.parametrize("status", ["skipped", "failed"])
def test_bridge_ignores_non_saved_results(ui, qapp, status):
    got = []
    ui.bridge.captured.connect(lambda: got.append(1))
    ui.bridge.notify(CaptureResult(status))
    qapp.processEvents()
    assert got == []


def test_tray_actions_when_available(ui, qapp):
    if ui.tray is None:
        pytest.skip("không có system tray trong môi trường test")
    ui.window.hide()
    ui.tray.open_action.trigger()
    assert ui.window.isVisible()
    assert ui.window.hide_on_close  # đóng cửa sổ = chạy nền
    ui.tray.toggle_requested.emit()


def test_window_close_keeps_app_alive_when_tray_exists(ui):
    if ui.tray is None:
        pytest.skip("không có system tray trong môi trường test")
    ui.window.show()
    ui.window.close()
    assert not ui.window.isVisible()


# --- delegate -----------------------------------------------------------------------------------------


def _item(**kw):
    base = dict(id=1, created_at=0, last_seen_at=0, copy_count=1, pinned=False, source_app=None,
                kind="text", total_size=2048, preview="hello  world\nsecond line",
                tags=frozenset({"cat:text"}))
    base.update(kw)
    return StoredItem(**base)


def test_row_texts():
    assert primary_text(_item()) == "hello world second line"
    assert primary_text(_item(preview=None)) == "(no text preview)"
    assert primary_text(_item(kind="image", tags=frozenset({"cat:image"}))) == "Image"
    meta = meta_text(_item(copy_count=3), now_ms=10 * 60_000)
    assert meta == "Text · 10 min ago · 2.0 KB · copied 3×"
    code = _item(tags=frozenset({"cat:code", "lang:csharp"}))
    assert meta_text(code, 0).startswith("Code · C# · ")
    assert meta_text(_item(tags=frozenset({"cat:link"})), 0).startswith("Link · ")


def test_delegate_paints_every_category_without_error(ui, qapp, service):
    for rep in (text_rep("https://example.com"), text_rep("def f():\n    pass\n"),
                text_rep("plain"), text_rep("#fff"), png_rep(500)):
        service.process(snap(rep))
    ui.history.set_pinned(ui.history.query("all")[0].id, True)
    ui.window.show()
    ui.window.model.reload()
    ui.window.model.fetchMore()
    delegate = ui.window.list.itemDelegate()
    assert isinstance(delegate, ItemDelegate)
    image = QImage(400, 60, QImage.Format.Format_ARGB32)
    for row in range(ui.window.model.rowCount()):
        image.fill(0)
        painter = QPainter(image)
        option = QStyleOptionViewItem()
        option.rect = image.rect()
        option.widget = ui.window.list
        option.font = ui.window.list.font()
        option.palette = ui.window.list.palette()
        delegate.paint(painter, option, ui.window.model.index(row))
        painter.end()
        assert delegate.sizeHint(option, QModelIndex()).height() > 0
    assert not ui.window.grab().isNull()  # cả cửa sổ vẽ được
