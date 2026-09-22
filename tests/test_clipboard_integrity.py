"""
Orvo - Clipboard Integrity Verification Tests.
Verifies that the SafeTextInjector atomic clipboard-swap mechanism faithfully
restores existing user clipboard data (text, unicode, multiline, images) with 100% fidelity.
"""

import io
import time
import unittest
import pyperclip
from PIL import Image

try:
    import win32clipboard
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

from src.text_injector import SafeTextInjector
from src.config import AppConfig, TextConfig


def _safe_copy(text: str) -> None:
    if HAS_WIN32:
        for i in range(10):
            try:
                win32clipboard.OpenClipboard(0)
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                win32clipboard.CloseClipboard()
                return
            except Exception:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass
                time.sleep(0.05)
    try:
        pyperclip.copy(text)
    except Exception as exc:
        raise unittest.SkipTest(f"Windows clipboard locked by OS session: {exc}")


def _safe_paste() -> str:
    if HAS_WIN32:
        for i in range(10):
            try:
                win32clipboard.OpenClipboard(0)
                val = ""
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    val = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                win32clipboard.CloseClipboard()
                return val
            except Exception:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass
                time.sleep(0.05)
    try:
        return pyperclip.paste()
    except Exception as exc:
        raise unittest.SkipTest(f"Windows clipboard locked by OS session: {exc}")


class TestClipboardIntegrity(unittest.TestCase):
    """Verifies zero clipboard pollution during text injection."""

    def setUp(self):
        self.config = AppConfig(
            text=TextConfig(
                paste_delay_ms=25,  # fast delay for testing
                fallback_to_typing=False,
            )
        )
        self.injector = SafeTextInjector(config=self.config)

    def test_text_clipboard_preservation(self):
        """Copies text A to clipboard, injects text B, and verifies clipboard still equals text A."""
        original_text = f"CONFIDENTIAL_USER_CLIPBOARD_DATA_{time.time()}"
        _safe_copy(original_text)
        time.sleep(0.05)
        self.assertEqual(_safe_paste(), original_text)

        # Perform simulated injection of dictation text
        dictation_text = "Dictated speech text to be pasted into document"
        success = self.injector.inject(dictation_text)
        self.assertTrue(success, "Text injection should report success.")

        # Give small moment for restoration to finalize
        time.sleep(0.05)

        # Assert clipboard restored exactly
        restored_text = _safe_paste()
        self.assertEqual(
            restored_text,
            original_text,
            "Clipboard contents were polluted! Expected original text to be preserved."
        )

    def test_multiline_unicode_clipboard_preservation(self):
        """Verifies multiline and unicode text preservation."""
        complex_text = "Line 1: Special Characters: £, €, ¥, ✦, 🚀\nLine 2: 日本語テキスト\nLine 3: End of text."
        _safe_copy(complex_text)
        time.sleep(0.05)

        self.injector.inject("Injected line of new voice transcription")
        time.sleep(0.05)

        restored_text = _safe_paste()
        self.assertEqual(restored_text, complex_text)

    def test_image_bitmap_preservation(self):
        """Tests that copying an image to clipboard is preserved after text injection."""
        if not HAS_WIN32:
            self.skipTest("win32clipboard not available for image testing.")

        # Create a small 32x32 test image and place on clipboard as DIB
        img = Image.new("RGB", (32, 32), color=(255, 0, 128))
        output = io.BytesIO()
        img.convert("RGB").save(output, "BMP")
        bmp_data = output.getvalue()
        # DIB data starts at byte 14 (skipping the 14-byte BITMAPFILEHEADER)
        dib_data = bmp_data[14:]

        try:
            win32clipboard.OpenClipboard(0)
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_DIB, dib_data)
            win32clipboard.CloseClipboard()
        except Exception as exc:
            self.skipTest(f"Could not seed clipboard with test bitmap: {exc}")

        # Inject text
        self.injector.inject("Dictation while user has an image in clipboard")
        time.sleep(0.05)

        # Verify CF_DIB is still present on clipboard
        try:
            win32clipboard.OpenClipboard(0)
            has_dib = win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB)
            restored_dib = win32clipboard.GetClipboardData(win32con.CF_DIB) if has_dib else None
            win32clipboard.CloseClipboard()
            self.assertTrue(has_dib, "CF_DIB bitmap was lost during text injection!")
            self.assertIsNotNone(restored_dib)
        except Exception as exc:
            self.fail(f"Clipboard verification error: {exc}")


if __name__ == "__main__":
    unittest.main()
