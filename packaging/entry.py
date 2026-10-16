"""Điểm vào cho bản đóng gói (PyInstaller): gọi đúng composition root của app."""

import sys

from clipvault.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
