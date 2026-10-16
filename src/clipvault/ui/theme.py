"""Design tokens + QSS + icon vẽ bằng code. Mọi màu, cỡ chữ, khoảng cách, bo góc của UI nằm ở đây.

Các file UI khác không hard-code style: chúng lấy token (`current()`, `sp()`, `RADIUS_*`, `ui_font()`...),
gọi `icon()/draw_icon()` và dùng `stylesheet()` do module này tạo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from string import Template

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPalette, QPen, QPixmap, QPolygonF

# --- khoảng cách (lưới 8 px), bo góc, cỡ chữ -----------------------------------------------------

SP = 8


def sp(n: float = 1) -> int:
    """Khoảng cách theo bội số của lưới 8 px (n có thể là 0.5 = 4 px)."""
    return round(SP * n)


RADIUS_SM = 4
RADIUS_MD = 8
RADIUS_LG = 12

FONT_UI = ('"Segoe UI Variable Text"', '"Segoe UI"', "sans-serif")
FONT_MONO = ('"Cascadia Mono"', "Consolas", '"Courier New"', "monospace")
SIZE_SMALL, SIZE_BASE, SIZE_TITLE = 9, 10, 13  # pt

CATEGORIES = ("image", "text", "link", "code", "other")
SIDEBAR_ICONS = {"all": "all", "image": "image", "text": "text", "link": "link", "code": "code",
                 "other": "other", "pinned": "pinned"}


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    sidebar: str
    surface: str
    hover: str
    selected: str
    border: str
    text: str
    muted: str
    faint: str
    accent: str
    accent_hover: str
    on_accent: str
    danger: str
    cat_image: str
    cat_text: str
    cat_link: str
    cat_code: str
    cat_other: str

    def category_color(self, category: str) -> QColor:
        return QColor(getattr(self, f"cat_{category}", self.accent))


DARK = Palette(
    name="dark", bg="#14161a", sidebar="#101216", surface="#1c1f26", hover="#242834", selected="#27334f",
    border="#2d323d", text="#e8eaf0", muted="#9aa3b2", faint="#6b7384", accent="#6ea8fe",
    accent_hover="#8dbbff", on_accent="#0b1220", danger="#ff7b7b",
    cat_image="#b794f6", cat_text="#9fb3c8", cat_link="#5eb0ff", cat_code="#5fd38d", cat_other="#f0b35a",
)
LIGHT = Palette(
    name="light", bg="#f4f5f8", sidebar="#eceef3", surface="#ffffff", hover="#eef1f7", selected="#e1eafe",
    border="#d9dde5", text="#14161a", muted="#566070", faint="#8a93a3", accent="#2563eb",
    accent_hover="#1d4fd0", on_accent="#ffffff", danger="#c62828",
    cat_image="#7c3aed", cat_text="#475569", cat_link="#2563eb", cat_code="#15803d", cat_other="#b45309",
)
_SCHEMES = {"dark": DARK, "light": LIGHT}


def contrast_ratio(fg: str, bg: str) -> float:
    """Tỉ lệ tương phản WCAG giữa hai màu hex."""
    def lum(color: str) -> float:
        c = QColor(color)
        chan = []
        for v in (c.redF(), c.greenF(), c.blueF()):
            chan.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2]

    a, b = sorted((lum(fg), lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


# --- trạng thái giao diện hiện tại ----------------------------------------------------------------


class _Bus(QObject):
    changed = Signal()


bus = _Bus()
_current: Palette = DARK


def current() -> Palette:
    return _current


def system_scheme() -> str:
    """Tối là mặc định; chỉ sáng khi hệ thống đặt sáng. CLIPVAULT_THEME=dark|light để ép."""
    forced = os.environ.get("CLIPVAULT_THEME", "").lower()
    if forced in _SCHEMES:
        return forced
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
    except (AttributeError, RuntimeError):
        return "dark"
    return "light" if scheme == Qt.ColorScheme.Light else "dark"


def set_scheme(name: str) -> None:
    global _current
    palette = _SCHEMES.get(name)
    if palette is None or palette is _current:
        return
    _current = palette
    app = QGuiApplication.instance()
    if app is not None and hasattr(app, "setPalette"):
        app.setPalette(qpalette(palette))
    bus.changed.emit()


def install(app) -> None:
    """Gọi một lần lúc khởi động: style Fusion (QSS nhất quán), palette theo scheme, theo dõi đổi scheme."""
    app.setStyle("Fusion")
    set_scheme(system_scheme())
    app.setPalette(qpalette(current()))
    try:
        app.styleHints().colorSchemeChanged.connect(lambda _s: set_scheme(system_scheme()))
    except AttributeError:
        pass


def qpalette(p: Palette) -> QPalette:
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: p.bg, QPalette.ColorRole.WindowText: p.text,
        QPalette.ColorRole.Base: p.surface, QPalette.ColorRole.AlternateBase: p.hover,
        QPalette.ColorRole.Text: p.text, QPalette.ColorRole.Button: p.surface,
        QPalette.ColorRole.ButtonText: p.text, QPalette.ColorRole.Highlight: p.accent,
        QPalette.ColorRole.HighlightedText: p.on_accent, QPalette.ColorRole.ToolTipBase: p.surface,
        QPalette.ColorRole.ToolTipText: p.text, QPalette.ColorRole.PlaceholderText: p.muted,
        QPalette.ColorRole.Link: p.accent,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(p.faint))
    return pal


# --- font -----------------------------------------------------------------------------------------


def ui_font(size: float = SIZE_BASE, bold: bool = False) -> QFont:
    font = QFont()
    font.setFamilies([f.strip('"') for f in FONT_UI[:-1]])
    font.setPointSizeF(size)
    font.setBold(bold)
    return font


def mono_font(size: float = SIZE_BASE) -> QFont:
    font = QFont()
    font.setFamilies([f.strip('"') for f in FONT_MONO[:-1]])
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSizeF(size)
    return font


# --- QSS -------------------------------------------------------------------------------------------

_QSS = Template("""
* { font-family: $font_ui; font-size: ${size_base}pt; }
QWidget { color: $text; }
QMainWindow, QDialog, QSplitter, QWidget#content, QWidget#previewPanel { background: $bg; }
QMessageBox { background: $bg; }
QSplitter::handle { background: $border; }
QSplitter::handle:horizontal { width: 1px; }

