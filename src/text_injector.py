"""
Orvo SafeTextInjector Module.
Provides atomic clipboard-swap text injection with zero clipboard pollution,
rapid paste keystroke simulation, and resilient direct typing fallback.
"""

import ctypes
from ctypes import wintypes
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from pynput.keyboard import Controller, Key
import pyperclip

try:
    import win32clipboard
    import win32con
    import pywintypes
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

from src.config import AppConfig, get_config

logger = logging.getLogger("Orvo.TextInjector")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Win32 SendInput structure definitions
ULONG_PTR = ctypes.c_ulong if ctypes.sizeof(ctypes.c_void_p) == 4 else ctypes.c_ulonglong
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_CONTROL = 0x11
VK_V = 0x56

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", _INPUT_UNION),
    ]


@dataclass
class ClipboardBackup:
    """Stores a complete snapshot of clipboard contents before text injection."""
    has_content: bool = False
    unicode_text: Optional[str] = None
    dib_data: Optional[bytes] = None
    hdrop_data: Optional[Any] = None
    other_formats: Dict[int, Any] = field(default_factory=dict)


class SafeTextInjector:
    """
    Safely injects text into the active foreground window.
    Employs an atomic clipboard-swap mechanism that backs up existing clipboard data
    (text, images, files), pastes the transcribed text, and faithfully restores the original
    contents. Includes a seamless fallback typing mechanism if the clipboard is locked.
    """

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or get_config()
        self._lock = threading.RLock()
        self._keyboard = Controller()

    @property
    def paste_delay_ms(self) -> int:
        return getattr(self.config.text, "paste_delay_ms", 65)

    # -------------------------------------------------------------------------
    # Win32 Clipboard Helpers
    # -------------------------------------------------------------------------

    def _open_clipboard_with_retry(self, retries: int = 8, delay: float = 0.015) -> bool:
        """
        Attempts to open the Windows clipboard with exponential backoff / retry.
        Returns True if opened successfully, False otherwise.
        """
        if not HAS_WIN32:
            return False

        for _ in range(retries):
            try:
                win32clipboard.OpenClipboard(0)
                return True
            except (pywintypes.error, Exception):
                time.sleep(delay)
        return False

    def _close_clipboard(self) -> None:
        """Safely closes the clipboard without throwing exceptions."""
        if not HAS_WIN32:
            return
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass

    def _backup_clipboard(self) -> ClipboardBackup:
        """
        Backs up current clipboard formats including unicode text, bitmaps (CF_DIB),
        and file drops (CF_HDROP).
        """
        backup = ClipboardBackup()

        if not self._open_clipboard_with_retry():
            # Fallback: attempt pyperclip text backup if win32 open fails
            try:
                txt = pyperclip.paste()
                if txt:
                    backup.has_content = True
                    backup.unicode_text = txt
            except Exception:
                pass
            return backup

        try:
            fmt = 0
            formats = []
            while True:
                fmt = win32clipboard.EnumClipboardFormats(fmt)
                if fmt == 0:
                    break
                formats.append(fmt)

            if not formats:
                return backup

            backup.has_content = True

            # 1. Unicode text
            if win32con.CF_UNICODETEXT in formats:
                try:
                    backup.unicode_text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                except Exception:
                    pass
            elif win32con.CF_TEXT in formats:
                try:
                    raw = win32clipboard.GetClipboardData(win32con.CF_TEXT)
                    backup.unicode_text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                except Exception:
                    pass

            # 2. Image / Bitmap (CF_DIB)
            if win32con.CF_DIB in formats:
                try:
                    backup.dib_data = win32clipboard.GetClipboardData(win32con.CF_DIB)
                except Exception:
                    pass

            # 3. File drops (CF_HDROP)
            if win32con.CF_HDROP in formats:
                try:
                    backup.hdrop_data = win32clipboard.GetClipboardData(win32con.CF_HDROP)
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"Warning during clipboard backup: {e}")
        finally:
            self._close_clipboard()

        return backup

    def _set_clipboard_text(self, text: str) -> bool:
        """Sets the clipboard text to the transcribed text."""
        if self._open_clipboard_with_retry():
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                return True
            except Exception as e:
                logger.debug(f"win32 SetClipboardData failed: {e}")
            finally:
                self._close_clipboard()

        # Fallback to pyperclip
        try:
            pyperclip.copy(text)
            return True
        except Exception as e:
            logger.debug(f"pyperclip copy failed: {e}")
            return False

    def _restore_clipboard(self, backup: ClipboardBackup) -> bool:
        """
        Restores the backed-up clipboard content.
        Guaranteed to run in a finally block to prevent clipboard pollution.
        """
        if not backup.has_content:
            # Clipboard was originally empty; empty it again
            if self._open_clipboard_with_retry():
                try:
                    win32clipboard.EmptyClipboard()
                    return True
                finally:
                    self._close_clipboard()
            return False

        if self._open_clipboard_with_retry():
            try:
                win32clipboard.EmptyClipboard()

                # Restore bitmap if present
                if backup.dib_data is not None:
                    try:
                        win32clipboard.SetClipboardData(win32con.CF_DIB, backup.dib_data)
                    except Exception as e:
                        logger.debug(f"Failed to restore CF_DIB: {e}")

                # Restore unicode text if present
                if backup.unicode_text is not None:
                    try:
                        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, backup.unicode_text)
                    except Exception as e:
                        logger.debug(f"Failed to restore CF_UNICODETEXT: {e}")

                # Restore file drop if present
                if backup.hdrop_data is not None:
                    try:
                        win32clipboard.SetClipboardData(win32con.CF_HDROP, backup.hdrop_data)
                    except Exception as e:
                        logger.debug(f"Failed to restore CF_HDROP: {e}")

                return True
            except Exception as e:
                logger.debug(f"Error restoring win32 clipboard: {e}")
            finally:
                self._close_clipboard()

        # Fallback to pyperclip for text restoration
        if backup.unicode_text is not None:
            try:
                pyperclip.copy(backup.unicode_text)
                return True
            except Exception:
                pass

        return False

    # -------------------------------------------------------------------------
    # Paste & Keystroke Simulation
    # -------------------------------------------------------------------------

    def _simulate_paste(self) -> bool:
        """
        Simulates Ctrl + V paste keystroke.
        Tries Win32 SendInput first, then Win32 keybd_event, and finally pynput Controller.
        """
        # Strategy 1: Win32 SendInput
        try:
            events = [
                INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(ki=KEYBDINPUT(wVk=VK_CONTROL, wScan=0, dwFlags=0, time=0, dwExtraInfo=0))),
                INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(ki=KEYBDINPUT(wVk=VK_V, wScan=0, dwFlags=0, time=0, dwExtraInfo=0))),
                INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(ki=KEYBDINPUT(wVk=VK_V, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0))),
                INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(ki=KEYBDINPUT(wVk=VK_CONTROL, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0))),
            ]
            num_inputs = len(events)
            arr = (INPUT * num_inputs)(*events)
            sent = ctypes.windll.user32.SendInput(num_inputs, arr, ctypes.sizeof(INPUT))
            if sent == num_inputs:
                return True
        except Exception:
            pass

        # Strategy 2: Win32 keybd_event
        try:
            user32 = ctypes.windll.user32
            user32.keybd_event(VK_CONTROL, 0, 0, 0)
            user32.keybd_event(VK_V, 0, 0, 0)
            user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
            return True
        except Exception:
            pass

        # Strategy 3: macOS native Command + V
        if sys.platform == "darwin":
            try:
                import subprocess
                res = subprocess.run(
                    ["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'],
                    capture_output=True,
                )
                if res.returncode == 0:
                    return True
            except Exception:
                pass
            try:
                with self._keyboard.pressed(Key.cmd):
                    self._keyboard.press('v')
                    self._keyboard.release('v')
                return True
            except Exception:
                pass

        # Strategy 4: Linux xdotool / pynput
        if sys.platform.startswith("linux"):
            try:
                import subprocess
                subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], check=True, capture_output=True)
                return True
            except Exception:
                pass

        # Strategy 5: Generic pynput keyboard Controller
        try:
            mod_key = Key.cmd if sys.platform == "darwin" else Key.ctrl
            with self._keyboard.pressed(mod_key):
                self._keyboard.press('v')
                self._keyboard.release('v')
            return True
        except Exception as e:
            logger.error(f"Failed to simulate paste keystroke: {e}")
            return False

    # -------------------------------------------------------------------------
    # Fallback Direct Typing
    # -------------------------------------------------------------------------

    def type_text(self, text: str) -> bool:
        """
        Types the text directly into the focused application character-by-character.
        Supports full Unicode, newlines, tabs, and symbols.
        """
        if not text:
            return True

        try:
            # Use pynput controller's unicode typing
            self._keyboard.type(text)
            return True
        except Exception as e:
            logger.error(f"Direct keyboard typing failed: {e}")
            return False

    # -------------------------------------------------------------------------
    # Public Entry Point
    # -------------------------------------------------------------------------

    def inject(self, text: str) -> bool:
        """
        Injects the given text into the active foreground window.

        Workflow:
        1. Backs up the current clipboard content.
        2. Sets the clipboard to `text`.
        3. Simulates atomic Ctrl + V.
        4. Waits `paste_delay_ms` for the target window to process WM_PASTE.
        5. In a finally block, faithfully restores the user's original clipboard.
        6. If the clipboard is unavailable or locked, seamlessly falls back to direct typing.

        Args:
            text: Transcribed text string to inject.

        Returns:
            True if text was injected successfully, False otherwise.
        """
        if not text:
            return True

        with self._lock:
            clipboard_pasted = False
            backup: Optional[ClipboardBackup] = None

            # Attempt Atomic Clipboard Swap
            try:
                backup = self._backup_clipboard()
                if self._set_clipboard_text(text):
                    try:
                        pasted = self._simulate_paste()
                        if pasted:
                            # Configurable wait so target window consumes WM_PASTE before clipboard restoration
                            time.sleep(self.paste_delay_ms / 1000.0)
                            clipboard_pasted = True
                    finally:
                        # Step 5: Always restore original clipboard in finally block!
                        self._restore_clipboard(backup)
                else:
                    logger.debug("Could not set clipboard data; attempting direct typing fallback.")
            except Exception as e:
                logger.warning(f"Clipboard paste mechanism encountered an error: {e}")
                if backup is not None:
                    try:
                        self._restore_clipboard(backup)
                    except Exception:
                        pass

            if clipboard_pasted:
                return True

            # Fallback to direct typing if clipboard was locked or failed
            if self.config.text.fallback_to_typing:
                logger.info("Clipboard busy or unavailable; fell back to direct typing.")
                return self.type_text(text)

            return False
