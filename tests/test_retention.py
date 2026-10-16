from clipvault.core.limits import Limits
from clipvault.core.model import Representation

from conftest import INLINE_MAX, png_rep, query, snap, text_rep


def _text_of_size(n_bytes: int, tag: str) -> Representation:
    return Representation("HTML Format", "text/html", (tag * n_bytes).encode()[:n_bytes])


def test_item_count_limit_prunes_oldest_unpinned_to_ninety_percent(make_service, db):
    svc = make_service(Limits(max_items=10))
    ids = [svc.process(snap(text_rep(f"t{i}"))).item_id for i in range(10)]
    db.set_pinned(ids[0], True)
    svc.process(snap(text_rep("t10")))  # 11 mục > 10 → còn ≤ 9
    remaining = {i.id for i in db.list_items()}
    assert len(remaining) == 9
    assert ids[0] in remaining  # mục ghim cũ nhất vẫn còn
    assert ids[1] not in remaining and ids[2] not in remaining  # cũ nhất chưa ghim bị xóa


def test_byte_limit_prunes_oldest(make_service, db):
    svc = make_service(Limits(max_total_bytes=1000))
    a = svc.process(snap(_text_of_size(400, "a")))
    svc.process(snap(_text_of_size(400, "b")))
    c = svc.process(snap(_text_of_size(400, "c")))  # 1200 > 1000 → còn ≤ 900
    assert db.stats().blob_bytes <= 900
    ids = {i.id for i in db.list_items()}
    assert a.item_id not in ids and c.item_id in ids


def test_only_pinned_over_limit_warns_but_still_accepts_new_item(make_service, db):
    big = make_service()
    for i in range(3):
        db.set_pinned(big.process(snap(text_rep(f"p{i}"))).item_id, True)
    tight = make_service(Limits(max_items=2))
    result = tight.process(snap(text_rep("new")))
    assert result.status == "saved" and result.pinned_over_limit
    assert len(db.list_items()) == 4  # không xóa gì, kể cả mục mới
    assert sum(i.pinned for i in db.list_items()) == 3


def test_new_item_is_protected_from_its_own_pruning(make_service, db):
    svc = make_service(Limits(max_total_bytes=100))
    first = svc.process(snap(_text_of_size(80, "a")))
    second = svc.process(snap(_text_of_size(80, "b")))
    ids = {i.id for i in db.list_items()}
    assert second.item_id in ids and first.item_id not in ids


def test_pruning_removes_external_file_but_keeps_shared_blob(make_service, db):
    svc = make_service(Limits(max_items=3, prune_ratio=1.0))
    shared = png_rep(INLINE_MAX + 50, seed=1)
    only_a = png_rep(INLINE_MAX + 60, seed=2)
    a = svc.process(snap(shared, only_a))
    b = svc.process(snap(shared, text_rep("b")))
    svc.process(snap(text_rep("c")))
    svc.process(snap(text_rep("d")))  # 4 > 3 → xóa a (cũ nhất)
    ids = {i.id for i in db.list_items()}
    assert a.item_id not in ids and b.item_id in ids
    files = [p for p in db.blobs.root.rglob("*") if p.is_file()]
    assert len(files) == 1  # chỉ còn blob dùng chung
    assert db.representations(b.item_id)[0] == shared
    assert query(db, "SELECT COUNT(*) FROM blobs WHERE external = 1") == [(1,)]


def test_pinned_item_is_never_deleted_by_pruning(make_service, db):
    svc = make_service(Limits(max_items=2))
    first = svc.process(snap(text_rep("keep")))
    db.set_pinned(first.item_id, True)
    for i in range(10):
        svc.process(snap(text_rep(f"x{i}")))
    assert first.item_id in {i.id for i in db.list_items()}
    assert db.list_items()[0].id == first.item_id  # ghim luôn nằm đầu
