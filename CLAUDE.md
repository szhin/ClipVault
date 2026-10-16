\# ClipVault

Clipboard manager desktop. Windows trước, macOS sau, không mobile.

Stack: Python 3.12 + PySide6 + SQLite.



\## Lệnh

\- Cài môi trường (một lần): `python -m venv .venv` rồi `.venv\Scripts\python -m pip install -e ".[dev]"`

\- Test: `.venv\Scripts\python -m pytest -q`

\- Chạy: `.venv\Scripts\python -m clipvault`



\## Cấu trúc

Xem docs/ARCHITECTURE.md. Tầng: ui / engine / classifier / storage / core / adapters(windows, macos).

core (model, ports, limits, paths) dùng chung cho mọi tầng và không import API hệ điều hành.

Code dùng chung (mọi tầng ngoài adapters) không import API hệ điều hành.



\## Quy tắc bắt buộc

\- Chỉ đọc và sửa file thuộc phase hiện tại (xem PLAN.md). Không refactor, không đổi thư viện hay schema nếu chưa được duyệt.

\- Giữ nguyên dữ liệu clipboard gốc. Phân loại không được sửa nội dung.

\- Không ghi nội dung clipboard vào log hay thông báo lỗi. Không gọi mạng. Không lưu dữ liệu trong thư mục mã nguồn hay thư mục cài đặt.

\- Không xóa hoặc sửa test cũ để làm test pass. Mỗi lỗi được sửa phải kèm test hồi quy.

\- Không nói "đã chạy" hay "hoạt động" nếu chưa chạy. Không thể xác minh macOS trên Windows.



\## Báo cáo cuối phase (tối đa 15 dòng)

File đã đổi, kết quả test (chỉ nêu phần lỗi), giới hạn còn lại. Không dán lại code.



\## Khi compact

Giữ: phase hiện tại, danh sách file đã sửa, lệnh test, quyết định kiến trúc.

