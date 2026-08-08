@echo off
setlocal
rem ============================================
rem  xiaoe_rvc_ui dependency installer
rem  Put this folder inside the RVC root directory.
rem  Installs deps into RVC's bundled runtime\python.exe
rem ============================================
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "RVC_ROOT=%SCRIPT_DIR%\.."
set "PYEXE=%RVC_ROOT%\runtime\python.exe"

if not exist "%PYEXE%" (
    echo [ERROR] RVC python not found: %PYEXE%
    echo Please put this folder under the RVC root directory.
    pause
    exit /b 1
)

cd /d "%SCRIPT_DIR%"

echo ============================================
echo   Installing xiaoe_ui into RVC bundled python
echo   Python: %PYEXE%
echo ============================================
echo.
echo Installing base requirements (PySide6, pywin32)...
"%PYEXE%" -m pip install --disable-pip-version-check -r "requirements.txt"
if errorlevel 1 (
    echo [ERROR] Install failed. Check your network and retry.
    pause
    exit /b 1
)

echo Installing xiaoe_ui (auto pulls its deps)...
"%PYEXE%" -m pip install --disable-pip-version-check "xiaoe_ui-1.4.4-py3-none-any.whl"
if errorlevel 1 (
    echo [ERROR] Install failed. Check your network and retry.
    pause
    exit /b 1
)
echo.
echo Done! Double-click run.vbs to launch the new RVC UI.
pause
