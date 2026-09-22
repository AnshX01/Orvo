#!/usr/bin/env bash
# =============================================================================
# Orvo - macOS Setup Script
# =============================================================================

set -e

echo "==================================================="
echo "    Orvo - macOS Voice Dictation Setup"
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
    echo "[ERROR] Compatible Python version (3.10 - 3.13) was not found."
    echo "Please install Python 3.11 via Homebrew: brew install python@3.11"
    exit 1
fi

echo "[INFO] Using Python interpreter: $PYTHON_CMD ($($PYTHON_CMD --version))"

# 2. Create Virtual Environment
VENV_DIR=".venv"
if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo "[INFO] Creating virtual environment at $VENV_DIR..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    echo "[SUCCESS] Virtual environment created."
fi

# 3. Upgrade Pip & Install Dependencies
echo ""
echo "[INFO] Installing project dependencies..."
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements.txt

# 4. Install Spotlight & Applications Shortcut
echo ""
echo "[INFO] Registering Orvo in macOS Applications for Spotlight..."
"$VENV_DIR/bin/python" src/startup_manager.py --install-shortcuts

# 5. Open on Login Prompt (macOS LaunchAgent)
echo ""
echo "==================================================="
echo "  Open on Login (macOS LaunchAgent)"
echo "==================================================="
echo "Would you like Orvo to start automatically when you log into your Mac?"
read -p "Enable Open on Login? (Y/n): " STARTUP_CHOICE
STARTUP_CHOICE=${STARTUP_CHOICE:-Y}

if [[ "$STARTUP_CHOICE" =~ ^[Nn] ]]; then
    "$VENV_DIR/bin/python" src/startup_manager.py --disable
    echo "[INFO] Open on Login skipped. You can toggle it anytime from the menu bar icon."
else
    "$VENV_DIR/bin/python" src/startup_manager.py --enable
    echo "[SUCCESS] Orvo is registered in macOS LaunchAgents."
fi

# 5. Pre-warm speech model
echo ""
echo "[INFO] Pre-warming speech-to-text model (base.en)..."
"$VENV_DIR/bin/python" -c "from src.transcriber import TranscriberManager; from src.config import get_config; TranscriberManager(get_config())"

# 6. Reminder for macOS Accessibility
echo ""
echo "==================================================="
echo "[IMPORTANT] macOS Accessibility Permissions Required"
echo "To allow global hotkey detection and text insertion:"
echo "1. Open System Settings -> Privacy & Security -> Accessibility"
echo "2. Add and toggle ON your Terminal / Python application."
echo "==================================================="
echo ""

# 7. Start in background
read -p "Launch Orvo in the background now? (Y/n): " START_NOW
START_NOW=${START_NOW:-Y}
if [[ ! "$START_NOW" =~ ^[Nn] ]]; then
    chmod +x run_mac.sh
    ./run_mac.sh
    echo "[INFO] Orvo is now running in the background. Press Alt + \` to speak!"
fi
