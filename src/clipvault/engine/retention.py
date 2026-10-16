"""Dọn dữ liệu cũ khi vượt giới hạn. Mục ghim không bao giờ bị xóa tự động."""

from __future__ import annotations

from dataclasses import dataclass

from clipvault.core.limits import Limits
from clipvault.storage.db import Database


@dataclass(frozen=True)
class RetentionResult:
    deleted: int = 0
    pinned_over_limit: bool = False  # chỉ còn mục ghim mà vẫn vượt giới hạn → UI cảnh báo


def _over(stats, limits: Limits) -> bool:
    return stats.items > limits.max_items or stats.blob_bytes > limits.max_total_bytes


def _above_target(stats, limits: Limits) -> bool:
    return (
        stats.items > limits.max_items * limits.prune_ratio
        or stats.blob_bytes > limits.max_total_bytes * limits.prune_ratio
    )


def enforce(db: Database, limits: Limits, protect_id: int | None = None) -> RetentionResult:
    """Vượt giới hạn → xóa mục chưa ghim cũ nhất theo last_seen_at đến khi ≤ prune_ratio.

    `protect_id` là mục vừa lưu, không bị xóa trong lần dọn này.
    """
    stats = db.stats()
    if not _over(stats, limits):
        return RetentionResult()
    deleted = 0
    for item_id in db.prune_candidates(exclude_id=protect_id):
        if not _above_target(stats, limits):
            break
        deleted += db.delete_items([item_id])
        stats = db.stats()
    return RetentionResult(deleted=deleted, pinned_over_limit=_over(stats, limits))


def purge_older_than(db: Database, days: int, now_ms: int) -> int:
    """Tự xóa mục chưa ghim không xem lại quá `days` ngày (0 = tắt). Trả số mục đã xóa."""
    if days <= 0:
        return 0
    return db.delete_older_than(now_ms - days * 86_400_000)
