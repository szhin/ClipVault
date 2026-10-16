from clipvault.core.limits import Limits
from clipvault.storage.blobstore import BlobStore

from conftest import query


def test_schema_version_and_pragmas(db):
    assert query(db, "PRAGMA user_version") == [(1,)]
    assert query(db, "PRAGMA journal_mode") == [("wal",)]
    assert query(db, "PRAGMA foreign_keys") == [(1,)]
    tables = {r[0] for r in query(db, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"items", "blobs", "representations", "tags", "settings"} <= tables


def test_reopening_existing_database_keeps_schema(data_dir):
    from clipvault.storage.db import Database

    Database(data_dir).close()
    db = Database(data_dir)
    try:
        assert query(db, "PRAGMA user_version") == [(1,)]
    finally:
        db.close()


def test_blobstore_write_is_atomic_and_idempotent(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    h = "ab" + "c" * 62
    assert store.write(h, b"data") is True
    assert store.write(h, b"data") is False
    assert store.read(h) == b"data"
    assert not list((tmp_path / "blobs" / "tmp").glob("*"))


def test_sweep_removes_tmp_and_orphans_but_keeps_known(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    known, orphan = "ab" + "1" * 62, "cd" + "2" * 62
    store.write(known, b"k")
    store.write(orphan, b"o")
    (store.tmp / "stale").write_bytes(b"t")
    assert store.sweep({known}) == 2
    assert store.exists(known) and not store.exists(orphan)
    assert not (store.tmp / "stale").exists()


def test_sweep_on_missing_root_is_noop(tmp_path):
    assert BlobStore(tmp_path / "nope").sweep(set()) == 0


def test_limits_from_settings(db):
    db._conn.execute("INSERT INTO settings VALUES ('limits.max_items', '42')")
    db._conn.execute("INSERT INTO settings VALUES ('limits.max_total_bytes', 'oops')")
    db._conn.execute("INSERT INTO settings VALUES ('limits.prune_ratio', '0.5')")
    limits = Limits.from_settings(db.settings())
    assert limits.max_items == 42 and limits.prune_ratio == 0.5
    assert limits.max_total_bytes == Limits().max_total_bytes  # giá trị hỏng → mặc định
