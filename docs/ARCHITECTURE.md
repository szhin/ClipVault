# ClipVault — Kiến trúc (Phase 0)

## 1. Sơ đồ tầng
```
   ui (PySide6): lịch sử, tìm kiếm, ghim, cài đặt, tray
        │ gọi service, nhận signal
   engine: capture pipeline · dedupe · giới hạn/dọn dẹp · paste-back
        │                  │                    │ qua Protocol trong core.ports
   classifier          storage              adapters/windows | adapters/macos
   (thuần, chỉ đọc)    (SQLite + blobs/)    (nơi DUY NHẤT import API OS)
        └────────┬─────────┘                    │
   core: model (dataclass) · ports (Protocol) · limits · paths   ◄──┘
```
- Hướng phụ thuộc: ui → engine → {classifier, storage, core}; adapters → core. Không chiều ngược.
- Chỉ `__main__.py` (composition root) chọn adapter theo `sys.platform` và tiêm vào engine.
- Code ngoài `adapters/` không import `ctypes`, `winreg`, `win32*`, `objc`, `AppKit`, `Foundation`,
  `msvcrt`. Test `tests/test_architecture.py` kiểm tra quy tắc này bằng AST.
- Luồng: OS báo đổi clipboard → adapter đọc nhanh các định dạng trong allowlist thành `Snapshot`
  (trên UI thread, giữ clipboard càng ngắn càng tốt) → engine đẩy sang 1 worker thread ghi duy nhất:
  kiểm tra giới hạn → hash → dedupe → storage → classifier → phát signal cho ui.

## 2. Mô hình dữ liệu (core.model)
- `Representation(native_format: str, mime: str, data: bytes)` — bytes đúng như OS trả về.
- `Snapshot(representations: tuple[Representation, ...], source_app: str | None, captured_at)`.
- `native_format` = tên gốc của OS (`CF_UNICODETEXT`, `HTML Format`, `Rich Text Format`, `PNG`,
  `CF_DIBV5`, `CF_HDROP`; macOS: UTI như `public.utf8-plain-text`). `mime` = nhãn chuẩn hóa để code
  chung xử lý (`text/plain`, `text/html`, `text/rtf`, `image/png`, `image/bmp`, `text/uri-list`).
- Không chuẩn hóa, không cắt NUL, không đổi encoding payload. Mọi thứ hiển thị/tìm kiếm (preview,
  text giải mã, thumbnail) là **dữ liệu dẫn xuất**, lưu cột riêng, không bao giờ ghi ngược lại.
- Paste-back ghi lại đúng từng cặp (native_format, data) theo thứ tự `ord` ban đầu.

## 3. Schema SQLite (`PRAGMA user_version = 1`)
PRAGMA: `journal_mode=WAL`, `foreign_keys=ON`, `synchronous=NORMAL`. Thời gian: Unix ms UTC.
```sql
CREATE TABLE items (
  id            INTEGER PRIMARY KEY,
  item_hash     BLOB    NOT NULL UNIQUE,      -- SHA-256 (32 byte) của cả tập representation
  created_at    INTEGER NOT NULL,
  last_seen_at  INTEGER NOT NULL,             -- cập nhật khi copy lại nội dung trùng
  copy_count    INTEGER NOT NULL DEFAULT 1,
  pinned        INTEGER NOT NULL DEFAULT 0,
  source_app    TEXT,                         -- tên process (vd. "chrome.exe"), có thể NULL
  kind          TEXT    NOT NULL,             -- text | rich | image | files | other
  total_size    INTEGER NOT NULL,             -- tổng byte payload của mục
  preview       TEXT,                         -- dẫn xuất, ≤ 500 ký tự
  search_text   TEXT                          -- dẫn xuất, ≤ 64 KB, cho tìm kiếm
);
CREATE INDEX idx_items_order ON items(pinned DESC, last_seen_at DESC);

CREATE TABLE blobs (
  hash      BLOB    PRIMARY KEY,              -- SHA-256 của data
  size      INTEGER NOT NULL,
  data      BLOB,                             -- NULL nếu external = 1
  external  INTEGER NOT NULL DEFAULT 0,       -- 1: nằm ở blobs/<2 hex đầu>/<hex>
  enc       INTEGER NOT NULL DEFAULT 0        -- dự phòng mã hóa sau v1, luôn 0 ở v1
);

CREATE TABLE representations (
  id             INTEGER PRIMARY KEY,
  item_id        INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  ord            INTEGER NOT NULL,            -- thứ tự OS liệt kê
  native_format  TEXT    NOT NULL,
  mime           TEXT    NOT NULL,
  blob_hash      BLOB    NOT NULL REFERENCES blobs(hash),
  UNIQUE (item_id, native_format)
);
CREATE INDEX idx_repr_blob ON representations(blob_hash);

CREATE TABLE tags (                           -- đầu ra classifier
  item_id  INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  tag      TEXT    NOT NULL,                  -- url, email, color, path, code, ...
  PRIMARY KEY (item_id, tag)
);

CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```
Đổi schema = tăng `user_version` + migration có test; phải được duyệt trước (CLAUDE.md).

## 4. Lưu đa định dạng (hybrid)
- Mỗi representation → 1 blob định danh theo SHA-256 của bytes (content-addressed, tự dedupe
  giữa các mục, vd. cùng một ảnh copy từ hai app).
- `size ≤ 256 KB` → `blobs.data` (inline). Lớn hơn → file `blobs/ab/abcdef…` trong thư mục dữ liệu.
- Ghi file ngoài: ghi `blobs/tmp/<uuid>` → `fsync` → `os.replace` sang tên hash → rồi mới commit DB.
  Khởi động: xóa `blobs/tmp/*` và file không có dòng `blobs` tương ứng (orphan sweep).
