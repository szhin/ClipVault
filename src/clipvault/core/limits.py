"""Giới hạn dung lượng mặc định (ARCHITECTURE.md §6), chỉnh được qua bảng settings."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from collections.abc import Mapping

MB = 1024 * 1024


@dataclass(frozen=True)
class Limits:
    max_item_bytes: int = 20 * MB
    max_total_bytes: int = 1024 * MB
    max_items: int = 5000
    inline_max_bytes: int = 256 * 1024
    prune_ratio: float = 0.9
    preview_chars: int = 500
    search_text_bytes: int = 64 * 1024

    @classmethod
    def from_settings(cls, settings: Mapping[str, str]) -> Limits:
        """Đọc các khóa `limits.<tên>`; giá trị hỏng hoặc không dương thì giữ mặc định."""
        limits = cls()
        for f in fields(cls):
            raw = settings.get(f"limits.{f.name}")
            if raw is None:
                continue
            try:
                value = float(raw) if f.type in (float, "float") else int(raw)
            except ValueError:
                continue
            if value > 0:
                limits = replace(limits, **{f.name: value})
        return limits
