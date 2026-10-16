"""System tray: chạy nền, mở lại cửa sổ bằng click hoặc menu, thoát hẳn từ menu."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from clipvault.ui import theme

_ICON_PATH = Path(__file__).resolve().parents[3] / "assets" / "icon.png"


def load_app_icon() -> QIcon:
    """assets/icon.png nếu có (chạy từ mã nguồn); không thì dùng biểu tượng vẽ sẵn của theme."""
    if _ICON_PATH.is_file():
        icon = QIcon(str(_ICON_PATH))
        if not icon.isNull():
            return icon
    return theme.app_icon()


class TrayIcon(QSystemTrayIcon):
    toggle_requested = Signal()
    open_requested = Signal()
    quit_requested = Signal()

    def __init__(self, icon: QIcon, parent=None) -> None:
        super().__init__(icon, parent)
        self.setToolTip("ClipVault")
        self.menu = QMenu()
        self.open_action = QAction("Open ClipVault", self.menu)
        self.quit_action = QAction("Quit", self.menu)
        self.menu.addAction(self.open_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.setContextMenu(self.menu)
        self.open_action.triggered.connect(self.open_requested)
        self.quit_action.triggered.connect(self.quit_requested)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.toggle_requested.emit()
