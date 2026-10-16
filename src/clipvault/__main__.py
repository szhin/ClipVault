"""Composition root: chọn adapter theo nền tảng, lắp engine + UI và khởi động app."""

import logging
import logging.handlers
import signal
import sys

from clipvault import __version__
from clipvault.core import paths


def _setup_logging(log_dir) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "clipvault.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def main() -> int:
    if sys.platform != "win32":
        print(f"ClipVault {__version__}: nền tảng {sys.platform} chưa được hỗ trợ (macOS: Phase 6).")
        return 1

    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication

    from clipvault.adapters.qt_notifier import QtChangeNotifier
    from clipvault.adapters.windows.clipboard import WindowsClipboardReader, WindowsClipboardWriter
    from clipvault.adapters.windows.hotkey import WindowsHotkey
    from clipvault.engine.capture import CaptureController
    from clipvault.engine.history import HistoryService
    from clipvault.engine.paste import PasteService
    from clipvault.ui.app import DEFAULT_HOTKEY, ClipVaultUi

    data_dir = paths.data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    _setup_logging(data_dir / "logs")

    app = QApplication(sys.argv)
    app.setApplicationName("ClipVault")
    app.setQuitOnLastWindowClosed(False)  # chạy nền ở system tray
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Hai tiến trình cùng bắt clipboard sẽ ghi trùng vào một DB: chỉ cho một bản chạy.
    lock = QLockFile(str(data_dir / "clipvault.lock"))
    if not lock.tryLock(0):
        print("ClipVault đang chạy (xem biểu tượng ở khay hệ thống).")
        return 0

    controller = CaptureController(WindowsClipboardReader(), QtChangeNotifier(), data_dir)
    paste = PasteService(controller.db, WindowsClipboardWriter(), on_written=controller.ignore_sequence)
    history = HistoryService(controller.db, paste)
    spec = controller.db.settings().get("ui.hotkey", DEFAULT_HOTKEY)
    ui = ClipVaultUi(history, WindowsHotkey(), spec)
    controller.on_result = ui.bridge.notify

    from clipvault.engine.settings import SettingsStore

    def apply_engine_settings(changed) -> None:
        s = ui.prefs.values
        if "paused" in changed:
            controller.set_paused(s.paused)
        if {"max_items", "max_total_mb"} & set(changed):
            controller.limits = controller.service.limits = SettingsStore.limits(s, controller.limits)

    controller.set_paused(ui.prefs.values.paused)  # tạm dừng được nhớ qua lần mở lại
    ui.prefs.changed.connect(apply_engine_settings)

    app.aboutToQuit.connect(ui.shutdown)  # dừng đọc DB từ UI trước khi đóng DB
    app.aboutToQuit.connect(controller.shutdown)
    controller.start()
    ui.start(show_window="--background" not in sys.argv)
    logging.getLogger(__name__).info("ClipVault %s started", __version__)
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
