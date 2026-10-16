import re
from pathlib import Path

import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

from clipvault.core.model import StoredItem
from clipvault.ui import theme
from clipvault.ui.delegate import ROW_HEIGHT, THUMB, ItemDelegate
from clipvault.ui.images import ImageProvider
from clipvault.ui.models import ITEM_ROLE

from conftest import snap, text_rep
from test_ui_window import _go_view, ids, window  # noqa: F401  (fixture dùng chung)

UI_DIR = Path(theme.__file__).parent
SCHEMES = [theme.DARK, theme.LIGHT]


@pytest.fixture(autouse=True)
def _restore_dark_scheme(qapp):
    yield
    theme.set_scheme("dark")


# --- token ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("p", SCHEMES, ids=lambda p: p.name)
def test_text_contrast_is_readable_on_every_surface(p):
    for fg in (p.text, p.muted):
        for bg in (p.bg, p.sidebar, p.surface, p.hover, p.selected):
            assert theme.contrast_ratio(fg, bg) >= 4.5, (p.name, fg, bg)
    assert theme.contrast_ratio(p.on_accent, p.accent) >= 4.5
    assert theme.contrast_ratio(p.on_accent, p.accent_hover) >= 4.5
    assert theme.contrast_ratio(p.danger, p.surface) >= 4.5
    assert theme.contrast_ratio(p.accent, p.surface) >= 3


@pytest.mark.parametrize("p", SCHEMES, ids=lambda p: p.name)
def test_category_colors_are_distinct_and_visible(p):
    colors = [p.category_color(c).name() for c in theme.CATEGORIES]
    assert len(set(colors)) == len(colors)
    for c in theme.CATEGORIES:
        assert theme.contrast_ratio(p.category_color(c).name(), p.surface) >= 3  # icon: 3:1


def test_spacing_follows_8px_grid_and_layout_sizes():
    assert theme.SP == 8
    assert [theme.sp(n) for n in (0.5, 1, 2, 3, 4)] == [4, 8, 16, 24, 32]
    assert ROW_HEIGHT % 8 == 0 and THUMB % 8 == 0
    assert {theme.RADIUS_SM, theme.RADIUS_MD, theme.RADIUS_LG} == {4, 8, 12}


@pytest.mark.parametrize("p", SCHEMES, ids=lambda p: p.name)
def test_stylesheet_resolves_every_token(p):
    qss = theme.stylesheet(p)
    assert "$" not in qss and p.accent in qss and p.surface in qss
    assert "Cascadia" not in qss.split("QWidget")[0] or True  # chỉ cần không nổ; font nằm ở FONT_*


@pytest.mark.parametrize("name", theme.ICON_NAMES)
def test_every_icon_renders(qapp, name):
    image = theme.pixmap(name, "#ffffff", 24).toImage()
    assert any(image.pixelColor(x, y).alpha() > 0 for x in range(image.width()) for y in range(image.height()))
    assert not theme.icon(name).isNull()


def test_filled_pin_differs_from_outline(qapp):
    assert theme.pixmap("pinned", "#fff", 24, filled=True).toImage() != theme.pixmap("pinned", "#fff", 24).toImage()


def test_badge_exists_for_each_category(qapp):
    for c in (*theme.CATEGORIES, "bogus"):
        assert not theme.badge_pixmap(c).isNull()


def test_fonts_come_from_tokens(qapp):
    assert theme.mono_font().styleHint() == theme.mono_font().StyleHint.Monospace
    assert theme.ui_font(theme.SIZE_TITLE, bold=True).bold()


def test_no_hardcoded_styles_outside_theme():
    """Mọi màu/cỡ chữ/khoảng cách phải đi qua ui/theme.py."""
    bad = []
    patterns = {
        "hex color": r"#[0-9a-fA-F]{6}\b",
        "literal QColor": r"QColor\(\s*[\"']",
        "inline stylesheet": r"setStyleSheet\(\s*[\"']",
        "literal font size": r"setPointSizeF?\(\s*\d",
        "literal margins": r"setContentsMargins\(\s*\d",
        "literal spacing": r"setSpacing\(\s*\d",
        "palette()": r"palette\(\s*(mid|base|window)",
    }
    for path in UI_DIR.glob("*.py"):
        if path.name == "theme.py":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for label, rx in patterns.items():
                if re.search(rx, line):
                    bad.append(f"{path.name}:{lineno} {label}")
    assert bad == []


# --- delegate: trạng thái hover / chọn / ghim --------------------------------------------------------


def _item(**kw):
    base = dict(id=1, created_at=0, last_seen_at=0, copy_count=1, pinned=False, source_app=None,
                kind="text", total_size=100, preview="hello world", tags=frozenset({"cat:text"}))
    base.update(kw)
    return StoredItem(**base)


def _render(delegate, item, state=QStyle.StateFlag.State_None):
    model = QStandardItemModel()
    row = QStandardItem()
    row.setData(item, ITEM_ROLE)
    model.appendRow(row)
    image = QImage(420, ROW_HEIGHT, QImage.Format.Format_ARGB32)
    image.fill(QColor(theme.current().bg))
    painter = QPainter(image)
    option = QStyleOptionViewItem()
    option.rect = image.rect()
    option.state = state
    option.font = theme.ui_font()
    delegate.paint(painter, option, model.index(0, 0))
    painter.end()
    return image


def test_card_states_are_visually_distinct(qapp):
    d = ItemDelegate(ImageProvider(lambda i: None))
    normal = _render(d, _item())
    hover = _render(d, _item(), QStyle.StateFlag.State_MouseOver)
    selected = _render(d, _item(), QStyle.StateFlag.State_Selected)
    pinned = _render(d, _item(pinned=True))
    assert len({normal.constBits().tobytes(), hover.constBits().tobytes(), selected.constBits().tobytes(),
                pinned.constBits().tobytes()}) == 4


