"""Design tokens + QSS + icon vẽ bằng code. Mọi màu, cỡ chữ, khoảng cách, bo góc của UI nằm ở đây.

Các file UI khác không hard-code style: chúng lấy token (`current()`, `sp()`, `RADIUS_*`, `ui_font()`...),
gọi `icon()/draw_icon()` và dùng `stylesheet()` do module này tạo.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from string import Template

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QGuiApplication, QIcon, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import QToolTip, QWidget

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
SIZE_SMALL, SIZE_BASE, SIZE_TITLE = 9, 10, 13  # pt (theo FONT_SCALES; đổi bằng apply())
FONT_SCALES = {"small": (8, 9, 12), "medium": (9, 10, 13), "large": (11, 12, 15)}  # (nhỏ, thường, tiêu đề)
# Chiều cao một dòng danh sách (px) theo mật độ và cỡ chữ.
ROW_HEIGHTS = {
    "comfortable": {"small": 60, "medium": 64, "large": 72},
    "compact": {"small": 48, "medium": 52, "large": 60},
}

CATEGORIES = ("image", "text", "link", "code", "other")
SIDEBAR_ICONS = {"all": "all", "image": "image", "text": "text", "link": "link", "code": "code",
                 "other": "other", "pinned": "pinned"}


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    sidebar: str
    surface: str
    elevated: str
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
    warn: str
    grad_start: str
    grad_end: str
    cat_image: str
    cat_text: str
    cat_link: str
    cat_code: str
    cat_other: str

    def category_color(self, category: str) -> QColor:
        return QColor(getattr(self, f"cat_{category}", self.accent))


DARK = Palette(
    name="dark", bg="#12141a", sidebar="#161922", surface="#1c2029", elevated="#232836", hover="#232836",
    selected="#222c44", border="#2b3140", text="#e6e9f0", muted="#8b93a7", faint="#6b7384", accent="#5b8cff",
    accent_hover="#7ba2ff", on_accent="#0b1220", danger="#ff7b7b", warn="#f0b35a",
    grad_start="#12141a", grad_end="#1a1f33",
    cat_image="#b794f6", cat_text="#9fb3c8", cat_link="#5eb0ff", cat_code="#5fd38d", cat_other="#f0b35a",
)
LIGHT = Palette(
    name="light", bg="#f4f5f8", sidebar="#eceef3", surface="#fbfcfe", elevated="#fdfdfe", hover="#eef1f7",
    selected="#e3ebfc", border="#dde1ea", text="#1b1f2a", muted="#5b6578", faint="#8a93a3", accent="#3566e4",
    accent_hover="#2b57cc", on_accent="#ffffff", danger="#c62828", warn="#b45309",
    grad_start="#f4f5f8", grad_end="#e9eefb",
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
_mode = "system"  # system | light | dark
_font_size = "medium"
_density = "comfortable"


def current() -> Palette:
    return _current


def mode() -> str:
    return _mode


def font_size() -> str:
    return _font_size


def density() -> str:
    return _density


def row_height() -> int:
    return ROW_HEIGHTS[_density][_font_size]


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


def resolved_scheme() -> str:
    return system_scheme() if _mode == "system" else _mode


def _sync_title_bar() -> bool:
    """Đặt color scheme của Qt (title bar Windows đổi theo). False nếu phiên bản Qt không hỗ trợ."""
    app = QGuiApplication.instance()
    if app is None:
        return False
    hints = app.styleHints()
    if not (hasattr(hints, "setColorScheme") and hasattr(hints, "unsetColorScheme")):
        return False
    if _mode == "system":
        hints.unsetColorScheme()
    else:
        hints.setColorScheme(Qt.ColorScheme.Light if _mode == "light" else Qt.ColorScheme.Dark)
    return True


def _install_look(changed_extra: bool = False) -> None:
    """Áp palette + QSS toàn app theo trạng thái hiện tại; phát bus.changed khi có gì đổi."""
    global _current
    palette = _SCHEMES[resolved_scheme()]
    changed = changed_extra or palette is not _current
    _current = palette
    app = QGuiApplication.instance()
    if app is not None and hasattr(app, "setPalette"):
        app.setPalette(qpalette(palette))
        QToolTip.setPalette(qpalette(palette))
    if changed:
        bus.changed.emit()


def set_scheme(name: str) -> None:
    """Đặt thẳng palette (không đổi mode). Dùng cho test và khi theo hệ thống."""
    global _current
    palette = _SCHEMES.get(name)
    if palette is None or palette is _current:
        return
    _current = palette
    app = QGuiApplication.instance()
    if app is not None and hasattr(app, "setPalette"):
        app.setPalette(qpalette(palette))
        QToolTip.setPalette(qpalette(palette))
    bus.changed.emit()


def apply(theme_mode: str | None = None, font: str | None = None, dens: str | None = None) -> None:
    """Đổi chế độ sáng/tối/hệ thống, cỡ chữ, mật độ. Áp ngay, phát bus.changed một lần."""
    global _mode, _font_size, _density, SIZE_SMALL, SIZE_BASE, SIZE_TITLE
    extra = False
    if theme_mode is not None and theme_mode in ("system", "light", "dark") and theme_mode != _mode:
        _mode = theme_mode
        _sync_title_bar()
        extra = True
    if font in FONT_SCALES and font != _font_size:
        _font_size = font
        SIZE_SMALL, SIZE_BASE, SIZE_TITLE = FONT_SCALES[font]
        extra = True
    if dens in ROW_HEIGHTS and dens != _density:
        _density = dens
        extra = True
    _install_look(extra)


def install(app) -> None:
    """Gọi một lần lúc khởi động: style Fusion (QSS nhất quán), palette theo mode, theo dõi đổi scheme hệ thống."""
    app.setStyle("Fusion")
    _sync_title_bar()
    _install_look(True)
    try:
        # Chỉ theo hệ thống khi mode == "system"; mode cố định thì bỏ qua tín hiệu.
        app.styleHints().colorSchemeChanged.connect(lambda _s: _mode == "system" and _install_look())
    except AttributeError:
        pass


class GradientBackground(QWidget):
    """Widget gốc DUY NHẤT có gradient: chéo từ trên-trái xuống dưới-phải, vẽ bằng QLinearGradient.

    Mọi widget con để nền trong suốt hoặc màu phẳng của token, nên gradient liền một mảng khi resize.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("gradientRoot")
        bus.changed.connect(self.update)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = current()
        grad = QLinearGradient(0, 0, self.width(), self.height())
        grad.setColorAt(0.0, QColor(p.grad_start))
        grad.setColorAt(1.0, QColor(p.grad_end))
        painter = QPainter(self)
        painter.fillRect(self.rect(), grad)
        painter.end()


