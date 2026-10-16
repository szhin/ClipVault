"""Copy: khôi phục clipboard đúng từng định dạng gốc theo thứ tự đã lưu."""

from __future__ import annotations

import time
from collections.abc import Callable

from clipvault.core.ports import ClipboardWriter
from clipvault.storage.db import Database


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


class PasteService:
    def __init__(
        self,
        db: Database,
        writer: ClipboardWriter,
        on_written: Callable[[int | None], None] | None = None,
        clock: Callable[[], int] = _now_ms,
    ) -> None:
        self.db = db
        self.writer = writer
        self.on_written = on_written  # nhận sequence number để capture bỏ qua lần đổi do chính mình
        self.clock = clock

    def restore(self, item_id: int) -> int:
        """Ghi mục lên clipboard. Trả số định dạng đã ghi. Mục nổi lên đầu danh sách."""
        reps = self.db.representations(item_id)
        if not reps:
            raise LookupError("item not found")
        sequence = self.writer.write(reps)
        if self.on_written is not None:
            self.on_written(sequence)
        self.db.touch(item_id, self.clock())
        return len(reps)
