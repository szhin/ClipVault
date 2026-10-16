import os
import sys

import pytest

from clipvault.adapters.windows import clipboard as win

CF_TEXT, CF_BITMAP, CF_OEMTEXT = 1, 2, 7
PNG_ID, HTML_ID = 0xC100, 0xC101


def _names(specs):
    return [s.native_format for s in specs]


def test_selects_allowlist_in_os_order():
    avail = [(PNG_ID, "PNG"), (win.CF_DIBV5, ""), (win.CF_UNICODETEXT, "")]
    assert _names(win.select_formats(avail)) == ["PNG", "CF_DIBV5", "CF_UNICODETEXT"]


def test_dibv5_preferred_over_dib():
    both = win.select_formats([(win.CF_DIB, ""), (win.CF_DIBV5, "")])
    assert _names(both) == ["CF_DIBV5"]
    only_dib = win.select_formats([(win.CF_DIB, "")])
    assert _names(only_dib) == ["CF_DIB"] and only_dib[0].mime == "image/bmp"


def test_drops_synthesized_and_gdi_formats():
    avail = [(CF_TEXT, ""), (CF_OEMTEXT, ""), (CF_BITMAP, ""), (win.CF_UNICODETEXT, "")]
    assert _names(win.select_formats(avail)) == ["CF_UNICODETEXT"]


def test_unknown_formats_give_empty_selection():
    assert win.select_formats([(HTML_ID, "SomeVendorFormat"), (0xC200, "Other")]) == []
    assert win.select_formats([]) == []


@pytest.mark.parametrize(
    "available,history",
    [
        ([(win.CF_UNICODETEXT, ""), (0xC300, win.EXCLUDE_MONITOR)], None),
        ([(win.CF_UNICODETEXT, ""), (0xC301, win.VIEWER_IGNORE)], None),
        ([(win.CF_UNICODETEXT, ""), (0xC302, win.CAN_INCLUDE_HISTORY)], 0),
    ],
)
def test_privacy_flags_mean_do_not_store(available, history):
    assert win.select_formats(available, history) is None


def test_can_include_history_nonzero_is_allowed():
    avail = [(win.CF_UNICODETEXT, ""), (0xC302, win.CAN_INCLUDE_HISTORY)]
    assert _names(win.select_formats(avail, 1)) == ["CF_UNICODETEXT"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_reader_constructs_and_reports_sequence_number():
    seq = win.WindowsClipboardReader().sequence_number()
    assert isinstance(seq, int) and seq >= 0


@pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("CLIPVAULT_LIVE_CLIPBOARD") != "1",
    reason="ghi đè clipboard thật; bật bằng CLIPVAULT_LIVE_CLIPBOARD=1",
)
def test_live_clipboard_roundtrip():
    import subprocess

    # conftest ép Qt sang platform "offscreen" (clipboard ảo), nên đặt text bằng Qt ở tiến trình
    # con dùng platform "windows" để ghi vào clipboard hệ thống thật.
    code = (
        "from PySide6.QtGui import QGuiApplication\n"
        "app = QGuiApplication([])\n"
        "app.clipboard().setText('clipvault-live-test')\n"
        "app.processEvents()\n"
    )
    subprocess.run([sys.executable, "-I", "-c", code], check=True, timeout=30,
                   env={**os.environ, "QT_QPA_PLATFORM": "windows"})
    reader = win.WindowsClipboardReader()
    snapshot = reader.read_snapshot(10 * 1024 * 1024)
    assert snapshot is not None
    text = next(r for r in snapshot.representations if r.native_format == "CF_UNICODETEXT")
    assert text.data.decode("utf-16-le").rstrip("\x00") == "clipvault-live-test"
    assert snapshot.sequence is not None


# --- phím tắt toàn cục ------------------------------------------------------------------------------


from clipvault.adapters.windows import hotkey as hk  # noqa: E402


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("Ctrl+Shift+V", (hk.MOD_CONTROL | hk.MOD_SHIFT, ord("V"))),
        ("ctrl+alt+k", (hk.MOD_CONTROL | hk.MOD_ALT, ord("K"))),
        ("Win+Shift+9", (hk.MOD_WIN | hk.MOD_SHIFT, ord("9"))),
        ("Ctrl+F12", (hk.MOD_CONTROL, 0x7B)),
        ("Alt+Space", (hk.MOD_ALT, 0x20)),
        (" Ctrl + Shift + V ", (hk.MOD_CONTROL | hk.MOD_SHIFT, ord("V"))),
    ],
)
def test_parse_hotkey(spec, expected):
    assert hk.parse_hotkey(spec) == expected


