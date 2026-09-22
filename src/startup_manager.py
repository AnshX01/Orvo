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
# Application Icons & OS Search Shortcuts
# =============================================================================

def ensure_app_icon() -> bool:
    """
    Ensures assets/icon.ico and assets/icon.png exist.
    Generates them dynamically with Pillow if missing.
    """
    assets_dir = os.path.join(ROOT_DIR, "assets")
    ico_path = os.path.join(assets_dir, "icon.ico")
    png_path = os.path.join(assets_dir, "icon.png")

    if os.path.isfile(ico_path) and os.path.isfile(png_path):
        return True

    try:
        from PIL import Image, ImageDraw
        os.makedirs(assets_dir, exist_ok=True)
        size = 256
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        # Squircle badge
        pad = 12
        radius = 54
        d.rounded_rectangle(
            [pad, pad, size - pad, size - pad],
            radius=radius,
            fill=(28, 30, 38, 255),
            outline=(100, 116, 139, 255),
            width=6,
        )

        # Microphone capsule
        cw, ch = 46, 76
        cx = size // 2
        cy_top = 62
        d.rounded_rectangle(
            [cx - cw // 2, cy_top, cx + cw // 2, cy_top + ch],
            radius=23,
            fill=(248, 250, 252, 255),
        )

        # Microphone cradle arc
        arc_pad = 16
        d.arc(
            [cx - cw // 2 - arc_pad, cy_top + 28, cx + cw // 2 + arc_pad, cy_top + ch + 18],
            start=0,
            end=180,
            fill=(248, 250, 252, 255),
            width=10,
        )

        # Stand & Base
        d.line([cx, cy_top + ch + 18, cx, cy_top + ch + 48], fill=(248, 250, 252, 255), width=10)
        d.line([cx - 36, cy_top + ch + 48, cx + 36, cy_top + ch + 48], fill=(248, 250, 252, 255), width=10)

        img.save(png_path, format="PNG")
        img.save(ico_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        logger.info("Generated high-resolution Orvo application icons in assets/")
        return True
    except Exception as exc:
        logger.warning("Could not generate app icon: %s", exc)
        return False


def _create_windows_lnk(lnk_path: str, target: str, args: str, workdir: str, icon: str, desc: str) -> bool:
    """Helper to create Windows .lnk shortcut with multiple robust fallbacks."""
    # 1. win32com
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(lnk_path)
        shortcut.TargetPath = target
        shortcut.Arguments = args
        shortcut.WorkingDirectory = workdir
        if os.path.isfile(icon):
            shortcut.IconLocation = f"{icon},0"
        shortcut.Description = desc
        shortcut.Save()
        if os.path.isfile(lnk_path):
            return True
    except Exception as e:
        logger.debug("win32com shortcut creation failed: %s", e)

    # 2. PowerShell
    try:
        import subprocess
        ps_cmd = (
            f'$ws = New-Object -ComObject WScript.Shell; '
            f'$s = $ws.CreateShortcut("{lnk_path}"); '
            f'$s.TargetPath = "{target}"; '
            f'$s.Arguments = \'{args}\'; '
            f'$s.WorkingDirectory = "{workdir}"; '
            f'$s.IconLocation = "{icon},0"; '
            f'$s.Description = "{desc}"; '
            f'$s.Save()'
        )
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
        )
        if os.path.isfile(lnk_path):
            return True
    except Exception as e:
        logger.debug("PowerShell shortcut creation failed: %s", e)

    # 3. VBScript via cscript
    try:
        import subprocess
        vbs_content = (
            'Set ws = CreateObject("WScript.Shell")\n'
            f'Set lnk = ws.CreateShortcut("{lnk_path}")\n'
            f'lnk.TargetPath = "{target}"\n'
            f'lnk.Arguments = "{args}"\n'
            f'lnk.WorkingDirectory = "{workdir}"\n'
            f'lnk.IconLocation = "{icon},0"\n'
            f'lnk.Description = "{desc}"\n'
            'lnk.Save\n'
        )
        tmp_vbs = os.path.join(ROOT_DIR, "_tmp_lnk.vbs")
        with open(tmp_vbs, "w", encoding="utf-8") as f:
            f.write(vbs_content)
        subprocess.run(["cscript.exe", "//Nologo", tmp_vbs], check=True, capture_output=True)
        if os.path.isfile(tmp_vbs):
            os.remove(tmp_vbs)
        return os.path.isfile(lnk_path)
    except Exception as e:
        logger.error("All Windows shortcut creation attempts failed for %s: %s", lnk_path, e)
        return False


def _install_windows_shortcuts() -> bool:
    appdata = os.environ.get("APPDATA", "")
    userprofile = os.environ.get("USERPROFILE", "")
    icon_path = os.path.join(ROOT_DIR, "assets", "icon.ico")
    vbs_path = os.path.join(ROOT_DIR, "run_silent.vbs")

    target = "wscript.exe"
    args = f'"{vbs_path}"'
    workdir = ROOT_DIR
    desc = "Orvo - Voice Dictation Everywhere"

    installed_any = False

    # 1. Start Menu (Indexed by Windows Search)
    start_menu_dir = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs")
    if os.path.isdir(start_menu_dir):
        start_menu_lnk = os.path.join(start_menu_dir, "Orvo.lnk")
        if _create_windows_lnk(start_menu_lnk, target, args, workdir, icon_path, desc):
            logger.info("Installed Start Menu shortcut for Windows Search: %s", start_menu_lnk)
            installed_any = True

    # 2. Desktop Shortcut
    desktop_dir = os.path.join(userprofile, "Desktop")
    if os.path.isdir(desktop_dir):
        desktop_lnk = os.path.join(desktop_dir, "Orvo.lnk")
        if _create_windows_lnk(desktop_lnk, target, args, workdir, icon_path, desc):
            logger.info("Installed Desktop shortcut: %s", desktop_lnk)
            installed_any = True

    return installed_any


def _install_macos_app_bundle() -> bool:
    apps_dir = os.path.expanduser("~/Applications")
    os.makedirs(apps_dir, exist_ok=True)
    app_path = os.path.join(apps_dir, "Orvo.app")
    macos_dir = os.path.join(app_path, "Contents", "MacOS")
    resources_dir = os.path.join(app_path, "Contents", "Resources")
    os.makedirs(macos_dir, exist_ok=True)
    os.makedirs(resources_dir, exist_ok=True)

    launcher_script = os.path.join(macos_dir, "Orvo")
    run_mac_path = os.path.join(ROOT_DIR, "run_mac.sh")
    with open(launcher_script, "w", encoding="utf-8") as f:
        f.write(f"""#!/bin/bash
exec /bin/bash "{run_mac_path}"
""")
    os.chmod(launcher_script, 0o755)

    plist_path = os.path.join(app_path, "Contents", "Info.plist")
    with open(plist_path, "w", encoding="utf-8") as f:
        f.write("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Orvo</string>
    <key>CFBundleDisplayName</key>
    <string>Orvo</string>
    <key>CFBundleIdentifier</key>
    <string>com.orvo.dictation</string>
    <key>CFBundleVersion</key>
    <string>1.0.1</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>Orvo</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
""")
    logger.info("Installed macOS Application bundle for Spotlight: %s", app_path)
    return True


def _install_linux_desktop_entry() -> bool:
    apps_dir = os.path.expanduser("~/.local/share/applications")
    os.makedirs(apps_dir, exist_ok=True)
    desktop_path = os.path.join(apps_dir, "orvo.desktop")
    run_linux_path = os.path.join(ROOT_DIR, "run_linux.sh")
    icon_path = os.path.join(ROOT_DIR, "assets", "icon.png")

    content = f"""[Desktop Entry]
Type=Application
Version=1.0
Name=Orvo
Comment=Universal Voice Dictation
Exec=/bin/bash "{run_linux_path}"
Icon={icon_path}
Terminal=false
Categories=Utility;Audio;
StartupNotify=false
"""
    with open(desktop_path, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(desktop_path, 0o755)

    try:
        import subprocess
        subprocess.run(["update-desktop-database", apps_dir], capture_output=True)
    except Exception:
        pass

    logger.info("Installed Linux desktop entry for application search: %s", desktop_path)
    return True


def install_app_shortcuts() -> bool:
    """
    Installs OS-native application search and launcher shortcuts:
    - Windows: Start Menu & Desktop shortcuts for Windows Search.
    - macOS: ~/Applications/Orvo.app bundle for Spotlight.
    - Linux: ~/.local/share/applications/orvo.desktop for application launchers.
    """
    ensure_app_icon()
    if sys.platform == "win32":
        return _install_windows_shortcuts()
    elif sys.platform == "darwin":
        return _install_macos_app_bundle()
    else:
        return _install_linux_desktop_entry()


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
    parser.add_argument("--install-shortcuts", action="store_true", help="Install Start Menu / Application search shortcuts")
    parser.add_argument("--ensure-icon", action="store_true", help="Ensure app icons are generated")
    args = parser.parse_args()

    if args.install_shortcuts:
        if install_app_shortcuts():
            print("Successfully installed application search shortcuts.")
        else:
            print("Failed to install application search shortcuts.")
    elif args.ensure_icon:
        if ensure_app_icon():
            print("Successfully ensured application icons.")
        else:
            print("Failed to generate application icons.")
    elif args.enable:
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

