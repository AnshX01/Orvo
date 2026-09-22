@echo off
setlocal
title Orvo Windows Startup Configuration

cd /d "%~dp0"

set "VENV_PYTHON=.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo [ERROR] Virtual environment not found. Please run setup.bat first.
    pause
    exit /b 1
)

if "%~1"=="--remove" goto :remove_startup
if "%~1"=="-r" goto :remove_startup
if "%~1"=="remove" goto :remove_startup
if "%~1"=="--status" goto :status_startup

:add_startup
echo ========================================================
echo       Orvo - Add to Windows Task Manager Startup Apps
echo ========================================================
echo.

"%VENV_PYTHON%" src\startup_manager.py --enable
echo.
echo To remove from startup later, run:
echo   add_to_startup.bat --remove
echo.
pause
exit /b 0

:remove_startup
echo ========================================================
echo     Orvo - Remove from Windows Task Manager Startup Apps
echo ========================================================
echo.

"%VENV_PYTHON%" src\startup_manager.py --disable
echo.
pause
exit /b 0

:status_startup
"%VENV_PYTHON%" src\startup_manager.py --status
exit /b 0
