"""Phím tắt toàn cục Windows: RegisterHotKey + QAbstractNativeEventFilter nhận WM_HOTKEY."""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY = 0x0312
_HOTKEY_ID = 0x1A2B  # 0x0000-0xBFFF dành cho ứng dụng (0xC000-0xFFFF dành cho DLL)

_MODIFIERS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "shift": MOD_SHIFT, "alt": MOD_ALT,
              "win": MOD_WIN, "meta": MOD_WIN}
_NAMED_KEYS = {"space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "insert": 0x2D,
               "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
               "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27}


def parse_hotkey(spec: str) -> tuple[int, int] | None:
    """"Ctrl+Shift+V" -> (modifiers, virtual-key). None nếu không hợp lệ.

    Cần ít nhất một phím bổ trợ (phím trần như "V" sẽ chặn việc gõ phím đó ở mọi app).
    """
    mods, vk = 0, None
    for part in (p.strip().lower() for p in spec.split("+")):
        if not part:
            return None
        if part in _MODIFIERS:
            mods |= _MODIFIERS[part]
        elif vk is not None:
            return None  # hai phím chính
        elif len(part) == 1 and (part.isascii() and part.isalnum()):
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            vk = 0x70 + int(part[1:]) - 1
        elif part in _NAMED_KEYS:
            vk = _NAMED_KEYS[part]
        else:
            return None
    if vk is None or not mods:
        return None
    return mods, vk


class WindowsHotkey(QAbstractNativeEventFilter):
    def __init__(self) -> None:
        super().__init__()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL
        self._user32 = user32
        self._callback: Callable[[], None] | None = None
        self._registered = False

    def register(self, spec: str, on_triggered: Callable[[], None]) -> bool:
        self.unregister()
        parsed = parse_hotkey(spec)
        if parsed is None:
            return False
        mods, vk = parsed
        # hwnd=None: WM_HOTKEY vào hàng đợi thông điệp của thread UI, Qt chuyển cho native event filter.
        if not self._user32.RegisterHotKey(None, _HOTKEY_ID, mods | MOD_NOREPEAT, vk):
            return False
        self._callback = on_triggered
        self._registered = True
        app = QCoreApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self)
        return True

    def unregister(self) -> None:
        if self._registered:
            self._user32.UnregisterHotKey(None, _HOTKEY_ID)
            self._registered = False
        app = QCoreApplication.instance()
        if app is not None:
            app.removeNativeEventFilter(self)
        self._callback = None

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (tên do Qt quy định)
        if self._callback is not None and bytes(event_type) == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                self._callback()
                return True, 0
        return False, 0
