"""Thư mục dữ liệu của app. Không bao giờ nằm trong mã nguồn hay thư mục cài đặt."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "ClipVault"
ENV_DATA_DIR = "CLIPVAULT_DATA_DIR"
DB_NAME = "clipvault.db"

_PACKAGE_DIR = Path(__file__).resolve().parents[1]


def _forbidden_roots() -> list[Path]:
    roots = [_PACKAGE_DIR, Path(sys.prefix), Path(sys.base_prefix), Path(sys.executable).parent]
    # Bố cục src/: chặn cả thư mục dự án chứa src/.
    if _PACKAGE_DIR.parent.name == "src":
        roots.append(_PACKAGE_DIR.parent.parent)
    return [r.resolve() for r in roots]


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise RuntimeError("LOCALAPPDATA is not set")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    raise RuntimeError(f"unsupported platform: {sys.platform}")


def data_dir() -> Path:
    raw = os.environ.get(ENV_DATA_DIR)
    path = (Path(raw) if raw else default_data_dir()).resolve()
    for root in _forbidden_roots():
        if _is_within(path, root):
            raise ValueError(f"data dir must be outside source/install dir: {path}")
    return path
