"""Hash chống trùng (ARCHITECTURE.md §5). Không chuẩn hóa nội dung trước khi hash."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from clipvault.core.model import Representation


def blob_hash(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _u64(n: int) -> bytes:
    return n.to_bytes(8, "big")


def item_hash(reps: Sequence[Representation], blob_hashes: Sequence[bytes]) -> bytes:
    """SHA-256 của các representation sắp theo native_format: len(name)‖name‖len(data)‖blob_hash."""
    h = hashlib.sha256()
    for rep, bh in sorted(zip(reps, blob_hashes, strict=True), key=lambda p: p[0].native_format):
        name = rep.native_format.encode("utf-8")
        h.update(_u64(len(name)) + name + _u64(len(rep.data)) + bh)
    return h.digest()
