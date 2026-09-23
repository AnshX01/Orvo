"""
Orvo - Global Hotkey Manager Module.
Provides low-level system-wide hotkey listening across all Windows applications
supporting both Push-to-Talk and Toggle recording modes, rapid-bounce debouncing,
canonical modifier handling, and Win32 lost-keyup safeguard detection.
"""

import concurrent.futures
import logging
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Union

from pynput import keyboard
from pynput.keyboard import Key, KeyCode, HotKey

# Windows API for physical key state verification
try:
    import win32api
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

logger = logging.getLogger(__name__)

__all__ = [
    "HotkeyManager",
    "normalize_hotkey_string",
    "parse_hotkey_keys",
    "get_vks_for_canonical_key",
]

# Virtual key mapping for common non-standard key names
VK_NAME_MAP: Dict[str, int] = {
    "`": 192,
    "~": 192,
    "grave": 192,
    "backquote": 192,
    "backtick": 192,
    "tilde": 192,
    "minus": 189,
    "equal": 187,
    "bracketleft": 219,
    "bracketright": 221,
    "semicolon": 186,
    "quote": 222,
    "comma": 188,
    "period": 190,
    "slash": 191,
    "backslash": 220,
}

# Key aliases mapping to standard pynput key descriptions
KEY_ALIASES: Dict[str, str] = {
    "`": "grave",
    "backtick": "grave",
    "backquote": "grave",
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "win": "cmd",
    "windows": "cmd",
    "super": "cmd",
    "meta": "cmd",
    "cmd": "cmd",
    "space": "space",
    "spacebar": "space",
    "enter": "enter",
    "return": "enter",
    "esc": "esc",
    "escape": "esc",
    "tab": "tab",
    "backspace": "backspace",
    "del": "delete",
    "delete": "delete",
    "ins": "insert",
    "insert": "insert",
    "home": "home",
    "end": "end",
    "pageup": "page_up",
    "page_up": "page_up",
    "pagedown": "page_down",
    "page_down": "page_down",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "caps": "caps_lock",
    "capslock": "caps_lock",
    "caps_lock": "caps_lock",
    "numlock": "num_lock",
    "num_lock": "num_lock",
    "scrolllock": "scroll_lock",
    "scroll_lock": "scroll_lock",
    "prtscr": "print_screen",
    "printscreen": "print_screen",
    "print_screen": "print_screen",
    "pause": "pause",
    "menu": "menu",
}


def normalize_hotkey_string(hotkey_str: str) -> str:
    """
    Normalize various user hotkey specifications into pynput-compatible format.

    Examples:
        'F8' -> '<f8>'
        'ctrl+alt+space' -> '<ctrl>+<alt>+<space>'
        'Alt + Space' -> '<alt>+<space>'
        'grave' -> '<192>'
        'Ctrl+Shift+D' -> '<ctrl>+<shift>+d'
    """
    raw_tokens = [t.strip() for t in hotkey_str.split("+") if t.strip()]
    normalized_parts: List[str] = []

    for token in raw_tokens:
        clean = token.strip("<>").lower()

        # Check for virtual key map first (e.g. grave)
        if clean in VK_NAME_MAP:
            normalized_parts.append(f"<{VK_NAME_MAP[clean]}>")
            continue

        # Check aliases
        if clean in KEY_ALIASES:
            clean = KEY_ALIASES[clean]

        # Check standard F-keys
        if clean.startswith("f") and clean[1:].isdigit() and 1 <= int(clean[1:]) <= 24:
            normalized_parts.append(f"<{clean}>")
        elif hasattr(Key, clean):
            normalized_parts.append(f"<{clean}>")
        elif len(clean) == 1:
            normalized_parts.append(clean)
        else:
            normalized_parts.append(f"<{clean}>")

    return "+".join(normalized_parts)


def parse_hotkey_keys(hotkey_str: str) -> Set[Union[Key, KeyCode]]:
    """
    Parse a hotkey string into a set of canonical pynput keys.
    """
    normalized = normalize_hotkey_string(hotkey_str)
    try:
        keys_list = HotKey.parse(normalized)
        return set(keys_list)
    except Exception as exc:
        logger.error("Failed to parse hotkey string '%s' (normalized '%s'): %s",
                     hotkey_str, normalized, exc)
        # Fallback to F8 if invalid
        return set(HotKey.parse("<f8>"))


