"""Giải mã ảnh clipboard (PNG, DIB/DIBV5) thành QImage để vẽ thumbnail/preview.

Chỉ tạo dữ liệu dẫn xuất trong bộ nhớ; payload gốc không bị sửa hay ghi lại.
"""

from __future__ import annotations

import struct
from collections import OrderedDict

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap

from clipvault.core.model import Representation

_BI_BITFIELDS, _BI_ALPHABITFIELDS = 3, 6


def dib_to_bmp(dib: bytes) -> bytes | None:
    """Thêm BITMAPFILEHEADER vào DIB/DIBV5 thô của clipboard để Qt đọc được. None nếu header hỏng."""
    if len(dib) < 40:
        return None
    header_size, _w, _h, _planes, bpp, compression, _img, _x, _y, clr_used = struct.unpack_from(
        "<IiiHHIIiiI", dib, 0
    )
    if header_size not in (40, 52, 56, 108, 124) or bpp == 0:
        return None
    colors = clr_used if clr_used else ((1 << bpp) if bpp <= 8 else 0)
    offset = 14 + header_size + colors * 4
    if header_size == 40 and compression == _BI_BITFIELDS:
        offset += 12
    elif header_size == 40 and compression == _BI_ALPHABITFIELDS:
        offset += 16
    if offset > 14 + len(dib):
        return None
    return b"BM" + struct.pack("<IHHI", 14 + len(dib), 0, 0, offset) + dib


def decode_image(rep: Representation, max_side: int | None = None) -> QImage:
    """QImage (có thể rỗng nếu không giải mã được). `max_side` giảm kích thước ngay khi đọc."""
    data, fmt = rep.data, None
    if rep.native_format in ("CF_DIB", "CF_DIBV5"):
        data, fmt = dib_to_bmp(rep.data), b"bmp"
        if data is None:
            return QImage()
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buf, fmt) if fmt else QImageReader(buf)
    reader.setAutoTransform(False)
    size = reader.size()
    if max_side and size.isValid() and max(size.width(), size.height()) > max_side:
        reader.setScaledSize(size.scaled(QSize(max_side, max_side), Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if max_side and not image.isNull() and max(image.width(), image.height()) > max_side:
        image = image.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    return image


class _Signals(QObject):
    done = Signal(int, int, QImage)  # item_id, max_side, ảnh (rỗng nếu lỗi)


class _Job(QRunnable):
    def __init__(self, loader, item_id: int, max_side: int, signals: _Signals) -> None:
        super().__init__()
        self.loader, self.item_id, self.max_side, self.signals = loader, item_id, max_side, signals

    def run(self) -> None:
        image = QImage()
        try:
            rep = self.loader(self.item_id)
            if rep is not None:
                image = decode_image(rep, self.max_side)
        except Exception:  # ảnh hỏng/mục đã bị xóa: hiển thị placeholder, không làm sập UI
            image = QImage()
        self.signals.done.emit(self.item_id, self.max_side, image)


class ImageProvider(QObject):
    """Tải ảnh ở thread nền, cache LRU các QPixmap đã giải mã. Gọi get() từ UI thread."""

    loaded = Signal(int, int)  # item_id, max_side

    def __init__(self, loader, capacity: int = 300, threads: int = 2) -> None:
        super().__init__()
        self._loader = loader  # item_id -> Representation | None (chạy ở thread nền)
        self._cache: OrderedDict[tuple[int, int], QPixmap | None] = OrderedDict()
        self._pending: set[tuple[int, int]] = set()
        self._capacity = capacity
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(threads)
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)

    def get(self, item_id: int, max_side: int) -> QPixmap | None:
        """Pixmap đã có, hoặc None (đã xếp lịch tải; `loaded` phát khi xong)."""
        key = (item_id, max_side)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        if key not in self._pending:
            self._pending.add(key)
            self._pool.start(_Job(self._loader, item_id, max_side, self._signals))
        return None

    def failed(self, item_id: int, max_side: int) -> bool:
        key = (item_id, max_side)
        return key in self._cache and self._cache[key] is None

    def forget(self, item_id: int) -> None:
        for key in [k for k in self._cache if k[0] == item_id]:
            del self._cache[key]

    def _on_done(self, item_id: int, max_side: int, image: QImage) -> None:
        key = (item_id, max_side)
        self._pending.discard(key)
        self._cache[key] = None if image.isNull() else QPixmap.fromImage(image)
        while len(self._cache) > self._capacity:
            self._cache.popitem(last=False)
        self.loaded.emit(item_id, max_side)

    def shutdown(self) -> None:
        self._pool.clear()
        self._pool.waitForDone(2000)