QStatusBar { background: $bg; color: $muted; border-top: 1px solid $border; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: $muted; font-size: ${size_small}pt; padding: 0 ${sp1}px; }

QListWidget#sidebar { background: $sidebar; border: none; outline: none; }
QListView#history { background: transparent; border: none; outline: none; }
QListView#history:focus { border: none; }

QLineEdit#search {
  background: $surface; color: $text; border: 1px solid $border; border-radius: ${r_md}px;
  padding: 0 ${sp1}px; min-height: ${sp5}px; selection-background-color: $accent; selection-color: $on_accent;
}
QLineEdit#search:hover { border-color: $faint; }
QLineEdit#search:focus { border: 1px solid $accent; }

QPlainTextEdit#previewText {
  background: $surface; color: $text; border: 1px solid $border; border-radius: ${r_lg}px;
  padding: ${sp2}px; selection-background-color: $accent; selection-color: $on_accent;
}
QLabel#previewImage, QLabel#previewMessage {
  background: $surface; border: 1px solid $border; border-radius: ${r_lg}px; color: $muted;
  padding: ${sp2}px;
}
QLabel#previewEmpty, QLabel#empty { color: $muted; background: transparent; }
QLabel#empty { padding: ${sp3}px; }
QLabel#title { font-size: ${size_title}pt; font-weight: 600; background: transparent; }
QLabel#meta { color: $muted; font-size: ${size_small}pt; background: transparent; }

