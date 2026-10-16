"""Phân loại lại mục đã lưu khi classifier đổi phiên bản (hoặc mục lưu từ trước Phase 2).

Chỉ ghi bảng tags và cột kind; không đụng payload. Mục đã Change Type giữ nguyên danh mục.
"""

from __future__ import annotations

import logging

from clipvault.classifier.rules import CLASSIFIER_VERSION, classify
from clipvault.core.model import Representation, Snapshot
from clipvault.storage.db import Database, StorageError

log = logging.getLogger(__name__)

SETTING_KEY = "classifier.version"
_MAX_TEXT_BYTES = 1_000_000  # văn bản lớn hơn vẫn phân loại, nhưng chỉ trên phần đầu


def reclassify_item(db: Database, item_id: int) -> None:
    reps = []
    text_done = False
    for native_format, mime in db.representation_meta(item_id):
        data = b""
        if mime == "text/plain" and not text_done:
            text_done = True
            full = db.representations(item_id, native_format)
            data = full[0].data[:_MAX_TEXT_BYTES] if full else b""
            if native_format == "CF_UNICODETEXT" and len(data) % 2:
                data = data[:-1]
        reps.append(Representation(native_format, mime, data))
    result = classify(Snapshot(tuple(reps)))
    db.set_classification(item_id, result.kind, result.tags)


def ensure_current(db: Database) -> int:
    """Chạy một lần mỗi phiên bản classifier. Trả số mục đã xử lý."""
    if db.settings().get(SETTING_KEY) == CLASSIFIER_VERSION:
        return 0
    done = 0
    for item_id in db.all_item_ids():
        try:
            reclassify_item(db, item_id)
            done += 1
        except (OSError, StorageError) as exc:
            log.warning("reclassify skipped one item: %s", type(exc).__name__)
    db.set_setting(SETTING_KEY, CLASSIFIER_VERSION)
    return done
