"""Đọc clipboard Windows bằng ctypes Win32 (không dùng pywin32).

Giữ nguyên bytes như OS trả về (kể cả NUL cuối của CF_UNICODETEXT). Kiểm tra GlobalSize trước khi copy.
Lưu ý: GetClipboardData buộc app nguồn render định dạng delayed-rendering, nên chỉ đọc allowlist.
"""

from __future__ import annotations

import ctypes
import time
from collections.abc import Sequence
from ctypes import wintypes
from dataclasses import dataclass

from clipvault.core.model import Representation, Snapshot
from clipvault.core.ports import ClipboardUnavailable, ClipboardWriteError, ItemTooLarge

CF_DIB = 8
CF_UNICODETEXT = 13
CF_DIBV5 = 17

# Cờ riêng tư của password manager: có là không lưu mục đó.
EXCLUDE_MONITOR = "ExcludeClipboardContentFromMonitorProcessing"
VIEWER_IGNORE = "Clipboard Viewer Ignore"
CAN_INCLUDE_HISTORY = "CanIncludeInClipboardHistory"  # DWORD, 0 = không được lưu lịch sử
_PRIVACY_NAMES = frozenset({EXCLUDE_MONITOR, VIEWER_IGNORE})

_OPEN_DEADLINE_S = 0.25


@dataclass(frozen=True)
class FormatSpec:
    format_id: int
    native_format: str
    mime: str


def select_formats(
    available: Sequence[tuple[int, str]], can_include_history: int | None = None
) -> list[FormatSpec] | None:
    """Chọn định dạng theo allowlist Phase 1, giữ thứ tự OS liệt kê.

    `available`: (format_id, tên đăng ký hoặc "" với định dạng chuẩn).
    Trả None nếu nguồn đánh dấu riêng tư; [] nếu không có định dạng nào trong allowlist.
    """
    if can_include_history == 0 or any(name in _PRIVACY_NAMES for _, name in available):
        return None
    ids = {fid for fid, _ in available}
    chosen: list[FormatSpec] = []
    for fid, name in available:
        if fid == CF_UNICODETEXT:
            chosen.append(FormatSpec(fid, "CF_UNICODETEXT", "text/plain"))
        elif name == "PNG":
            chosen.append(FormatSpec(fid, "PNG", "image/png"))
        elif fid == CF_DIBV5:
            chosen.append(FormatSpec(fid, "CF_DIBV5", "image/bmp"))
        elif fid == CF_DIB and CF_DIBV5 not in ids:
            chosen.append(FormatSpec(fid, "CF_DIB", "image/bmp"))
    return chosen


GMEM_MOVEABLE = 0x0002

_STANDARD_FORMATS = {
    "CF_TEXT": 1, "CF_BITMAP": 2, "CF_DIB": CF_DIB, "CF_OEMTEXT": 7,
    "CF_UNICODETEXT": CF_UNICODETEXT, "CF_DIBV5": CF_DIBV5, "CF_HDROP": 15,
}


