@echo off
chcp 65001 >nul
title 猫娘 Bot 启动器
setlocal enabledelayedexpansion

:restart
cls
echo ============================================
echo        🐱 猫娘 Bot 启动中...
echo ============================================

:: ── 0. 清理残留的旧进程 ──
echo.
echo [0/4] 清理旧的进程...
taskkill /f /im NapCatWinBootMain.exe >nul 2>&1
taskkill /f /im QQ.exe >nul 2>&1
timeout /t 2 /nobreak >nul

:: ── 1. 定位 QQ 安装路径（从注册表） ──
echo.
echo [1/4] 查找 QQ 安装路径...

set QQPath=
set RetString=
cd /d "%~dp0NapCat.Shell"

for /f "tokens=2*" %%a in ('reg query "HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ" /v "UninstallString" 2^>nul') do (
    set "RetString=%%~b"
)
if not defined RetString (
    for /f "tokens=2*" %%a in ('reg query "HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQ" /v "UninstallString" 2^>nul') do (
        set "RetString=%%~b"
    )
)
if defined RetString (
    for %%a in ("%RetString%") do set "QQPath=%%~dpaQQ.exe"
)

if not exist "%QQPath%" (
    echo [错误] 找不到 QQ.exe！
    echo 请确认已安装 QQNT（QQNT 9.9.x），并重新运行本脚本。
    echo 尝试路径: %QQPath%
    pause
    exit /b
)
echo [OK] 找到 QQ: %QQPath%

:: ── 2. 启动 NapCat 注入 QQ ──
echo.
echo [2/4] 启动 NapCat 注入 QQ...
set NAPCAT_PATCH_PACKAGE=%cd%\qqnt.json
set NAPCAT_LOAD_PATH=%cd%\loadNapCat.js
set NAPCAT_INJECT_PATH=%cd%\NapCatWinBootHook.dll
set NAPCAT_LAUNCHER_PATH=%cd%\NapCatWinBootMain.exe
set NAPCAT_MAIN_PATH=%cd%\napcat.mjs
set NAPCAT_MAIN_PATH=%NAPCAT_MAIN_PATH:\=/%
echo (async () =^> {await import("file:///%NAPCAT_MAIN_PATH%")})() > "%NAPCAT_LOAD_PATH%"

:: 清理上一次的二维码缓存，确保能检测到新二维码
if exist "cache\qrcode.png" del "cache\qrcode.png" >nul 2>&1

echo [启动] 正在启动 NapCat，请稍候...
start "NapCat" /D "%~dp0NapCat.Shell" "%NAPCAT_LAUNCHER_PATH%" "%QQPath%" "%NAPCAT_INJECT_PATH%"

:: ── 3. 等二维码出现 → 自动弹窗 + 等 WebSocket 就绪 ──
echo.
echo [3/4] 等待 QQ 加载（将自动弹出二维码供扫码）...

set QR_PATH=%~dp0NapCat.Shell\cache\qrcode.png
set QR_OPENED=
set PORT_READY=
for /l %%i in (1,1,90) do (
    :: 检测二维码文件出现 → 自动打开
    if not defined QR_OPENED (
        if exist "!QR_PATH!" (
            set QR_OPENED=1
            echo [扫码] 二维码已生成，正在自动打开...
            >nul start "" "!QR_PATH!"
        )
    )
    :: 检测 WebSocket 端口就绪（可能绑定 127.0.0.1 或 0.0.0.0）
    >nul 2>&1 netstat -an | findstr ":8080.*LISTENING"
    if !ERRORLEVEL! equ 0 (
        set PORT_READY=1
        echo [OK] WebSocket 端口 8080 已就绪（约 %%i 秒）
        goto :wait_done
    )
    if %%i equ 10 if not defined QR_OPENED echo [等待] 正在等待二维码生成...
    if %%i equ 30 if defined QR_OPENED echo [等待] 二维码已打开，请用手机 QQ 扫码并确认登录...
    if %%i equ 45 echo [等待] 手机 QQ 上可能需要点「确认登录」...
    if %%i equ 70 echo [等待] NapCat 可能遇到了问题...
    timeout /t 1 /nobreak >nul
)

:wait_done
if not defined PORT_READY (
    echo [提示] 未检测到 WebSocket 端口，继续启动 Bot...
    echo 如果 QQ 还没登录，请扫码 qrcode.png 后重试。
)

:: ── 4. 启动 QQ Bot（带自动重启） ──
echo.
echo [4/4] 启动 QQ Bot...
cd /d "%~dp0"

if not exist "env\Scripts\python.exe" (
    echo [错误] 找不到 Python 环境：env\Scripts\python.exe
    echo 请确认虚拟环境存在。
    pause
    exit /b
)

:bot_loop
echo.
echo ========== 猫娘 Bot 运行中（按 Ctrl+C 停止）==========
env\Scripts\python.exe qq_bot_standalone.py
echo ============================================
echo [Bot] 猫娘挂了！5 秒后自动重启...
echo 按 Ctrl+C 可完全退出。
timeout /t 5 /nobreak >nul
goto bot_loop
