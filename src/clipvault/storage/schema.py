"""Schema SQLite v1 (ARCHITECTURE.md §3). Đổi schema phải tăng SCHEMA_VERSION kèm migration có test."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA secure_delete=ON",  # ghi đè nội dung đã xóa bằng 0 (clipboard có thể chứa mật khẩu)
)

DDL = """
CREATE TABLE items (
  id            INTEGER PRIMARY KEY,
  item_hash     BLOB    NOT NULL UNIQUE,
  created_at    INTEGER NOT NULL,
  last_seen_at  INTEGER NOT NULL,
  copy_count    INTEGER NOT NULL DEFAULT 1,
  pinned        INTEGER NOT NULL DEFAULT 0,
  source_app    TEXT,
  kind          TEXT    NOT NULL,
  total_size    INTEGER NOT NULL,
  preview       TEXT,
  search_text   TEXT
);
CREATE INDEX idx_items_order ON items(pinned DESC, last_seen_at DESC);

CREATE TABLE blobs (
  hash      BLOB    PRIMARY KEY,
  size      INTEGER NOT NULL,
  data      BLOB,
  external  INTEGER NOT NULL DEFAULT 0,
  enc       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE representations (
  id             INTEGER PRIMARY KEY,
  item_id        INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  ord            INTEGER NOT NULL,
  native_format  TEXT    NOT NULL,
  mime           TEXT    NOT NULL,
  blob_hash      BLOB    NOT NULL REFERENCES blobs(hash),
  UNIQUE (item_id, native_format)
);
CREATE INDEX idx_repr_blob ON representations(blob_hash);

CREATE TABLE tags (
  item_id  INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  tag      TEXT    NOT NULL,
  PRIMARY KEY (item_id, tag)
);

CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class SchemaVersionError(Exception):
    pass


def apply(conn: sqlite3.Connection) -> None:
    for pragma in PRAGMAS:
        conn.execute(pragma)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    if version != 0:
        raise SchemaVersionError(f"unsupported schema version {version}")
    with conn:
        conn.executescript(f"BEGIN; {DDL} PRAGMA user_version = {SCHEMA_VERSION}; COMMIT;")
