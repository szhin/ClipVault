"""Mô hình dữ liệu dùng chung. Payload là bytes đúng như OS trả về, không chuẩn hóa."""

from __future__ import annotations

from dataclasses import dataclass, field


LANGUAGE_NAMES = {
    "python": "Python", "javascript": "JavaScript", "typescript": "TypeScript", "java": "Java",
    "csharp": "C#", "c": "C", "cpp": "C++", "go": "Go", "rust": "Rust", "sql": "SQL", "css": "CSS",
    "html": "HTML", "xml": "XML", "json": "JSON", "powershell": "PowerShell", "bash": "Shell (Bash)",
    "php": "PHP",
}


@dataclass(frozen=True)
class Representation:
    native_format: str  # tên gốc của OS, vd. "CF_UNICODETEXT", "PNG"
    mime: str  # nhãn chuẩn hóa cho code chung, vd. "text/plain"
    data: bytes = field(repr=False)  # không bao giờ in nội dung ra repr/log


@dataclass(frozen=True)
class Snapshot:
    representations: tuple[Representation, ...]
    source_app: str | None = None
    captured_at: int = 0  # Unix ms UTC
    sequence: int | None = None  # số thứ tự thay đổi clipboard của OS, nếu có

    @property
    def total_size(self) -> int:
        return sum(len(r.data) for r in self.representations)


@dataclass(frozen=True)
class StoredItem:
    id: int
    created_at: int
    last_seen_at: int
    copy_count: int
    pinned: bool
    source_app: str | None
    kind: str
    total_size: int
    preview: str | None = field(repr=False)
    tags: frozenset[str] = frozenset()

    @property
    def category(self) -> str:
        """Danh mục hiển thị (image/text/link/code/other), lấy từ tag `cat:*`."""
        for tag in self.tags:
            if tag.startswith("cat:"):
                return tag[4:]
        return "image" if self.kind == "image" else "text" if self.kind in ("text", "rich") else "other"

    @property
    def language(self) -> str | None:
        for tag in self.tags:
            if tag.startswith("lang:"):
                return tag[5:]
        return None

    @property
    def language_name(self) -> str | None:
        lang = self.language
        return LANGUAGE_NAMES.get(lang, lang) if lang else None
