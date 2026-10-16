"""SQLite: lịch sử clipboard. Thông báo lỗi chỉ mang loại lỗi, không mang nội dung."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from clipvault.core.model import Representation, Snapshot, StoredItem
from clipvault.core.paths import DB_NAME
from clipvault.storage import schema
from clipvault.storage.blobstore import BlobStore


class StorageError(Exception):
    """Lỗi DB/lưu trữ. Message không chứa nội dung clipboard."""


@dataclass(frozen=True)
class SaveResult:
    item_id: int
    is_new: bool


@dataclass(frozen=True)
class Stats:
    items: int
    pinned_items: int
    blob_bytes: int  # tổng byte blob unique


class Database:
    """Một connection dùng chung, tuần tự hóa bằng lock (worker ghi là chính, test đọc từ thread khác)."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.blobs = BlobStore(self.data_dir / "blobs")
        self._lock = threading.RLock()
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self.data_dir / DB_NAME), isolation_level=None, check_same_thread=False
            )
        except (OSError, sqlite3.Error) as exc:
            raise StorageError(f"cannot open database: {type(exc).__name__}") from None
        try:
            schema.apply(self._conn)
            # Tìm kiếm không phân biệt hoa/thường cả với ký tự Unicode (LIKE chỉ lo ASCII).
            self._conn.create_function(
                "casefold", 1, lambda s: s.casefold() if isinstance(s, str) else "", deterministic=True
            )
        except (sqlite3.Error, schema.SchemaVersionError) as exc:
            self._conn.close()
            raise StorageError(f"cannot initialise database: {type(exc).__name__}") from None

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """Transaction ghi; sqlite3.Error được đổi thành StorageError (không kèm nội dung)."""
        with self._lock:
            c = self._conn
            try:
                c.execute("BEGIN IMMEDIATE")
                try:
                    yield c
                    c.execute("COMMIT")
                except BaseException:
                    c.execute("ROLLBACK")
                    raise
            except sqlite3.Error as exc:
                raise StorageError(f"write failed: {type(exc).__name__}") from None

    def _scrub(self) -> None:
        """Sau khi xóa: checkpoint + cắt WAL để bản sao cũ của trang đã xóa không còn trên đĩa."""
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass  # đang có reader: lần checkpoint tự động sau sẽ dọn

    # --- ghi ---------------------------------------------------------------------------------

    def find_item(self, item_hash: bytes) -> int | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM items WHERE item_hash = ?", (item_hash,)
            ).fetchone()
        return row[0] if row else None

    def touch(self, item_id: int, now: int) -> None:
        """Copy lại nội dung trùng: nổi lên đầu, tăng bộ đếm."""
        with self._lock:
            try:
                self._conn.execute(
                    "UPDATE items SET last_seen_at = ?, copy_count = copy_count + 1 WHERE id = ?",
                    (now, item_id),
                )
            except sqlite3.Error as exc:
                raise StorageError(f"touch failed: {type(exc).__name__}") from None

    def save(
        self,
        snapshot: Snapshot,
        item_hash: bytes,
        blob_hashes: Sequence[bytes],
        kind: str,
        preview: str | None,
        search_text: str | None,
        now: int,
        inline_max_bytes: int,
        tags: Iterable[str] = (),
    ) -> SaveResult:
        """Lưu mục mới (hoặc cập nhật nếu trùng item_hash).

        File ngoài được ghi trước, DB commit sau; DB lỗi thì xóa các file vừa tạo.
        """
        with self._lock:
            existing = self.find_item(item_hash)
            if existing is not None:
                self.touch(existing, now)
                return SaveResult(existing, False)

            created: list[str] = []
            try:
                for rep, bh in zip(snapshot.representations, blob_hashes, strict=True):
                    if len(rep.data) > inline_max_bytes and self.blobs.write(bh.hex(), rep.data):
                        created.append(bh.hex())
                try:
                    item_id = self._insert(
                        snapshot, item_hash, blob_hashes, kind, preview, search_text, now,
                        inline_max_bytes, tuple(tags),
                    )
                except sqlite3.Error as exc:
                    raise StorageError(f"save failed: {type(exc).__name__}") from None
            except BaseException:
                for hex_hash in created:
                    self.blobs.delete(hex_hash)
                raise
            return SaveResult(item_id, True)

    def _insert(
        self, snapshot, item_hash, blob_hashes, kind, preview, search_text, now, inline_max_bytes,
        tags,
    ) -> int:
        c = self._conn
        c.execute("BEGIN IMMEDIATE")
        try:
            cur = c.execute(
                "INSERT INTO items (item_hash, created_at, last_seen_at, source_app, kind,"
                " total_size, preview, search_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (item_hash, now, now, snapshot.source_app, kind, snapshot.total_size,
                 preview, search_text),
            )
            item_id = cur.lastrowid
            for ord_, (rep, bh) in enumerate(zip(snapshot.representations, blob_hashes, strict=True)):
                external = len(rep.data) > inline_max_bytes
                c.execute(
                    "INSERT OR IGNORE INTO blobs (hash, size, data, external) VALUES (?, ?, ?, ?)",
                    (bh, len(rep.data), None if external else rep.data, int(external)),
                )
                c.execute(
                    "INSERT INTO representations (item_id, ord, native_format, mime, blob_hash)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (item_id, ord_, rep.native_format, rep.mime, bh),
                )
            c.executemany(
                "INSERT OR IGNORE INTO tags (item_id, tag) VALUES (?, ?)", [(item_id, t) for t in tags]
            )
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        return item_id

    def set_pinned(self, item_id: int, pinned: bool) -> None:
        with self._lock:
            try:
                self._conn.execute("UPDATE items SET pinned = ? WHERE id = ?", (int(pinned), item_id))
            except sqlite3.Error as exc:
                raise StorageError(f"pin failed: {type(exc).__name__}") from None

    def delete_items(self, ids: Sequence[int]) -> int:
        """Xóa mục, rồi blob không còn tham chiếu: DB trước, file sau. Trả số mục đã xóa."""
        if not ids:
            return 0
        with self._lock:
            try:
                c = self._conn
                c.execute("BEGIN IMMEDIATE")
                try:
                    marks = ",".join("?" * len(ids))
                    cur = c.execute(f"DELETE FROM items WHERE id IN ({marks})", tuple(ids))
                    deleted = cur.rowcount
                    orphans = c.execute(
                        "SELECT hash, external FROM blobs WHERE hash NOT IN"
                        " (SELECT blob_hash FROM representations)"
                    ).fetchall()
                    c.execute(
                        "DELETE FROM blobs WHERE hash NOT IN (SELECT blob_hash FROM representations)"
                    )
                    c.execute("COMMIT")
                except BaseException:
                    c.execute("ROLLBACK")
                    raise
            except sqlite3.Error as exc:
                raise StorageError(f"delete failed: {type(exc).__name__}") from None
            for h, external in orphans:
                if external:
                    self.blobs.delete(bytes(h).hex())
            self._scrub()
            return deleted

    @staticmethod
    def _scope_where(category: str | None, include_pinned: bool) -> tuple[str, list]:
        where: list[str] = []
        params: list = []
        if category:
            where.append("EXISTS (SELECT 1 FROM tags t WHERE t.item_id = items.id AND t.tag = ?)")
            params.append("cat:" + category)
        if not include_pinned:
            where.append("pinned = 0")
        return (" WHERE " + " AND ".join(where)) if where else "", params

    def scope_summary(self, category: str | None, include_pinned: bool) -> tuple[int, int]:
        """(số mục, tổng byte payload) của phạm vi xóa; category None = mọi loại."""
        where, params = self._scope_where(category, include_pinned)
        with self._lock:
            count, size = self._conn.execute(
                f"SELECT COUNT(*), COALESCE(SUM(total_size), 0) FROM items{where}", params
            ).fetchone()
        return count, size

    def _delete_where(self, where: str, params: Sequence) -> int:
        """Xóa mục theo điều kiện trong MỘT transaction cùng blob mồ côi; file ngoài xóa sau khi commit."""
        with self._lock:
            try:
                c = self._conn
                c.execute("BEGIN IMMEDIATE")
                try:
                    deleted = c.execute(f"DELETE FROM items{where}", tuple(params)).rowcount
                    orphans = c.execute(
                        "SELECT hash, external FROM blobs WHERE hash NOT IN"
                        " (SELECT blob_hash FROM representations)"
                    ).fetchall()
                    c.execute("DELETE FROM blobs WHERE hash NOT IN (SELECT blob_hash FROM representations)")
                    c.execute("COMMIT")
                except BaseException:
                    c.execute("ROLLBACK")
                    raise
            except sqlite3.Error as exc:
                raise StorageError(f"delete failed: {type(exc).__name__}") from None
            for h, external in orphans:
                if external:
                    self.blobs.delete(bytes(h).hex())
            self._scrub()
            return deleted

    def delete_scope(self, category: str | None, include_pinned: bool) -> int:
        where, params = self._scope_where(category, include_pinned)
        return self._delete_where(where, params)

    def count_older_than(self, cutoff_ms: int) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM items WHERE pinned = 0 AND last_seen_at < ?", (cutoff_ms,)
            ).fetchone()[0]

    def delete_older_than(self, cutoff_ms: int) -> int:
        """Xóa mục chưa ghim có last_seen_at < cutoff. Mục ghim không bao giờ bị động đến."""
        return self._delete_where(" WHERE pinned = 0 AND last_seen_at < ?", (cutoff_ms,))

    def sweep_orphans(self) -> int:
        """Dọn file blob mồ côi. Giữ lock để không xóa nhầm file capture đang ghi dở."""
        with self._lock:
            return self.blobs.sweep(self.external_hashes())

    # --- đọc ---------------------------------------------------------------------------------

    _ITEM_COLS = (
        "i.id, i.created_at, i.last_seen_at, i.copy_count, i.pinned, i.source_app, i.kind,"
        " i.total_size, i.preview,"
        " (SELECT group_concat(tag, char(31)) FROM tags WHERE item_id = i.id)"
    )

    @staticmethod
    def _to_item(r) -> StoredItem:
        tags = frozenset(r[9].split("\x1f")) if r[9] else frozenset()
        return StoredItem(r[0], r[1], r[2], r[3], bool(r[4]), r[5], r[6], r[7], r[8], tags)

    def list_items(self, limit: int = 100) -> list[StoredItem]:
        return self.query_items(limit=limit)

    def query_items(
        self,
        category: str | None = None,
        pinned_only: bool = False,
        text: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StoredItem]:
        """Danh sách theo thứ tự hiển thị (ghim trước, mới xem gần nhất trước), có phân trang."""
        where: list[str] = []
        params: list = []
        if pinned_only:
            where.append("i.pinned = 1")
        if category:
            where.append("EXISTS (SELECT 1 FROM tags t WHERE t.item_id = i.id AND t.tag = ?)")
            params.append("cat:" + category)
        if text:
            escaped = text.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.append("casefold(COALESCE(i.search_text, i.preview, '')) LIKE ? ESCAPE '\\'")
            params.append(f"%{escaped}%")
        sql = (
            f"SELECT {self._ITEM_COLS} FROM items i"
            + (" WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY i.pinned DESC, i.last_seen_at DESC, i.id DESC LIMIT ? OFFSET ?"
        )
        with self._lock:
            rows = self._conn.execute(sql, (*params, limit, offset)).fetchall()
        return [self._to_item(r) for r in rows]

    def get_item(self, item_id: int) -> StoredItem | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {self._ITEM_COLS} FROM items i WHERE i.id = ?", (item_id,)
            ).fetchone()
        return self._to_item(row) if row else None

    def all_item_ids(self) -> list[int]:
        with self._lock:
            return [r[0] for r in self._conn.execute("SELECT id FROM items ORDER BY id").fetchall()]

    def representation_meta(self, item_id: int) -> list[tuple[str, str]]:
        """(native_format, mime) theo thứ tự OS, không đọc payload."""
        with self._lock:
            return self._conn.execute(
                "SELECT native_format, mime FROM representations WHERE item_id = ? ORDER BY ord",
                (item_id,),
            ).fetchall()

    def set_classification(self, item_id: int, kind: str, tags: Iterable[str]) -> None:
        """Ghi kết quả phân loại lại. Mục đã Change Type (tag `manual`) giữ nguyên `cat:*`."""
        tags = list(tags)
        with self._tx() as c:
            manual = c.execute(
                "SELECT 1 FROM tags WHERE item_id = ? AND tag = 'manual'", (item_id,)
            ).fetchone()
            if manual:
                c.execute(
                    "DELETE FROM tags WHERE item_id = ? AND tag != 'manual' AND tag NOT LIKE 'cat:%'",
                    (item_id,),
                )
                tags = [t for t in tags if not t.startswith("cat:")]
            else:
                c.execute("DELETE FROM tags WHERE item_id = ?", (item_id,))
            c.executemany("INSERT OR IGNORE INTO tags VALUES (?, ?)", [(item_id, t) for t in tags])
            c.execute("UPDATE items SET kind = ? WHERE id = ?", (kind, item_id))

    def change_category(self, item_id: int, category: str) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM tags WHERE item_id = ? AND tag LIKE 'cat:%'", (item_id,))
            c.execute(
                "INSERT OR IGNORE INTO tags VALUES (?, ?), (?, 'manual')",
                (item_id, "cat:" + category, item_id),
            )

    def set_setting(self, key: str, value: str) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def representations(
        self, item_id: int, native_format: str | None = None
    ) -> list[Representation]:
        """Mọi representation của mục theo thứ tự OS, hoặc chỉ một định dạng nếu có `native_format`."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT r.native_format, r.mime, b.hash, b.data, b.external FROM representations r"
                " JOIN blobs b ON b.hash = r.blob_hash WHERE r.item_id = ?"
                " AND (? IS NULL OR r.native_format = ?) ORDER BY r.ord",
                (item_id, native_format, native_format),
            ).fetchall()
        out = []
        for native_format, mime, h, data, external in rows:
            if external:
                try:
                    data = self.blobs.read(bytes(h).hex())
                except OSError as exc:
                    raise StorageError(f"blob file unreadable: {type(exc).__name__}") from None
            out.append(Representation(native_format, mime, bytes(data)))
        return out

    def stats(self) -> Stats:
        with self._lock:
            items, pinned = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(pinned), 0) FROM items"
            ).fetchone()
            (blob_bytes,) = self._conn.execute("SELECT COALESCE(SUM(size), 0) FROM blobs").fetchone()
        return Stats(items, pinned, blob_bytes)

    def prune_candidates(self, exclude_id: int | None = None) -> list[int]:
        """Id mục chưa ghim, cũ nhất (theo last_seen_at) trước."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM items WHERE pinned = 0 AND id IS NOT ?"
                " ORDER BY last_seen_at ASC, id ASC",
                (exclude_id,),
            ).fetchall()
        return [r[0] for r in rows]

    def external_hashes(self) -> set[str]:
        with self._lock:
            rows = self._conn.execute("SELECT hash FROM blobs WHERE external = 1").fetchall()
        return {bytes(r[0]).hex() for r in rows}

    def settings(self) -> dict[str, str]:
        with self._lock:
            return dict(self._conn.execute("SELECT key, value FROM settings").fetchall())
