@echo off
chcp 65001 >nul
title 猫娘 Bot 启动器

:: 检查管理员权限，没有则自动提权
net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [启动] 需要管理员权限，正在请求...
    powershell -Command "Start-Process 'cmd.exe' -ArgumentList '/c cd /d \"%~dp0\" && \"%~f0\"' -Verb runAs"
    exit /b
)

:restart
echo ==============================
echo   🐱 猫娘 Bot 启动中...
echo ==============================

:: 1. 通过注册表查找 QQ 安装路径
echo [1/3] 查找 QQ 安装路径...
cd /d "%~dp0NapCat.Shell"

set QQPath=
for /f "tokens=2*" %%a in ('reg query "HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ" /v "UninstallString" 2^>nul') do (
    set "RetString=%%~b"
)
if defined RetString (
    for %%a in ("%RetString%") do set "QQPath=%%~dpaQQ.exe"
)

if not exist "%QQPath%" (
    echo [错误] 找不到 QQ.exe！请确认已安装 QQNT
    echo 尝试路径: %QQPath%
    pause
    exit /b
)
echo [启动] 找到 QQ: %QQPath%

:: 2. 启动 NapCat 注入 QQ
echo [2/3] 启动 QQ + NapCat...
set NAPCAT_PATCH_PACKAGE=%cd%\qqnt.json
set NAPCAT_LOAD_PATH=%cd%\loadNapCat.js
set NAPCAT_INJECT_PATH=%cd%\NapCatWinBootHook.dll
set NAPCAT_LAUNCHER_PATH=%cd%\NapCatWinBootMain.exe
set NAPCAT_MAIN_PATH=%cd%\napcat.mjs
set NAPCAT_MAIN_PATH=%NAPCAT_MAIN_PATH:\=/%
echo (async () =^> {await import("file:///%NAPCAT_MAIN_PATH%")})() > "%NAPCAT_LOAD_PATH%"

start "NapCat" "%NAPCAT_LAUNCHER_PATH%" "%QQPath%" "%NAPCAT_INJECT_PATH%"

:: 等待 QQ 启动
echo [启动] 等待 QQ 加载（15秒）...
timeout /t 15 /nobreak >nul

:: 3. 启动 QQ Bot（带自动重启）
echo [3/3] 启动 QQ Bot...
cd /d "%~dp0"
:bot_loop
echo [Bot] 正在启动猫娘...
env\Scripts\python.exe qq_bot_standalone.py
echo [Bot] 猫娘挂了！5秒后重启...
timeout /t 5 /nobreak >nul
goto bot_loop
