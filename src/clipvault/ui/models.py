"""Model danh sách lịch sử: phân trang (fetchMore) để danh sách lớn không phải nạp hết một lần."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal

from clipvault.core.model import StoredItem
from clipvault.engine.history import HistoryError, HistoryService
from clipvault.ui.format import one_line

ITEM_ROLE = Qt.ItemDataRole.UserRole + 1


class HistoryModel(QAbstractListModel):
    error = Signal(str)  # thông báo an toàn (HistoryError), không chứa nội dung clipboard

    def __init__(self, history: HistoryService, page_size: int = 100, parent=None) -> None:
        super().__init__(parent)
        self._history = history
        self._page = page_size
        self._view = "all"
        self._query = ""
        self._items: list[StoredItem] = []
        self._more = True

    # --- QAbstractListModel ----------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        if role == ITEM_ROLE:
            return item
        if role == Qt.ItemDataRole.DisplayRole:
            return one_line(item.preview) or item.category
        return None

    def canFetchMore(self, parent: QModelIndex = QModelIndex()) -> bool:  # noqa: B008
        return not parent.isValid() and self._more

    def fetchMore(self, parent: QModelIndex = QModelIndex()) -> None:  # noqa: B008
        if parent.isValid() or not self._more:
            return
        rows = self._load(len(self._items), self._page)
        if rows is None:
            return
        if rows:
            self.beginInsertRows(QModelIndex(), len(self._items), len(self._items) + len(rows) - 1)
            self._items.extend(rows)
            self.endInsertRows()
        self._more = len(rows) == self._page

    # --- API cho UI -------------------------------------------------------------------------

    @property
    def view(self) -> str:
        return self._view

    @property
    def query(self) -> str:
        return self._query

    def set_view(self, view: str) -> None:
        if view != self._view:
            self._view = view
            self.reload()

    def set_query(self, text: str) -> None:
        if text != self._query:
            self._query = text
            self.reload()

    def reload(self, keep_loaded: bool = False) -> None:
        """Nạp lại từ trang đầu (hoặc đúng số dòng đã nạp nếu keep_loaded) rồi reset model."""
        count = max(len(self._items), self._page) if keep_loaded else self._page
        rows = self._load(0, count)
        self.beginResetModel()
        self._items = rows or []
        self._more = rows is not None and len(rows) == count
        self.endResetModel()

    def refresh(self) -> None:
        """Cập nhật sau thay đổi dữ liệu; bỏ qua nếu danh sách hiển thị không đổi."""
        count = max(len(self._items), self._page)
        rows = self._load(0, count)
        if rows is None or rows == self._items:
            return
        self.beginResetModel()
        self._items = rows
        self._more = len(rows) == count
        self.endResetModel()

    def item_at(self, row: int) -> StoredItem | None:
        return self._items[row] if 0 <= row < len(self._items) else None

    def row_of(self, item_id: int) -> int:
        for row, item in enumerate(self._items):
            if item.id == item_id:
                return row
        return -1

    def _load(self, offset: int, limit: int) -> list[StoredItem] | None:
        try:
            return self._history.query(self._view, self._query, limit, offset)
        except HistoryError as exc:
            self.error.emit(str(exc))
            return None
