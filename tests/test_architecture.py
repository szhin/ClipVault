"""Quy tắc tầng: code dùng chung (ngoài adapters/) không import API hệ điều hành."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "clipvault"
ADAPTERS = SRC / "adapters"
FORBIDDEN = {
    "ctypes", "winreg", "msvcrt", "_winapi", "winsound",
    "win32api", "win32clipboard", "win32con", "win32gui", "pywintypes",
    "objc", "AppKit", "Foundation", "Quartz", "Cocoa",
}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_imported_roots_handles_utf8_bom(tmp_path):
    # Hồi quy: file lưu kèm BOM UTF-8 (PowerShell Set-Content) từng gây SyntaxError.
    f = tmp_path / "bom.py"
    f.write_bytes(b"\xef\xbb\xbfimport ctypes.wintypes\nfrom AppKit import X\n")
    assert _imported_roots(f) == {"ctypes", "AppKit"}


def test_shared_code_does_not_import_os_apis():
    files = [p for p in SRC.rglob("*.py") if ADAPTERS not in p.parents]
    assert files, "không tìm thấy mã nguồn"
    violations = {
        str(p.relative_to(SRC)): sorted(_imported_roots(p) & FORBIDDEN)
        for p in files
        if _imported_roots(p) & FORBIDDEN
    }
    assert violations == {}