QPushButton, QToolButton {
  background: $surface; color: $text; border: 1px solid $border; border-radius: ${r_md}px;
  padding: ${sp1}px ${sp1_5}px; min-height: ${sp2}px;
}
QPushButton:hover, QToolButton:hover { background: $hover; border-color: $faint; }
QPushButton:pressed, QToolButton:pressed { background: $selected; }
QPushButton:focus, QToolButton:focus { border: 1px solid $accent; }
QPushButton:disabled, QToolButton:disabled { color: $faint; background: transparent; border-color: $border; }
QPushButton[variant="primary"], QToolButton[variant="primary"] { background: $accent; color: $on_accent; border-color: $accent; font-weight: 600; }
QPushButton[variant="primary"]:hover, QToolButton[variant="primary"]:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton[variant="primary"]:disabled, QToolButton[variant="primary"]:disabled { background: $border; color: $faint; border-color: $border; }
QPushButton[variant="danger"]:hover, QToolButton[variant="danger"]:hover { color: $danger; border-color: $danger; }
QToolButton::menu-indicator { subcontrol-position: right center; subcontrol-origin: padding; right: ${sp1}px; }

QMenu { background: $surface; color: $text; border: 1px solid $border; border-radius: ${r_md}px; padding: ${sp0_5}px; }
QMenu::item { padding: ${sp1}px ${sp3}px ${sp1}px ${sp2}px; border-radius: ${r_sm}px; }
QMenu::item:selected { background: $selected; }
QMenu::indicator { width: ${sp2}px; height: ${sp2}px; }
QMenu::separator { height: 1px; background: $border; margin: ${sp0_5}px ${sp1}px; }

QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: ${sp0_5}px ${sp1}px; }

