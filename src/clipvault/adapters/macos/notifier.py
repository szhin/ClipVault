"""Báo thay đổi clipboard macOS bằng cách poll changeCount (~300 ms): QClipboard không báo tin cậy khi app ở nền."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer

from clipvault.core.ports import ClipboardReader

POLL_INTERVAL_MS = 300


class PollingChangeNotifier:
    def __init__(self, reader: ClipboardReader, interval_ms: int = POLL_INTERVAL_MS) -> None:
        self._reader = reader
        self._timer = QTimer()
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)
        self._callback: Callable[[], None] | None = None
        self._last: int | None = None

    def start(self, on_change: Callable[[], None]) -> None:
        self._callback = on_change
        self._last = self._reader.sequence_number()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._callback = None

    def _poll(self) -> None:
        current = self._reader.sequence_number()
        if current != self._last:
            self._last = current
            if self._callback is not None:
                self._callback()