def qpalette(p: Palette) -> QPalette:
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: p.bg, QPalette.ColorRole.WindowText: p.text,
        QPalette.ColorRole.Base: p.surface, QPalette.ColorRole.AlternateBase: p.hover,
        QPalette.ColorRole.Text: p.text, QPalette.ColorRole.Button: p.surface,
        QPalette.ColorRole.ButtonText: p.text, QPalette.ColorRole.Highlight: p.accent,
        QPalette.ColorRole.HighlightedText: p.on_accent, QPalette.ColorRole.ToolTipBase: p.elevated,
        QPalette.ColorRole.ToolTipText: p.text, QPalette.ColorRole.PlaceholderText: p.muted,
        QPalette.ColorRole.Link: p.accent,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(p.faint))
    return pal


# --- font -----------------------------------------------------------------------------------------


def ui_font(size: float | None = None, bold: bool = False) -> QFont:
    size = SIZE_BASE if size is None else size
    font = QFont()
    font.setFamilies([f.strip('"') for f in FONT_UI[:-1]])
    font.setPointSizeF(size)
    font.setBold(bold)
    return font


def mono_font(size: float | None = None) -> QFont:
    size = SIZE_BASE if size is None else size
    font = QFont()
    font.setFamilies([f.strip('"') for f in FONT_MONO[:-1]])
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSizeF(size)
    return font


# --- QSS -------------------------------------------------------------------------------------------

