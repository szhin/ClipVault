# PLAN — phase hiện tại: 0

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
- Giới hạn mặc định: 20 MB/mục (vượt thì bỏ qua), 1 GB tổng, 5000 mục; mục ghim không bị xóa tự động.
- Dữ liệu: `%LOCALAPPDATA%\ClipVault` / `~/Library/Application Support/ClipVault`.
- Bố cục src/; tầng `core` (model, ports, limits, paths) dùng chung cho mọi tầng.

## Tiến độ
- [x] 0 Kiến trúc + khung dự án
- [ ] 1 Clipboard engine (Windows)
- [ ] 2 Classifier
- [ ] 3 UI
- [ ] 4 Rà soát bảo mật
- [ ] 5 Đóng gói Windows
- [ ] 6 macOS

## Nợ kỹ thuật / ghi chú
- Máy dev có Python 3.12.10, CLAUDE.md ghi 3.11 (`requires-python >=3.11`); chưa test trên 3.11.
- PySide6 có trong dependencies nhưng chưa cài vào .venv (cài bằng `pip install -e ".[dev]"` khi cần UI).
- Rủi ro macOS trong ARCHITECTURE.md §9 chưa kiểm chứng.