@echo off
chcp 65001 >nul
cd /d "%~dp0"

set NAPCAT_PATCH_PACKAGE=%cd%\qqnt.json
set NAPCAT_LOAD_PATH=%cd%\loadNapCat.js
set NAPCAT_INJECT_PATH=%cd%\NapCatWinBootHook.dll
set NAPCAT_LAUNCHER_PATH=%cd%\NapCatWinBootMain.exe
set "NAPCAT_MAIN_PATH=%cd%\napcat.mjs"
set "NAPCAT_MAIN_PATH=%NAPCAT_MAIN_PATH:\=/%"

echo (async () =^> {await import("file:///%NAPCAT_MAIN_PATH%")})() > "%NAPCAT_LOAD_PATH%"

"%NAPCAT_LAUNCHER_PATH%" "C:\Program Files\Tencent\QQNT\QQ.exe" "%NAPCAT_INJECT_PATH%"
