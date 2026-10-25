"""
UTE-Calendar - Local Runner
Chạy ứng dụng cục bộ (Localhost) an toàn, riêng tư.
"""

import sys
import os
import secrets

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Auto-generate ephemeral session secret for local development if not configured
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = f"local_dev_secret_{secrets.token_hex(16)}"

from src.web_server import run_app

if __name__ == "__main__":
    from src.branding import APP_NAME
    print("\n" + "=" * 60)
    print(f"{APP_NAME} — Lịch học & Lịch thi tự cập nhật")
    print("Trang chủ: http://localhost:5000")
    print("=" * 60 + "\n")
    run_app(port=5000, open_browser=True)
