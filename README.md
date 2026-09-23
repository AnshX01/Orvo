# Orvo

Orvo is a lightweight, low-latency, system-wide voice dictation application for Windows, macOS, and Linux. It allows you to trigger voice-to-text dictation globally across any active desktop application (editors, browsers, messaging apps, and terminals) using a global hotkey, with zero clipboard pollution and a minimal, hardware-composited status overlay.

---

## Core Capabilities

- **Local Speech Recognition**: Transcribes spoken audio locally using faster-whisper (CTranslate2) with int8 quantization or CUDA acceleration, with optional fallback to cloud Whisper APIs (Groq and OpenAI).
- **Linguistic Structuring**: Normalizes spoken sentence fragments, filters verbal hesitation fillers (such as "um" and "uh"), removes repetition stutters, formats questions, and capitalizes technical proper nouns.
- **Minimal Status Overlay**: Floating dark graphite status squircle with subtle grey interior accent, smoothly pulsing borders, wave microphone lines during listening, a 3-dot cascading bounce during processing, and an inward merge into a single dot on completion. Runs at the display's native refresh rate using 32-bit per-pixel alpha blending without stealing window focus.
- **Atomic Clipboard Injection**: Preserves existing clipboard contents (text, Unicode, and bitmap images). Pastes transcribed text into the focused window and restores the original clipboard within milliseconds, with simulated typing fallback.
- **Open on Startup**: Integrated into Windows Task Manager Startup Apps (HKCU Run key), macOS LaunchAgents, and Linux autostart. Configurable during setup and toggleable in real time via the system tray menu.
- **Single-Instance Protection & Auto-Wake**: Opening Orvo while it is already running safely detects the existing background process, signals the active instance to pulse on-screen and notify the system tray, and prevents duplicate instances or audio conflicts.
- **Silent Operation**: Audio chimes are disabled by default for silent, frictionless operation.

---

## Installation & Setup

### Requirements
- Python 3.10, 3.11, or 3.12 (Python 3.11 recommended; Python 3.14 is currently unsupported by ctranslate2 wheels).
- Microphone input device.

### Windows
Run the single automated setup script:
```cmd
setup_windows.bat
```
The script will:
1. Detect or configure a virtual environment (`.venv`).
2. Install dependencies from `requirements.txt`.
3. Register application search and Start Menu shortcuts.
4. Prompt whether to register Orvo in Windows Task Manager Startup Apps.
5. Pre-warm the local speech recognition model (`base.en`).
6. Prompt to launch Orvo immediately in the background.

To run manually after setup:
- Background mode (recommended): launch `Orvo.exe`, double-click `run_windows.bat`, or click the `Orvo` Desktop / Start Menu shortcut.
- Terminal / debug mode: run `run_windows.bat --console` or `python main.py`.

### macOS
Run the single automated setup script:
```bash
chmod +x setup_mac.sh
./setup_mac.sh
```
The script configures the virtual environment, installs dependencies, registers the application for Spotlight search, pre-warms the model, and prompts to configure Open on Login via LaunchAgents.

*Note on macOS Permissions:*
Grant Accessibility permissions to your Terminal/Python application under `System Settings -> Privacy & Security -> Accessibility` to allow global hotkey detection and text insertion.

To run manually in the background:
```bash
./run_mac.sh
```

### Linux
Install system audio and clipboard dependencies (Ubuntu/Debian example):
```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip libportaudio2 xclip xdotool
```
Run the single automated setup script:
```bash
chmod +x setup_linux.sh
./setup_linux.sh
```
The script configures the virtual environment, installs dependencies, registers the desktop entry for application search, pre-warms the model, and prompts to configure desktop autostart.

To run manually in the background:
```bash
./run_linux.sh
```

---

## Operation & Hotkeys

- **Default Hotkey**: `Alt + ` ` (Backtick / Grave, `<alt>+<grave>`).
- **Toggle Mode (Default)**:
  - Press `Alt + ` ` once to start listening. The minimal HUD appears with wave microphone lines.
  - Press `Alt + ` ` again to finish. The HUD transitions through 3 processing dots, merges into a single completion dot, and injects the formatted text at the cursor.
- **Push-to-Talk Mode**:
  - Hold `Alt + ` ` while speaking, release to transcribe and paste.
  - Mode can be switched via the system tray menu or in `config.json`.

---

## System Search & Desktop Integration

- **Windows**: Search `Orvo` in the Start Menu to launch silently in the background. Shortcut is located at `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Orvo.lnk`.
- **macOS**: Search `Orvo` in Spotlight (`Cmd + Space`) from `~/Applications/Orvo.app`.
- **Linux**: Search `Orvo` in application menus from `~/.local/share/applications/orvo.desktop`.
- **Single Instance**: Running Orvo when it is already active safely detects the existing background process and exits cleanly.

---

## Startup Configuration

- **Windows**: Registered in `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, visible in Windows Task Manager Startup Apps.
- **macOS**: Registered in `~/Library/LaunchAgents/com.orvo.dictation.plist`.
- **Linux**: Registered in `~/.config/autostart/orvo.desktop`.
- **System Tray Toggle**: Right-click the Orvo tray icon and toggle `Start with Windows` / `Start on Login` anytime.

---

## License

MIT License. See `LICENSE` for details.
