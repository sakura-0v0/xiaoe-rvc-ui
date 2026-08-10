@echo off
rem ============================================
rem  xiaoe_rvc_ui deploy installer
rem  Copies this xiaoe_rvc_ui package into an RVC root.
rem  Core logic lives in install.ps1 (UTF-8 BOM, Chinese dialogs).
rem ============================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
set "code=%ERRORLEVEL%"
pause
exit /b %code%
