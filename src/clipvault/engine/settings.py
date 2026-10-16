"""Cài đặt người dùng: giá trị mặc định, kiểm tra hợp lệ, lưu trong bảng `settings` (cùng nơi với `ui.hotkey`).

Không import Qt. Giới hạn dung lượng/số mục dùng đúng khóa `limits.*` mà `Limits.from_settings` đã đọc.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace

from clipvault.core.limits import MB, Limits
from clipvault.storage.db import Database

THEME_MODES = ("system", "light", "dark")
FONT_SIZES = ("small", "medium", "large")
DENSITIES = ("compact", "comfortable")

MAX_ITEMS_RANGE = (1, 1_000_000)
MAX_TOTAL_MB_RANGE = (1, 1_048_576)  # tới 1 TB
RETENTION_DAYS_RANGE = (0, 3650)  # 0 = tắt


class SettingsError(ValueError):
    """Giá trị cài đặt không hợp lệ. Message hiển thị được cho người dùng."""


@dataclass(frozen=True)
class AppSettings:
    theme: str = "system"
    font_size: str = "medium"
    density: str = "comfortable"
    max_items: int = Limits().max_items
    max_total_mb: int = Limits().max_total_bytes // MB
    retention_days: int = 0
    close_to_tray: bool = True
    confirm_delete: bool = False  # giữ hành vi cũ: chỉ hỏi khi mục đã ghim
    paused: bool = False


# field -> khóa trong bảng settings
KEYS = {
    "theme": "ui.theme",
    "font_size": "ui.font_size",
    "density": "ui.density",
    "max_items": "limits.max_items",
    "max_total_mb": "limits.max_total_bytes",  # lưu bằng byte, giống Limits.from_settings
    "retention_days": "retention.days",
    "close_to_tray": "behavior.close_to_tray",
    "confirm_delete": "behavior.confirm_delete",
    "paused": "privacy.paused",
}
_CHOICES = {"theme": THEME_MODES, "font_size": FONT_SIZES, "density": DENSITIES}
_RANGES = {"max_items": MAX_ITEMS_RANGE, "max_total_mb": MAX_TOTAL_MB_RANGE, "retention_days": RETENTION_DAYS_RANGE}
_LABELS = {"max_items": "Số mục tối đa", "max_total_mb": "Dung lượng tối đa (MB)", "retention_days": "Số ngày"}


def parse_int(value: object, field: str) -> int:
    """Số nguyên ASCII trong khoảng của `field`; trống, chữ, số âm, quá lớn đều bị từ chối."""
    low, high = _RANGES[field]
    label = _LABELS[field]
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SettingsError(f"{label}: phải là số nguyên")
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            raise SettingsError(f"{label}: không được để trống")
        digits = text[1:] if text[0] == "-" else text
        if not (digits.isascii() and digits.isdigit()):
            raise SettingsError(f"{label}: phải là số nguyên")
        number = int(text)
    else:
        number = value
    if number < low or number > high:
        raise SettingsError(f"{label}: phải từ {low} đến {high}")
    return number


def validate(field: str, value: object) -> object:
    """Trả giá trị đã chuẩn hóa hoặc ném SettingsError."""
    if field in _CHOICES:
        if value not in _CHOICES[field]:
            raise SettingsError(f"{field}: giá trị không hợp lệ")
        return value
    if field in _RANGES:
        return parse_int(value, field)
    if field in ("close_to_tray", "confirm_delete", "paused"):
        if not isinstance(value, bool):
            raise SettingsError(f"{field}: phải là bật/tắt")
        return value
    raise SettingsError(f"cài đặt không tồn tại: {field}")


def _encode(field: str, value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if field == "max_total_mb":
        return str(int(value) * MB)
    return str(value)


def from_rows(rows: Mapping[str, str]) -> AppSettings:
    """Đọc từ bảng settings; giá trị thiếu hoặc hỏng thì dùng mặc định (không bao giờ ném lỗi)."""
    out = AppSettings()
    for f in fields(AppSettings):
        raw = rows.get(KEYS[f.name])
        if raw is None:
            continue
        default = getattr(out, f.name)
        try:
            if f.name == "max_total_mb":
                value: object = int(raw) // MB
            elif isinstance(default, bool):
                if raw not in ("0", "1"):
                    continue
                value = raw == "1"
            elif isinstance(default, int):
                value = int(raw)
            else:
                value = raw
            out = replace(out, **{f.name: validate(f.name, value)})
        except (ValueError, SettingsError):
            continue
    return out


class SettingsStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def load(self) -> AppSettings:
        return from_rows(self.db.settings())

    def save(self, **changes: object) -> AppSettings:
        """Kiểm tra tất cả trước, rồi mới ghi: một giá trị sai thì không ghi gì."""
        clean = {name: validate(name, value) for name, value in changes.items()}
        current = self.load()
        for name, value in clean.items():
            self.db.set_setting(KEYS[name], _encode(name, value))
            current = replace(current, **{name: value})
        return current

    def reset(self) -> AppSettings:
        """Đặt lại mọi cài đặt về mặc định. Không đụng dữ liệu clipboard."""
        defaults = AppSettings()
        for f in fields(AppSettings):
            self.db.set_setting(KEYS[f.name], _encode(f.name, getattr(defaults, f.name)))
        return defaults

    @staticmethod
    def limits(settings: AppSettings, base: Limits | None = None) -> Limits:
        return replace(base or Limits(), max_items=settings.max_items, max_total_bytes=settings.max_total_mb * MB)
