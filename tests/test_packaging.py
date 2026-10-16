"""Phase 5: các ràng buộc của bản đóng gói (không cần chạy PyInstaller/Inno Setup)."""

import re
import sys
from pathlib import Path

import clipvault

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packaging"


def test_versions_agree():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "([^"]+)"', text, re.M).group(1) == clipvault.__version__
    sys.path.insert(0, str(PKG))
    try:
        import make_version_info
    finally:
        sys.path.remove(str(PKG))
    assert make_version_info.version() == clipvault.__version__


def test_icon_files_exist_and_ico_is_valid():
    assert (ROOT / "assets" / "icon.png").is_file()
    ico = (ROOT / "assets" / "icon.ico").read_bytes()
    assert ico[:4] == b"\x00\x00\x01\x00"  # header ICO hợp lệ


def test_installer_is_per_user_and_keeps_user_data():
    iss = (PKG / "installer.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in iss  # không cần quyền admin
    assert "{autopf}" in iss and "{commonpf" not in iss  # cài theo user, không vào Program Files chung
    # không có lệnh xóa dữ liệu người dùng khi gỡ cài đặt
    assert "[UninstallDelete]" not in iss
    assert " --background" in iss and "Tasks: startup" in iss  # tác vụ chạy cùng Windows dùng chế độ nền
    assert "Flags: unchecked" in iss  # chạy cùng Windows là tùy chọn, không mặc định


def test_spec_bundles_icon_and_excludes_network():
    spec = (PKG / "clipvault.spec").read_text(encoding="utf-8")
    assert "icon.png" in spec and "console=False" in spec
    assert "PySide6.QtNetwork" in spec and "PySide6.QtWebEngineCore" in spec


def test_entry_point_calls_main():
    assert "from clipvault.__main__ import main" in (PKG / "entry.py").read_text(encoding="utf-8")


def test_icon_lookup_supports_frozen_bundle(monkeypatch, tmp_path):
    from clipvault.ui import tray

    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "icon.png").write_bytes(b"x")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert tray._icon_path() == tmp_path / "assets" / "icon.png"
    monkeypatch.delattr(sys, "_MEIPASS")
    assert tray._icon_path() == ROOT / "assets" / "icon.png" and tray._icon_path().is_file()
