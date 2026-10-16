"""Định dạng hiển thị thuần (không Qt) cho danh sách và preview."""

from __future__ import annotations

CATEGORY_LABELS = {
    "all": "All", "image": "Images", "text": "Text", "link": "Links", "code": "Code",
    "other": "Other", "pinned": "Pinned",
}
CATEGORY_NAMES = {"image": "Image", "text": "Text", "link": "Link", "code": "Code", "other": "Other"}
CATEGORY_BADGES = {"image": "IMG", "text": "TXT", "link": "URL", "code": "</>", "other": "···"}


def format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    size = float(n)
    for unit in ("KB", "MB", "GB"):
        size /= 1024
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if size < 10 else f"{size:.0f} {unit}"
    return f"{n} B"  # không tới được


def format_age(now_ms: int, then_ms: int) -> str:
    seconds = max(0, (now_ms - then_ms) // 1000)
    if seconds < 45:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{max(minutes, 1)} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h ago"
    return f"{hours // 24} d ago"


def one_line(text: str | None, limit: int = 200) -> str:
    """Gộp khoảng trắng/xuống dòng thành một dòng — chỉ để hiển thị, không đổi dữ liệu gốc."""
    collapsed = " ".join((text or "").split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"
