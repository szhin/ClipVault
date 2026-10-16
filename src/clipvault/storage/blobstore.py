"""Blob lớn lưu thành file content-addressed `blobs/<2 hex đầu>/<hex>` trong thư mục dữ liệu."""

from __future__ import annotations

import logging
import os
import re
import uuid
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger(__name__)
_HASH_RE = re.compile(r"[0-9a-f]{64}")


class BlobStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.tmp = self.root / "tmp"

    def path_for(self, hex_hash: str) -> Path:
        # Chỉ nhận đúng SHA-256 dạng hex thường: chặn "../", đường dẫn tuyệt đối, tên lạ.
        if not _HASH_RE.fullmatch(hex_hash):
            raise ValueError("invalid blob name")
        return self.root / hex_hash[:2] / hex_hash

    def exists(self, hex_hash: str) -> bool:
        return self.path_for(hex_hash).is_file()

    def write(self, hex_hash: str, data: bytes) -> bool:
        """Ghi nguyên tử: tmp → fsync → os.replace. Trả False nếu file đã có sẵn."""
        final = self.path_for(hex_hash)
        if final.is_file():
            return False
        self.tmp.mkdir(parents=True, exist_ok=True)
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.tmp / uuid.uuid4().hex
        try:
            with open(tmp, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, final)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return True

    def read(self, hex_hash: str) -> bytes:
        return self.path_for(hex_hash).read_bytes()

    def delete(self, hex_hash: str) -> None:
        try:
            self.path_for(hex_hash).unlink(missing_ok=True)
        except OSError as exc:
            # File còn sót sẽ được orphan sweep dọn ở lần khởi động sau.
            log.warning("could not delete blob file: %s", type(exc).__name__)

    def sweep(self, known: Iterable[str]) -> int:
        """Xóa blobs/tmp/* và file không có dòng tương ứng trong bảng blobs. Trả số file đã xóa."""
        keep = set(known)
        removed = 0
        if not self.root.is_dir():
            return 0
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            in_tmp = path.parent == self.tmp
            if in_tmp or path.name not in keep or path.parent.name != path.name[:2]:
                try:
                    path.unlink()
                    removed += 1
                except OSError as exc:
                    log.warning("sweep could not delete file: %s", type(exc).__name__)
        return removed
