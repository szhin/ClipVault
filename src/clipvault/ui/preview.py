"""Panel bên phải: preview theo loại + các nút Copy / Pin / Delete / Change Type."""

from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QActionGroup, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout,
    QWidget,
)

from clipvault.core.model import StoredItem
from clipvault.engine.history import HistoryError, HistoryService, allowed_categories
from clipvault.ui import theme
from clipvault.ui.format import CATEGORY_NAMES, format_age, format_size
from clipvault.ui.images import ImageProvider

PREVIEW_IMAGE_SIDE = 1600
BADGE = theme.sp(4)  # 32
ICON = theme.sp(2.25)  # 18
COMPACT_BELOW = theme.sp(52)  # panel hẹp hơn mức này: nút chỉ còn icon (tooltip vẫn đủ chữ)

PAGE_EMPTY, PAGE_TEXT, PAGE_IMAGE, PAGE_MESSAGE = range(4)


class _ScaledImageLabel(QLabel):
    """Hiển thị pixmap vừa khung, giữ tỉ lệ, co giãn theo kích thước widget."""

    def __init__(self) -> None:
        super().__init__()
        self._source: QPixmap | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(QSize(theme.sp(15), theme.sp(15)))
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def set_source(self, pixmap: QPixmap | None) -> None:
        self._source = pixmap
        self._rescale()

    def source(self) -> QPixmap | None:
        return self._source

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._source is None or self._source.isNull():
            self.setPixmap(QPixmap())
            return
        dpr = self.devicePixelRatioF()
        pad = theme.sp(2) * 2  # chừa đúng phần đệm QSS để ảnh không bị cắt
        target = (self.size() - QSize(pad, pad)) * dpr
        scaled = self._source.scaled(target, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        self.setPixmap(scaled)


class PreviewPanel(QWidget):
    copy_requested = Signal()
    pin_requested = Signal()
    delete_requested = Signal()
    category_chosen = Signal(str)

    def __init__(self, history: HistoryService, images: ImageProvider, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("previewPanel")
        self._history = history
        self._images = images
        self._item: StoredItem | None = None

        # --- header: badge loại + tiêu đề + meta
        self.badge = QLabel()
        self.badge.setFixedSize(BADGE, BADGE)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.title.setTextFormat(Qt.TextFormat.PlainText)  # không bao giờ hiểu dữ liệu là HTML
        self.meta = QLabel()
        self.meta.setObjectName("meta")
        self.meta.setTextFormat(Qt.TextFormat.PlainText)
        self.meta.setWordWrap(True)
        titles = QVBoxLayout()
        titles.setSpacing(theme.sp(0))
        titles.addWidget(self.title)
        titles.addWidget(self.meta)
        header = QHBoxLayout()
        header.setSpacing(theme.sp(1.5))
        header.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        header.addLayout(titles, 1)

        # --- nội dung theo loại
        self.text_view = QPlainTextEdit()
        self.text_view.setObjectName("previewText")
        self.text_view.setReadOnly(True)
        self.text_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.text_view.setAccessibleName("Preview text")
        self.image_view = _ScaledImageLabel()
        self.image_view.setObjectName("previewImage")
        self.image_view.setAccessibleName("Preview image")
        self.message = QLabel()
        self.message.setObjectName("previewMessage")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)

        self.stack = QStackedWidget()
        empty = QLabel("Select an item to preview it")
        empty.setObjectName("previewEmpty")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for page in (empty, self.text_view, self.image_view, self.message):
            self.stack.addWidget(page)

        # --- thanh thao tác
        self.copy_button = QToolButton()
        self.copy_button.setText("Copy")
        self.copy_button.setProperty("variant", "primary")
        self.pin_button = QToolButton()
        self.pin_button.setText("Pin")
        self.delete_button = QToolButton()
        self.delete_button.setText("Delete")
        self.delete_button.setProperty("variant", "danger")
        self.type_button = QToolButton()
        self.type_button.setText("Change Type")
        self.type_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.type_menu = QMenu(self.type_button)
        self.type_button.setMenu(self.type_menu)
        self._type_group = QActionGroup(self)
        self._type_group.setExclusive(True)
        self.copy_button.setToolTip("Copy to clipboard in its original formats  (Enter)")
        self.pin_button.setToolTip("Pin / unpin this item  (Ctrl+P)")
        self.delete_button.setToolTip("Delete this item  (Del)")
        self.type_button.setToolTip("Change how this item is categorised")

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.sp(1))
        for b in (self.copy_button, self.pin_button, self.type_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(self.delete_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.sp(2), theme.sp(2), theme.sp(2), theme.sp(2))
        layout.setSpacing(theme.sp(1.5))
        layout.addLayout(header)
        layout.addWidget(self.stack, 1)
        layout.addLayout(buttons)

        self.copy_button.clicked.connect(self.copy_requested)
        self.pin_button.clicked.connect(self.pin_requested)
        self.delete_button.clicked.connect(self.delete_requested)
        images.loaded.connect(self._on_image_loaded)
        self._apply_button_style()
        self.show_item(None)

    # --- hiển thị ----------------------------------------------------------------------------

    def current_item(self) -> StoredItem | None:
        return self._item

    def _buttons(self) -> tuple[QToolButton, ...]:
        return (self.copy_button, self.pin_button, self.type_button, self.delete_button)

    def _apply_button_style(self) -> None:
        compact = self.width() < COMPACT_BELOW
        style = Qt.ToolButtonStyle.ToolButtonIconOnly if compact else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        for b in self._buttons():
            b.setToolButtonStyle(style)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_button_style()

    def refresh_theme(self) -> None:
        """Vẽ lại icon/badge/font theo scheme hiện tại (không nạp lại dữ liệu)."""
        self._apply_icons()
        self.text_view.setFont(theme.mono_font() if self._is_code(self._item) else theme.ui_font())

    @staticmethod
    def _is_code(item: StoredItem | None) -> bool:
        return item is not None and item.category == "code"

    def _apply_icons(self) -> None:
        item = self._item
        self.copy_button.setIcon(theme.icon("copy", theme.current().on_accent, ICON))
        self.pin_button.setIcon(theme.icon("pinned", size=ICON, filled=bool(item and item.pinned)))
        self.delete_button.setIcon(theme.icon("delete", size=ICON))
        self.type_button.setIcon(theme.icon("tag", size=ICON))
        for b in (self.copy_button, self.pin_button, self.delete_button, self.type_button):
            b.setIconSize(QSize(ICON, ICON))
        self.badge.setPixmap(theme.badge_pixmap(item.category if item else "other", BADGE))
        self.badge.setVisible(item is not None)

    def show_item(self, item: StoredItem | None) -> None:
        self._item = item
        has = item is not None
        for b in (self.copy_button, self.pin_button, self.delete_button, self.type_button):
            b.setEnabled(has)
        if item is None:
            self.title.setText("")
            self.meta.setText("")
            self.pin_button.setText("Pin")
            self.type_menu.clear()
            self._apply_icons()
            self.stack.setCurrentIndex(PAGE_EMPTY)
            return
        self.pin_button.setText("Unpin" if item.pinned else "Pin")
        self._apply_icons()
        self._fill_type_menu(item)
        self.title.setText(self._title_for(item))
        self.meta.setText(self._meta_for(item))
        try:
            if item.kind == "image":  # kể cả khi người dùng đổi loại sang Other
                self._show_image(item)
            elif item.category in ("link", "code", "text"):
                self._show_text(item)
            else:
                self._show_other(item)
        except HistoryError as exc:
            self._show_message(str(exc))

    @staticmethod
    def _title_for(item: StoredItem) -> str:
        if item.category == "code":
            return f"Code — {item.language_name}" if item.language_name else "Code"
        if item.category == "link":
            return "Link"
        return CATEGORY_NAMES.get(item.category, item.category.title())

    @staticmethod
    def _meta_for(item: StoredItem) -> str:
        parts = [format_size(item.total_size), format_age(time.time_ns() // 1_000_000, item.last_seen_at)]
        if item.copy_count > 1:
            parts.insert(1, f"copied {item.copy_count}×")
        if item.pinned:
            parts.insert(0, "pinned")
        return " · ".join(parts)

    def _fill_type_menu(self, item: StoredItem) -> None:
        self.type_menu.clear()
        for action in list(self._type_group.actions()):
            self._type_group.removeAction(action)
        for category in allowed_categories(item):
            action = self.type_menu.addAction(CATEGORY_NAMES[category])
            action.setCheckable(True)
            action.setChecked(category == item.category)
            action.setData(category)
            self._type_group.addAction(action)
            action.triggered.connect(lambda _checked=False, c=category: self.category_chosen.emit(c))

    def _show_text(self, item: StoredItem) -> None:
        text = self._history.text(item.id)
        if text is None:
            return self._show_message("No text available for this item")
        # Code: monospace. Link: hiển thị đúng chuỗi gốc đã copy (không rút gọn, không chuẩn hóa).
        self.text_view.setFont(theme.mono_font() if item.category == "code" else theme.ui_font())
        self.text_view.setPlainText(text)
        self.stack.setCurrentIndex(PAGE_TEXT)

    def _show_image(self, item: StoredItem) -> None:
        self._request_image(item)

    def _request_image(self, item: StoredItem) -> None:
        pixmap = self._images.get(item.id, PREVIEW_IMAGE_SIDE)
        if pixmap is not None:
            self.image_view.set_source(pixmap)
            self.stack.setCurrentIndex(PAGE_IMAGE)
            self.meta.setText(f"{pixmap.width()} × {pixmap.height()} · {self._meta_for(item)}")
        elif self._images.failed(item.id, PREVIEW_IMAGE_SIDE):
            self._show_message("This image can't be previewed")
        else:
            self._show_message("Loading…")

    def _show_other(self, item: StoredItem) -> None:
        text = self._history.text(item.id)
        if text:
            self._show_text(item)
        else:
            names = ", ".join(self._history.format_names(item.id))
            self._show_message(f"No preview for this content type\n({names})")

    def _show_message(self, text: str) -> None:
        self.message.setText(text)
        self.stack.setCurrentIndex(PAGE_MESSAGE)

    def _on_image_loaded(self, item_id: int, max_side: int) -> None:
        if self._item is not None and self._item.id == item_id and max_side == PREVIEW_IMAGE_SIDE \
                and self._item.kind == "image":
            self._request_image(self._item)
