@echo off
setlocal
rem ============================================
rem  Launch xiaoe_rvc_ui (with console window)
rem  First run auto-installs dependencies.
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

rem Check deps; install automatically on first run.
"%PYEXE%" -c "import xiaoe_ui, PySide6, win32com, pyrnnoise, pedalboard" >nul 2>&1
if errorlevel 1 (
    echo Dependencies not found. Installing first run...
    "%PYEXE%" -m pip install --disable-pip-version-check -r "requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Dependency install failed. Check your network.
        pause
        exit /b 1
    )
    "%PYEXE%" -m pip install --disable-pip-version-check "xiaoe_ui-1.4.4-py3-none-any.whl"
    if errorlevel 1 (
        echo [ERROR] xiaoe_ui install failed. Check your network.
        pause
        exit /b 1
    )
)

cd /d "%RVC_ROOT%"
set "PATH=%RVC_ROOT%\runtime;%PATH%"
"%PYEXE%" -I "%SCRIPT_DIR%\main.py"
pause
