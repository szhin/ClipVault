"""Cửa sổ chính: sidebar loại, ô tìm kiếm, danh sách (model/view), preview và thao tác."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QBoxLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSplitter, QStackedWidget, QToolButton, QVBoxLayout,
    QWidget,
)

from clipvault.core.model import StoredItem
from clipvault.engine.history import VIEWS, HistoryError, HistoryService
from clipvault.engine.settings import SettingsStore
from clipvault.ui import theme
from clipvault.ui.delegate import COUNT_ROLE, ROW_HEIGHT, ItemDelegate, SidebarDelegate
from clipvault.ui.format import CATEGORY_LABELS
from clipvault.ui.images import ImageProvider
from clipvault.ui.models import ITEM_ROLE, HistoryModel
from clipvault.ui.prefs import Preferences
from clipvault.ui.preview import PreviewPanel
from clipvault.ui.settings_dialog import SettingsDialog

SEARCH_DEBOUNCE_MS = 150
COUNTS_DEBOUNCE_MS = 250
STATUS_MS = 4000
SIDEBAR_WIDTH = theme.sp(22)  # 176
SIDEBAR_COMPACT_WIDTH = theme.sp(7)  # 56: chỉ icon
COMPACT_BELOW = 860  # cửa sổ hẹp hơn mức này thì sidebar thu gọn
COUNT_LIMIT = 10_000
HINT = "↑ ↓ navigate   ·   Enter copy   ·   Ctrl+P pin   ·   Del delete   ·   Ctrl+F search   ·   Esc close"


class SearchEdit(QLineEdit):
    """Ô tìm kiếm: ↑/↓ chọn mục trong danh sách, Enter copy mục đang chọn — không cần rời ô tìm kiếm."""

    navigate = Signal(int)
    submit = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setTextMargins(theme.sp(3), 0, 0, 0)  # chừa chỗ cho icon kính lúp

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        size = theme.sp(2.25)
        painter = QPainter(self)
        rect = QRect(theme.sp(1.5), (self.height() - size) // 2, size, size)
        theme.draw_icon(painter, "search", rect, theme.current().muted)
        painter.end()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1, Qt.Key.Key_PageDown: 8, Qt.Key.Key_PageUp: -8}.get(
            event.key()
        )
        if step is not None:
            self.navigate.emit(step)
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.submit.emit()
        else:
            super().keyPressEvent(event)


class MainWindow(QMainWindow):
    quit_requested = Signal()  # nút đóng khi cài đặt là "thoát hẳn"
    data_changed = Signal()  # Settings đã xóa dữ liệu

    def __init__(
        self, history: HistoryService, model: HistoryModel, images: ImageProvider, parent=None,
        prefs: Preferences | None = None,
    ) -> None:
        super().__init__(parent)
        self.history = history
        self.prefs = prefs or Preferences(SettingsStore(history.db))
        self.model = model
        self.images = images
        self.hide_on_close = False  # bật khi có system tray: nút đóng chỉ ẩn cửa sổ
        self._quitting = False
        self.setWindowTitle("ClipVault")
        self.resize(1040, 660)
        self.setMinimumSize(QSize(theme.sp(80), theme.sp(50)))  # 640 × 400: vẫn dùng được trên màn hình nhỏ
        self.setStyleSheet(theme.stylesheet())

        # --- sidebar
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setAccessibleName("Categories")
        self.sidebar.setMouseTracking(True)
        self.sidebar.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar_delegate = SidebarDelegate(self.sidebar)
        self.sidebar.setItemDelegate(self.sidebar_delegate)
        for n, view in enumerate(VIEWS, start=1):
            entry = QListWidgetItem(CATEGORY_LABELS[view])
            entry.setData(Qt.ItemDataRole.UserRole, view)
            entry.setToolTip(f"{CATEGORY_LABELS[view]}  (Ctrl+{n})")
            self.sidebar.addItem(entry)

        # --- chân sidebar: switch sáng/tối (góc dưới trái) + nút Settings
        self.theme_button = QToolButton()
        self.theme_button.setObjectName("themeSwitch")
        self.theme_button.setAccessibleName("Theme switch")
        self.settings_button = QToolButton()
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.setAccessibleName("Settings")
        self.settings_button.setToolTip("Cài đặt")
        self.sidebar_footer = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.sidebar_footer.setContentsMargins(theme.sp(1), theme.sp(1), theme.sp(1), theme.sp(1))
        self.sidebar_footer.addWidget(self.theme_button)
        self.sidebar_footer.addWidget(self.settings_button)
        self.sidebar_footer.addStretch(1)
        self.sidebar_panel = QWidget()
        self.sidebar_panel.setObjectName("sidebarPanel")
        panel_layout = QVBoxLayout(self.sidebar_panel)
        panel_layout.setContentsMargins(theme.sp(0), theme.sp(0), theme.sp(0), theme.sp(0))
        panel_layout.setSpacing(theme.sp(0))
        panel_layout.addWidget(self.sidebar, 1)
        panel_layout.addLayout(self.sidebar_footer)

        # --- banner tạm dừng
        self.pause_banner = QFrame()
        self.pause_banner.setObjectName("pauseBanner")
        banner_layout = QHBoxLayout(self.pause_banner)
        banner_layout.setContentsMargins(theme.sp(1.5), theme.sp(1), theme.sp(1.5), theme.sp(1))
        banner_text = QLabel("Đang tạm dừng ghi clipboard — nội dung mới sẽ không được lưu.")
        banner_text.setWordWrap(True)
        self.resume_button = QPushButton("Tiếp tục ghi")
        banner_layout.addWidget(banner_text, 1)
        banner_layout.addWidget(self.resume_button)
        self.pause_banner.hide()

        # --- tìm kiếm + danh sách
        self.search = SearchEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search clipboard history")
        self.search.setToolTip("Search  (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search")

        self.list = QListView()
        self.list.setObjectName("history")
        self.list.setAccessibleName("History")
        self.list.setModel(model)
        self.list.setUniformItemSizes(True)
        self.list.setMouseTracking(True)  # hover trên thẻ
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.verticalScrollBar().setSingleStep(ROW_HEIGHT // 2)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setItemDelegate(ItemDelegate(images, self.list))

        self.empty_label = QLabel()
        self.empty_label.setObjectName("empty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setTextFormat(Qt.TextFormat.RichText)
        self.list_stack = QStackedWidget()
        self.list_stack.addWidget(self.list)
        self.list_stack.addWidget(self.empty_label)

        middle = QWidget()
        middle.setObjectName("content")
        middle.setMinimumWidth(theme.sp(35))  # 280
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(theme.sp(1), theme.sp(1.5), theme.sp(1), 0)
        middle_layout.setSpacing(theme.sp(1))
        middle_layout.addWidget(self.pause_banner)
        middle_layout.addWidget(self.search)
        middle_layout.addWidget(self.list_stack, 1)

        self.preview = PreviewPanel(history, images)
        self.preview.setMinimumWidth(theme.sp(35))

        self.splitter = QSplitter()
        self.splitter.addWidget(self.sidebar_panel)
        self.splitter.addWidget(middle)
        self.splitter.addWidget(self.preview)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 2)
        self.splitter.setSizes([SIDEBAR_WIDTH, 400, 464])
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)
        self.root = theme.GradientBackground()  # widget gốc duy nhất có gradient
        root_layout = QVBoxLayout(self.root)
        root_layout.setContentsMargins(theme.sp(0), theme.sp(0), theme.sp(0), theme.sp(0))
        root_layout.addWidget(self.splitter)
        self.setCentralWidget(self.root)

        self.statusBar().setSizeGripEnabled(False)
        self.hint_label = QLabel(HINT)  # phím tắt luôn hiển thị
        self.hint_label.setObjectName("meta")
        self.statusBar().addPermanentWidget(self.hint_label)
        self.pause_status = QLabel("⏸ Đang tạm dừng ghi")
        self.pause_status.setObjectName("pauseStatus")
        self.statusBar().addPermanentWidget(self.pause_status)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._counts_timer = QTimer(self)
        self._counts_timer.setSingleShot(True)
        self._counts_timer.setInterval(COUNTS_DEBOUNCE_MS)

        self._connect()
        self._install_shortcuts()
        self.sidebar.setCurrentRow(0)
        self.model.reload()
        self._after_reload()
        self.update_counts()
        self.preview.refresh_theme()
        self._apply_theme_controls()
        self._apply_pause_state()
        self._apply_compact()
        self.setTabOrder(self.sidebar, self.search)
        self.setTabOrder(self.search, self.list)

    # --- wiring ---------------------------------------------------------------------------------

    def _connect(self) -> None:
        self.sidebar.currentItemChanged.connect(self._on_view_changed)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        self._search_timer.timeout.connect(self._apply_query)
        self.search.navigate.connect(self._navigate)
        self.search.submit.connect(self._submit_from_search)
        self.list.selectionModel().currentChanged.connect(self._on_current_changed)
        self.list.doubleClicked.connect(lambda _i: self.copy_current(hide=True))
        self._counts_timer.timeout.connect(self.update_counts)
        theme.bus.changed.connect(self._on_theme_changed)
        self.theme_button.clicked.connect(self.toggle_theme)
        self.settings_button.clicked.connect(self.open_settings)
        self.resume_button.clicked.connect(lambda: self.prefs.set(paused=False))
        self.prefs.changed.connect(self._on_prefs_changed)
        self.model.error.connect(self._show_status)
        for signal in (self.model.modelReset, self.model.rowsInserted, self.model.rowsRemoved):
            signal.connect(self._update_empty_state)
        self.images.loaded.connect(lambda *_: self.list.viewport().update())
        self.preview.copy_requested.connect(lambda: self.copy_current(hide=False))
        self.preview.pin_requested.connect(self.toggle_pin)
        self.preview.delete_requested.connect(self.delete_current)
        self.preview.category_chosen.connect(self.change_category)

    def _install_shortcuts(self) -> None:
        def add(seq, slot, parent: QWidget, context=Qt.ShortcutContext.WindowShortcut) -> None:
            sc = QShortcut(QKeySequence(seq), parent)
            sc.setContext(context)
            sc.activated.connect(slot)

        add("Ctrl+F", self.focus_search, self)
        add("Ctrl+P", self.toggle_pin, self)
        add("Esc", self.escape, self)
        for n, _view in enumerate(VIEWS, start=1):
            add(f"Ctrl+{n}", lambda row=n - 1: self.sidebar.setCurrentRow(row), self)
        only_list = Qt.ShortcutContext.WidgetShortcut
        add(Qt.Key.Key_Return, lambda: self.copy_current(hide=True), self.list, only_list)
        add(Qt.Key.Key_Enter, lambda: self.copy_current(hide=True), self.list, only_list)
        add("Ctrl+C", lambda: self.copy_current(hide=False), self.list, only_list)
        add(Qt.Key.Key_Delete, self.delete_current, self.list, only_list)

    # --- trạng thái hiện tại ---------------------------------------------------------------------

    def current_item(self) -> StoredItem | None:
        index = self.list.currentIndex()
        return index.data(ITEM_ROLE) if index.isValid() else None

    def _current_row(self) -> int:
        index = self.list.currentIndex()
        return index.row() if index.isValid() else -1

    def _select_row(self, row: int) -> None:
        if 0 <= row < self.model.rowCount():
            index = self.model.index(row)
            self.list.setCurrentIndex(index)
            self.list.scrollTo(index, QAbstractItemView.ScrollHint.EnsureVisible)

    def select_item(self, item_id: int) -> bool:
        row = self.model.row_of(item_id)
        self._select_row(row)
        return row >= 0

    def _show_status(self, text: str) -> None:
        self.statusBar().showMessage(text, STATUS_MS)

    def _sync_preview(self) -> None:
        self.preview.show_item(self.current_item())

    def _on_current_changed(self, _current: QModelIndex, _previous: QModelIndex) -> None:
        self._sync_preview()

    def _update_empty_state(self, *_args) -> None:
        if self.model.rowCount() > 0:
            self.list_stack.setCurrentWidget(self.list)
            return
        if self.model.query.strip():
            title, hint = "No matches", "Try a different word, or press Esc to clear the search."
        elif self.model.view == "pinned":
            title, hint = "No pinned items", "Select an item and press Ctrl+P to pin it."
        elif self.model.view == "all":
            title, hint = "Nothing copied yet", "Copy some text or an image and it will show up here."
        else:
            title, hint = "Nothing in this category yet", "New copies are sorted here automatically."
        p = theme.current()
        self.empty_label.setText(
            f'<p style="font-size:{theme.SIZE_TITLE}pt; font-weight:600; color:{p.text};">{title}</p>'
            f'<p style="color:{p.muted};">{hint}</p>'
        )
        self.list_stack.setCurrentWidget(self.empty_label)

    # --- số lượng ở sidebar / theme / cửa sổ hẹp ---------------------------------------------------

    def update_counts(self) -> None:
        """Đếm số mục từng loại (không phụ thuộc ô tìm kiếm) và hiện ở sidebar."""
        try:
            items = self.history.query("all", "", COUNT_LIMIT)
        except HistoryError:
            return
        counts = {view: 0 for view in VIEWS}
        counts["all"] = len(items)
        for item in items:
            counts[item.category] = counts.get(item.category, 0) + 1
            counts["pinned"] += int(item.pinned)
        for row in range(self.sidebar.count()):
            entry = self.sidebar.item(row)
            entry.setData(COUNT_ROLE, counts.get(entry.data(Qt.ItemDataRole.UserRole)))
        self.sidebar.viewport().update()

    def _apply_theme_controls(self) -> None:
        dark = theme.current().name == "dark"
        self.theme_button.setIcon(theme.icon("sun" if dark else "moon", size=theme.sp(2.5)))
        self.theme_button.setToolTip("Chuyển sang giao diện sáng" if dark else "Chuyển sang giao diện tối")
        self.settings_button.setIcon(theme.icon("gear", size=theme.sp(2.5)))

    def _apply_pause_state(self) -> None:
        paused = self.prefs.values.paused
        self.pause_banner.setVisible(paused)
        self.pause_status.setVisible(paused)

    def _on_prefs_changed(self, _diff) -> None:
        self._apply_pause_state()

    def toggle_theme(self) -> None:
        """Đảo sáng/tối ngay (thành chế độ cố định; chọn lại "Hệ thống" trong Settings)."""
        self.prefs.set(theme="light" if theme.current().name == "dark" else "dark")

    def open_settings(self) -> SettingsDialog:
        current = getattr(self, "_settings_dialog", None)
        try:
            if current is not None and current.isVisible():  # đang mở: đưa lên trước, không mở thêm
                current.raise_()
                current.activateWindow()
                return current
        except RuntimeError:  # widget C++ đã bị xóa sau khi đóng
            pass
        dialog = SettingsDialog(self.history, self.prefs, self)
        dialog.data_changed.connect(self.after_data_deleted)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()
        self._settings_dialog = dialog
        return dialog

    def after_data_deleted(self) -> None:
        """Settings vừa xóa/dọn dữ liệu: nạp lại danh sách và số đếm ở sidebar."""
        self.images.clear()
        self._refresh()
        self.update_counts()
        self.data_changed.emit()

    def _on_theme_changed(self) -> None:
        self.setStyleSheet(theme.stylesheet())
        self._apply_theme_controls()
        self.list.verticalScrollBar().setSingleStep(theme.row_height() // 2)
        self.list.doItemsLayout()
        self.search.update()
        self.preview.refresh_theme()
        self._update_empty_state()
        self.list.viewport().update()
        self.sidebar.viewport().update()

    def _apply_compact(self) -> None:
        compact = self.width() < COMPACT_BELOW
        self.sidebar_delegate.compact = compact
        self.sidebar_panel.setFixedWidth(SIDEBAR_COMPACT_WIDTH if compact else SIDEBAR_WIDTH)
        self.sidebar_footer.setDirection(
            QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
        self.hint_label.setVisible(self.width() >= COMPACT_BELOW)
        self.sidebar.viewport().update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_compact()

    def _after_reload(self) -> None:
        """Sau khi đổi view/tìm kiếm: chọn dòng đầu, cập nhật preview và trạng thái rỗng."""
        self._update_empty_state()
        if self.model.rowCount() > 0:
            self._select_row(0)
        self._sync_preview()

    def _refresh(self, prefer_id: int | None = None, fallback_row: int | None = None) -> None:
        """Nạp lại dữ liệu nhưng giữ lựa chọn (theo id) và vị trí cuộn."""
        current = self.current_item()
        keep_id = prefer_id if prefer_id is not None else (current.id if current else None)
        fallback = fallback_row if fallback_row is not None else max(self._current_row(), 0)
        scroll = self.list.verticalScrollBar().value()
        self.model.refresh()
        self._counts_timer.start()
        self._update_empty_state()
        row = self.model.row_of(keep_id) if keep_id is not None else -1
        if row < 0:
            row = min(fallback, self.model.rowCount() - 1)
        if row >= 0:
            self._select_row(row)
            self.list.verticalScrollBar().setValue(scroll)
            self.list.scrollTo(self.model.index(row), QAbstractItemView.ScrollHint.EnsureVisible)
        self._sync_preview()

    def refresh(self) -> None:
        """Gọi khi có mục mới được ghi (từ capture)."""
        self._refresh()

    # --- view / tìm kiếm ------------------------------------------------------------------------------

    def _on_view_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        self.model.set_view(current.data(Qt.ItemDataRole.UserRole))
        self._after_reload()

    def _apply_query(self) -> None:
        self._search_timer.stop()
        self.model.set_query(self.search.text())
        self._after_reload()

    def focus_search(self) -> None:
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def escape(self) -> None:
        if self.search.text():
            self.search.clear()
            self._apply_query()
        else:
            self.hide()

    def _navigate(self, step: int) -> None:
        count = self.model.rowCount()
        if not count:
            return
        row = self._current_row()
        self._select_row(0 if row < 0 else max(0, min(count - 1, row + step)))

    def _submit_from_search(self) -> None:
        if self._search_timer.isActive():  # áp dụng truy vấn đang chờ debounce trước khi chọn mục
            self._apply_query()
        self.copy_current(hide=True)

    # --- thao tác ---------------------------------------------------------------------------------------

    def confirm(self, text: str) -> bool:
        return QMessageBox.question(self, "ClipVault", text) == QMessageBox.StandardButton.Yes

    def copy_current(self, hide: bool = False) -> bool:
        item = self.current_item()
        if item is None:
            return False
        try:
            self.history.copy(item.id)
        except HistoryError as exc:
            self._show_status(str(exc))
            return False
        self._show_status("Copied — paste it with Ctrl+V")
        self._refresh(prefer_id=item.id)
        if hide:
            self.hide()
        return True

    def toggle_pin(self) -> None:
        item = self.current_item()
        if item is None:
            return
        try:
            self.history.set_pinned(item.id, not item.pinned)
        except HistoryError as exc:
            self._show_status(str(exc))
            return
        self._show_status("Unpinned" if item.pinned else "Pinned")
        self._refresh(prefer_id=item.id, fallback_row=self._current_row())

    def delete_current(self) -> None:
        item = self.current_item()
        if item is None:
            return
        if item.pinned and not self.confirm("This item is pinned. Delete it anyway?"):
            return
        if not item.pinned and self.prefs.values.confirm_delete and not self.confirm("Delete this item?"):
            return
        row = self._current_row()
        try:
            self.history.delete(item.id)
        except HistoryError as exc:
            self._show_status(str(exc))
            return
        self.images.forget(item.id)
        self._show_status("Deleted")
        self._refresh(prefer_id=-1, fallback_row=row)

    def change_category(self, category: str) -> None:
        item = self.current_item()
        if item is None:
            return
        try:
            self.history.change_category(item.id, category)
        except HistoryError as exc:
            self._show_status(str(exc))
            return
        self._show_status(f"Type changed to {CATEGORY_LABELS.get(category, category)}")
        self._refresh(prefer_id=item.id, fallback_row=self._current_row())

    # --- vòng đời ---------------------------------------------------------------------------------------

    def show_and_focus(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._refresh()
        self.focus_search()

    def toggle_visibility(self) -> None:
        if self.isVisible() and self.isActiveWindow():
            self.hide()
        else:
            self.show_and_focus()

    def request_quit(self) -> None:
        self._quitting = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.hide_on_close and not self._quitting:
            event.ignore()
            if self.prefs.values.close_to_tray:
                self.hide()
            else:
                self.quit_requested.emit()
        else:
            event.accept()