def get_vks_for_canonical_key(key: Union[Key, KeyCode]) -> List[int]:
    """
    Get the list of Windows Virtual Key (VK) codes associated with a canonical pynput key.
    Includes both left and right physical variants for modifiers.
    """
    if key in (Key.ctrl, Key.ctrl_l, Key.ctrl_r):
        return [17, 162, 163]  # VK_CONTROL, VK_LCONTROL, VK_RCONTROL
    elif key in (Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr):
        return [18, 164, 165]  # VK_MENU, VK_LMENU, VK_RMENU
    elif key in (Key.shift, Key.shift_l, Key.shift_r):
        return [16, 160, 161]  # VK_SHIFT, VK_LSHIFT, VK_RSHIFT
    elif key in (Key.cmd, Key.cmd_l, Key.cmd_r):
        return [91, 92]        # VK_LWIN, VK_RWIN
    elif isinstance(key, Key):
        if hasattr(key.value, "vk") and key.value.vk is not None:
            return [key.value.vk]
    elif isinstance(key, KeyCode):
        if key.vk is not None:
            return [key.vk]
        if key.char and HAS_WIN32:
            try:
                vk = win32api.VkKeyScan(key.char) & 0xFF
                if vk > 0:
                    return [vk]
            except Exception:
                pass
    return []


