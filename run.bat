@echo off
setlocal
title Orvo Console

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found!
    echo Please run setup.bat first to set up the environment and install dependencies.
    echo.
    pause
    exit /b 1
)

echo ===================================================
echo     Starting Orvo (Console Mode)
echo ===================================================
echo Hotkey: Alt + ` (Backtick) - Press to dictate anywhere!
echo Press Ctrl+C or right-click Tray icon to exit.
echo.

".venv\Scripts\python.exe" main.py

if %errorlevel% neq 0 (
    echo.
    echo [NOTICE] Application terminated with exit code %errorlevel%.
    pause
)
