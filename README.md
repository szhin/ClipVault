# ClipVault

Trình quản lý clipboard cho máy tính để bàn. Lưu lịch sử text và ảnh bạn đã copy, tìm lại nhanh, ghim mục quan trọng và copy lại đúng định dạng gốc.

- **Nền tảng:** Windows (macOS: chưa hỗ trợ, dự kiến Phase 6). Không có bản mobile.
- **Công nghệ:** Python 3.12, PySide6, SQLite.
- **Riêng tư:** mọi dữ liệu nằm trên máy bạn. Ứng dụng không gọi mạng và không ghi nội dung clipboard vào log.

## Tính năng

- Tự động bắt text và ảnh khi bạn copy; mục trùng chỉ cập nhật thời gian, không tạo bản sao.
- Giữ nguyên dữ liệu gốc (định dạng, byte) nên Copy lại dán được như lúc đầu.
- Tự phân loại: Images, Text, Links, Code (kèm tên ngôn ngữ), Other (email, màu, đường dẫn...). Có thể đổi loại thủ công bằng Change Type.
- Tìm kiếm tức thì, Pin/Unpin, Delete, thumbnail ảnh, giao diện tối/sáng theo Windows.
- Chạy nền ở khay hệ thống; mở bằng phím tắt toàn cục `Ctrl+Shift+V`.
- Bỏ qua nội dung từ trình quản lý mật khẩu (các cờ riêng tư của Windows).
- Giới hạn mặc định: 20 MB mỗi mục, 1 GB tổng, 5000 mục. Khi vượt, mục cũ chưa ghim bị dọn trước; mục ghim không bao giờ bị xóa tự động.

## Cài đặt và chạy

Cần Python 3.12 trên Windows.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m clipvault              # mở cửa sổ
.venv\Scripts\python -m clipvault --background # khởi động ẩn, chỉ còn icon ở khay
```

Chỉ chạy được một bản cùng lúc; chạy lần hai sẽ tự thoát.

## Cách dùng

| Thao tác | Cách làm |
|---|---|
| Mở/ẩn cửa sổ | `Ctrl+Shift+V` hoặc click icon ở khay |
| Chọn mục | `↑` `↓` (cả khi đang gõ ở ô tìm kiếm) |
| Copy mục đang chọn | `Enter`, nút Copy, hoặc double-click, sau đó `Ctrl+V` ở app khác để dán |
| Tìm kiếm | `Ctrl+F`, gõ chữ; `Esc` để xóa tìm kiếm |
| Ghim / bỏ ghim | `Ctrl+P` hoặc nút Pin |
| Xóa | `Del` hoặc nút Delete (mục đang ghim sẽ hỏi xác nhận) |
| Chuyển danh mục | click sidebar hoặc `Ctrl+1` đến `Ctrl+7` |
| Đổi loại | nút Change Type |
| Đóng cửa sổ | `Esc` hoặc nút X: app vẫn chạy nền. Thoát hẳn: chuột phải icon khay > Quit |

Đổi phím tắt toàn cục: ghi khóa `ui.hotkey` (ví dụ `Ctrl+Alt+K`) vào bảng `settings` của cơ sở dữ liệu. Chưa có giao diện cài đặt.

## Dữ liệu lưu ở đâu

`%LOCALAPPDATA%\ClipVault\` gồm `clipvault.db` (lịch sử), `blobs\` (ảnh lớn) và `logs\`. Đặt biến môi trường `CLIPVAULT_DATA_DIR` để dùng thư mục khác (ứng dụng từ chối thư mục nằm trong mã nguồn hoặc thư mục cài đặt). Xóa thư mục này để xóa toàn bộ lịch sử.

## Phát triển

```powershell
.venv\Scripts\python -m pytest -q
```

Test UI chạy không cần màn hình (Qt offscreen). Hai test ghi vào clipboard thật là tùy chọn vì chúng ghi đè clipboard của bạn:

```powershell
$env:CLIPVAULT_LIVE_CLIPBOARD = "1"; .venv\Scripts\python -m pytest -q tests/test_windows_adapter.py
```

Cấu trúc (chi tiết trong [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)):

```
src/clipvault/
  core/        model, ports (Protocol), limits, paths: dùng chung, không gọi API hệ điều hành
  storage/     SQLite + blob store
  classifier/  phân loại (thuần, chỉ đọc)
  engine/      capture, dedupe, retention, lịch sử, paste-back
  ui/          PySide6: cửa sổ, model/view, theme, tray
  adapters/    windows (ctypes Win32) và macos (chưa làm); nơi duy nhất được import API hệ điều hành
tests/
```

Tiến độ và quyết định kiến trúc: [PLAN.md](PLAN.md). Quy tắc làm việc trong repo: [CLAUDE.md](CLAUDE.md).

## Giới hạn hiện tại

- Mới lưu text và ảnh (PNG, bitmap); chưa lưu HTML/RTF/danh sách file.
- Copy chỉ đặt dữ liệu lên clipboard, chưa tự gửi `Ctrl+V`.
- Tìm kiếm chưa bỏ dấu tiếng Việt ("chao" không khớp "chào").
- Phân loại dựa trên quy tắc nên có thể nhầm; dùng Change Type để sửa.
- Chưa đóng gói thành bản cài đặt; chưa có macOS.
