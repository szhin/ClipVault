"""Cài đặt người dùng cho UI: một nguồn sự thật, phát signal để switch ở sidebar, dialog Settings,
tray và cửa sổ luôn đồng bộ. Lưu qua engine.settings (bảng settings)."""

from __future__ import annotations

from dataclasses import fields

from PySide6.QtCore import QObject, Signal

from clipvault.engine.settings import AppSettings, SettingsStore
from clipvault.ui import theme

APPEARANCE = ("theme", "font_size", "density")


class Preferences(QObject):
    changed = Signal(object)  # tuple tên các cài đặt vừa đổi

    def __init__(self, store: SettingsStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.values: AppSettings = store.load()

    def apply_appearance(self) -> None:
        v = self.values
        theme.apply(v.theme, v.font_size, v.density)

    def set(self, **changes: object) -> AppSettings:
        """Kiểm tra + lưu + áp dụng. Giá trị sai ném SettingsError và không đổi gì."""
        new = self.store.save(**changes)
        diff = tuple(f.name for f in fields(AppSettings) if getattr(new, f.name) != getattr(self.values, f.name))
        self.values = new
        if any(name in APPEARANCE for name in diff):
            self.apply_appearance()
        if diff:
            self.changed.emit(diff)
        return new

    def reset(self) -> AppSettings:
        """Về mặc định (chỉ cài đặt, không đụng dữ liệu clipboard)."""
        old = self.values
        self.values = self.store.reset()
        diff = tuple(f.name for f in fields(AppSettings) if getattr(old, f.name) != getattr(self.values, f.name))
        self.apply_appearance()
        if diff:
            self.changed.emit(diff)
        return self.values
