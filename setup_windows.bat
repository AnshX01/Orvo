@echo off
setlocal enabledelayedexpansion
title Orvo Windows Setup

echo ===================================================
echo     Orvo - Windows Setup
echo ===================================================
echo.

:: Detect suitable Python executable (Python 3.10 - 3.13)
set "PY_CMD="

:: 1. Try py -3.11 (recommended version)
py -3.11 --version >nul 2>&1
if !errorlevel! equ 0 (
    set "PY_CMD=py -3.11"
    goto :found_python
)

:: 2. Try py -3.12
py -3.12 --version >nul 2>&1
if !errorlevel! equ 0 (
    set "PY_CMD=py -3.12"
    goto :found_python
)

:: 3. Try py -3.10
py -3.10 --version >nul 2>&1
if !errorlevel! equ 0 (
    set "PY_CMD=py -3.10"
    goto :found_python
)

:: 4. Check python command
python --version >nul 2>&1
if !errorlevel! equ 0 (
    for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
    for /f "tokens=1,2 delims=." %%a in ("!PY_VER!") do (
        set "MAJOR=%%a"
        set "MINOR=%%b"
    )
    if "!MAJOR!"=="3" (
        if !MINOR! geq 10 (
            if !MINOR! lss 14 (
                set "PY_CMD=python"
                goto :found_python
            )
        )
    )
)

:: 5. Try py default launcher
py --version >nul 2>&1
if !errorlevel! equ 0 (
    for /f "tokens=2 delims= " %%v in ('py --version 2^>^&1') do set "PY_VER=%%v"
    for /f "tokens=1,2 delims=." %%a in ("!PY_VER!") do (
        set "MAJOR=%%a"
        set "MINOR=%%b"
    )
    if "!MAJOR!"=="3" (
        if !MINOR! geq 10 (
            if !MINOR! lss 14 (
                set "PY_CMD=py"
                goto :found_python
            )
        )
    )
)

:no_python
echo [ERROR] Compatible Python version (3.10, 3.11, or 3.12) was not found!
echo Please install Python 3.11 64-bit from https://www.python.org/downloads/
echo Ensure "Add Python to PATH" is checked during installation.
echo.
pause
exit /b 1

:found_python
echo [INFO] Selected Python interpreter: !PY_CMD!
!PY_CMD! --version

set "VENV_DIR=.venv"

if exist "!VENV_DIR!\Scripts\python.exe" (
    echo [INFO] Existing virtual environment found at !VENV_DIR!.
) else (
    echo [INFO] Creating virtual environment at !VENV_DIR!...
    !PY_CMD! -m venv !VENV_DIR!
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [SUCCESS] Virtual environment created.
)

:: Upgrade pip
echo.
echo [INFO] Upgrading pip in virtual environment...
"!VENV_DIR!\Scripts\python.exe" -m pip install --upgrade pip

:: Install requirements
echo.
echo [INFO] Installing project dependencies from requirements.txt...
"!VENV_DIR!\Scripts\python.exe" -m pip install -r requirements.txt
if !errorlevel! neq 0 (
    echo [ERROR] Failed to install requirements.
    pause
    exit /b 1
)

:: Startup configuration
echo.
echo ===================================================
echo  Open on Startup / Windows Task Manager
echo ===================================================
echo  Would you like Orvo to start automatically when you log in?
echo  (This registers Orvo in Windows Task Manager Startup Apps)
set "STARTUP_CHOICE=Y"
set /p STARTUP_CHOICE="Enable Open on Startup? (Y/N, default Y): "

if /i "!STARTUP_CHOICE!"=="N" (
    "!VENV_DIR!\Scripts\python.exe" src\startup_manager.py --disable
    echo [INFO] Startup registration disabled. You can toggle this anytime in the tray icon.
) else (
    "!VENV_DIR!\Scripts\python.exe" src\startup_manager.py --enable
    echo [SUCCESS] Orvo is now registered in Windows Task Manager Startup Apps!
)

:: Model pre-warm
echo.
echo [INFO] Pre-warming local speech-to-text model (base.en)...
"!VENV_DIR!\Scripts\python.exe" -c "from src.transcriber import TranscriberManager; from src.config import get_config; TranscriberManager(get_config())"

echo.
echo ===================================================
echo [SUCCESS] Orvo installation is complete!
echo.
echo Hotkey: Alt + ` (press to start dictation, press again to stop)
echo System Tray: Right-click the Orvo icon for quick settings.
echo ===================================================
echo.

set "START_NOW=Y"
set /p START_NOW="Launch Orvo in the background now? (Y/N, default Y): "
if /i not "!START_NOW!"=="N" (
    start "" wscript.exe run_silent.vbs
    echo [INFO] Orvo is running in the background. Enjoy dictating!
)

echo.
pause
