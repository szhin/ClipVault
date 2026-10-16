"""Trang Settings: Giao diện, Lưu trữ, Hành vi, Quyền riêng tư, Dữ liệu (xóa), Khôi phục mặc định.

Style hoàn toàn do ui/theme.py (object name + thuộc tính), dialog là con của cửa sổ chính nên thừa kế QSS.
Không ghi nội dung clipboard vào log hay thông báo.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QSignalBlocker, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from clipvault.engine.history import DELETE_SCOPES, HistoryError, HistoryService
from clipvault.engine.settings import SettingsError, SettingsStore, parse_int
from clipvault.ui import theme
from clipvault.ui.format import format_size
from clipvault.ui.prefs import Preferences

THEME_LABELS = {"system": "Hệ thống", "light": "Sáng", "dark": "Tối"}
FONT_LABELS = {"small": "Nhỏ", "medium": "Vừa", "large": "Lớn"}
DENSITY_LABELS = {"compact": "Gọn", "comfortable": "Thoải mái"}
CLOSE_LABELS = {True: "Thu xuống khay hệ thống", False: "Thoát hẳn"}
SCOPE_LABELS = {
    "text": "Xóa toàn bộ Text", "image": "Xóa toàn bộ Images", "link": "Xóa toàn bộ Links",
    "code": "Xóa toàn bộ Code", "other": "Xóa toàn bộ Other", "all": "Xóa tất cả",
}


def _combo(options: dict) -> QComboBox:
    box = QComboBox()
    for value, label in options.items():
        box.addItem(label, value)
    return box


class SettingsDialog(QDialog):
    data_changed = Signal()  # dữ liệu clipboard đã bị xóa/dọn: cửa sổ chính phải nạp lại

    def __init__(self, history: HistoryService, prefs: Preferences, parent=None) -> None:
        super().__init__(parent)
        self.history = history
        self.prefs = prefs
        self.setWindowTitle("Cài đặt")
        self.resize(theme.sp(68), theme.sp(78))
        self.setMinimumSize(theme.sp(52), theme.sp(40))

        # --- Giao diện
        self.theme_box = _combo(THEME_LABELS)
        self.font_box = _combo(FONT_LABELS)
        self.density_box = _combo(DENSITY_LABELS)
        appearance = self._group("Giao diện")
        form = QFormLayout(appearance)
        form.addRow("Chế độ", self.theme_box)
        form.addRow("Cỡ chữ", self.font_box)
        form.addRow("Mật độ danh sách", self.density_box)

        # --- Lưu trữ
        self.usage_label = QLabel()
        self.max_items_edit = QLineEdit()
        self.max_mb_edit = QLineEdit()
        self.days_edit = QLineEdit()
        self.storage_error = QLabel()
        self.storage_error.setObjectName("error")
        self.storage_error.setWordWrap(True)
        self.apply_storage_button = QPushButton("Áp dụng")
        self.apply_storage_button.setProperty("variant", "primary")
        self.open_folder_button = QPushButton("Mở thư mục dữ liệu")
        storage = self._group("Lưu trữ")
        form = QFormLayout(storage)
        form.addRow("Đang dùng", self.usage_label)
        form.addRow("Số mục tối đa", self.max_items_edit)
        form.addRow("Dung lượng tối đa (MB)", self.max_mb_edit)
        form.addRow("Tự xóa mục cũ sau (ngày)", self.days_edit)
        hint = QLabel("0 = tắt tự xóa. Mục đã ghim luôn được giữ.")
        hint.setObjectName("hint")
        form.addRow("", hint)
        form.addRow("", self.storage_error)
        buttons = QHBoxLayout()
        buttons.addWidget(self.apply_storage_button)
        buttons.addWidget(self.open_folder_button)
        buttons.addStretch(1)
        form.addRow("", buttons)

        # --- Hành vi
        self.close_box = _combo({True: CLOSE_LABELS[True], False: CLOSE_LABELS[False]})
        self.confirm_check = QCheckBox("Hỏi xác nhận trước khi xóa từng mục")
        behavior = self._group("Hành vi")
        form = QFormLayout(behavior)
        form.addRow("Nút đóng cửa sổ", self.close_box)
        form.addRow("", self.confirm_check)

        # --- Quyền riêng tư
        self.pause_check = QCheckBox("Tạm dừng ghi clipboard")
        privacy = self._group("Quyền riêng tư")
        form = QFormLayout(privacy)
        form.addRow("", self.pause_check)

        # --- Dữ liệu (xóa)
        self.scope_box = _combo({s: SCOPE_LABELS[s] for s in DELETE_SCOPES})
        self.include_pinned = QCheckBox("Bao gồm cả mục đã ghim")  # mặc định TẮT: mục ghim được giữ
        self.delete_button = QPushButton("Xóa")
        self.delete_button.setProperty("variant", "danger")
        self.delete_result = QLabel()
        self.delete_result.setObjectName("hint")
        self.delete_result.setWordWrap(True)
        data = self._group("Dữ liệu")
        form = QFormLayout(data)
        form.addRow("Phạm vi", self.scope_box)
        form.addRow("", self.include_pinned)
        form.addRow("", self.delete_button)
        form.addRow("", self.delete_result)

        # --- Khôi phục
        self.reset_button = QPushButton("Khôi phục cài đặt mặc định")
        reset_note = QLabel("Chỉ đặt lại cài đặt; dữ liệu clipboard không bị xóa.")
        reset_note.setObjectName("hint")

        body = QWidget()
        body.setObjectName("settingsBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(theme.sp(2), theme.sp(1), theme.sp(2), theme.sp(2))
        layout.setSpacing(theme.sp(2))
        for group in (appearance, storage, behavior, privacy, data):
            group.layout().setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            layout.addWidget(group)
        layout.addWidget(self.reset_button)
        layout.addWidget(reset_note)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.sp(0), theme.sp(0), theme.sp(0), theme.sp(0))
        outer.addWidget(scroll)

        self._sync()
        self.refresh_usage()
        self._connect()

    @staticmethod
    def _group(title: str) -> QGroupBox:
        return QGroupBox(title)

    # --- đồng bộ với Preferences -------------------------------------------------------------------

    def _connect(self) -> None:
        self.theme_box.currentIndexChanged.connect(lambda _i: self._set(theme=self.theme_box.currentData()))
        self.font_box.currentIndexChanged.connect(lambda _i: self._set(font_size=self.font_box.currentData()))
        self.density_box.currentIndexChanged.connect(lambda _i: self._set(density=self.density_box.currentData()))
        self.close_box.currentIndexChanged.connect(lambda _i: self._set(close_to_tray=self.close_box.currentData()))
        self.confirm_check.toggled.connect(lambda on: self._set(confirm_delete=on))
        self.pause_check.toggled.connect(lambda on: self._set(paused=on))
        self.apply_storage_button.clicked.connect(self.apply_storage)
        self.open_folder_button.clicked.connect(self.open_data_folder)
        self.delete_button.clicked.connect(self.delete_data)
        self.reset_button.clicked.connect(self.reset_defaults)
        self.prefs.changed.connect(self._on_prefs_changed)

    def _on_prefs_changed(self, _diff) -> None:
        self._sync()

    def _disconnect_prefs(self) -> None:
        try:
            self.prefs.changed.disconnect(self._on_prefs_changed)
        except (RuntimeError, TypeError):
            pass  # đã ngắt rồi

    def done(self, result: int) -> None:
        self._disconnect_prefs()
        super().done(result)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._disconnect_prefs()  # dialog tự xóa khi đóng: không để prefs gọi vào widget đã hủy
        super().closeEvent(event)

    def _set(self, **changes) -> None:
        try:
            self.prefs.set(**changes)
        except SettingsError:
            self._sync()  # giá trị sai: trả widget về trạng thái đã lưu

    def _sync(self) -> None:
        v = self.prefs.values
        for box, value in ((self.theme_box, v.theme), (self.font_box, v.font_size),
                           (self.density_box, v.density), (self.close_box, v.close_to_tray)):
            with QSignalBlocker(box):
                box.setCurrentIndex(max(box.findData(value), 0))
        for check, value in ((self.confirm_check, v.confirm_delete), (self.pause_check, v.paused)):
            with QSignalBlocker(check):
                check.setChecked(value)
        self.max_items_edit.setText(str(v.max_items))
        self.max_mb_edit.setText(str(v.max_total_mb))
        self.days_edit.setText(str(v.retention_days))
        self._show_storage_error("")

    def refresh_usage(self) -> None:
        try:
            stats = self.history.storage_info()
        except HistoryError as exc:
            self.usage_label.setText(str(exc))
            return
        self.usage_label.setText(f"{stats.items} mục · {format_size(stats.blob_bytes)}")

    # --- hộp thoại (tách riêng để test thay thế) ----------------------------------------------------------

    def confirm(self, text: str) -> bool:
        return QMessageBox.question(self, "ClipVault", text) == QMessageBox.StandardButton.Yes

    # --- Lưu trữ ---------------------------------------------------------------------------------------------

    def _show_storage_error(self, text: str, edit: QLineEdit | None = None) -> None:
        self.storage_error.setText(text)
        for e in (self.max_items_edit, self.max_mb_edit, self.days_edit):
            e.setProperty("invalid", e is edit)
            e.style().unpolish(e)
            e.style().polish(e)

    def apply_storage(self) -> bool:
        """Kiểm tra cả ba ô; sai ô nào thì báo ô đó và không lưu gì. Trả True nếu đã lưu."""
        parsed = {}
        for field, edit in (("max_items", self.max_items_edit), ("max_total_mb", self.max_mb_edit),
                            ("retention_days", self.days_edit)):
            try:
                parsed[field] = parse_int(edit.text(), field)
            except SettingsError as exc:
                self._show_storage_error(str(exc), edit)
                return False
        self._show_storage_error("")
        limits = SettingsStore.limits(replace(self.prefs.values, **parsed))
        try:
            expired = self.history.count_expired(parsed["retention_days"])
            trims = self.history.would_trim(limits)
        except HistoryError as exc:
            self._show_storage_error(str(exc))
            return False
        if expired or trims:
            if not self.confirm("Cài đặt mới sẽ xóa các mục chưa ghim cũ nhất để đạt giới hạn "
                                "hoặc quá hạn. Mục đã ghim được giữ. Tiếp tục?"):
                self._sync()
                return False
        self.prefs.set(**parsed)
        try:
            removed = self.history.apply_limits(limits) + self.history.purge_expired(parsed["retention_days"])
        except HistoryError as exc:
            self._show_storage_error(str(exc))
            return False
        if removed:
            self.delete_result.setText(f"Đã xóa {removed} mục theo giới hạn mới.")
            self.data_changed.emit()
        self.refresh_usage()
        return True

    def open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.history.db.data_dir)))

    # --- Dữ liệu (xóa) -----------------------------------------------------------------------------------------

    def delete_data(self) -> int:
        """Xóa theo phạm vi sau khi xác nhận nêu rõ số mục và dung lượng. Trả số mục đã xóa (0 nếu hủy)."""
        scope = self.scope_box.currentData()
        include_pinned = self.include_pinned.isChecked()
        try:
            count, size = self.history.scope_summary(scope, include_pinned)
        except HistoryError as exc:
            self.delete_result.setText(str(exc))
            return 0
        if count == 0:
            self.delete_result.setText("Không có mục nào để xóa.")
            return 0
        pinned_note = "kể cả mục đã ghim" if include_pinned else "mục đã ghim được giữ lại"
        if not self.confirm(f"{SCOPE_LABELS[scope]}: sẽ xóa {count} mục ({format_size(size)}), {pinned_note}. "
                            "Không thể hoàn tác. Tiếp tục?"):
            return 0
        try:
            deleted = self.history.delete_scope(scope, include_pinned)
        except HistoryError as exc:
            self.delete_result.setText(str(exc))
            return 0
        self.delete_result.setText(f"Đã xóa {deleted} mục.")
        self.refresh_usage()
        self.data_changed.emit()
        return deleted

    # --- Khôi phục -----------------------------------------------------------------------------------------------

    def reset_defaults(self) -> bool:
        if not self.confirm("Khôi phục mọi cài đặt về mặc định? Dữ liệu clipboard sẽ không bị xóa."):
            return False
        self.prefs.reset()
        self._sync()
        return True