- Allowlist v1 Windows: `CF_UNICODETEXT`, `HTML Format`, `Rich Text Format`, `PNG`, `CF_DIBV5`
  (hoặc `CF_DIB` nếu không có V5), `CF_HDROP` (chỉ danh sách đường dẫn, không copy file).
  Bỏ định dạng tự tổng hợp (`CF_TEXT`, `CF_OEMTEXT`, `CF_BITMAP`) và định dạng dạng handle GDI.

## 5. Chống trùng bằng hash
- `blob hash` = SHA-256(data). `item_hash` = SHA-256 của chuỗi chuẩn tắc: các representation sắp
  theo `native_format`, mỗi cái nối `len(name)‖name‖len(data)‖blob_hash` (độ dài 8 byte big-endian).
- Không chuẩn hóa nội dung trước khi hash: cùng text nhưng app khác thêm `HTML Format` là mục khác.
- Trùng `item_hash` → không chèn; `last_seen_at = now`, `copy_count += 1` (mục nổi lên đầu).
- Tự kích hoạt: khi paste-back, adapter ghi nhớ sequence number/changeCount sau khi ghi và engine bỏ
  qua đúng lần thay đổi đó. Dedupe là lớp bảo vệ thứ hai.
- Không ghi hash vào log (hash của chuỗi ngắn như mật khẩu có thể dò ngược).

## 6. Giới hạn dung lượng (mặc định, chỉnh được trong settings)
| Giới hạn | Mặc định | Khi vượt |
|---|---|---|
| Mỗi mục (tổng payload) | 20 MB | Bỏ qua cả mục; log chỉ ghi kích thước + tên định dạng |
| Tổng blob (unique) | 1 GB | Xóa mục chưa ghim cũ nhất theo `last_seen_at` đến khi ≤ 90% |
| Số mục | 5000 | Như trên |
- Adapter kiểm tra kích thước trước khi copy bytes (Windows: `GlobalSize`) để không đọc payload khổng lồ.
- Mục ghim không bị xóa tự động; nếu riêng mục ghim vượt giới hạn → cảnh báo trên UI, vẫn nhận mục mới.
- Sau khi xóa mục: xóa blob không còn representation tham chiếu (DB trước, file sau, trong worker).

## 7. Cấu trúc thư mục
```
ClipVault/
  pyproject.toml  CLAUDE.md  PLAN.md  docs/ARCHITECTURE.md
  src/clipvault/
    __init__.py  __main__.py         # composition root
    core/        model.py ports.py limits.py paths.py
    engine/      capture.py dedupe.py retention.py paste.py
    classifier/  rules.py            # classify(snapshot) -> (kind, tags); không sửa input
    storage/     db.py schema.py blobstore.py
    ui/          app.py widgets/ …
    adapters/windows/  clipboard.py hotkey.py   # ctypes Win32
    adapters/macos/    clipboard.py hotkey.py   # Phase 6
  tests/
```
Thư mục dữ liệu (ngoài mã nguồn và thư mục cài đặt, `core.paths` từ chối nếu trùng):
- Windows: `%LOCALAPPDATA%\ClipVault\` (không roaming: dữ liệu lớn và riêng tư).
- macOS: `~/Library/Application Support/ClipVault/`. Test dùng biến `CLIPVAULT_DATA_DIR` trỏ vào tmp.
- Bên trong: `clipvault.db`, `blobs/`, `logs/` (log không chứa nội dung clipboard, preview hay hash).

## 8. Rủi ro riêng Windows
- `OpenClipboard` thất bại khi app khác đang giữ → retry có backoff, giới hạn thời gian, đóng ngay sau đọc.
- Delayed rendering: đọc một định dạng buộc app nguồn render; app treo có thể làm ta treo → chỉ đọc
  allowlist, kiểm tra `GlobalSize`, đọc trên UI thread nhưng thật ngắn.
- Phải tôn trọng cờ riêng tư của password manager: `ExcludeClipboardContentFromMonitorProcessing`,
  `CanIncludeInClipboardHistory`=0, `Clipboard Viewer Ignore` → không lưu mục đó.
- ctypes 64-bit: khai báo đủ `argtypes/restype`, handle là `c_void_p`, không thì cắt con trỏ → crash.
- `HTML Format` có header offset tính theo byte UTF-8; DIB/DIBV5 có biến thể header — chỉ giải mã
  cho thumbnail, giữ nguyên bytes khi lưu và paste-back.
- UIPI: gửi phím paste (`SendInput`) vào cửa sổ chạy quyền admin bị chặn khi ClipVault chạy thường.
- RDP (`rdpclip`), Win+V cloud clipboard cùng theo dõi clipboard → nhiều sự kiện liên tiếp; cần debounce.
- `RegisterHotKey` có thể trùng phím với app khác → báo lỗi và cho đổi phím.

## 9. Rủi ro riêng macOS (không kiểm chứng được trên Windows — xác minh ở Phase 6)
- Không có sự kiện thay đổi pasteboard: phải poll `NSPasteboard.changeCount` (~300 ms); `QClipboard`
  không báo tin cậy khi app ở nền.
- Bản macOS mới có cảnh báo/quyền riêng tư khi app đọc pasteboard không do người dùng thao tác —
  có thể chặn việc theo dõi nền; cần thử trên máy thật.
- Bỏ qua type `org.nspasteboard.ConcealedType`, `TransientType`, `AutoGeneratedType`.
- Truy cập đủ UTI có thể cần `pyobjc` (dependency mới, phải duyệt ở Phase 6).
- Paste-back qua `CGEventPost` cần quyền Accessibility; hotkey toàn cục cần API Carbon/riêng.
- File promise / lazy data; ký số + notarize + hardened runtime khi đóng gói.
