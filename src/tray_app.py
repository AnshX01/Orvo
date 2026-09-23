"""
System Tray Application for Orvo.
Provides background taskbar integration using pystray and Pillow,
dynamic status icons (Idle, Recording, Transcribing), and a comprehensive
context menu for mode switching, model selection, audio device choosing,
and preferences.
"""

import os
import subprocess
import sys
import threading
import time
from typing import Optional, Callable, List, Tuple
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item, Menu

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False

try:
    from src.config import get_config, ConfigManager, CONFIG_FILE_PATH, AppConfig
except ImportError:
    from config import get_config, ConfigManager, CONFIG_FILE_PATH, AppConfig

try:
    from src.history_dialog import HistoryDialog
except ImportError:
    from history_dialog import HistoryDialog


def generate_tray_icon(state: str = "idle", size: int = 64) -> Image.Image:
    """
    Generates dynamic crisp PIL icons for system tray.
    - idle: Sleek dark slate badge with clean white microphone silhouette.
    - recording: Vibrant red badge with active glowing mic.
    - transcribing: Amber badge with processing spinner indicator.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    scale = size / 64.0

    if state == "idle":
        # Neutral dark slate badge with subtle outline
        d.ellipse(
            [3 * scale, 3 * scale, 61 * scale, 61 * scale],
            fill=(30, 32, 40, 255),
            outline=(148, 163, 184, 255),
            width=max(1, int(2.5 * scale)),
        )
        # Microphone capsule
        d.rounded_rectangle(
            [25 * scale, 16 * scale, 39 * scale, 36 * scale],
            radius=7 * scale,
            fill=(241, 245, 249, 255),
        )
        # Microphone cradle
        d.arc(
            [18 * scale, 24 * scale, 46 * scale, 42 * scale],
            start=0,
            end=180,
            fill=(241, 245, 249, 255),
            width=max(1, int(3 * scale)),
        )
        # Stand & Base
        d.line(
            [32 * scale, 42 * scale, 32 * scale, 48 * scale],
            fill=(241, 245, 249, 255),
            width=max(1, int(3 * scale)),
        )
        d.line(
            [22 * scale, 48 * scale, 42 * scale, 48 * scale],
            fill=(241, 245, 249, 255),
            width=max(1, int(3 * scale)),
        )

    elif state in ("recording", "listening"):
        # Vibrant glowing crimson badge
        d.ellipse(
            [3 * scale, 3 * scale, 61 * scale, 61 * scale],
            fill=(220, 38, 38, 255),
            outline=(254, 202, 202, 255),
            width=max(1, int(2.5 * scale)),
        )
        # Crisp white mic
        d.rounded_rectangle(
            [25 * scale, 16 * scale, 39 * scale, 36 * scale],
            radius=7 * scale,
            fill=(255, 255, 255, 255),
        )
        d.arc(
            [18 * scale, 24 * scale, 46 * scale, 42 * scale],
            start=0,
            end=180,
            fill=(255, 255, 255, 255),
            width=max(1, int(3 * scale)),
        )
        d.line(
            [32 * scale, 42 * scale, 32 * scale, 48 * scale],
            fill=(255, 255, 255, 255),
            width=max(1, int(3 * scale)),
        )
        d.line(
            [22 * scale, 48 * scale, 42 * scale, 48 * scale],
            fill=(255, 255, 255, 255),
            width=max(1, int(3 * scale)),
        )

    elif state in ("transcribing", "processing"):
        # Warm amber / gold badge
        d.ellipse(
            [3 * scale, 3 * scale, 61 * scale, 61 * scale],
            fill=(217, 119, 6, 255),
            outline=(253, 230, 138, 255),
            width=max(1, int(2.5 * scale)),
        )
        # Center sparkle core
        d.ellipse(
            [26 * scale, 26 * scale, 38 * scale, 38 * scale],
            fill=(255, 255, 255, 255),
        )
        # 4 rotating orbital indicator dots
        orbital_pts = [(16, 32), (48, 32), (32, 16), (32, 48)]
        for px, py in orbital_pts:
            d.ellipse(
                [
                    (px - 3) * scale,
                    (py - 3) * scale,
                    (px + 3) * scale,
                    (py + 3) * scale,
                ],
                fill=(254, 243, 199, 255),
            )

    return img


def get_audio_input_devices() -> List[Tuple[int, str]]:
    """Queries available audio input devices from sounddevice."""
    if not HAS_SOUNDDEVICE:
        return []
    devices = []
    try:
        raw_devices = sd.query_devices()
        seen = set()
        for idx, dev in enumerate(raw_devices):
            if dev.get("max_input_channels", 0) > 0:
                name = dev.get("name", f"Device {idx}").strip()
                # Clean windows driver strings
                clean_name = name.split("\r\n")[0].strip()
                if len(clean_name) > 38:
                    clean_name = clean_name[:35] + "..."
                key = clean_name
                if key in seen:
                    hostapi = dev.get("hostapi", 0)
                    key = f"{clean_name} [API {hostapi}]"
                seen.add(key)
                devices.append((idx, key))
    except Exception as e:
        print(f"[TrayApp] Warning: Device enumeration error: {e}")
    return devices


class TrayApp:
    """
    Main system tray application controller.
    Manages pystray icon, context menu, state transitions, and user actions.
    """

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        on_mode_change: Optional[Callable[[str], None]] = None,
        on_model_change: Optional[Callable[[str, str], None]] = None,
        on_device_change: Optional[Callable[[Optional[int]], None]] = None,
        on_sound_toggle: Optional[Callable[[bool], None]] = None,
        on_hud_toggle: Optional[Callable[[bool], None]] = None,
        on_history_clicked: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
    ):
        self.config = config or get_config()

        # Callbacks
        self.on_mode_change = on_mode_change
        self.on_model_change = on_model_change
        self.on_device_change = on_device_change
        self.on_sound_toggle = on_sound_toggle
        self.on_hud_toggle = on_hud_toggle
        self.on_history_clicked = on_history_clicked
        self.on_exit = on_exit

        # State
        self.current_state = "idle"
        self._lock = threading.Lock()

        # Pre-render state icons
        self.icons = {
            "idle": generate_tray_icon("idle", 64),
            "recording": generate_tray_icon("recording", 64),
            "transcribing": generate_tray_icon("transcribing", 64),
        }

        # Initialize pystray Icon
        self.icon = pystray.Icon(
            name="Orvo",
            icon=self.icons["idle"],
            title="Orvo • Idle",
            menu=self._build_menu(),
        )

        # On Windows, pystray by default only shows menu on right-click (WM_RBUTTONUP).
        # Intercept WM_LBUTTONUP so left-clicking the tray icon also opens the context menu immediately.
        if sys.platform == "win32" and hasattr(self.icon, "_message_handlers"):
            orig_notify = getattr(self.icon, "_on_notify", None)
            if orig_notify:
                def _patched_notify(wparam, lparam):
                    if lparam == 0x0202:  # WM_LBUTTONUP -> route to WM_RBUTTONUP (0x0205)
                        lparam = 0x0205
                    return orig_notify(wparam, lparam)
                self.icon._on_notify = _patched_notify
                for k, v in list(self.icon._message_handlers.items()):
                    if getattr(v, "__name__", "") == "_on_notify":
                        self.icon._message_handlers[k] = _patched_notify

    # =========================================================================
    # Context Menu Construction
    # =========================================================================

    def _build_menu(self) -> Menu:
        """Constructs the rich context menu with dynamic checkmarks."""
        # Status header
        status_label = f"Orvo: {self.current_state.capitalize()}"
        if self.current_state == "recording":
            status_label = "🔴 Orvo: Recording..."
        elif self.current_state == "transcribing":
            status_label = "🟡 Orvo: Transcribing..."
        else:
            status_label = "⚪ Orvo: Idle"

        # Mode options
        mode_menu = Menu(
            item(
                "Push-to-Talk",
                lambda: self.set_mode("push_to_talk"),
                checked=lambda it: self.config.hotkey.mode == "push_to_talk",
                radio=True,
            ),
            item(
                "Toggle Mode",
                lambda: self.set_mode("toggle"),
                checked=lambda it: self.config.hotkey.mode == "toggle",
                radio=True,
            ),
        )

        # Model options
        model_menu = Menu(
            item(
                "tiny.en (Fastest, ~40MB)",
                lambda: self.set_model("tiny.en", "local"),
                checked=lambda it: self.is_model("tiny.en", "local"),
                radio=True,
            ),
            item(
                "base.en (Balanced, ~75MB)",
                lambda: self.set_model("base.en", "local"),
                checked=lambda it: self.is_model("base.en", "local"),
                radio=True,
            ),
            item(
                "small.en (High Accuracy, ~240MB)",
                lambda: self.set_model("small.en", "local"),
                checked=lambda it: self.is_model("small.en", "local"),
                radio=True,
            ),
            item(
                "Cloud (Groq Whisper-Large-v3)",
                lambda: self.set_model("whisper-large-v3-turbo", "groq"),
                checked=lambda it: self.is_model("whisper-large-v3-turbo", "groq"),
                radio=True,
            ),
        )

        # Audio devices submenu
        mic_items = [
            item(
                "Default Microphone",
                lambda: self.set_device(None),
                checked=lambda it: self.config.audio.device_index is None,
                radio=True,
            )
        ]
        input_devices = get_audio_input_devices()
        for dev_idx, dev_name in input_devices:
            mic_items.append(
                item(
                    dev_name,
                    self._create_device_handler(dev_idx),
                    checked=self._create_device_checker(dev_idx),
                    radio=True,
                )
            )
        devices_menu = Menu(*mic_items)

        # Full context menu structure
        return Menu(
            item(status_label, lambda: None, enabled=False),
            Menu.SEPARATOR,
            item("Dictation Mode", mode_menu),
            item("Model / Engine", model_menu),
            item("Microphone", devices_menu),
            Menu.SEPARATOR,
            item(
                "Floating HUD",
                self.toggle_hud,
                checked=lambda it: self.config.ui.show_hud,
            ),
            item(
                "Start with Windows" if sys.platform == "win32" else "Start on Login",
                self.toggle_startup,
                checked=lambda it: self.is_startup_enabled(),
            ),
            Menu.SEPARATOR,
            item("History / Past Dictations...", self.open_history),
            item("Edit Settings...", self.open_settings),
            item("Open Logs...", self.open_logs),
            Menu.SEPARATOR,
            item("Exit", self.exit_app),
        )

    def _create_device_handler(self, dev_idx: int):
        return lambda: self.set_device(dev_idx)

    def _create_device_checker(self, dev_idx: int):
        return lambda it: self.config.audio.device_index == dev_idx

    # =========================================================================
    # Action Handlers & Settings Modifiers
    # =========================================================================

    def update_state(self, state: str) -> None:
        """Updates the tray icon state ('idle', 'recording', 'transcribing')."""
        with self._lock:
            self.current_state = state
            icon_img = self.icons.get(state, self.icons["idle"])
            if self.icon:
                self.icon.icon = icon_img
                self.icon.title = f"Orvo • {state.capitalize()}"
                self.refresh_menu()

    def set_mode(self, mode: str) -> None:
        """Sets push-to-talk or toggle mode."""
        self.config.hotkey.mode = mode
        ConfigManager().update(hotkey=self.config.hotkey)
        if self.on_mode_change:
            self.on_mode_change(mode)
        self.refresh_menu()

    def set_model(self, model_name: str, backend: str = "local") -> None:
        """Switches transcription model and backend."""
        self.config.model.backend = backend
        if backend == "local":
            self.config.model.local_model = model_name
        elif backend == "groq":
            self.config.model.groq_model = model_name
        ConfigManager().update(model=self.config.model)
        if self.on_model_change:
            self.on_model_change(model_name, backend)
        self.refresh_menu()

    def is_model(self, model_name: str, backend: str) -> bool:
        if self.config.model.backend != backend:
            return False
        if backend == "groq":
            return self.config.model.groq_model == model_name
        return self.config.model.local_model == model_name

    def set_device(self, device_index: Optional[int]) -> None:
        """Switches active audio input device."""
        self.config.audio.device_index = device_index
        ConfigManager().update(audio=self.config.audio)
        if self.on_device_change:
            self.on_device_change(device_index)
        self.refresh_menu()

    def toggle_sound(self) -> None:
        """No-op: All audio feedback sounds have been permanently removed from Orvo."""
        self.config.audio.sound_effects = False
        self.config.ui.sound_feedback = False
        self.refresh_menu()

    def toggle_hud(self) -> None:
        """Toggles floating HUD overlay on/off."""
        new_val = not self.config.ui.show_hud
        self.config.ui.show_hud = new_val
        ConfigManager().update(ui=self.config.ui)
        if self.on_hud_toggle:
            self.on_hud_toggle(new_val)
        self.refresh_menu()

    def toggle_startup(self) -> None:
        """Toggles start on boot/login via StartupManager."""
        try:
            from src.startup_manager import toggle_startup
            toggle_startup()
            self.refresh_menu()
        except Exception as exc:
            print(f"[TrayApp] Error toggling startup: {exc}")

    def is_startup_enabled(self) -> bool:
        """Checks if startup is enabled."""
        try:
            from src.startup_manager import is_startup_enabled
            return is_startup_enabled()
        except Exception:
            return False

    def open_history(self) -> None:
        """Opens the dictation history dialog safely in a dedicated thread."""
        if self.on_history_clicked:
            self.on_history_clicked()
            return
        def _launch():
            try:
                from src.history_dialog import HistoryDialog
                HistoryDialog.show(parent=None)
            except Exception as exc:
                print(f"[TrayApp] Error opening history dialog: {exc}")

        threading.Thread(target=_launch, daemon=True, name="HistoryDialogThread").start()

    def open_settings(self) -> None:
        """Opens config.json in default system text editor with notepad fallback."""
        cfg_path = CONFIG_FILE_PATH
        if not os.path.exists(cfg_path):
            ConfigManager().save()
        try:
            if sys.platform == "win32":
                try:
                    os.startfile(cfg_path)
                except Exception:
                    subprocess.Popen(["notepad.exe", cfg_path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", cfg_path])
            else:
                subprocess.Popen(["xdg-open", cfg_path])
        except Exception as e:
            if sys.platform == "win32":
                try:
                    subprocess.Popen(["notepad.exe", cfg_path])
                except Exception:
                    pass
            print(f"[TrayApp] Error launching settings: {e}")

    def open_logs(self) -> None:
        """Opens application logs directory or log file with notepad/explorer fallback."""
        log_dir = os.path.abspath(
            os.path.join(os.path.dirname(CONFIG_FILE_PATH), "..", "logs")
        )
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "orvo.log")
        target = log_file if os.path.exists(log_file) else log_dir
        try:
            if sys.platform == "win32":
                try:
                    os.startfile(target)
                except Exception:
                    if os.path.isfile(target):
                        subprocess.Popen(["notepad.exe", target])
                    else:
                        subprocess.Popen(["explorer.exe", target])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
        except Exception as e:
            if sys.platform == "win32":
                try:
                    subprocess.Popen(["explorer.exe", log_dir])
                except Exception:
                    pass
            print(f"[TrayApp] Error opening logs: {e}")

    def refresh_menu(self) -> None:
        """Re-builds and updates context menu checkmarks."""
        if self.icon:
            self.icon.menu = self._build_menu()
            try:
                self.icon.update_menu()
            except Exception:
                pass

    def exit_app(self) -> None:
        """Triggers application shutdown."""
        if self.on_exit:
            try:
                self.on_exit()
            except Exception as e:
                print(f"[TrayApp] Error in on_exit callback: {e}")
        self.stop()

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    def run(self) -> None:
        """Runs the tray icon blocking the current thread."""
        self.icon.run()

    def run_detached(self) -> None:
        """Runs the tray icon in a dedicated background thread."""
        self.icon.run_detached()

    def stop(self) -> None:
        """Stops the system tray icon cleanly."""
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass


if __name__ == "__main__":
    print("Testing TrayApp in detached mode...")
    app = TrayApp()
    app.run_detached()
    time.sleep(0.5)

    print("Updating state to recording...")
    app.update_state("recording")
    time.sleep(1.0)

    print("Updating state to transcribing...")
    app.update_state("transcribing")
    time.sleep(1.0)

    print("Updating state to idle...")
    app.update_state("idle")
    time.sleep(0.5)

    print("Stopping TrayApp...")
    app.stop()
    print("TrayApp test passed!")
