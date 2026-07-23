@echo off
chcp 65001 >nul
title 猫娘 Bot 桌面版
cd /d "%~dp0"
echo ============================================
echo    🐱 正在启动猫娘 Bot 桌面版...
echo ============================================
echo.
if not exist "env\Scripts\python.exe" (
    echo [错误] 找不到 Python 环境！
    pause
    exit /b
)
start "" "env\Scripts\pythonw.exe" bot_app.py
echo ✅ 猫娘 Bot 已启动，可在系统托盘找到图标
timeout /t 3 /nobreak >nul
