import hashlib

from clipvault.core.model import Representation
from clipvault.engine.dedupe import blob_hash, item_hash


def _reps():
    return [
        Representation("PNG", "image/png", b"\x89PNG-data"),
        Representation("CF_UNICODETEXT", "text/plain", "a\x00".encode("utf-16-le")),
    ]


def test_blob_hash_is_sha256():
    assert blob_hash(b"abc") == hashlib.sha256(b"abc").digest()


def test_item_hash_matches_canonical_string():
    reps = _reps()
    hashes = [blob_hash(r.data) for r in reps]
    expected = hashlib.sha256()
    for rep, bh in sorted(zip(reps, hashes), key=lambda p: p[0].native_format):
        name = rep.native_format.encode()
        expected.update(
            len(name).to_bytes(8, "big") + name + len(rep.data).to_bytes(8, "big") + bh
        )
    assert item_hash(reps, hashes) == expected.digest()


def test_item_hash_ignores_representation_order():
    reps = _reps()
    hashes = [blob_hash(r.data) for r in reps]
    assert item_hash(reps, hashes) == item_hash(reps[::-1], hashes[::-1])


def test_extra_format_makes_a_different_item():
    reps = _reps()
    hashes = [blob_hash(r.data) for r in reps]
    html = Representation("HTML Format", "text/html", b"<b>a</b>")
    more = reps + [html]
    assert item_hash(reps, hashes) != item_hash(more, hashes + [blob_hash(html.data)])
