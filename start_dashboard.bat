@echo off
chcp 65001 >nul
title 猫娘 Bot 管理面板
cd /d "%~dp0"
echo ============================================
echo    🐱 正在启动猫娘 Bot 管理面板...
echo ============================================
echo.
if not exist "env\Scripts\python.exe" (
    echo [错误] 找不到 Python 环境！
    pause
    exit /b
)
env\Scripts\python.exe bot_dashboard.py
pause
