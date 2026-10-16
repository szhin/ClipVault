"""System tray: chạy nền, mở lại cửa sổ bằng click hoặc menu, thoát hẳn từ menu."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from clipvault.ui import theme


def _icon_path() -> Path:
    """assets/icon.png: cạnh mã nguồn khi chạy từ source, trong thư mục dữ liệu của PyInstaller khi đã đóng gói."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "assets" / "icon.png"
    return Path(__file__).resolve().parents[3] / "assets" / "icon.png"


def load_app_icon() -> QIcon:
    """assets/icon.png nếu có (chạy từ mã nguồn); không thì dùng biểu tượng vẽ sẵn của theme."""
    if _icon_path().is_file():
        icon = QIcon(str(_icon_path()))
        if not icon.isNull():
            return icon
    return theme.app_icon()


class TrayIcon(QSystemTrayIcon):
    toggle_requested = Signal()
    open_requested = Signal()
    quit_requested = Signal()
    pause_toggled = Signal(bool)

    def __init__(self, icon: QIcon, parent=None) -> None:
        super().__init__(icon, parent)
        self.setToolTip("ClipVault")
        self.menu = QMenu()
        self.open_action = QAction("Open ClipVault", self.menu)
        self.pause_action = QAction("Tạm dừng ghi clipboard", self.menu)
        self.pause_action.setCheckable(True)
        self.quit_action = QAction("Quit", self.menu)
        self.menu.addAction(self.open_action)
        self.menu.addAction(self.pause_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.setContextMenu(self.menu)
        self.open_action.triggered.connect(self.open_requested)
        self.quit_action.triggered.connect(self.quit_requested)
        self.pause_action.toggled.connect(self.pause_toggled)
        theme.bus.changed.connect(self._restyle)
        self._restyle()
        self.activated.connect(self._on_activated)

    def _restyle(self) -> None:
        self.menu.setStyleSheet(theme.stylesheet())  # menu không có parent nên không thừa kế QSS cửa sổ

    def set_paused(self, paused: bool) -> None:
        """Đồng bộ trạng thái tạm dừng (không phát lại signal)."""
        blocker = QSignalBlocker(self.pause_action)
        self.pause_action.setChecked(paused)
        del blocker
        self.setToolTip("ClipVault — đang tạm dừng ghi" if paused else "ClipVault")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.toggle_requested.emit()
