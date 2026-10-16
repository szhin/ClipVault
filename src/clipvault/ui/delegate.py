"""Vẽ danh sách dạng thẻ và các dòng sidebar. Màu/cỡ chữ/khoảng cách lấy từ ui.theme."""

from __future__ import annotations

import time

from PySide6.QtCore import QModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from clipvault.core.model import StoredItem
from clipvault.ui import theme
from clipvault.ui.format import CATEGORY_NAMES, format_age, format_size, one_line
from clipvault.ui.images import ImageProvider
from clipvault.ui.models import ITEM_ROLE

ROW_HEIGHT = theme.sp(8)  # 64: thẻ 56 + khe 8
THUMB = theme.sp(5)  # 40
THUMB_REQUEST = 96  # cạnh tối đa khi giải mã thumbnail
SIDEBAR_ROW_HEIGHT = theme.sp(5)
COUNT_ROLE = Qt.ItemDataRole.UserRole + 1  # số lượng hiển thị ở sidebar (int | None)
VIEW_ROLE = Qt.ItemDataRole.UserRole


def primary_text(item: StoredItem) -> str:
    if item.category == "image":
        return "Image"
    return one_line(item.preview) or "(no text preview)"


def meta_text(item: StoredItem, now_ms: int) -> str:
    parts = [CATEGORY_NAMES.get(item.category, item.category.title())]
    if item.category == "code" and item.language_name:
        parts.append(item.language_name)
    parts += [format_age(now_ms, item.last_seen_at), format_size(item.total_size)]
    if item.copy_count > 1:
        parts.append(f"copied {item.copy_count}×")
    return " · ".join(parts)


