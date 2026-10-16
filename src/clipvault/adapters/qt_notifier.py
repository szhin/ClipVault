"""Báo thay đổi clipboard qua QClipboard.dataChanged (Windows). macOS sẽ cần notifier poll riêng (Phase 6)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QGuiApplication


class QtChangeNotifier:
    def __init__(self) -> None:
        self._callback: Callable[[], None] | None = None
        self._clipboard = None

    def start(self, on_change: Callable[[], None]) -> None:
        self._callback = on_change
        self._clipboard = QGuiApplication.clipboard()
        self._clipboard.dataChanged.connect(self._emit)

    def stop(self) -> None:
        if self._clipboard is not None:
            try:
                self._clipboard.dataChanged.disconnect(self._emit)
            except (RuntimeError, TypeError):
                pass
        self._callback = None
        self._clipboard = None

    def _emit(self) -> None:
        if self._callback is not None:
            self._callback()
