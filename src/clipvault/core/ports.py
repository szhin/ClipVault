"""Interface giữa engine và adapter của từng hệ điều hành."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from clipvault.core.model import Representation, Snapshot


class ClipboardUnavailable(Exception):
    """Không mở được clipboard (app khác đang giữ) sau khi đã retry."""


class ItemTooLarge(Exception):
    """Mục vượt giới hạn kích thước. Chỉ mang kích thước và tên định dạng, không mang nội dung."""

    def __init__(self, size: int, formats: Sequence[str]) -> None:
        self.size = size
        self.formats = tuple(formats)
        super().__init__(f"item too large: {size} bytes, formats={list(self.formats)}")


class ClipboardWriteError(Exception):
    """Ghi clipboard thất bại. Chỉ nêu tên định dạng, không nêu nội dung."""


class ClipboardWriter(Protocol):
    def write(self, representations: Sequence[Representation]) -> int | None:
        """Ghi lại đúng từng cặp (native_format, data) theo thứ tự đã lưu.

        Trả về sequence number của clipboard ngay sau khi ghi (để engine bỏ qua lần đổi do chính mình),
        hoặc None nếu nền tảng không có. Ném ClipboardUnavailable / ClipboardWriteError khi lỗi.
        """


class HotkeyService(Protocol):
    def register(self, spec: str, on_triggered: Callable[[], None]) -> bool:
        """Đăng ký phím tắt toàn cục dạng "Ctrl+Shift+V". False nếu trùng/không hợp lệ."""

    def unregister(self) -> None: ...


class ClipboardReader(Protocol):
    def sequence_number(self) -> int | None:
        """Bộ đếm thay đổi clipboard của OS; None nếu nền tảng không có."""

    def read_snapshot(self, max_item_bytes: int) -> Snapshot | None:
        """Đọc các định dạng trong allowlist.

        Trả None khi clipboard rỗng, chỉ có định dạng lạ, hoặc nguồn đánh dấu riêng tư.
        Ném ItemTooLarge trước khi copy payload vượt giới hạn; ClipboardUnavailable khi không mở được.
        """


class ChangeNotifier(Protocol):
    def start(self, on_change: Callable[[], None]) -> None: ...

    def stop(self) -> None: ...