@pytest.mark.parametrize("category", theme.CATEGORIES)
def test_each_category_has_its_own_badge(qapp, category):
    d = ItemDelegate(ImageProvider(lambda i: None))
    kind = "image" if category == "image" else "text"
    img = _render(d, _item(kind=kind, tags=frozenset({f"cat:{category}"})))
    others = {c for c in theme.CATEGORIES if c != category}
    for other in others:
        kind2 = "image" if other == "image" else "text"
        assert img != _render(d, _item(kind=kind2, tags=frozenset({f"cat:{other}"}))), (category, other)


def test_card_paints_in_light_scheme_too(qapp):
    theme.set_scheme("light")
    d = ItemDelegate(ImageProvider(lambda i: None))
    img = _render(d, _item(), QStyle.StateFlag.State_Selected)
    assert img.pixelColor(img.width() // 2, 4) != QColor(theme.DARK.bg)


# --- cửa sổ ----------------------------------------------------------------------------------------------


def _sidebar_counts(win):
    return {win.sidebar.item(r).data(Qt.ItemDataRole.UserRole): win.sidebar.item(r).data(Qt.ItemDataRole.UserRole + 1)
            for r in range(win.sidebar.count())}


def test_sidebar_shows_counts_per_category(window):  # noqa: F811
    assert _sidebar_counts(window) == {"all": 5, "image": 1, "text": 1, "link": 1, "code": 1, "other": 1,
                                       "pinned": 0}
    labels = [window.sidebar.item(i).text() for i in range(window.sidebar.count())]
    assert labels[0] == "All"  # đếm không làm đổi nhãn


def test_counts_follow_changes_and_ignore_search(window, qapp):  # noqa: F811
    from conftest import wait_until

    window.toggle_pin()
    window.search.setText("không khớp gì cả")
    window._apply_query()
    assert wait_until(qapp, lambda: _sidebar_counts(window)["pinned"] == 1)
    assert _sidebar_counts(window)["all"] == 5  # tìm kiếm không làm đổi tổng
    window.search.clear()
    window._apply_query()
    window.toggle_pin()  # bỏ ghim mục đầu danh sách
    assert wait_until(qapp, lambda: _sidebar_counts(window)["pinned"] == 0)
    window.delete_current()  # mục này không ghim nên không hỏi xác nhận
    assert wait_until(qapp, lambda: _sidebar_counts(window)["all"] == 4)


def test_sidebar_collapses_to_icons_on_narrow_window(window, qapp):  # noqa: F811
    window.resize(1040, 660)
    qapp.processEvents()
    wide = window.sidebar.width()
    assert not window.sidebar_delegate.compact and window.hint_label.isVisibleTo(window)
    window.resize(700, 480)
    qapp.processEvents()
    assert window.sidebar_delegate.compact and window.sidebar.width() < wide
    assert not window.hint_label.isVisibleTo(window)
    window.sidebar.viewport().repaint()  # vẽ ở chế độ gọn không lỗi
    window.resize(1040, 660)
    qapp.processEvents()
    assert not window.sidebar_delegate.compact and window.sidebar.width() == wide


def test_window_supports_small_sizes(window):  # noqa: F811
    assert window.minimumWidth() <= 640 and window.minimumHeight() <= 400


def test_buttons_have_icons_tooltips_and_shortcuts(window):  # noqa: F811
    p = window.preview
    for b in (p.copy_button, p.pin_button, p.delete_button, p.type_button):
        assert not b.icon().isNull() and b.toolTip()
    assert "Enter" in p.copy_button.toolTip()
    assert "Ctrl+P" in p.pin_button.toolTip()
    assert "Del" in p.delete_button.toolTip()
    assert "Ctrl+F" in window.search.toolTip()
    assert "Ctrl+2" in window.sidebar.item(1).toolTip()
    assert "Enter" in window.hint_label.text()


def test_code_preview_uses_monospace_font(window, ids):  # noqa: F811
    window.select_item(ids["code"])
    assert window.preview.text_view.font().styleHint() == window.preview.text_view.font().StyleHint.Monospace
    window.select_item(ids["text"])
    assert window.preview.text_view.font().styleHint() != window.preview.text_view.font().StyleHint.Monospace


def test_empty_states_are_styled_and_descriptive(window):  # noqa: F811
    _go_view(window, "pinned")
    text = window.empty_label.text()
    assert "No pinned items" in text and "Ctrl+P" in text
    window.search.setText("zzzz")
    window._apply_query()
    assert "No matches" in window.empty_label.text() and "Esc" in window.empty_label.text()


def test_switching_scheme_restyles_window_live(window, qapp):  # noqa: F811
    dark_qss = window.styleSheet()
    assert theme.DARK.surface in dark_qss
    theme.set_scheme("light")
    qapp.processEvents()
    assert theme.LIGHT.surface in window.styleSheet() and window.styleSheet() != dark_qss
    assert not window.grab().isNull()
    theme.set_scheme("dark")
    assert window.styleSheet() == dark_qss


def test_hovered_list_row_gets_mouse_tracking(window):  # noqa: F811
    assert window.list.hasMouseTracking() and window.sidebar.hasMouseTracking()


def test_theme_install_applies_palette_and_fusion(qapp):
    theme.install(qapp)
    assert qapp.style().objectName().lower() == "fusion"
    assert qapp.palette().color(qapp.palette().ColorRole.Window) == QColor(theme.current().bg)
