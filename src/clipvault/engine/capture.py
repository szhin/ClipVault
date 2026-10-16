"""Capture pipeline: giới hạn → hash → dedupe → storage → dọn dữ liệu.

Không import Qt. Log chỉ ghi kích thước, tên định dạng và loại lỗi; không ghi nội dung hay hash.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from clipvault.classifier.rules import Classification, classify, kind_of
from clipvault.core.limits import Limits
from clipvault.core.model import Representation, Snapshot
from clipvault.core.ports import ChangeNotifier, ClipboardReader, ClipboardUnavailable, ItemTooLarge
from clipvault.engine import reclassify, retention
from clipvault.engine.dedupe import blob_hash, item_hash
from clipvault.storage.db import Database, StorageError

log = logging.getLogger(__name__)

SAVED, DUPLICATE, SKIPPED, FAILED = "saved", "duplicate", "skipped", "failed"


@dataclass(frozen=True)
class CaptureResult:
    status: str
    item_id: int | None = None
    pinned_over_limit: bool = False


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _decode_text(rep: Representation) -> str:
    """Giải mã chỉ để hiển thị/tìm kiếm (dữ liệu dẫn xuất), không bao giờ ghi ngược lại."""
    codec = "utf-16-le" if rep.native_format == "CF_UNICODETEXT" else "utf-8"
    return rep.data.decode(codec, errors="replace").split("\x00", 1)[0]


def _derive_text(reps: tuple[Representation, ...], limits: Limits) -> tuple[str | None, str | None]:
    for rep in reps:
        if rep.mime == "text/plain":
            text = _decode_text(rep)
            search = text.encode("utf-8")[: limits.search_text_bytes].decode("utf-8", errors="ignore")
            return text[: limits.preview_chars], search
    return None, None


class CaptureService:
    """Xử lý một Snapshot đồng bộ. Gọi từ worker ghi duy nhất."""

    def __init__(
        self, db: Database, limits: Limits, clock: Callable[[], int] = _now_ms
    ) -> None:
        self.db = db
        self.limits = limits
        self.clock = clock

    def process(self, snapshot: Snapshot) -> CaptureResult:
        # Mỗi native_format chỉ một lần (UNIQUE trong schema): giữ cái đầu theo thứ tự OS.
        seen: set[str] = set()
        reps = tuple(
            r for r in snapshot.representations if not (r.native_format in seen or seen.add(r.native_format))
        )
        if not reps:
            return CaptureResult(SKIPPED)
        snapshot = Snapshot(reps, snapshot.source_app, snapshot.captured_at, snapshot.sequence)

        if snapshot.total_size > self.limits.max_item_bytes:
            log.info(
                "skip oversized item: %d bytes, formats=%s",
                snapshot.total_size, [r.native_format for r in reps],
            )
            return CaptureResult(SKIPPED)

        blob_hashes = [blob_hash(r.data) for r in reps]
        preview, search = _derive_text(reps, self.limits)
        try:
            cls = classify(snapshot)
        except Exception as exc:  # phân loại hỏng không được làm mất mục clipboard
            log.error("classify failed: %s", type(exc).__name__)
            cls = Classification(kind_of(reps), frozenset())
        try:
            saved = self.db.save(
                snapshot, item_hash(reps, blob_hashes), blob_hashes, cls.kind,
                preview, search, self.clock(), self.limits.inline_max_bytes, cls.tags,
            )
        except (OSError, StorageError) as exc:
            log.error("capture failed: %s", type(exc).__name__)
            return CaptureResult(FAILED)

        over = False
        try:
            over = retention.enforce(self.db, self.limits, protect_id=saved.item_id).pinned_over_limit
        except (OSError, StorageError) as exc:
            log.error("retention failed: %s", type(exc).__name__)
        return CaptureResult(SAVED if saved.is_new else DUPLICATE, saved.item_id, over)


class CaptureController:
    """Nối reader/notifier với CaptureService.

    `_on_change` chạy trên UI thread (đọc clipboard thật ngắn); việc ghi chạy trên 1 worker duy nhất.
    `on_result` được gọi từ worker thread — tầng UI phải tự chuyển sang UI thread (Phase 3).
    """

    def __init__(
        self,
        reader: ClipboardReader,
        notifier: ChangeNotifier,
        data_dir: Path,
        limits: Limits | None = None,
        on_result: Callable[[CaptureResult], None] | None = None,
        clock: Callable[[], int] = _now_ms,
    ) -> None:
        self.reader = reader
        self.notifier = notifier
        self.db = Database(data_dir)
        self.limits = limits or Limits.from_settings(self.db.settings())
        self.service = CaptureService(self.db, self.limits, clock)
        self.on_result = on_result
        self._last_sequence: int | None = None
        self._paused = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipvault-writer")
        self._closed = threading.Event()
        removed = self.db.blobs.sweep(self.db.external_hashes())
        if removed:
            log.info("orphan sweep removed %d files", removed)
        reclassify.ensure_current(self.db)

    def start(self) -> None:
        self.notifier.start(self._on_change)

    def ignore_sequence(self, sequence: int | None) -> None:
        """Bỏ qua lần đổi clipboard do chính app gây ra (Copy/paste-back, §5). Gọi từ UI thread."""
        if sequence is not None:
            self._last_sequence = sequence

    def set_paused(self, paused: bool) -> None:
        """Tạm dừng/tiếp tục ghi clipboard. Khi tạm dừng không đọc và không lưu gì."""
        self._paused = bool(paused)

    @property
    def paused(self) -> bool:
        return self._paused

    def _on_change(self) -> Future | None:
        if self._closed.is_set() or self._paused:
            return None
        seq = self.reader.sequence_number()
        if seq is not None and seq == self._last_sequence:
            return None  # cùng một lần thay đổi (RDP/Win+V báo nhiều sự kiện)
        try:
            snapshot = self.reader.read_snapshot(self.limits.max_item_bytes)
        except ClipboardUnavailable:
            log.warning("clipboard unavailable, change ignored")
            return None  # không ghi nhớ seq: sự kiện sau có thể đọc được
        except ItemTooLarge as exc:
            self._last_sequence = seq
            log.info("skip oversized item: %d bytes, formats=%s", exc.size, list(exc.formats))
            return None
        self._last_sequence = seq
        if snapshot is None:
            return None
        return self.submit(snapshot)

    def submit(self, snapshot: Snapshot) -> Future:
        return self._executor.submit(self._run, snapshot)

    def _run(self, snapshot: Snapshot) -> CaptureResult:
        try:
            result = self.service.process(snapshot)
        except Exception as exc:  # worker không được chết vì một mục lỗi
            log.error("capture crashed: %s", type(exc).__name__)
            result = CaptureResult(FAILED)
        if self.on_result is not None:
            try:
                self.on_result(result)
            except Exception as exc:
                log.error("on_result callback failed: %s", type(exc).__name__)
        return result

    def shutdown(self) -> None:
        self._closed.set()
        self.notifier.stop()
        self._executor.shutdown(wait=True)
        self.db.close()
