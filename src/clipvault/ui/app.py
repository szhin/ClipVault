"""Lắp ráp UI: model, cửa sổ, tray, phím tắt toàn cục, cầu nối từ worker capture sang UI thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from clipvault.core.ports import HotkeyService
from clipvault.engine.settings import SettingsStore
from clipvault.engine.capture import CaptureResult
from clipvault.engine.history import HistoryError, HistoryService
from clipvault.ui import theme
from clipvault.ui.images import ImageProvider
from clipvault.ui.main_window import MainWindow
from clipvault.ui.models import HistoryModel
from clipvault.ui.prefs import Preferences
from clipvault.ui.tray import TrayIcon, load_app_icon

DEFAULT_HOTKEY = "Ctrl+Shift+V"
REFRESH_DEBOUNCE_MS = 150
PURGE_INTERVAL_MS = 3_600_000  # tự xóa mục quá hạn mỗi giờ


class CaptureBridge(QObject):
    """on_result của CaptureController chạy ở worker thread; signal này chuyển về UI thread."""

    captured = Signal()

    def notify(self, result: CaptureResult) -> None:
        if result.status in ("saved", "duplicate"):
            self.captured.emit()


class ClipVaultUi(QObject):
    def __init__(
        self,
        history: HistoryService,
        hotkey: HotkeyService | None = None,
        hotkey_spec: str = DEFAULT_HOTKEY,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        app = QApplication.instance()
        if app is not None:
            theme.install(app)  # Fusion + title bar + palette
        self.history = history
        self.prefs = Preferences(SettingsStore(history.db), self)
        self.prefs.apply_appearance()  # theme/cỡ chữ/mật độ đã lưu (mặc định: theo hệ thống)
        self.bridge = CaptureBridge()
        self.images = ImageProvider(self._load_image)
        self.model = HistoryModel(history)
        self.window = MainWindow(history, self.model, self.images, prefs=self.prefs)
        self.icon = load_app_icon()
        self.window.setWindowIcon(self.icon)
        self._hotkey = hotkey
        self.hotkey_spec = hotkey_spec
        self.hotkey_ok = False

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(REFRESH_DEBOUNCE_MS)
        self._refresh_timer.timeout.connect(self.window.refresh)
        self.bridge.captured.connect(self._refresh_timer.start)

        self.window.quit_requested.connect(self.quit)
        self._purge_timer = QTimer(self)
        self._purge_timer.setInterval(PURGE_INTERVAL_MS)
        self._purge_timer.timeout.connect(self.purge_expired)
        self._purge_timer.start()
        self.tray: TrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = TrayIcon(self.icon)
            self.tray.toggle_requested.connect(self.window.toggle_visibility)
            self.tray.open_requested.connect(self.window.show_and_focus)
            self.tray.quit_requested.connect(self.quit)
            self.tray.pause_toggled.connect(lambda on: self.prefs.set(paused=on))
            self.prefs.changed.connect(lambda _d: self.tray.set_paused(self.prefs.values.paused))
            self.tray.set_paused(self.prefs.values.paused)
            self.window.hide_on_close = True  # đóng cửa sổ = chạy nền, thoát bằng menu tray
            self.tray.show()

        if hotkey is not None:
            self.hotkey_ok = hotkey.register(hotkey_spec, self.window.toggle_visibility)

    def purge_expired(self) -> int:
        """Tự xóa mục chưa ghim quá hạn (retention.days; 0 = tắt) rồi nạp lại giao diện."""
        try:
            deleted = self.history.purge_expired(self.prefs.values.retention_days)
        except HistoryError:
            return 0
        if deleted:
            self.window.after_data_deleted()
        return deleted

    def _load_image(self, item_id: int):
        return self.history.image(item_id)

    def start(self, show_window: bool = True) -> None:
        self.purge_expired()
        if show_window or self.tray is None:
            self.window.show_and_focus()
        if not self.hotkey_ok and self._hotkey is not None:
            self._notify(f"Hotkey {self.hotkey_spec} is unavailable (already used by another app). "
                         "Open ClipVault from the tray icon instead.")
        elif self.tray is not None and not show_window:
            self._notify(f"ClipVault is running in the background. Press {self.hotkey_spec} to open it.")

    def _notify(self, text: str) -> None:
        if self.tray is not None:
            self.tray.showMessage("ClipVault", text, QSystemTrayIcon.MessageIcon.Information, 6000)
        else:
            self.window.statusBar().showMessage(text, 10000)

    def quit(self) -> None:
        self.shutdown()
        self.window.request_quit()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def shutdown(self) -> None:
        if self._hotkey is not None:
            self._hotkey.unregister()
        if self.tray is not None:
            self.tray.hide()
        self.images.shutdown()