def _with_alpha(color: QColor | str, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(alpha)
    return c


class ItemDelegate(QStyledItemDelegate):
    """Mỗi mục là một thẻ: badge loại hoặc thumbnail ảnh, nội dung rút gọn, dòng meta, dấu ghim."""

    def __init__(self, images: ImageProvider, parent=None) -> None:
        super().__init__(parent)
        self._images = images

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        # Chiều rộng do view quyết định (ListMode giãn theo viewport); chỉ cố định chiều cao.
        return QSize(0, theme.row_height())

    def paint(self, painter: QPainter, option, index) -> None:
        item: StoredItem | None = index.data(ITEM_ROLE)
        if item is None:
            return super().paint(painter, option, index)
        pal = theme.current()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        card = QRectF(option.rect.adjusted(theme.sp(1), theme.sp(0.5), -theme.sp(1), -theme.sp(0.5)))

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = pal.selected if selected else pal.hover if hovered else pal.surface
        border = pal.accent if selected else pal.faint if hovered else pal.border
        painter.setBrush(QColor(fill))
        painter.setPen(QPen(QColor(border), 1))
        painter.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), theme.RADIUS_MD, theme.RADIUS_MD)

        pad_v = theme.sp(1) if theme.density() == "comfortable" else theme.sp(0.5)
        inner = card.toRect().adjusted(theme.sp(1.5), pad_v, -theme.sp(1.5), -pad_v)
        thumb = min(THUMB, inner.height())
        lead = QRect(inner.left(), inner.top() + (inner.height() - thumb) // 2, thumb, thumb)
        self._paint_lead(painter, lead, item)

        right = inner.right()
        if item.pinned:  # ghim: icon ghim đặc màu nhấn ở góc phải
            pin = QRect(right - theme.sp(2) + 1, inner.top(), theme.sp(2), theme.sp(2))
            theme.draw_icon(painter, "pinned", pin, pal.accent, filled=True, stroke=1.5)
            right -= theme.sp(2.5)

        left = lead.right() + theme.sp(1.5)
        width = max(right - left, theme.sp(1))
        half = inner.height() // 2
        main_rect = QRect(left, inner.top(), width, half)
        meta_rect = QRect(left, inner.top() + half, width, half)

        base, small = theme.ui_font(theme.SIZE_BASE), theme.ui_font(theme.SIZE_SMALL)
        painter.setFont(base)
        painter.setPen(QColor(pal.text))
        painter.drawText(main_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         QFontMetrics(base).elidedText(primary_text(item), Qt.TextElideMode.ElideRight, width))
        painter.setFont(small)
        painter.setPen(QColor(pal.muted))
        painter.drawText(meta_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         QFontMetrics(small).elidedText(meta_text(item, time.time_ns() // 1_000_000),
                                                        Qt.TextElideMode.ElideRight, width))
        painter.restore()

    def _paint_lead(self, painter: QPainter, rect: QRect, item: StoredItem) -> None:
        pal = theme.current()
        if item.kind == "image":
            pixmap = self._images.get(item.id, THUMB_REQUEST)
            if pixmap is not None:
                clip = QPainterPath()
                clip.addRoundedRect(QRectF(rect), theme.RADIUS_SM * 1.5, theme.RADIUS_SM * 1.5)
                painter.save()
                painter.setClipPath(clip)
                # "cover": phủ kín ô vuông, cắt phần thừa ở giữa.
                scale = max(rect.width() / pixmap.width(), rect.height() / pixmap.height())
                sw, sh = rect.width() / scale, rect.height() / scale
                source = QRectF((pixmap.width() - sw) / 2, (pixmap.height() - sh) / 2, sw, sh)
                painter.drawPixmap(QRectF(rect), pixmap, source)
                painter.restore()
                return
            color = QColor(pal.faint if self._images.failed(item.id, THUMB_REQUEST) else pal.category_color("image"))
        else:
            color = pal.category_color(item.category)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_with_alpha(color, 0.16))
        painter.drawRoundedRect(QRectF(rect), theme.RADIUS_SM * 1.5, theme.RADIUS_SM * 1.5)
        icon_name = item.category if item.category in theme.CATEGORIES else "other"
        if item.kind == "image":
            icon_name = "image"
        side = int(rect.width() * 0.55)
        target = QRect(0, 0, side, side)
        target.moveCenter(rect.center())
        theme.draw_icon(painter, icon_name, target, color)


class SidebarDelegate(QStyledItemDelegate):
    """Dòng sidebar: icon loại + nhãn + số lượng; mục đang chọn nổi bật. Ở chế độ gọn chỉ còn icon."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.compact = False

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(0, SIDEBAR_ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        pal = theme.current()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        view = index.data(VIEW_ROLE)
        count = index.data(COUNT_ROLE)
        label = index.data(Qt.ItemDataRole.DisplayRole) or ""

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        row = QRectF(option.rect.adjusted(theme.sp(1), theme.sp(0.5), -theme.sp(1), -theme.sp(0.5)))
        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal.selected if selected else pal.hover))
            painter.drawRoundedRect(row, theme.RADIUS_MD, theme.RADIUS_MD)
        if selected:  # thanh nhấn bên trái cho mục đang chọn
            painter.setBrush(QColor(pal.accent))
            painter.drawRoundedRect(QRectF(row.left(), row.top() + theme.sp(1), 3, row.height() - theme.sp(2)), 1.5, 1.5)

        color = QColor(pal.accent if selected else pal.muted)
        icon_size = theme.sp(2.5)  # 20
        icon_rect = QRect(0, 0, icon_size, icon_size)
        if self.compact:
            icon_rect.moveCenter(row.center().toPoint())
        else:
            icon_rect.moveTo(int(row.left()) + theme.sp(1.5), int(row.center().y()) - icon_size // 2)
        theme.draw_icon(painter, theme.SIDEBAR_ICONS.get(view, "other"), icon_rect, color)

        if not self.compact:
            font = theme.ui_font(theme.SIZE_BASE, bold=selected)
            painter.setFont(font)
            painter.setPen(QColor(pal.text if selected else pal.muted))
            right = int(row.right()) - theme.sp(1)
            if count is not None:
                small = theme.ui_font(theme.SIZE_SMALL)
                text = str(count) if count < 10_000 else "9999+"
                fm = QFontMetrics(small)
                pill_w = max(fm.horizontalAdvance(text) + theme.sp(1.5), theme.sp(3))
                pill = QRectF(right - pill_w, row.center().y() - theme.sp(1.25), pill_w, theme.sp(2.5))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(_with_alpha(pal.accent if selected else pal.faint, 0.2))
                painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
                painter.setFont(small)
                painter.setPen(QColor(pal.text if selected else pal.muted))
                painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
                right = int(pill.left()) - theme.sp(1)
                painter.setFont(font)
                painter.setPen(QColor(pal.text if selected else pal.muted))
            text_rect = QRect(icon_rect.right() + theme.sp(1.5), int(row.top()),
                              max(right - icon_rect.right() - theme.sp(1.5), theme.sp(1)), int(row.height()))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             QFontMetrics(font).elidedText(label, Qt.TextElideMode.ElideRight, text_rect.width()))
        painter.restore()
