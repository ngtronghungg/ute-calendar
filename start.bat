@echo off
title UTE-Calendar - Local Host
chcp 65001 >nul
echo.
echo ========================================================
echo   UTE-CALENDAR - LỊCH HỌC & LỊCH THI TỰ CẬP NHẬT
echo   Bảo mật 100% • Chạy trực tiếp trên máy tính của bạn
echo ========================================================
echo.

if not exist ".venv" (
    echo [1/3] Đang khởi tạo môi trường Python ảo (.venv)...
    python -m venv .venv
)

echo [2/3] Kích hoạt môi trường và kiểm tra thư viện...
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q

echo.
echo [3/3] Đang khởi chạy máy chủ cục bộ...
python run.py
pause
