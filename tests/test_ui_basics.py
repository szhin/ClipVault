import struct

import pytest

from clipvault.core.model import Representation
from clipvault.ui.format import format_age, format_size, one_line


# --- format ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n,expected",
    [(0, "0 B"), (1023, "1023 B"), (1024, "1.0 KB"), (1536, "1.5 KB"), (10 * 1024, "10 KB"),
     (5 * 1024 * 1024, "5.0 MB"), (3 * 1024**3, "3.0 GB")],
)
def test_format_size(n, expected):
    assert format_size(n) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "just now"), (44, "just now"), (60, "1 min ago"), (3000, "50 min ago"),
     (3 * 3600, "3 h ago"), (2 * 86400, "2 d ago"), (-5, "just now")],
)
def test_format_age(seconds, expected):
    assert format_age(10_000_000, 10_000_000 - seconds * 1000) == expected


def test_one_line_collapses_whitespace_and_truncates():
    assert one_line("a\n  b\t\tc") == "a b c"
    assert one_line(None) == ""
    assert one_line("x" * 300, 50) == "x" * 49 + "…"


# --- ảnh -----------------------------------------------------------------------------------------


def _qt_image_bytes(fmt: str, w=40, h=30, qimage_format=None) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage

    img = QImage(w, h, qimage_format or QImage.Format.Format_RGB32)
    img.fill(QColor(200, 30, 60))
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, fmt)
    return bytes(ba)


def test_decode_png(qapp):
    from clipvault.ui.images import decode_image

    image = decode_image(Representation("PNG", "image/png", _qt_image_bytes("PNG")))
    assert (image.width(), image.height()) == (40, 30)


def test_decode_png_scaled_down(qapp):
    from clipvault.ui.images import decode_image

    rep = Representation("PNG", "image/png", _qt_image_bytes("PNG", 400, 200))
    image = decode_image(rep, max_side=100)
    assert (image.width(), image.height()) == (100, 50)


def test_decode_png_is_not_upscaled(qapp):
    from clipvault.ui.images import decode_image

    rep = Representation("PNG", "image/png", _qt_image_bytes("PNG", 40, 30))
    assert decode_image(rep, max_side=500).width() == 40


def test_decode_dib_from_clipboard_without_file_header(qapp):
    from clipvault.ui.images import decode_image

    bmp = _qt_image_bytes("BMP", 32, 16)
    dib = bmp[14:]  # clipboard lưu DIB không có BITMAPFILEHEADER
    for name in ("CF_DIB", "CF_DIBV5"):
        image = decode_image(Representation(name, "image/bmp", dib))
        assert (image.width(), image.height()) == (32, 16), name


def test_dib_to_bmp_roundtrips_pixels(qapp):
    from PySide6.QtGui import QImage

    from clipvault.ui.images import decode_image

    bmp = _qt_image_bytes("BMP", 8, 8)
    again = decode_image(Representation("CF_DIB", "image/bmp", bmp[14:]))
    original = QImage.fromData(bmp)
    assert again.pixelColor(3, 3) == original.pixelColor(3, 3)


def _v5_dib(w=2, h=2) -> bytes:
    """DIBV5 32-bit BI_BITFIELDS tự dựng (124 byte header, mặt nạ nằm trong header)."""
    header = struct.pack(
        "<IiiHHIIiiII", 124, w, h, 1, 32, 3, w * h * 4, 0, 0, 0, 0
    ) + struct.pack("<IIII", 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    # bV5CSType (sRGB) + endpoints (36) + gamma (12) + intent/profile data/size/reserved (16)
    header += struct.pack("<I", 0x73524742) + b"\x00" * 36 + b"\x00" * 12 + struct.pack("<IIII", 4, 0, 0, 0)
    assert len(header) == 124
    return header + b"\x10\x20\x30\xFF" * (w * h)


def test_decode_handcrafted_dibv5(qapp):
    from clipvault.ui.images import decode_image, dib_to_bmp

    dib = _v5_dib(3, 2)
    bmp = dib_to_bmp(dib)
    assert bmp[:2] == b"BM" and struct.unpack_from("<I", bmp, 10)[0] == 14 + 124  # offset pixel
    image = decode_image(Representation("CF_DIBV5", "image/bmp", dib))
    assert (image.width(), image.height()) == (3, 2)


def test_dib_to_bmp_accounts_for_bitfield_masks_and_palette():
    from clipvault.ui.images import dib_to_bmp

    bitfields = struct.pack("<IiiHHIIiiII", 40, 1, 1, 1, 32, 3, 4, 0, 0, 0, 0) + b"\x00" * 12 + b"\x00" * 4
    assert struct.unpack_from("<I", dib_to_bmp(bitfields), 10)[0] == 14 + 40 + 12
    palette = struct.pack("<IiiHHIIiiII", 40, 1, 1, 1, 8, 0, 1, 0, 0, 0, 0) + b"\x00" * 1024 + b"\x00" * 4
    assert struct.unpack_from("<I", dib_to_bmp(palette), 10)[0] == 14 + 40 + 256 * 4


@pytest.mark.parametrize("junk", [b"", b"\x00" * 10, b"\x28\x00\x00\x00" + b"\xff" * 36, b"not an image at all" * 5])
def test_corrupt_images_give_null_image_not_exception(qapp, junk):
    from clipvault.ui.images import decode_image

    for name, mime in (("CF_DIB", "image/bmp"), ("CF_DIBV5", "image/bmp"), ("PNG", "image/png")):
        assert decode_image(Representation(name, mime, junk)).isNull()


def test_image_provider_loads_in_background_and_caches(qapp):
    from conftest import wait_until
    from clipvault.ui.images import ImageProvider

    data = Representation("PNG", "image/png", _qt_image_bytes("PNG", 200, 100))
    calls = []

    def loader(item_id):
        calls.append(item_id)
        return data if item_id == 1 else None

    provider = ImageProvider(loader)
    try:
        seen = []
        provider.loaded.connect(lambda i, s: seen.append((i, s)))
        assert provider.get(1, 64) is None  # chưa có: xếp lịch tải
        assert provider.get(1, 64) is None  # không xếp lịch trùng
        assert wait_until(qapp, lambda: (1, 64) in seen)
        pm = provider.get(1, 64)
        assert pm is not None and max(pm.width(), pm.height()) == 64
        assert calls == [1]
        provider.get(2, 64)  # loader trả None → thất bại, không nổ
        assert wait_until(qapp, lambda: provider.failed(2, 64))
        provider.forget(1)
        assert provider.get(1, 64) is None
    finally:
        provider.shutdown()


def test_image_provider_survives_loader_exception(qapp):
    from conftest import wait_until
    from clipvault.ui.images import ImageProvider

    provider = ImageProvider(lambda i: (_ for _ in ()).throw(RuntimeError("boom")))
    try:
        provider.get(5, 32)
        assert wait_until(qapp, lambda: provider.failed(5, 32))
    finally:
        provider.shutdown()
