"""Sinh packaging/version_info.txt (thông tin phiên bản của ClipVault.exe) từ clipvault.__version__."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def version() -> str:
    text = (ROOT / "src" / "clipvault" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def main() -> None:
    v = version()
    nums = (tuple(int(p) for p in re.findall(r"\d+", v)) + (0, 0, 0, 0))[:4]
    out = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'ClipVault'),
      StringStruct('FileDescription', 'ClipVault - clipboard manager'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'ClipVault'),
      StringStruct('OriginalFilename', 'ClipVault.exe'),
      StringStruct('ProductName', 'ClipVault'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    (ROOT / "packaging" / "version_info.txt").write_text(out, encoding="utf-8")
    print(v, file=sys.stdout)


if __name__ == "__main__":
    main()
