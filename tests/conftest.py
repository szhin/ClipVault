import itertools
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # test UI không cần màn hình thật

import pytest

from clipvault.core.limits import Limits
from clipvault.core.model import Representation, Snapshot
from clipvault.engine.capture import CaptureService
from clipvault.engine.history import HistoryService
from clipvault.engine.paste import PasteService
from clipvault.storage.db import Database

INLINE_MAX = Limits().inline_max_bytes


@pytest.fixture
def data_dir(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "data"
    monkeypatch.setenv("CLIPVAULT_DATA_DIR", str(path))
    return path


@pytest.fixture
def clock():
    """Đồng hồ giả tăng 1 ms mỗi lần gọi."""
    counter = itertools.count(1_000)
    return lambda: next(counter)


@pytest.fixture
def db(data_dir):
    database = Database(data_dir)
    yield database
    try:
        database.close()
    except Exception:
        pass


@pytest.fixture
def make_service(db, clock):
    def factory(limits: Limits | None = None) -> CaptureService:
        return CaptureService(db, limits or Limits(), clock)

    return factory


@pytest.fixture
def service(make_service):
    return make_service()


class FakeWriter:
    """Thay WindowsClipboardWriter: ghi nhận những gì được ghi lên clipboard."""

    def __init__(self):
        self.writes: list[list[Representation]] = []
        self.sequence = 100
        self.error: Exception | None = None

    def write(self, representations):
        if self.error:
            raise self.error
        self.writes.append(list(representations))
        self.sequence += 1
        return self.sequence


@pytest.fixture
def writer():
    return FakeWriter()


@pytest.fixture
def written_sequences():
    return []


@pytest.fixture
def history(db, writer, clock, written_sequences):
    paste = PasteService(db, writer, on_written=written_sequences.append, clock=clock)
    return HistoryService(db, paste)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def wait_until(qapp, predicate, timeout_s: float = 3.0) -> bool:
    """Chạy event loop đến khi điều kiện đúng (ảnh tải nền, timer debounce)."""
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return predicate()


def text_rep(text: str) -> Representation:
    # CF_UNICODETEXT thật: UTF-16LE kèm NUL cuối.
    return Representation("CF_UNICODETEXT", "text/plain", (text + "\x00").encode("utf-16-le"))


def png_rep(size: int, seed: int = 0) -> Representation:
    header = b"\x89PNG\r\n\x1a\n"
    body = bytes((seed + i) % 251 for i in range(size - len(header)))
    return Representation("PNG", "image/png", header + body)


def snap(*reps: Representation) -> Snapshot:
    return Snapshot(tuple(reps), None, 0, None)


def query(db: Database, sql: str, params=()):
    return db._conn.execute(sql, params).fetchall()