@pytest.mark.parametrize("spec", ["", "V", "Ctrl", "Ctrl+", "Ctrl+A+B", "Ctrl+F99", "Ctrl+é", "Hyper+V", "+V"])
def test_parse_hotkey_rejects_invalid(spec):
    assert hk.parse_hotkey(spec) is None  # phím trần bị từ chối: sẽ chặn gõ phím đó ở mọi app


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_native_event_filter_dispatches_only_our_hotkey(qapp):
    import ctypes
    from ctypes import wintypes

    f = hk.WindowsHotkey()
    calls = []
    f._callback = lambda: calls.append(1)  # không đăng ký thật: chỉ thử đường xử lý thông điệp

    def feed(message, wparam, kind=b"windows_generic_MSG"):
        msg = wintypes.MSG()
        msg.message, msg.wParam = message, wparam
        return f.nativeEventFilter(kind, ctypes.addressof(msg))

    assert feed(hk.WM_HOTKEY, hk._HOTKEY_ID) == (True, 0)
    assert feed(hk.WM_HOTKEY, hk._HOTKEY_ID + 1) == (False, 0)  # phím tắt của app khác
    assert feed(0x0100, hk._HOTKEY_ID) == (False, 0)  # không phải WM_HOTKEY
    assert feed(hk.WM_HOTKEY, hk._HOTKEY_ID, kind=b"other") == (False, 0)
    assert calls == [1]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_real_register_unregister_and_conflict(qapp):
    first, second = hk.WindowsHotkey(), hk.WindowsHotkey()
    spec = "Ctrl+Alt+Shift+F24"  # tổ hợp hiếm để không đụng app đang chạy
    try:
        assert first.register(spec, lambda: None) is True
        assert second.register(spec, lambda: None) is False  # trùng → báo thất bại, không ném lỗi
        assert first.register("not a hotkey", lambda: None) is False
        assert first.register(spec, lambda: None) is True  # đăng ký lại sau khi hủy được
    finally:
        first.unregister()
        second.unregister()
    third = hk.WindowsHotkey()
    try:
        assert third.register(spec, lambda: None) is True  # đã giải phóng
    finally:
        third.unregister()


# --- ghi clipboard (Copy) -----------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_writer_resolves_format_ids_without_touching_clipboard():
    w = win.WindowsClipboardWriter()
    assert w._format_id("CF_UNICODETEXT") == win.CF_UNICODETEXT
    assert w._format_id("CF_DIBV5") == win.CF_DIBV5
    assert w._format_id("PNG") >= 0xC000  # định dạng đăng ký
    assert w._format_id("PNG") == w._format_id("PNG")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_writer_rejects_empty_write():
    from clipvault.core.ports import ClipboardWriteError

    with pytest.raises(ClipboardWriteError):
        win.WindowsClipboardWriter().write([])


@pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("CLIPVAULT_LIVE_CLIPBOARD") != "1",
    reason="ghi đè clipboard thật; bật bằng CLIPVAULT_LIVE_CLIPBOARD=1",
)
def test_live_writer_restores_exact_bytes_and_formats():
    from clipvault.core.model import Representation

    reps = [
        Representation("PNG", "image/png", b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8),
        Representation("CF_UNICODETEXT", "text/plain", "chào 😀\x00".encode("utf-16-le")),
        Representation("HTML Format", "text/html", b"Version:0.9\r\n<b>x</b>"),
    ]
    writer, reader = win.WindowsClipboardWriter(), win.WindowsClipboardReader()
    sequence = writer.write(reps)
    assert sequence == reader.sequence_number()  # nhờ vậy engine bỏ qua lần đổi do chính mình
    got = reader.read_snapshot(10 * 1024 * 1024)
    by_format = {r.native_format: r.data for r in got.representations}
    assert by_format["PNG"] == reps[0].data
    assert by_format["CF_UNICODETEXT"] == reps[1].data  # byte-exact, kể cả NUL cuối