_QSS = Template("""
* { font-family: $font_ui; font-size: ${size_base}pt; }
QWidget { color: $text; }
QMainWindow, QDialog, QMessageBox { background: $bg; }
QSplitter, QWidget#content, QWidget#previewPanel { background: transparent; }
QWidget#sidebarPanel { background: $sidebar; }
QSplitter::handle { background: $border; }
QSplitter::handle:horizontal { width: 1px; }

QStatusBar { background: $bg; color: $muted; border-top: 1px solid $border; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: $muted; font-size: ${size_small}pt; padding: 0 ${sp1}px; }

QListWidget#sidebar { background: transparent; border: none; outline: none; }
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

QMenu { background: $elevated; color: $text; border: 1px solid $border; border-radius: ${r_md}px; padding: ${sp0_5}px; }
QMenu::item { padding: ${sp1}px ${sp3}px ${sp1}px ${sp2}px; border-radius: ${r_sm}px; }
QMenu::item:selected { background: $selected; }
QMenu::indicator { width: ${sp2}px; height: ${sp2}px; }
QMenu::separator { height: 1px; background: $border; margin: ${sp0_5}px ${sp1}px; }

QToolTip { background: $elevated; color: $text; border: 1px solid $border; padding: ${sp0_5}px ${sp1}px; }

QDialog QScrollArea, QScrollArea#settingsScroll { background: transparent; border: none; }
QWidget#settingsBody { background: $bg; }
QGroupBox { background: $surface; border: 1px solid $border; border-radius: ${r_lg}px; margin-top: ${sp2}px; padding: ${sp2}px ${sp2}px ${sp1_5}px ${sp2}px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: ${sp2}px; padding: 0 ${sp0_5}px; color: $text; background: transparent; }
QGroupBox QLabel { background: transparent; font-weight: 400; }
QLabel#error { color: $danger; background: transparent; }
QLabel#hint { color: $muted; font-size: ${size_small}pt; background: transparent; }
QCheckBox, QRadioButton { background: transparent; spacing: ${sp1}px; font-weight: 400; }
QLineEdit { background: $elevated; color: $text; border: 1px solid $border; border-radius: ${r_md}px; padding: ${sp0_5}px ${sp1}px; min-height: ${sp3}px; selection-background-color: $accent; selection-color: $on_accent; }
QLineEdit:focus { border: 1px solid $accent; }
QLineEdit[invalid="true"] { border: 1px solid $danger; }
QComboBox { background: $elevated; color: $text; border: 1px solid $border; border-radius: ${r_md}px; padding: ${sp0_5}px ${sp1}px; min-height: ${sp3}px; }
QComboBox:hover { border-color: $faint; }
QComboBox:focus { border: 1px solid $accent; }
QComboBox QAbstractItemView { background: $elevated; color: $text; border: 1px solid $border; outline: 0; selection-background-color: $selected; selection-color: $text; padding: ${sp0_5}px; }
QToolButton#themeSwitch, QToolButton#settingsButton { background: transparent; border: 1px solid transparent; border-radius: ${r_md}px; padding: ${sp1}px; }
QToolButton#themeSwitch:hover, QToolButton#settingsButton:hover { background: $hover; border-color: $border; }
QFrame#pauseBanner { background: $elevated; border: 1px solid $warn; border-radius: ${r_md}px; }
QFrame#pauseBanner QLabel { background: transparent; color: $text; }
QLabel#pauseStatus { color: $warn; font-size: ${size_small}pt; font-weight: 600; padding: 0 ${sp1}px; }

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


def _i_sun(p, c, filled):
    p.drawEllipse(QPointF(12, 12), 4.2, 4.2)
    for k in range(8):
        p.save()
        p.translate(12, 12)
        p.rotate(k * 45)
        p.drawLine(QPointF(0, -7.5), QPointF(0, -10))
        p.restore()


def _i_moon(p, c, filled):
    disc = QPainterPath()
    disc.addEllipse(QPointF(12, 12), 8, 8)
    bite = QPainterPath()
    bite.addEllipse(QPointF(16.5, 8.5), 7, 7)
    p.drawPath(disc.subtracted(bite))


def _i_gear(p, c, filled):
    # Bánh răng: thân tròn có 8 răng vuông + lỗ giữa (khác hẳn mặt trời là vòng tròn + tia)
    teeth, r_in, r_out, half = 8, 6.8, 9.6, 0.20  # half: nửa góc (rad) của mỗi răng
    step = 2 * math.pi / teeth
    pts = []
    for k in range(teeth):
        a = k * step
        for ang, r in ((a - half * 1.5, r_in), (a - half, r_out), (a + half, r_out), (a + half * 1.5, r_in)):
            pts.append((12 + r * math.sin(ang), 12 - r * math.cos(ang)))
    p.drawPolygon(_poly(*pts))
    p.drawEllipse(QPointF(12, 12), 2.8, 2.8)


def _i_pause(p, c, filled):
    p.drawLine(QPointF(9, 5.5), QPointF(9, 18.5))
    p.drawLine(QPointF(15, 5.5), QPointF(15, 18.5))


_ICONS = {
    "all": _i_all, "image": _i_image, "text": _i_text, "link": _i_link, "code": _i_code, "other": _i_other,
    "pinned": _i_pinned, "sun": _i_sun, "moon": _i_moon, "gear": _i_gear, "pause": _i_pause, "copy": _i_copy, "delete": _i_delete, "tag": _i_tag, "search": _i_search,
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