class HotkeyManager:
    """
    Global hotkey listener for Orvo.
    Captures hotkey presses system-wide across all Windows desktop applications.
    Supports 'push_to_talk' and 'toggle' modes, key debounce, and lost-keyup watchdog.
    """

    def __init__(
        self,
        config: Optional[Any] = None,
        hotkey: str = "<alt>+<grave>",
        mode: str = "toggle",
        debounce_ms: int = 150,
        on_start: Optional[Callable[[], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        on_record_start: Optional[Callable[[], None]] = None,
        on_record_stop: Optional[Callable[[], None]] = None,
        on_hotkey_triggered: Optional[Callable[[str], None]] = None,
        max_duration_seconds: float = 120.0,
    ):
        """
        Initialize the HotkeyManager.

        Args:
            config: Optional HotkeyConfig instance. If provided, values override defaults.
            hotkey: Hotkey string, e.g. 'F8', '<alt>+<space>', '<ctrl>+<alt>+<space>'.
            mode: 'push_to_talk' or 'toggle'.
            debounce_ms: Debounce threshold in milliseconds to ignore rapid bounce.
            on_start: Callback invoked when recording should begin.
            on_stop: Callback invoked when recording should stop.
            on_record_start: Alias for on_start.
            on_record_stop: Alias for on_stop.
            on_hotkey_triggered: Callback invoked when hotkey activates with hotkey string.
            max_duration_seconds: Safeguard timeout for push-to-talk in seconds.
        """
        # Apply config if provided
        if config is not None:
            self.hotkey_string = getattr(config, "key", hotkey)
            self.mode = getattr(config, "mode", mode).lower()
            self.debounce_ms = getattr(config, "debounce_ms", debounce_ms)
        else:
            self.hotkey_string = hotkey
            self.mode = mode.lower()
            self.debounce_ms = debounce_ms

        self.max_duration_seconds = max_duration_seconds

        # User callbacks (supporting both on_start and on_record_start aliases)
        self.on_start = on_start or on_record_start
        self.on_stop = on_stop or on_record_stop
        self.on_record_start = self.on_start
        self.on_record_stop = self.on_stop
        self.on_hotkey_triggered = on_hotkey_triggered

        # Thread synchronization and state
        self._lock = threading.RLock()
        self._is_listening = False
        self._is_active = False            # True when recording is active
        self._key_held = False              # Used for toggle mode key-repeat suppression
        self._last_event_time: float = 0.0  # Used for debouncing
        self._recording_start_time: float = 0.0

        # Pressed keys tracking
        self._target_keys: Set[Union[Key, KeyCode]] = set()
        self._target_vk_groups: List[List[int]] = []
        self._currently_pressed: Set[Union[Key, KeyCode]] = set()

        # Keyboard listener and background worker executor
        self._listener: Optional[keyboard.Listener] = None
        self._callback_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="HotkeyCallback"
        )

        # Watchdog thread for lost keyup events
        self._watchdog_thread: Optional[threading.Thread] = None
        self._stop_watchdog_event = threading.Event()

        # Parse initial hotkey
        self._update_target_keys(self.hotkey_string)

    # -------------------------------------------------------------------------
    # Hotkey Configuration & Parsing
    # -------------------------------------------------------------------------

    def _update_target_keys(self, hotkey_str: str) -> None:
        """Parse hotkey string into target canonical keys and VK groups."""
        with self._lock:
            self.hotkey_string = hotkey_str
            self._target_keys = parse_hotkey_keys(hotkey_str)
            self._target_vk_groups = [
                get_vks_for_canonical_key(k) for k in self._target_keys
            ]
            self._currently_pressed.clear()
            self._key_held = False
            logger.info("Hotkey registered: '%s' -> target keys %s (VK groups: %s)",
                        self.hotkey_string, self._target_keys, self._target_vk_groups)

    def set_hotkey(self, hotkey: str, mode: Optional[str] = None) -> None:
        """Dynamically update hotkey and optionally the recording mode."""
        with self._lock:
            if self._is_active:
                self._dispatch_stop()

            self._update_target_keys(hotkey)
            if mode is not None:
                self.mode = mode.lower()
            logger.info("HotkeyManager updated: hotkey='%s', mode='%s'", self.hotkey_string, self.mode)

    def set_mode(self, mode: str) -> None:
        """Set recording mode ('push_to_talk' or 'toggle')."""
        with self._lock:
            if self._is_active:
                self._dispatch_stop()
            self.mode = mode.lower()
            logger.info("HotkeyManager mode set to: '%s'", self.mode)

    def set_callbacks(
        self,
        on_start: Optional[Callable[[], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        on_record_start: Optional[Callable[[], None]] = None,
        on_record_stop: Optional[Callable[[], None]] = None,
        on_hotkey_triggered: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Set callback handlers."""
        with self._lock:
            start_cb = on_start or on_record_start
            stop_cb = on_stop or on_record_stop
            if start_cb is not None:
                self.on_start = start_cb
                self.on_record_start = start_cb
            if stop_cb is not None:
                self.on_stop = stop_cb
                self.on_record_stop = stop_cb
            if on_hotkey_triggered is not None:
                self.on_hotkey_triggered = on_hotkey_triggered

    def update_config(self, config: Any) -> None:
        """Update settings from a HotkeyConfig instance."""
        with self._lock:
            new_key = getattr(config, "key", self.hotkey_string)
            new_mode = getattr(config, "mode", self.mode)
            self.debounce_ms = getattr(config, "debounce_ms", self.debounce_ms)
            self.set_hotkey(new_key, new_mode)

    # -------------------------------------------------------------------------
    # Asynchronous Callback Dispatching
    # -------------------------------------------------------------------------

    def _dispatch_start(self) -> None:
        """Dispatch on_start and on_hotkey_triggered callbacks asynchronously."""
        self._is_active = True
        self._recording_start_time = time.monotonic()
        hotkey_name = self.hotkey_string

        def _worker():
            try:
                if self.on_hotkey_triggered is not None:
                    self.on_hotkey_triggered(hotkey_name)
            except Exception as exc:
                logger.error("Error in on_hotkey_triggered callback: %s", exc)

            try:
                if self.on_start is not None:
                    self.on_start()
            except Exception as exc:
                logger.error("Error in on_start callback: %s", exc)

        self._callback_executor.submit(_worker)

    def _dispatch_stop(self) -> None:
        """Dispatch on_stop callback asynchronously."""
        if not self._is_active:
            return

        self._is_active = False

        def _worker():
            try:
                if self.on_stop is not None:
                    self.on_stop()
            except Exception as exc:
                logger.error("Error in on_stop callback: %s", exc)

        self._callback_executor.submit(_worker)

    def reset_state(self) -> None:
        """Reset internal key-tracking and active state when recording stops externally."""
        with self._lock:
            self._is_active = False
            self._key_held = False
            self._currently_pressed.clear()

    # -------------------------------------------------------------------------
    # Keyboard Hook Handlers
    # -------------------------------------------------------------------------

    def _canonical(self, key: Union[Key, KeyCode]) -> Union[Key, KeyCode]:
        """Convert a received key event to canonical form using listener or fallback."""
        if self._listener is not None:
            try:
                return self._listener.canonical(key)
            except Exception:
                pass
        try:
            from pynput.keyboard import _NORMAL_MODIFIERS
            if isinstance(key, KeyCode) and key.char is not None:
                return KeyCode.from_char(key.char.lower())
            elif isinstance(key, Key) and key.value in _NORMAL_MODIFIERS:
                return _NORMAL_MODIFIERS[key.value]
            elif isinstance(key, Key) and hasattr(key.value, "vk") and key.value.vk is not None:
                return KeyCode.from_vk(key.value.vk)
        except Exception:
            pass
        return key

    def _matches_target_key(self, target: Union[Key, KeyCode], candidate: Union[Key, KeyCode]) -> bool:
        """Check if an incoming key event matches a target hotkey component."""
        if target == candidate:
            return True

        # Check modifier keys (canonical or left/right variants)
        if isinstance(target, Key) and isinstance(candidate, Key):
            if target in (Key.alt, Key.alt_l, Key.alt_r) and candidate in (Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr):
                return True
            if target in (Key.ctrl, Key.ctrl_l, Key.ctrl_r) and candidate in (Key.ctrl, Key.ctrl_l, Key.ctrl_r):
                return True
            if target in (Key.shift, Key.shift_l, Key.shift_r) and candidate in (Key.shift, Key.shift_l, Key.shift_r):
                return True
            if target in (Key.cmd, Key.cmd_l, Key.cmd_r) and candidate in (Key.cmd, Key.cmd_l, Key.cmd_r):
                return True
            return False

        # Check KeyCode instances
        target_vk = getattr(target, "vk", None)
        cand_vk = getattr(candidate, "vk", None)
        target_char = getattr(target, "char", None)
        cand_char = getattr(candidate, "char", None)

        # 1. Direct VK match
        if target_vk is not None and cand_vk is not None and target_vk == cand_vk:
            return True

        # 2. Direct char match (case-insensitive)
        if target_char is not None and cand_char is not None and target_char.lower() == cand_char.lower():
            return True

        # 3. Known special virtual keys (e.g. backtick/tilde VK 192)
        if target_vk == 192 and cand_char in ('`', '~'):
            return True
        if cand_vk == 192 and target_char in ('`', '~'):
            return True

        # 4. Windows VkKeyScan resolution between char and VK
        if HAS_WIN32:
            if target_vk is not None and cand_char is not None:
                try:
                    if (win32api.VkKeyScan(cand_char) & 0xFF) == target_vk:
                        return True
                except Exception:
                    pass
            if cand_vk is not None and target_char is not None:
                try:
                    if (win32api.VkKeyScan(target_char) & 0xFF) == cand_vk:
                        return True
                except Exception:
                    pass

        return False

    def _on_press(self, key: Union[Key, KeyCode]) -> None:
        """Low-level key press callback."""
        try:
            canonical_key = self._canonical(key)

            with self._lock:
                if not self._is_listening or not self._target_keys:
                    return

                matched_target = None
                for target in self._target_keys:
                    if self._matches_target_key(target, key) or self._matches_target_key(target, canonical_key):
                        matched_target = target
                        break

                if matched_target is not None:
                    self._currently_pressed.add(matched_target)

                    # Check if all target keys are pressed
                    if self._target_keys.issubset(self._currently_pressed):
                        now = time.monotonic()

                        if self.mode == "push_to_talk":
                            # If already active, this is an OS key repeat -> ignore
                            if self._is_active:
                                return

                            # Debounce check
                            if (now - self._last_event_time) < (self.debounce_ms / 1000.0):
                                return
                            self._last_event_time = now

                            logger.debug("Push-to-talk started by hotkey press.")
                            self._dispatch_start()

                        elif self.mode == "toggle":
                            # Key repeat suppression: ignore if already held
                            if self._key_held:
                                return
                            self._key_held = True

                            # Debounce check
                            if (now - self._last_event_time) < (self.debounce_ms / 1000.0):
                                return
                            self._last_event_time = now

                            if not self._is_active:
                                logger.info("Toggle mode started recording via hotkey.")
                                self._dispatch_start()
                            else:
                                logger.info("Toggle mode stopped recording via hotkey.")
                                self._dispatch_stop()
        except Exception as exc:
            logger.debug("Exception in hotkey _on_press: %s", exc)

    def _on_release(self, key: Union[Key, KeyCode]) -> None:
        """Low-level key release callback."""
        try:
            canonical_key = self._canonical(key)

            with self._lock:
                if not self._is_listening or not self._target_keys:
                    return

                matched_target = None
                for target in self._target_keys:
                    if self._matches_target_key(target, key) or self._matches_target_key(target, canonical_key):
                        matched_target = target
                        break

                if matched_target is not None:
                    self._currently_pressed.discard(matched_target)

                # If combination is broken
                if not self._target_keys.issubset(self._currently_pressed):
                    self._key_held = False

                    if self.mode == "push_to_talk" and self._is_active:
                        self._last_event_time = time.monotonic()
                        logger.debug("Push-to-talk stopped by hotkey release.")
                        self._dispatch_stop()
        except Exception as exc:
            logger.debug("Exception in hotkey _on_release: %s", exc)

    # -------------------------------------------------------------------------
    # Win32 Watchdog Safeguard for Lost Keyup Events & Max Duration
    # -------------------------------------------------------------------------

    def _are_all_target_keys_physically_down(self) -> bool:
        """
        Check whether all target keys are physically pressed down right now using Win32 API.
        Returns False if any required key is released.
        """
        if not HAS_WIN32 or not self._target_vk_groups:
            return True

        for vk_group in self._target_vk_groups:
            if not vk_group:
                continue
            # For this target key, at least one VK in group must be down
            key_down = False
            for vk in vk_group:
                try:
                    if bool(win32api.GetAsyncKeyState(vk) & 0x8000):
                        key_down = True
                        break
                except Exception:
                    key_down = True  # If API fails, avoid false positive
            if not key_down:
                return False

        return True

    def _watchdog_loop(self) -> None:
        """
        Background watchdog thread that continuously checks physical key states
        and safeguard timeouts across all modes (push-to-talk and toggle).
        """
        while not self._stop_watchdog_event.is_set():
            time.sleep(0.06)  # 60ms polling interval

            with self._lock:
                # Key-held recovery for toggle mode: if keys are physically up, clear _key_held
                if self.mode == "toggle" and self._key_held:
                    if not self._are_all_target_keys_physically_down():
                        self._key_held = False
                        self._currently_pressed.clear()

                if not self._is_listening or not self._is_active:
                    continue

                duration = time.monotonic() - self._recording_start_time

                # Safeguard 1: Universal maximum duration safeguard (all modes)
                if duration > self.max_duration_seconds:
                    logger.warning(
                        "Recording exceeded max duration safeguard (%.1fs) in mode '%s'. Auto-stopping.",
                        self.max_duration_seconds, self.mode
                    )
                    self._currently_pressed.clear()
                    self._key_held = False
                    self._dispatch_stop()
                    continue

                # Safeguard 2: Physical key state check via GetAsyncKeyState for Push-to-Talk
                if self.mode == "push_to_talk":
                    if not self._are_all_target_keys_physically_down():
                        logger.info("Lost keyup detected via Win32 GetAsyncKeyState in push-to-talk. Stopping recording.")
                        self._currently_pressed.clear()
                        self._key_held = False
                        self._dispatch_stop()
                        continue

    # -------------------------------------------------------------------------
    # Lifecycle Control
    # -------------------------------------------------------------------------

    def start(self) -> None:
        """Start listening for global hotkeys across the operating system."""
        with self._lock:
            if self._is_listening:
                logger.warning("HotkeyManager: start called while already listening.")
                return

            self._is_listening = True
            self._is_active = False
            self._key_held = False
            self._currently_pressed.clear()

            # Start low-level keyboard listener
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release
            )
            self._listener.daemon = True
            self._listener.start()

            # Start watchdog thread
            self._stop_watchdog_event.clear()
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop,
                daemon=True,
                name="HotkeyWatchdog"
            )
            self._watchdog_thread.start()

            logger.info("HotkeyManager started listening for '%s' (mode=%s)",
                        self.hotkey_string, self.mode)

    def stop(self) -> None:
        """Stop listening for global hotkeys and clean up resources."""
        with self._lock:
            if not self._is_listening:
                return

            self._is_listening = False

            # If recording was active, stop it
            if self._is_active:
                self._dispatch_stop()

            # Stop watchdog
            self._stop_watchdog_event.set()
            if self._watchdog_thread and self._watchdog_thread.is_alive():
                self._watchdog_thread.join(timeout=0.5)
            self._watchdog_thread = None

            # Stop listener
            if self._listener is not None:
                try:
                    self._listener.stop()
                except Exception as exc:
                    logger.debug("Exception stopping listener: %s", exc)
                self._listener = None

            self._currently_pressed.clear()
            self._key_held = False
            logger.info("HotkeyManager stopped.")

    # -------------------------------------------------------------------------
    # State & Getters
    # -------------------------------------------------------------------------

    def is_listening(self) -> bool:
        """Check if hotkey listener is active."""
        with self._lock:
            return self._is_listening

    def is_active(self) -> bool:
        """Check if hotkey is currently engaged / recording."""
        with self._lock:
            return self._is_active