def _load_win32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
    user32.EnumClipboardFormats.restype = wintypes.UINT
    user32.GetClipboardFormatNameW.argtypes = [wintypes.UINT, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClipboardFormatNameW.restype = ctypes.c_int
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.GetClipboardSequenceNumber.argtypes = []
    user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p
    kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    return user32, kernel32


def _open_clipboard(user32) -> None:
    """OpenClipboard có retry + backoff, tối đa ~250 ms (app khác có thể đang giữ clipboard)."""
    deadline = time.monotonic() + _OPEN_DEADLINE_S
    delay = 0.005
    while not user32.OpenClipboard(None):
        if time.monotonic() + delay > deadline:
            raise ClipboardUnavailable("OpenClipboard failed")
        time.sleep(delay)
        delay = min(delay * 2, 0.05)


class WindowsClipboardReader:
    def __init__(self) -> None:
        self._user32, self._kernel32 = _load_win32()

    def sequence_number(self) -> int | None:
        return int(self._user32.GetClipboardSequenceNumber())

    def _open(self) -> None:
        _open_clipboard(self._user32)

    def _enumerate(self) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        buf = ctypes.create_unicode_buffer(256)
        fid = 0
        while True:
            fid = self._user32.EnumClipboardFormats(fid)
            if fid == 0:
                break
            name = ""
            if fid >= 0xC000 and self._user32.GetClipboardFormatNameW(fid, buf, len(buf)) > 0:
                name = buf.value
            out.append((fid, name))
        return out

    def _handle(self, fid: int) -> ctypes.c_void_p | None:
        return self._user32.GetClipboardData(fid) or None

    def _history_flag(self, available: Sequence[tuple[int, str]]) -> int | None:
        for fid, name in available:
            if name == CAN_INCLUDE_HISTORY:
                handle = self._handle(fid)
                if handle and self._kernel32.GlobalSize(handle) >= 4:
                    ptr = self._kernel32.GlobalLock(handle)
                    if ptr:
                        try:
                            return int.from_bytes(ctypes.string_at(ptr, 4), "little")
                        finally:
                            self._kernel32.GlobalUnlock(handle)
        return None

    def read_snapshot(self, max_item_bytes: int) -> Snapshot | None:
        self._open()
        try:
            available = self._enumerate()
            chosen = select_formats(available, self._history_flag(available))
            if not chosen:
                return None
            sequence = self.sequence_number()

            handles: list[tuple[FormatSpec, ctypes.c_void_p, int]] = []
            total = 0
            for spec in chosen:
                handle = self._handle(spec.format_id)
                if not handle:
                    continue
                size = int(self._kernel32.GlobalSize(handle))
                total += size
                handles.append((spec, handle, size))
            if total > max_item_bytes:
                raise ItemTooLarge(total, [s.native_format for s, _, _ in handles])

            reps = []
            for spec, handle, size in handles:
                ptr = self._kernel32.GlobalLock(handle)
                if not ptr:
                    continue
                try:
                    data = ctypes.string_at(ptr, size)
                finally:
                    self._kernel32.GlobalUnlock(handle)
                reps.append(Representation(spec.native_format, spec.mime, data))
            if not reps:
                return None
            return Snapshot(tuple(reps), None, time.time_ns() // 1_000_000, sequence)
        finally:
            self._user32.CloseClipboard()


class WindowsClipboardWriter:
    """Ghi lại đúng từng (native_format, bytes) theo thứ tự đã lưu (paste-back, không tổng hợp định dạng)."""

    def __init__(self) -> None:
        self._user32, self._kernel32 = _load_win32()

    def _format_id(self, native_format: str) -> int:
        fid = _STANDARD_FORMATS.get(native_format)
        if fid is None:
            fid = int(self._user32.RegisterClipboardFormatW(native_format))
        if not fid:
            raise ClipboardWriteError(f"unknown format: {native_format}")
        return fid

    def _alloc(self, data: bytes, native_format: str) -> int:
        handle = self._kernel32.GlobalAlloc(GMEM_MOVEABLE, max(len(data), 1))
        if not handle:
            raise ClipboardWriteError(f"GlobalAlloc failed: {native_format}")
        ptr = self._kernel32.GlobalLock(handle)
        if not ptr:
            self._kernel32.GlobalFree(handle)
            raise ClipboardWriteError(f"GlobalLock failed: {native_format}")
        try:
            ctypes.memmove(ptr, data, len(data))
        finally:
            self._kernel32.GlobalUnlock(handle)
        return handle

    def write(self, representations: Sequence[Representation]) -> int | None:
        if not representations:
            raise ClipboardWriteError("nothing to write")
        # Đăng ký/cấp phát trước khi mở clipboard để giữ thời gian giữ clipboard ngắn.
        prepared = [(self._format_id(r.native_format), r.native_format, r.data) for r in representations]
        _open_clipboard(self._user32)
        try:
            if not self._user32.EmptyClipboard():
                raise ClipboardWriteError("EmptyClipboard failed")
            for fid, name, data in prepared:
                handle = self._alloc(data, name)
                if not self._user32.SetClipboardData(fid, handle):
                    self._kernel32.GlobalFree(handle)  # SetClipboardData thất bại: ta vẫn sở hữu bộ nhớ
                    raise ClipboardWriteError(f"SetClipboardData failed: {name}")
        finally:
            self._user32.CloseClipboard()
        return int(self._user32.GetClipboardSequenceNumber())