QScrollBar:vertical { background: transparent; width: ${sp1}px; margin: 0; }
QScrollBar::handle:vertical { background: $border; border-radius: ${r_sm}px; min-height: ${sp4}px; }
QScrollBar::handle:vertical:hover { background: $faint; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: ${sp1}px; margin: 0; }
QScrollBar::handle:horizontal { background: $border; border-radius: ${r_sm}px; min-width: ${sp4}px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
""")


def stylesheet(p: Palette | None = None) -> str:
    p = p or current()
    values = {k: v for k, v in p.__dict__.items() if isinstance(v, str)}
    values.update(
        font_ui=", ".join(FONT_UI), size_small=SIZE_SMALL, size_base=SIZE_BASE, size_title=SIZE_TITLE,
        r_sm=RADIUS_SM, r_md=RADIUS_MD, r_lg=RADIUS_LG,
        sp0_5=sp(0.5), sp1=sp(1), sp1_5=sp(1.5), sp2=sp(2), sp3=sp(3), sp4=sp(4), sp5=sp(5),
    )
    return _QSS.substitute(values)


# --- icon vẽ bằng code (lưới 24, nét tròn) ------------------------------------------------------------


def _poly(*pts: tuple[float, float]) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in pts])


def _i_all(p: QPainter, c: QColor, filled: bool) -> None:
    for x, y in ((4, 4), (13.5, 4), (4, 13.5), (13.5, 13.5)):
        p.drawRoundedRect(QRectF(x, y, 6.5, 6.5), 1.8, 1.8)


def _i_image(p, c, filled):
    p.drawRoundedRect(QRectF(3, 4.5, 18, 15), 3, 3)
    p.drawEllipse(QPointF(9, 10), 1.6, 1.6)
    p.drawPolyline(_poly((4.5, 18), (10, 13), (14, 16.5), (16.5, 14.5), (20, 18)))


def _i_text(p, c, filled):
    p.drawLine(QPointF(4, 7), QPointF(20, 7))
    p.drawLine(QPointF(4, 12), QPointF(20, 12))
    p.drawLine(QPointF(4, 17), QPointF(13, 17))


def _i_link(p, c, filled):
    p.save()
    p.translate(12, 12)
    p.rotate(-45)
    p.drawRoundedRect(QRectF(-10, -3.6, 11.5, 7.2), 3.6, 3.6)
    p.drawRoundedRect(QRectF(-1.5, -3.6, 11.5, 7.2), 3.6, 3.6)
    p.restore()


def _i_code(p, c, filled):
    p.drawPolyline(_poly((8.5, 7), (3.5, 12), (8.5, 17)))
    p.drawPolyline(_poly((15.5, 7), (20.5, 12), (15.5, 17)))
    p.drawLine(QPointF(13.5, 5.5), QPointF(10.5, 18.5))


def _i_other(p, c, filled):
    p.setBrush(c)
    for x in (5.5, 12, 18.5):
        p.drawEllipse(QPointF(x, 12), 1.5, 1.5)


def _i_pinned(p, c, filled):
    if filled:
        p.setBrush(c)
    p.drawPolygon(_poly((8, 3.5), (16, 3.5), (15, 10), (18, 13.5), (6, 13.5), (9, 10)))
    p.drawLine(QPointF(12, 13.5), QPointF(12, 21))


def _i_copy(p, c, filled):
    p.drawRoundedRect(QRectF(8.5, 8.5, 12, 12), 2.5, 2.5)  # tờ phía trước
    p.drawPolyline(_poly((15.5, 5.5), (15.5, 4.5), (4.5, 4.5), (4.5, 15.5), (5.5, 15.5)))  # tờ phía sau


def _i_delete(p, c, filled):
    p.drawLine(QPointF(4, 7), QPointF(20, 7))
    p.drawPolyline(_poly((9, 7), (9, 4.5), (15, 4.5), (15, 7)))
    p.drawPolygon(_poly((6.5, 7), (17.5, 7), (16.5, 20), (7.5, 20)))
    p.drawLine(QPointF(10, 11), QPointF(10, 16.5))
    p.drawLine(QPointF(14, 11), QPointF(14, 16.5))


def _i_tag(p, c, filled):
    p.drawPolygon(_poly((3.5, 12), (12, 3.5), (20.5, 3.5), (20.5, 12), (12, 20.5)))
    p.setBrush(c)
    p.drawEllipse(QPointF(16, 8), 1.4, 1.4)


def _i_search(p, c, filled):
    p.drawEllipse(QPointF(10.5, 10.5), 6, 6)
    p.drawLine(QPointF(15, 15), QPointF(20.5, 20.5))


_ICONS = {
    "all": _i_all, "image": _i_image, "text": _i_text, "link": _i_link, "code": _i_code, "other": _i_other,
    "pinned": _i_pinned, "copy": _i_copy, "delete": _i_delete, "tag": _i_tag, "search": _i_search,
}
ICON_NAMES = tuple(_ICONS)


def draw_icon(painter: QPainter, name: str, rect, color: QColor | str, filled: bool = False,
              stroke: float = 1.75) -> None:
    """Vẽ icon `name` vừa khít `rect` (QRect/QRectF)."""
    rect = QRectF(rect)
    scale = min(rect.width(), rect.height()) / 24
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(rect.center().x() - 12 * scale, rect.center().y() - 12 * scale)
    painter.scale(scale, scale)
    col = QColor(color)
    pen = QPen(col, stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    _ICONS[name](painter, col, filled)
    painter.restore()


def pixmap(name: str, color: QColor | str | None = None, size: int = 20, filled: bool = False,
           dpr: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    draw_icon(painter, name, QRectF(0, 0, size, size), color or current().text, filled)
    painter.end()
    return pm


def icon(name: str, color: QColor | str | None = None, size: int = 20, filled: bool = False) -> QIcon:
    """QIcon theo màu hiện tại (có biến thể disabled)."""
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size, filled), QIcon.Mode.Normal)
    ic.addPixmap(pixmap(name, current().faint, size, filled), QIcon.Mode.Disabled)
    return ic


def badge_pixmap(category: str, size: int = 32, dpr: float = 2.0) -> QPixmap:
    """Ô vuông bo góc tô nhạt màu loại + icon loại (dùng ở preview)."""
    p = current()
    color = p.category_color(category)
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    tint = QColor(color)
    tint.setAlphaF(0.16)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(tint)
    painter.drawRoundedRect(QRectF(0, 0, size, size), RADIUS_MD, RADIUS_MD)
    inner = size * 0.55
    draw_icon(painter, category if category in _ICONS else "other",
              QRectF((size - inner) / 2, (size - inner) / 2, inner, inner), color)
    painter.end()
    return pm


def app_icon() -> QIcon:
    """Biểu tượng dự phòng của app (khi không có assets/icon.png)."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(DARK.accent))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRectF(4, 4, 56, 56), RADIUS_LG, RADIUS_LG)
    draw_icon(painter, "copy", QRectF(16, 16, 32, 32), QColor(DARK.on_accent), stroke=2.2)
    painter.end()
    return QIcon(pm)
