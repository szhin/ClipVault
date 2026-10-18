"""Phase 6: phần thuần của adapter macOS (chạy được trên mọi nền tảng, không cần pyobjc/Carbon)."""

import re
from pathlib import Path

import pytest

from clipvault.adapters.macos import clipboard as mac
from clipvault.adapters.macos import hotkey as hk
from clipvault.adapters.macos.notifier import PollingChangeNotifier

ROOT = Path(__file__).resolve().parents[1]


def _natives(specs):
    return [s.native_format for s in specs]


def test_selects_allowlist_in_os_order():
    avail = ["public.png", "public.tiff", "com.apple.flat-rtfd", "public.utf8-plain-text"]
    chosen = mac.select_types(avail)
    assert _natives(chosen) == ["public.png", "public.utf8-plain-text"]
    assert [s.mime for s in chosen] == ["image/png", "text/plain"]


def test_tiff_kept_only_without_png():
    only_tiff = mac.select_types(["public.tiff"])
    assert _natives(only_tiff) == ["public.tiff"] and only_tiff[0].mime == "image/tiff"


def test_unknown_types_give_empty_selection():
    assert mac.select_types(["public.html", "dyn.ah62d4rv4gu"]) == []
    assert mac.select_types([]) == []


@pytest.mark.parametrize("flag", sorted(mac.PRIVACY_TYPES))
def test_privacy_flags_skip_item(flag):
    assert mac.select_types(["public.utf8-plain-text", flag]) is None


def test_parse_hotkey():
    assert hk.parse_hotkey("Ctrl+Shift+V") == (hk.CONTROL | hk.SHIFT, 9)
    assert hk.parse_hotkey("cmd+option+F1") == (hk.CMD | hk.OPTION, 122)
    assert hk.parse_hotkey("Ctrl+Space") == (hk.CONTROL, 49)


@pytest.mark.parametrize("spec", ["V", "", "Ctrl+", "Ctrl+V+C", "Ctrl+F13", "Ctrl+Nope", "Shift"])
def test_parse_hotkey_rejects_invalid(spec):
    assert hk.parse_hotkey(spec) is None


def test_polling_notifier_fires_only_on_change(qapp):
    class Reader:
        value = 1

        def sequence_number(self):
            return self.value

    reader, calls = Reader(), []
    n = PollingChangeNotifier(reader, interval_ms=1000)
    n.start(lambda: calls.append(1))
    n._poll()
    assert calls == []
    reader.value = 2
    n._poll()
    n._poll()
    assert calls == [1]
    n.stop()
    reader.value = 3
    n._poll()
    assert calls == [1]


def test_macos_packaging_files():
    spec = (ROOT / "packaging" / "clipvault_macos.spec").read_text(encoding="utf-8")
    assert "BUNDLE(" in spec and "PySide6.QtNetwork" in spec and "console=False" in spec
    sh = (ROOT / "packaging" / "build_macos.sh").read_text(encoding="utf-8")
    assert "\r" not in sh and "hdiutil create" in sh and "iconutil" in sh
    wf = (ROOT / ".github" / "workflows" / "macos.yml").read_text(encoding="utf-8")
    assert "macos-latest" in wf and "pytest" in wf and "build_macos.sh" in wf


def test_pyobjc_is_darwin_only_dependency():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'"pyobjc-framework-Cocoa[^"]*sys_platform == \'darwin\'"', text)
