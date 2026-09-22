"""
Unit tests for HudOverlay component.
Verifies minimalist Apple/ChatGPT-style aesthetic constants, square geometry,
bottom-right and cursor positioning, smooth pulse color interpolation, and state transitions.
"""

import unittest
from unittest.mock import patch, MagicMock
from src.hud_overlay import HudOverlay, interpolate_rgb, get_rounded_rect_points, BORDER_LOW_HEX, BORDER_HIGH_HEX


class TestHudOverlay(unittest.TestCase):
    def setUp(self):
        self.hud = HudOverlay(position_mode="bottom_right", style="square")

    def test_dimensions_and_styling(self):
        """Verify the overlay adheres to the 56x56 minimal style."""
        self.assertEqual(self.hud.width, 56)
        self.assertEqual(self.hud.height, 56)
        self.assertEqual(self.hud.CORNER_RADIUS, 15)
        self.assertEqual(self.hud.BG_COLOR, "#161618")
        self.assertEqual(self.hud.BG_ACCENT, "#242429")

    def test_bottom_right_positioning(self):
        """Verify default position calculation places overlay in bottom-right above taskbar."""
        with patch("win32api.GetSystemMetrics", side_effect=lambda idx: 1920 if idx == 0 else 1080):
            self.hud.position_mode = "bottom_right"
            x, y = self.hud._calculate_position()
            self.assertEqual(x, 1920 - self.hud.width - 28)
            self.assertEqual(y, 1080 - self.hud.height - 48)

    def test_near_cursor_positioning(self):
        """Verify position calculation offsets by +20, +26 when near_cursor is active."""
        with patch("win32api.GetSystemMetrics", side_effect=lambda idx: 1920 if idx == 0 else 1080):
            with patch("src.hud_overlay.get_cursor_pos", return_value=(500, 400)):
                self.hud.position_mode = "near_cursor"
                x, y = self.hud._calculate_position()
                self.assertEqual(x, 500 + 20)
                self.assertEqual(y, 400 + 26)

    def test_boundary_clamping(self):
        """Verify overlay clamps near the edge of the display."""
        with patch("win32api.GetSystemMetrics", side_effect=lambda idx: 1920 if idx == 0 else 1080):
            with patch("src.hud_overlay.get_cursor_pos", return_value=(1910, 1070)):
                self.hud.position_mode = "near_cursor"
                x, y = self.hud._calculate_position()
                self.assertLessEqual(x + self.hud.width, 1920 - 12)
                self.assertLessEqual(y + self.hud.height, 1080 - 12)
                self.assertGreaterEqual(x, 12)
                self.assertGreaterEqual(y, 12)

    def test_pulsing_border_color_interpolation(self):
        """Verify smooth pulse interpolation produces valid hex colors across factors."""
        for factor in (0.0, 0.25, 0.5, 0.75, 1.0):
            c = interpolate_rgb(BORDER_LOW_HEX, BORDER_HIGH_HEX, factor)
            self.assertTrue(c.startswith("#") and len(c) == 7)

    def test_rounded_rect_points_generation(self):
        """Verify rounded rect generator creates closed points outlining squircle."""
        pts = get_rounded_rect_points(56, 56, 15, n_arc=8, offset=2.0)
        self.assertGreaterEqual(len(pts), 24)
        for x, y in pts:
            self.assertGreaterEqual(x, 2.0)
            self.assertLessEqual(x, 54.0)
            self.assertGreaterEqual(y, 2.0)
            self.assertLessEqual(y, 54.0)

    def test_state_updates_queued(self):
        """Verify public API methods safely queue actions without raising exceptions."""
        self.hud.show_recording(level=0.5)
        self.assertEqual(self.hud._queue.qsize(), 1)

        self.hud.update_audio_level(0.8)
        self.hud.show_transcribing()
        self.hud.show_success()
        self.hud.hide()
        self.assertGreaterEqual(self.hud._queue.qsize(), 3)


if __name__ == "__main__":
    unittest.main()
