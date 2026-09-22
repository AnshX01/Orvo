#!/usr/bin/env bash
# =============================================================================
# Orvo - Linux Setup Script
# =============================================================================

set -e

echo "==================================================="
echo "    Orvo - Linux Voice Dictation Setup"
echo "==================================================="
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Detect Python 3.10 - 3.13
PYTHON_CMD=""
for cmd in python3.11 python3.12 python3.10 python3; do
    if command -v "$cmd" >/dev/null 2>&1; then
        VER=$($cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 10 ] && [ "$MINOR" -le 13 ]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "[ERROR] Compatible Python 3.10 - 3.13 interpreter was not found."
    echo "Install via: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

echo "[INFO] Using Python: $PYTHON_CMD ($($PYTHON_CMD --version))"

# 2. Check for system audio / clipboard dependencies on Linux
echo ""
echo "[INFO] Checking system dependencies..."
MISSING_PKGS=()
if ! command -v xclip >/dev/null 2>&1 && ! command -v wl-copy >/dev/null 2>&1; then
    MISSING_PKGS+=("xclip or wl-clipboard")
fi
if ! command -v xdotool >/dev/null 2>&1 && ! command -v ydotool >/dev/null 2>&1; then
    MISSING_PKGS+=("xdotool or ydotool")
fi

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    echo "[WARNING] Recommended clipboard/injection tools not detected: ${MISSING_PKGS[*]}"
    echo "For Ubuntu/Debian, consider running: sudo apt install xclip xdotool libportaudio2"
    echo "For Fedora, consider running: sudo dnf install xclip xdotool portaudio"
    echo "For Arch Linux, consider running: sudo pacman -S xclip xdotool portaudio"
fi

# 3. Create Virtual Environment
VENV_DIR=".venv"
if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo "[INFO] Creating virtual environment at $VENV_DIR..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    echo "[SUCCESS] Virtual environment created."
fi

# 4. Install Dependencies
echo ""
echo "[INFO] Installing project dependencies..."
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements.txt

# 5. Open on Login Prompt
echo ""
echo "==================================================="
echo "  Open on Login (Linux Autostart)"
echo "==================================================="
echo "Would you like Orvo to start automatically when you log into your desktop?"
read -p "Enable Open on Login? (Y/n): " STARTUP_CHOICE
STARTUP_CHOICE=${STARTUP_CHOICE:-Y}

if [[ "$STARTUP_CHOICE" =~ ^[Nn] ]]; then
    "$VENV_DIR/bin/python" src/startup_manager.py --disable
    echo "[INFO] Autostart disabled. You can toggle it anytime from the tray icon."
else
    "$VENV_DIR/bin/python" src/startup_manager.py --enable
    echo "[SUCCESS] Orvo registered in ~/.config/autostart/orvo.desktop"
fi

# 6. Pre-warm speech model
echo ""
echo "[INFO] Pre-warming speech-to-text model (base.en)..."
"$VENV_DIR/bin/python" -c "from src.transcriber import TranscriberManager; from src.config import get_config; TranscriberManager(get_config())"

# 7. Start in background
echo ""
read -p "Launch Orvo in the background now? (Y/n): " START_NOW
START_NOW=${START_NOW:-Y}
if [[ ! "$START_NOW" =~ ^[Nn] ]]; then
    chmod +x run_linux.sh
    ./run_linux.sh
    echo "[INFO] Orvo is now running in the background. Press Alt + \` to speak!"
fi
