"""Phím tắt toàn cục macOS: Carbon RegisterEventHotKey qua ctypes (không cần quyền Accessibility).

CHƯA kiểm chứng trên máy thật. `parse_hotkey` là hàm thuần (test được trên Windows); phần Carbon chỉ chạy trên darwin.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from collections.abc import Callable

CMD, SHIFT, OPTION, CONTROL = 0x100, 0x200, 0x800, 0x1000  # cmdKey, shiftKey, optionKey, controlKey

_MODIFIERS = {"ctrl": CONTROL, "control": CONTROL, "shift": SHIFT, "alt": OPTION, "option": OPTION,
              "cmd": CMD, "command": CMD, "meta": CMD, "win": CMD}
_NAMED_KEYS = {"return": 36, "enter": 36, "tab": 48, "space": 49, "esc": 53, "delete": 117,
               "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
               "left": 123, "right": 124, "down": 125, "up": 126}
# Mã phím ANSI (kVK_ANSI_*), không phụ thuộc bố cục bàn phím.
_KEYS = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12,
    "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38,
    "k": 40, "n": 45, "m": 46,
    "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26, "8": 28, "9": 25, "0": 29,
}
_FUNCTION = [122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111]  # F1..F12

_SIGNATURE = int.from_bytes(b"CVLT", "big")
_HOTKEY_ID = 1
_EVENT_CLASS_KEYBOARD = int.from_bytes(b"keyb", "big")
_EVENT_HOTKEY_PRESSED = 5


def parse_hotkey(spec: str) -> tuple[int, int] | None:
    """"Ctrl+Shift+V" -> (modifiers Carbon, keycode). None nếu không hợp lệ (cần ít nhất một phím bổ trợ)."""
    mods, key = 0, None
    for part in (p.strip().lower() for p in spec.split("+")):
        if not part:
            return None
        if part in _MODIFIERS:
            mods |= _MODIFIERS[part]
        elif key is not None:
            return None  # hai phím chính
        elif part in _KEYS:
            key = _KEYS[part]
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 12:
            key = _FUNCTION[int(part[1:]) - 1]
        elif part in _NAMED_KEYS:
            key = _NAMED_KEYS[part]
        else:
            return None
    if key is None or not mods:
        return None
    return mods, key


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


class MacHotkey:
    def __init__(self) -> None:
        path = ctypes.util.find_library("Carbon")
        if not path:
            raise OSError("Carbon framework not found")
        carbon = ctypes.CDLL(path)
        carbon.GetApplicationEventTarget.argtypes = []
        carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
        carbon.InstallEventHandler.argtypes = [ctypes.c_void_p, _HANDLER, ctypes.c_uint32,
                                               ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p,
                                               ctypes.POINTER(ctypes.c_void_p)]
        carbon.InstallEventHandler.restype = ctypes.c_int32
        carbon.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID,
                                               ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        carbon.RegisterEventHotKey.restype = ctypes.c_int32
        carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        carbon.UnregisterEventHotKey.restype = ctypes.c_int32
        self._carbon = carbon
        self._callback: Callable[[], None] | None = None
        self._ref = ctypes.c_void_p()
        self._registered = False
        self._handler_ref = ctypes.c_void_p()
        self._handler = _HANDLER(self._on_event)  # giữ tham chiếu để không bị GC
        self._handler_installed = False

    def _on_event(self, _call_ref, _event, _user_data) -> int:
        if self._callback is not None:
            self._callback()
        return 0

    def register(self, spec: str, on_triggered: Callable[[], None]) -> bool:
        self.unregister()
        parsed = parse_hotkey(spec)
        if parsed is None:
            return False
        mods, keycode = parsed
        target = self._carbon.GetApplicationEventTarget()
        if not self._handler_installed:
            types = (_EventTypeSpec * 1)(_EventTypeSpec(_EVENT_CLASS_KEYBOARD, _EVENT_HOTKEY_PRESSED))
            if self._carbon.InstallEventHandler(target, self._handler, 1, types, None,
                                                ctypes.byref(self._handler_ref)) != 0:
                return False
            self._handler_installed = True
        hotkey_id = _EventHotKeyID(_SIGNATURE, _HOTKEY_ID)
        if self._carbon.RegisterEventHotKey(keycode, mods, hotkey_id, target, 0, ctypes.byref(self._ref)) != 0:
            return False
        self._callback = on_triggered
        self._registered = True
        return True

    def unregister(self) -> None:
        if self._registered:
            self._carbon.UnregisterEventHotKey(self._ref)
            self._registered = False
        self._callback = None
