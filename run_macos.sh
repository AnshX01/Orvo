#!/usr/bin/env bash
# =============================================================================
# Orvo - macOS Background Launcher
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p logs

if [ -f ".venv/bin/python" ]; then
    PY_BIN=".venv/bin/python"
elif [ -f ".venv/bin/python3" ]; then
    PY_BIN=".venv/bin/python3"
else
    echo "Virtual environment not found! Run ./setup_macos.sh first."
    exit 1
fi

nohup "$PY_BIN" main.py > logs/orvo.log 2>&1 &
echo "[Orvo] Process started in background (PID: $!). Log: logs/orvo.log"
