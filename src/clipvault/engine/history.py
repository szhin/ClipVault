"""Dịch vụ lịch sử cho UI: truy vấn, tìm kiếm, ghim, xóa, đổi loại, Copy.

UI chỉ nói chuyện với lớp này (không chạm Database/adapter). Lỗi được đổi thành HistoryError
với thông báo chỉ nêu thao tác và loại lỗi, không bao giờ kèm nội dung clipboard.
"""

from __future__ import annotations

import functools
import sqlite3

from clipvault.classifier.rules import CATEGORIES, text_of
from clipvault.core.model import Representation, StoredItem
from clipvault.core.ports import ClipboardUnavailable, ClipboardWriteError
from clipvault.engine.paste import PasteService
from clipvault.storage.db import Database, StorageError

# (view trong sidebar) -> (danh mục, chỉ mục ghim)
VIEWS: dict[str, tuple[str | None, bool]] = {
    "all": (None, False),
    "image": ("image", False),
    "text": ("text", False),
    "link": ("link", False),
    "code": ("code", False),
    "other": ("other", False),
    "pinned": (None, True),
}

_IMAGE_CHOICES = ("image", "other")
_TEXT_CHOICES = ("text", "link", "code", "other")


class HistoryError(Exception):
    """Thao tác thất bại. Message an toàn để hiện cho người dùng và ghi log."""


def _guard(operation: str):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except HistoryError:
                raise
            except LookupError:
                raise HistoryError(f"{operation}: item no longer exists") from None
            except ClipboardUnavailable:
                raise HistoryError(f"{operation}: clipboard is busy, try again") from None
            except (StorageError, ClipboardWriteError, sqlite3.Error, OSError) as exc:
                raise HistoryError(f"{operation} failed ({type(exc).__name__})") from None

        return wrapper

    return decorate


def allowed_categories(item: StoredItem) -> tuple[str, ...]:
    """Danh mục người dùng được chọn khi Change Type."""
    return _IMAGE_CHOICES if item.kind == "image" else _TEXT_CHOICES


class HistoryService:
    def __init__(self, db: Database, paste: PasteService) -> None:
        self.db = db
        self.paste = paste

    @_guard("load history")
    def query(self, view: str = "all", text: str = "", limit: int = 100, offset: int = 0) -> list[StoredItem]:
        category, pinned_only = VIEWS[view]
        return self.db.query_items(category, pinned_only, text.strip() or None, limit, offset)

    @_guard("load item")
    def get(self, item_id: int) -> StoredItem | None:
        return self.db.get_item(item_id)

    @_guard("load text")
    def text(self, item_id: int, max_chars: int = 50_000) -> str | None:
        """Văn bản hiển thị của mục (chỉ để xem, không phải dữ liệu gốc); None nếu không có text."""
        for native_format, mime in self.db.representation_meta(item_id):
            if mime == "text/plain":
                reps = self.db.representations(item_id, native_format)
                return text_of(tuple(reps))[:max_chars] if reps else None
        return None

    @_guard("load image")
    def image(self, item_id: int) -> Representation | None:
        """Representation ảnh để dựng thumbnail/preview (ưu tiên PNG)."""
        meta = [(f, m) for f, m in self.db.representation_meta(item_id) if m.startswith("image/")]
        if not meta:
            return None
        meta.sort(key=lambda fm: fm[1] != "image/png")
        reps = self.db.representations(item_id, meta[0][0])
        return reps[0] if reps else None

    @_guard("load formats")
    def format_names(self, item_id: int) -> list[str]:
        return [f for f, _ in self.db.representation_meta(item_id)]

    @_guard("copy")
    def copy(self, item_id: int) -> int:
        return self.paste.restore(item_id)

    @_guard("pin")
    def set_pinned(self, item_id: int, pinned: bool) -> None:
        self.db.set_pinned(item_id, pinned)

    @_guard("delete")
    def delete(self, item_id: int) -> None:
        if self.db.delete_items([item_id]) == 0:
            raise LookupError

    @_guard("change type")
    def change_category(self, item_id: int, category: str) -> None:
        item = self.db.get_item(item_id)
        if item is None:
            raise LookupError
        if category not in CATEGORIES or category not in allowed_categories(item):
            raise HistoryError(f"change type: '{category}' is not allowed for this item")
        self.db.change_category(item_id, category)
