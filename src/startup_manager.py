"""
Startup Manager for Orvo.
Provides cross-platform "Open on Startup / Login" configuration:
- Windows: Registers in HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
  Shows up directly in Windows Task Manager under the "Startup apps" tab.
- macOS: Registers in ~/Library/LaunchAgents/com.orvo.dictation.plist.
- Linux: Registers in ~/.config/autostart/orvo.desktop.
"""

import sys
import os
import logging
from typing import Optional

logger = logging.getLogger("Orvo.StartupManager")

APP_NAME = "Orvo"
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get_windows_launch_command() -> str:
    """Returns the Windows launch command pointing to run_silent.vbs."""
    vbs_path = os.path.join(ROOT_DIR, "run_silent.vbs")
    return f'wscript.exe "{vbs_path}"'


def get_macos_launch_command() -> str:
    """Returns the macOS launch script path."""
    return os.path.join(ROOT_DIR, "run_mac.sh")


def get_linux_launch_command() -> str:
    """Returns the Linux launch script path."""
    return os.path.join(ROOT_DIR, "run_linux.sh")


# =============================================================================
# Windows Registry Startup Implementation
# =============================================================================

def _is_windows_startup_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        )
        try:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(val)
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception as exc:
        logger.debug("Error checking Windows startup registry: %s", exc)
        return False


def _set_windows_startup(enable: bool) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            if enable:
                cmd = get_windows_launch_command()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                logger.info("Enabled Orvo in Windows Startup Apps registry.")
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    logger.info("Disabled Orvo in Windows Startup Apps registry.")
                except FileNotFoundError:
                    pass
            return True
        finally:
            winreg.CloseKey(key)
    except Exception as exc:
        logger.error("Failed to update Windows startup registry: %s", exc)
        return False


# =============================================================================
# macOS LaunchAgent Implementation
# =============================================================================

def _get_macos_plist_path() -> str:
    return os.path.expanduser("~/Library/LaunchAgents/com.orvo.dictation.plist")


def _is_macos_startup_enabled() -> bool:
    return os.path.isfile(_get_macos_plist_path())


def _set_macos_startup(enable: bool) -> bool:
    plist_path = _get_macos_plist_path()
    try:
        if enable:
            os.makedirs(os.path.dirname(plist_path), exist_ok=True)
            script_path = get_macos_launch_command()
            plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.orvo.dictation</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>{script_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
"""
            with open(plist_path, "w", encoding="utf-8") as f:
                f.write(plist_content)
            logger.info("Enabled Orvo LaunchAgent for macOS login.")
            return True
        else:
            if os.path.isfile(plist_path):
                os.remove(plist_path)
            logger.info("Disabled Orvo LaunchAgent for macOS.")
            return True
    except Exception as exc:
        logger.error("Failed to update macOS LaunchAgent: %s", exc)
        return False


# =============================================================================
# Linux Autostart Desktop File Implementation
# =============================================================================

def _get_linux_desktop_path() -> str:
    return os.path.expanduser("~/.config/autostart/orvo.desktop")


def _is_linux_startup_enabled() -> bool:
    return os.path.isfile(_get_linux_desktop_path())


def _set_linux_startup(enable: bool) -> bool:
    desktop_path = _get_linux_desktop_path()
    try:
        if enable:
            os.makedirs(os.path.dirname(desktop_path), exist_ok=True)
            script_path = get_linux_launch_command()
            desktop_content = f"""[Desktop Entry]
Type=Application
Exec=/bin/bash "{script_path}"
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=Orvo
Comment=Universal Voice Dictation
"""
            with open(desktop_path, "w", encoding="utf-8") as f:
                f.write(desktop_content)
            logger.info("Enabled Orvo autostart entry for Linux login.")
            return True
        else:
            if os.path.isfile(desktop_path):
                os.remove(desktop_path)
            logger.info("Disabled Orvo autostart entry for Linux.")
            return True
    except Exception as exc:
        logger.error("Failed to update Linux autostart: %s", exc)
        return False


# =============================================================================
# Public Unified API
# =============================================================================

def is_startup_enabled() -> bool:
    """Checks whether Orvo is configured to run at startup/login on current OS."""
    if sys.platform == "win32":
        return _is_windows_startup_enabled()
    elif sys.platform == "darwin":
        return _is_macos_startup_enabled()
    else:
        return _is_linux_startup_enabled()


def enable_startup() -> bool:
    """Registers Orvo to run automatically on startup/login."""
    if sys.platform == "win32":
        return _set_windows_startup(True)
    elif sys.platform == "darwin":
        return _set_macos_startup(True)
    else:
        return _set_linux_startup(True)


def disable_startup() -> bool:
    """Unregisters Orvo from startup/login."""
    if sys.platform == "win32":
        return _set_windows_startup(False)
    elif sys.platform == "darwin":
        return _set_macos_startup(False)
    else:
        return _set_linux_startup(False)


def toggle_startup() -> bool:
    """Toggles startup registration on/off. Returns new state."""
    current = is_startup_enabled()
    if current:
        disable_startup()
        return False
    else:
        enable_startup()
        return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Orvo Startup Manager")
    parser.add_argument("--enable", action="store_true", help="Enable open on startup")
    parser.add_argument("--disable", action="store_true", help="Disable open on startup")
    parser.add_argument("--status", action="store_true", help="Check open on startup status")
    args = parser.parse_args()

    if args.enable:
        if enable_startup():
            print("Successfully enabled open on startup.")
        else:
            print("Failed to enable open on startup.")
    elif args.disable:
        if disable_startup():
            print("Successfully disabled open on startup.")
        else:
            print("Failed to disable open on startup.")
    else:
        status = is_startup_enabled()
        print(f"Open on startup is currently: {'ENABLED' if status else 'DISABLED'}")
