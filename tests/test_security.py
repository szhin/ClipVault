"""Phase 4: rà soát bảo mật. Mỗi test khóa một quy tắc trong CLAUDE.md (riêng tư, không mạng, không rò rỉ nội dung)."""

import ast
import logging
import os
import struct
import zlib
from pathlib import Path

import pytest

from clipvault.core.model import Representation
from clipvault.engine.capture import CaptureService
from clipvault.storage.blobstore import BlobStore
from clipvault.storage.db import StorageError
from clipvault.ui.images import decode_image

from conftest import snap, text_rep

SRC = Path(__file__).resolve().parents[1] / "src" / "clipvault"
SECRET = "SECRETPASSWORD-hunter2-xyz"


def _db_bytes(db) -> bytes:
    """Toàn bộ byte trên đĩa của DB + WAL (nơi dữ liệu đã xóa có thể còn sót)."""
    db._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return b"".join(p.read_bytes() for p in sorted(db.data_dir.glob("clipvault.db*")))


def _leaks(raw: bytes) -> bool:
    return SECRET.encode() in raw or SECRET.encode("utf-16-le") in raw


# --- dữ liệu đã xóa không được còn trong file DB -------------------------------------------------------------------------


@pytest.mark.parametrize("how", ["delete_items", "delete_scope", "delete_older_than", "history_delete_scope"])
def test_deleted_content_is_physically_gone_from_db_files(service, db, history, how):
    item = service.process(snap(text_rep(SECRET))).item_id
    assert _leaks(_db_bytes(db))  # kiểm tra test có tác dụng: trước khi xóa phải thấy
    if how == "delete_items":
        db.delete_items([item])
    elif how == "delete_scope":
        db.delete_scope(None, True)
    elif how == "delete_older_than":
        db.delete_older_than(10**12)
    else:
        history.delete_scope("all", include_pinned=True)
    assert not _leaks(_db_bytes(db))


def test_retention_prune_also_scrubs(service, db):
    from clipvault.core.limits import Limits
    from clipvault.engine import retention

    service.process(snap(text_rep(SECRET)))
    service.process(snap(text_rep("newer one")))
    retention.enforce(db, Limits(max_items=1, prune_ratio=0.5))
    assert not _leaks(_db_bytes(db))


# --- không rò rỉ nội dung qua log / thông báo lỗi ---------------------------------------------------------------------------


def test_logs_and_errors_never_contain_clipboard_content(service, db, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    # đường thành công, trùng, quá lớn và các đường lỗi
    service.process(snap(text_rep(SECRET)))
    service.process(snap(text_rep(SECRET)))
    service.limits = service.limits.__class__(max_item_bytes=10)
    service.process(snap(text_rep(SECRET)))
    service.limits = service.limits.__class__()
    monkeypatch.setattr("clipvault.engine.capture.classify", lambda s: (_ for _ in ()).throw(ValueError(SECRET)))
    service.process(snap(text_rep(SECRET + "2")))
    monkeypatch.setattr(db, "save", lambda *a, **k: (_ for _ in ()).throw(StorageError("write failed: OperationalError")))
    service.process(snap(text_rep(SECRET + "3")))
    assert SECRET not in caplog.text and SECRET.encode("utf-16-le").hex() not in caplog.text


def test_history_errors_do_not_carry_content(history, service, db, monkeypatch):
    from clipvault.engine.history import HistoryError

    item = service.process(snap(text_rep(SECRET))).item_id
    monkeypatch.setattr(db, "representations", lambda *a, **k: (_ for _ in ()).throw(OSError(SECRET)))
    with pytest.raises(HistoryError) as exc:
        history.text(item)
    assert SECRET not in str(exc.value)


# --- không gọi mạng, không chạy mã ngoài --------------------------------------------------------------------------------------

FORBIDDEN_IMPORTS = {
    "socket", "ssl", "urllib", "urllib3", "http", "httpx", "requests", "aiohttp", "ftplib", "smtplib", "telnetlib",
    "xmlrpc", "websocket", "websockets", "subprocess", "pickle", "marshal", "shelve", "webbrowser",
}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__"}


def test_source_has_no_network_or_dynamic_code():
    bad = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                root = n.split(".")[0]
                if root in FORBIDDEN_IMPORTS or "QtNetwork" in n or "QtWebEngine" in n:
                    bad.append(f"{path.name}: import {n}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                bad.append(f"{path.name}:{node.lineno} {node.func.id}()")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("system", "popen"):
                bad.append(f"{path.name}:{node.lineno} .{node.func.attr}()")
    assert bad == []


def test_only_local_urls_are_opened():
    """QDesktopServices chỉ được mở thư mục dữ liệu cục bộ (fromLocalFile), không URL ngoài."""
    for path in (SRC / "ui").glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "openUrl" in line:
                assert "fromLocalFile" in line, f"{path.name}: {line.strip()}"


# --- SQL, đường dẫn, ảnh độc hại -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["'; DROP TABLE items; --", "%", "_", "\\", "x' OR '1'='1"])
def test_search_input_is_never_interpreted_as_sql(service, db, text):
    service.process(snap(text_rep("ordinary item")))
    assert db.query_items(text=text) == []
    assert len(db.list_items()) == 1  # bảng còn nguyên


@pytest.mark.parametrize("bad", ["../../evil", "..\\evil", "ab/../../x", "zz" * 32, "AB" + "c" * 62, "", "ab"])
def test_blobstore_rejects_non_hash_names(tmp_path, bad):
    store = BlobStore(tmp_path / "blobs")
    for op in (lambda: store.path_for(bad), lambda: store.write(bad, b"x"), lambda: store.read(bad),
               lambda: store.delete(bad)):
        with pytest.raises(ValueError):
            op()
    assert not (tmp_path / "evil").exists()


def _png_bomb(w, h):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))

    raw = (b"\x00" + b"\x00" * ((w + 7) // 8)) * h
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 1, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def test_decompression_bomb_images_are_rejected(qapp):
    big = decode_image(Representation("PNG", "image/png", _png_bomb(20000, 20000)), 96)
    assert big.isNull()
    dib = struct.pack("<IiiHHIIiiI", 40, 100000, 100000, 1, 24, 0, 0, 0, 0, 0) + b"\x00" * 64
    assert decode_image(Representation("CF_DIB", "image/bmp", dib), 96).isNull()
    assert decode_image(Representation("PNG", "image/png", b"\x89PNG\r\n\x1a\n" + os.urandom(64)), 96).isNull()
    assert decode_image(Representation("CF_DIBV5", "image/bmp", b"\x00" * 10), 96).isNull()


# --- hiển thị nội dung không được hiểu là HTML ---------------------------------------------------------------------------------------


def test_preview_labels_render_plain_text_only(qapp, history):
    from PySide6.QtCore import Qt
    from clipvault.ui.images import ImageProvider
    from clipvault.ui.preview import PreviewPanel

    panel = PreviewPanel(history, ImageProvider(history.image))
    for label in (panel.title, panel.meta, panel.message):
        assert label.textFormat() == Qt.TextFormat.PlainText
    panel.message.setText('<a href="http://evil.example">x</a><img src="http://evil.example/a.png">')
    assert "<a" in panel.message.text() and panel.message.openExternalLinks() is False


def test_data_dir_cannot_be_inside_source(monkeypatch):
    from clipvault.core import paths

    monkeypatch.setenv(paths.ENV_DATA_DIR, str(SRC / "data"))
    with pytest.raises(ValueError):
        paths.data_dir()
