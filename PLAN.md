# PLAN — phase hiện tại: 3

## Lệnh
- Test: `.venv\Scripts\python -m pytest -q`
- Chạy: `.venv\Scripts\python -m clipvault`

## Quyết định đã chốt
Chi tiết: docs/ARCHITECTURE.md.
- Payload hybrid: ≤256 KB BLOB trong SQLite, lớn hơn là file content-addressed `blobs/ab/<sha256>`.
- Lưu bytes gốc + `native_format` + `mime`; preview/search_text/thumbnail là dữ liệu dẫn xuất.
- Chống trùng: SHA-256 cho từng blob + `item_hash` cho cả mục; trùng thì cập nhật `last_seen_at`.
- Không mã hóa ở v1 (cột `blobs.enc` để dành).
- Adapter Windows: ctypes Win32, không dùng pywin32.
- Theo dõi (Windows): `QClipboard.dataChanged` báo thay đổi, adapter ctypes đọc bytes gốc (không đọc qua QMimeData).
- Giới hạn mặc định: 20 MB/mục (vượt thì bỏ qua), 1 GB tổng, 5000 mục; mục ghim không bị xóa tự động.
- Dữ liệu: `%LOCALAPPDATA%\ClipVault` / `~/Library/Application Support/ClipVault`.
- Bố cục src/; tầng `core` (model, ports, limits, paths) dùng chung cho mọi tầng.
- Phân loại không đổi schema: lưu trong bảng `tags` (`cat:<image|text|link|code|other>`, `lang:<tên>`, `url|email|color|path|code`,
  `manual` = người dùng đã Change Type nên `cat:*` không bị phân loại lại đè). Sidebar: All, Images, Text, Links, Code, Other, Pinned.
  email/color/path thuộc Other. Mục lưu từ Phase 1 được phân loại lại một lần (`settings.classifier.version`).
- Copy = ghi lại từng (native_format, bytes) theo thứ tự đã lưu qua `ClipboardWriter`; engine bỏ qua đúng lần đổi do mình (sequence number).
- UI chỉ gọi `engine.history.HistoryService`; lỗi trả về `HistoryError` (thông báo không chứa nội dung clipboard).
- Phím tắt mở cửa sổ: mặc định `Ctrl+Shift+V` (đọc `settings.ui.hotkey`); trùng phím thì báo qua tray, vẫn mở được từ tray.
- Một bản chạy duy nhất (`QLockFile` trong thư mục dữ liệu); đóng cửa sổ = chạy nền ở tray; `--background` khởi động không hiện cửa sổ.
- Phase 3c: cài đặt lưu trong bảng `settings` (`engine/settings.py`; khóa `ui.theme|font_size|density`, `limits.max_items|max_total_bytes`,
  `retention.days`, `behavior.close_to_tray|confirm_delete`, `privacy.paused`). Theme: gradient chỉ ở `theme.GradientBackground` (widget gốc),
  mọi bề mặt khác phẳng/trong suốt. Engine chỉ thêm: `CaptureController.set_paused`, xóa theo phạm vi/tuổi (`Database.delete_scope|delete_older_than`).

## Tiến độ
- [x] 0 Kiến trúc + khung dự án
- [x] 1 Clipboard engine (Windows)
- [x] 2 Classifier
- [x] 3 UI
- [ ] 4 Rà soát bảo mật
- [ ] 5 Đóng gói Windows
- [ ] 6 macOS

## Nợ kỹ thuật / ghi chú
- Máy dev có Python 3.12.10 (CLAUDE.md ghi 3.12); `requires-python >=3.11` giữ nguyên, chưa test trên 3.11.
- PySide6 6.12.0 đã cài trong .venv (cùng pytest 9.1.1).
- Rủi ro macOS trong ARCHITECTURE.md §9 chưa kiểm chứng.
- Chỉ đọc `CF_UNICODETEXT`, `PNG`, `CF_DIBV5`/`CF_DIB`. Chưa làm: `HTML Format`, `Rich Text Format`, `CF_HDROP`,
  `source_app` (luôn NULL), tự gửi Ctrl+V sau khi Copy (`SendInput`/UIPI), UI đổi phím tắt (hiện sửa `settings.ui.hotkey`),
  cảnh báo UI khi mục ghim vượt giới hạn (engine đã trả cờ `pinned_over_limit`).
- Classifier là heuristic (regex): có thể nhầm; Change Type là cách sửa. Chưa có HTML/RTF/files nên kind `rich`/`files` chưa xuất hiện.
- Search dùng `casefold(...) LIKE` trên `search_text` (≤64 KB đầu): chưa bỏ dấu tiếng Việt (gõ "chao" không khớp "chào"); chưa có FTS.
- Chưa kiểm chứng bằng tay: system tray thật, phím tắt toàn cục bấm thật, thumbnail trên màn hình HiDPI (xem danh sách thao tác thử tay).
- Text lưu đúng `GlobalSize` byte (kể cả NUL cuối / đệm của app nguồn) nên cùng văn bản từ hai app có thể thành hai mục.
- `CaptureController.on_result` chạy trên worker thread; `ui.app.CaptureBridge` chuyển sang UI thread bằng Qt signal.
- Test clipboard thật là opt-in: `CLIPVAULT_LIVE_CLIPBOARD=1` (ghi đè clipboard của máy). Test UI chạy với `QT_QPA_PLATFORM=offscreen` (conftest).