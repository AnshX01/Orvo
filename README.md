# Orvo

Orvo is a lightweight, low-latency, system-wide voice dictation application for Windows, macOS, and Linux. It allows you to trigger voice-to-text dictation globally across any active desktop application (editors, browsers, messaging apps, and terminals) using a global hotkey, with zero clipboard pollution and a minimal, hardware-composited status overlay.

---

## Core Capabilities

- **Local Speech Recognition**: Transcribes spoken audio locally using faster-whisper (CTranslate2) with int8 quantization or CUDA acceleration, with optional fallback to cloud Whisper APIs (Groq and OpenAI).
- **Linguistic Structuring**: Normalizes spoken sentence fragments, filters verbal hesitation fillers (such as "um" and "uh"), removes repetition stutters, formats questions, and capitalizes technical proper nouns.
- **Minimal Status Overlay**: Floating dark graphite status squircle with subtle grey interior accent, smoothly pulsing borders, wave microphone lines during listening, a 3-dot cascading bounce during processing, and an inward merge into a single dot on completion. Runs at the display's native refresh rate using 32-bit per-pixel alpha blending without stealing window focus.
- **Atomic Clipboard Injection**: Preserves existing clipboard contents (text, Unicode, and bitmap images). Pastes transcribed text into the focused window and restores the original clipboard within milliseconds, with simulated typing fallback.
- **Open on Startup**: Integrated into Windows Task Manager Startup Apps (HKCU Run key), macOS LaunchAgents, and Linux autostart. Configurable during setup and toggleable in real time via the system tray menu.
- **Single-Instance Protection**: Opening Orvo while it is already running safely detects the existing background process and exits without opening duplicate instances or conflicting with audio hardware.
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
3. Prompt whether to register Orvo in Windows Task Manager Startup Apps.
4. Pre-warm the local speech recognition model (`base.en`).
5. Prompt to launch Orvo immediately in the background.

To run manually after setup:
- Background mode (recommended): double-click `run_windows.bat`, `run_silent.vbs`, or execute `pythonw main.py`.
- Terminal / debug mode: run `run_windows.bat --console` or `python main.py`.

### macOS
Run the single automated setup script:
```bash
chmod +x setup_mac.sh
./setup_mac.sh
```
The script configures the virtual environment, installs dependencies, pre-warms the model, and prompts to configure Open on Login via LaunchAgents.

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
The script configures the virtual environment, installs dependencies, pre-warms the model, and prompts to configure desktop autostart.

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

## Startup Configuration

Orvo provides native operating system startup integration:
- **Windows**: Registered in `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. Shows up directly in Windows Task Manager under the **Startup apps** tab as `Orvo`.
- **macOS**: Configured via LaunchAgent plist at `~/Library/LaunchAgents/com.orvo.dictation.plist`.
- **Linux**: Configured via autostart desktop entry at `~/.config/autostart/orvo.desktop`.
- **Quick Settings Toggle**: Right-click the Orvo system tray icon and click `Start with Windows` (or `Start on Login`) to toggle startup registration on or off at any time.

---

## Configuration Reference (`config.json`)

Settings are stored in `config.json` in the root directory:

```json
{
    "hotkey": {
        "key": "<alt>+<grave>",
        "mode": "toggle",
        "debounce_ms": 150
    },
    "audio": {
        "device_index": null,
        "sample_rate": 16000,
        "channels": 1,
        "sound_effects": false,
        "silence_trim": true,
        "silence_threshold_db": -48.0,
        "pad_duration_ms": 350,
        "normalize_audio": true
    },
    "model": {
        "backend": "local",
        "local_model": "base.en",
        "compute_type": "int8",
        "device": "auto",
        "beam_size": 5,
        "initial_prompt": "Orvo dictation: accurate transcription of spoken English into clear, coherent, well-structured sentences with proper grammar and punctuation.",
        "vad_filter": false,
        "groq_api_key": "",
        "groq_model": "whisper-large-v3-turbo",
        "openai_api_key": "",
        "openai_model": "whisper-1",
        "language": "en"
    },
    "text": {
        "auto_capitalize": true,
        "auto_punctuate": true,
        "smart_sentence_formation": true,
        "remove_fillers": true,
        "fix_disfluencies": true,
        "voice_commands": true,
        "paste_delay_ms": 60,
        "fallback_to_typing": true
    },
    "ui": {
        "show_hud": true,
        "hud_style": "square",
        "hud_position": "bottom_right",
        "sound_feedback": false,
        "tray_notifications": false,
        "history_limit": 100,
        "start_minimized_to_tray": true
    }
}
```

---

## System Architecture

```
                       Global Hotkey (pynput)
                        Default: Alt + `
                              │
                              ▼
┌──────────────────┐    ┌───────────┐    ┌─────────────────────┐
│  System Tray App │◄───┤  OrvoApp  ├───►│ Minimal Status HUD  │
│ (pystray+Pillow) │    │  Engine   │    │ 32-bit Alpha Window │
└──────────────────┘    └─────┬─────┘    └─────────────────────┘
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
        AudioRecorder               TranscriberManager
         16kHz Mono                  faster-whisper int8
        -48dB Threshold             SentenceFormer Engine
               │                             │
               └──────────────┬──────────────┘
                              ▼
                      SafeTextInjector
                   Atomic Clipboard Backup
                    Paste Key Simulation
                  Instant Clipboard Restore
```

---

## License

MIT License. See `LICENSE` for details.
