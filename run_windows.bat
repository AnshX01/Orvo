@echo off
setlocal
title Orvo Launcher

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found!
    echo Please run setup_windows.bat first to configure Orvo.
    pause
    exit /b 1
)

:: If --console or -c is provided, launch with interactive terminal output
if "%~1"=="--console" goto :console
if "%~1"=="-c" goto :console
if "%~1"=="console" goto :console

:: Default: Launch silently in the background with tray icon and status HUD
start "" wscript.exe run_silent.vbs
exit /b 0

:console
echo ===================================================
echo     Starting Orvo (Console Mode)
echo ===================================================
echo Hotkey: Alt + ` (Backtick) - Press to dictate anywhere!
echo Press Ctrl+C or right-click Tray icon to exit.
echo.
".venv\Scripts\python.exe" main.py
