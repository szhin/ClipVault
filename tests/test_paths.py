import sys
from pathlib import Path

import pytest

from clipvault.core import paths


def test_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPVAULT_DATA_DIR", str(tmp_path / "d"))
    assert paths.data_dir() == (tmp_path / "d").resolve()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_default_is_localappdata(tmp_path, monkeypatch):
    monkeypatch.delenv("CLIPVAULT_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert paths.data_dir() == (tmp_path / "ClipVault").resolve()


@pytest.mark.parametrize(
    "inside",
    [
        Path(paths.__file__).parent / "data",  # thư mục mã nguồn
        Path(sys.prefix) / "clipvault-data",  # môi trường cài đặt
        Path(paths.__file__).resolve().parents[3] / "data",  # thư mục dự án
    ],
)
def test_rejects_source_and_install_dirs(inside, monkeypatch):
    monkeypatch.setenv("CLIPVAULT_DATA_DIR", str(inside))
    with pytest.raises(ValueError):
        paths.data_dir()
