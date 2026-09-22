"""
Ultra-Smooth Apple/ChatGPT-Grade Minimalist Status Overlay for Orvo.

Features:
- Native Win32 32-bit ARGB UpdateLayeredWindow with true per-pixel subpixel alpha blending.
- 2x Retina supersampling with Lanczos downsampling: ZERO jagged edges, ZERO 1-bit colorkey halos.
- Runs at the display's native high refresh rate (e.g. 120Hz - 200Hz) with high-precision time pacing.
- ChatGPT/Apple minimal aesthetic:
  - Dark graphite matte squircle (#161618) with a subtle inset grey accent (#242429).
  - Light-greyish border smoothly breathing in a sinusoidal pulse between #3f3f46 and #a1a1aa.
  - Light-greyish icons:
    - Listening: 3 vertical capsule lines pulsing with fluid idle waves and live voice reactivity.
    - Processing: 3 circular dots bouncing up and down one by one like a generic 3-dots loader.
    - Completion: The 3 dots smoothly glide inward and merge into a single big light dot only.
- Floats in bottom-right corner above taskbar.
- Click-through, non-activating: WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TRANSPARENT.
"""

import ctypes
from ctypes import wintypes
import math
import os
import queue
import sys
import threading
import time
from typing import Optional, Tuple, List
import numpy as np
from PIL import Image, ImageDraw

try:
    import win32gui
    import win32con
    import win32api
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    from src.config import get_config
except ImportError:
    from config import get_config


# =============================================================================
# Win32 Structures & Constants for Per-Pixel Alpha Layered Window
# =============================================================================

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
ULW_ALPHA = 0x02


def get_cursor_pos() -> Optional[Tuple[int, int]]:
    """Safe cursor position retrieval using ctypes or win32gui."""
    try:
        pt = POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            if pt.x != 0 or pt.y != 0:
                return int(pt.x), int(pt.y)
    except Exception:
        pass
    if HAS_WIN32:
        try:
            return win32gui.GetCursorPos()
        except Exception:
            pass
    return None


def get_display_refresh_rate() -> int:
    """Queries display hardware refresh rate (e.g. 60Hz, 120Hz, 144Hz, 200Hz)."""
    if HAS_WIN32:
        try:
            devmode = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)
            freq = int(devmode.DisplayFrequency)
            if 30 <= freq <= 360:
                return freq
        except Exception:
            pass
    return 120


# =============================================================================
# Color Helpers
# =============================================================================

BG_OUTER_HEX = "#161618"
BG_INNER_HEX = "#242429"
BORDER_LOW_HEX = "#3f3f46"
BORDER_HIGH_HEX = "#a1a1aa"
BORDER_SPEECH_HEX = "#e4e4e7"
BORDER_SUCCESS_HEX = "#e5e7eb"
ICON_BASE_HEX = "#d1d5db"
ICON_ACTIVE_HEX = "#f4f4f5"

# RGBA Tuples (0..255)
BG_OUTER_RGBA = (22, 22, 24, 248)
BG_INNER_RGBA = (36, 36, 41, 248)
BORDER_LOW_RGBA = (63, 63, 70, 255)
BORDER_HIGH_RGBA = (161, 161, 170, 255)
BORDER_SPEECH_RGBA = (228, 228, 231, 255)
BORDER_SUCCESS_RGBA = (229, 231, 235, 255)
ICON_BASE_RGBA = (209, 213, 219, 255)
ICON_ACTIVE_RGBA = (244, 244, 245, 255)


def interpolate_rgb(c1: str, c2: str, factor: float) -> str:
    """Interpolates between two hex colors."""
    rgb1 = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
    rgb2 = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
    f = max(0.0, min(1.0, factor))
    r = int(rgb1[0] + (rgb2[0] - rgb1[0]) * f)
    g = int(rgb1[1] + (rgb2[1] - rgb1[1]) * f)
    b = int(rgb1[2] + (rgb2[2] - rgb1[2]) * f)
    return f"#{r:02x}{g:02x}{b:02x}"


def interpolate_tuple(c1: Tuple[int, int, int, int], c2: Tuple[int, int, int, int], factor: float) -> Tuple[int, int, int, int]:
    """Interpolates between two RGBA color tuples."""
    f = max(0.0, min(1.0, factor))
    return (
        int(c1[0] + (c2[0] - c1[0]) * f),
        int(c1[1] + (c2[1] - c1[1]) * f),
        int(c1[2] + (c2[2] - c1[2]) * f),
        int(c1[3] + (c2[3] - c1[3]) * f),
    )


def get_rounded_rect_points(w: float, h: float, r: float, n_arc: int = 8, offset: float = 2.0) -> List[Tuple[float, float]]:
    """Generates continuous ordered points outlining a squircle (used for geometry testing)."""
    x1, y1 = offset, offset
    x2, y2 = w - offset, h - offset
    pts: List[Tuple[float, float]] = []

    pts.append((x1 + r, y1))
    pts.append((x2 - r, y1))

    for i in range(1, n_arc):
        a = -math.pi / 2 + (math.pi / 2) * (i / n_arc)
        pts.append((x2 - r + r * math.cos(a), y1 + r + r * math.sin(a)))

    pts.append((x2, y1 + r))
    pts.append((x2, y2 - r))

    for i in range(1, n_arc):
        a = (math.pi / 2) * (i / n_arc)
        pts.append((x2 - r + r * math.cos(a), y2 - r + r * math.sin(a)))

    pts.append((x2 - r, y2))
    pts.append((x1 + r, y2))

    for i in range(1, n_arc):
        a = math.pi / 2 + (math.pi / 2) * (i / n_arc)
        pts.append((x1 + r + r * math.cos(a), y2 - r + r * math.sin(a)))

    pts.append((x1, y2 - r))
    pts.append((x1, y1 + r))

    for i in range(1, n_arc):
        a = math.pi + (math.pi / 2) * (i / n_arc)
        pts.append((x1 + r + r * math.cos(a), y1 + r + r * math.sin(a)))

    return pts


# =============================================================================
# High-Refresh-Rate Per-Pixel Alpha Layered Window Overlay
# =============================================================================

class HudOverlay:
    """
    Apple/ChatGPT-grade desktop status overlay for Orvo.
    Composited directly via Windows DWM UpdateLayeredWindow with full 32-bit ARGB
    subpixel antialiasing and native high-refresh rate fluid animations.
    """

    # Dimensions
    SQUARE_SIZE = 56
    CORNER_RADIUS = 15
    BORDER_WIDTH = 1.8

    # Legacy Pill Dimensions
    PILL_WIDTH = 220
    PILL_HEIGHT = 48
    PILL_CORNER_RADIUS = 18

    # Constants
    BG_COLOR = BG_OUTER_HEX
    BG_ACCENT = BG_INNER_HEX
    BORDER_LOW = BORDER_LOW_HEX
    BORDER_HIGH = BORDER_HIGH_HEX
    SCALE = 2  # 2x Retina supersampling for subpixel edge antialiasing

    def __init__(self, position_mode: str = "bottom_right", style: str = "square"):
        self.position_mode = position_mode  # "bottom_right", "near_cursor", "bottom_center", "top_center"
        self.hud_style = style              # "square", "pill"
        self._enabled = True

        try:
            cfg = get_config()
            self._enabled = cfg.ui.show_hud
            pos = cfg.ui.hud_position
            if pos:
                self.position_mode = pos
            st = getattr(cfg.ui, "hud_style", "square")
            if st:
                self.hud_style = st
        except Exception:
            pass

        self.width = self.SQUARE_SIZE if self.hud_style == "square" else self.PILL_WIDTH
        self.height = self.SQUARE_SIZE if self.hud_style == "square" else self.PILL_HEIGHT

        # Threading and synchronization
        self._queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._is_running = False
        self._ready_event = threading.Event()

        # State tracking: "idle", "recording", "transcribing", "merging", "success"
        self.current_state = "idle"
        self.audio_level = 0.0
        self._anim_time = 0.0
        self._merge_start_time = 0.0
        self._success_start_time = 0.0
        self._auto_hide_deadline = 0.0
        self._last_cursor_pos = (500, 500)
        self._is_visible = False

        # Win32 Handles
        self.hwnd = None
        self.root = None  # Compatibility stub for test mocks
        self._hdc_screen = None
        self._hdc_mem = None
        self._h_bitmap = None
        self._h_old_bitmap = None
        self._p_bits = None

        # Display refresh rate pacing
        self.fps = get_display_refresh_rate()
        self.frame_interval = 1.0 / float(self.fps)

    def start(self) -> None:
        """Starts the overlay on a dedicated rendering thread."""
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._run_render_loop, daemon=True, name="HudOverlayThread")
        self._thread.start()
        self._ready_event.wait(timeout=3.0)

    def run(self) -> None:
        """Runs on the current thread."""
        self._is_running = True
        self._run_render_loop()

    def _run_render_loop(self) -> None:
        """High-refresh rate render loop driving UpdateLayeredWindow."""
        if not HAS_WIN32:
            self._ready_event.set()
            while self._is_running:
                while not self._queue.empty():
                    try:
                        task = self._queue.get_nowait()
                        task()
                    except Exception:
                        pass
                time.sleep(0.016)
            return

        # 1. Register Win32 Window Class
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = win32gui.DefWindowProc
        wc.lpszClassName = "OrvoSmoothHUDClass"
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        try:
            win32gui.RegisterClass(wc)
        except Exception:
            pass

        # 2. Create Layered, Non-activating, Click-through Popup Window
        ex_style = (
            win32con.WS_EX_LAYERED
            | win32con.WS_EX_TRANSPARENT
            | win32con.WS_EX_TOPMOST
            | win32con.WS_EX_TOOLWINDOW
            | 0x08000000  # WS_EX_NOACTIVATE
        )
        self.hwnd = win32gui.CreateWindowEx(
            ex_style,
            "OrvoSmoothHUDClass",
            "Orvo HUD",
            win32con.WS_POPUP,
            -2000, -2000, self.width, self.height,
            0, 0, wc.hInstance, None
        )

        # 3. Setup persistent GDI 32-bit DIB surface
        self._hdc_screen = win32gui.GetDC(0)
        self._hdc_mem = win32gui.CreateCompatibleDC(self._hdc_screen)

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = self.width
        bmi.bmiHeader.biHeight = -self.height  # Top-down DIB
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB

        self._p_bits = ctypes.c_void_p()
        self._h_bitmap = ctypes.windll.gdi32.CreateDIBSection(
            self._hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(self._p_bits), None, 0
        )
        self._h_old_bitmap = win32gui.SelectObject(self._hdc_mem, self._h_bitmap)

        self._ready_event.set()

        last_time = time.perf_counter()

        # 4. Main high-refresh-rate render & message loop
        while self._is_running:
            now = time.perf_counter()
            dt = now - last_time
            last_time = now
            self._anim_time += dt

            # Process Win32 messages
            while True:
                has_msg, msg = win32gui.PeekMessage(self.hwnd, 0, 0, win32con.PM_REMOVE)
                if not has_msg:
                    break
                win32gui.TranslateMessage(msg)
                win32gui.DispatchMessage(msg)

            # Process queued thread actions
            while not self._queue.empty():
                try:
                    task = self._queue.get_nowait()
                    task()
                except Exception:
                    pass

            if not self._is_running:
                break

            # Handle auto-hide timer
            if self._auto_hide_deadline > 0.0 and now >= self._auto_hide_deadline:
                self._auto_hide_deadline = 0.0
                self.current_state = "idle"
                self._hide_window()

            # Render frame if active
            if self.current_state != "idle" and self._enabled:
                self._render_and_present()
                elapsed = time.perf_counter() - now
                sleep_time = max(0.0005, self.frame_interval - elapsed)
                time.sleep(sleep_time)
            else:
                time.sleep(0.012)

        # Cleanup GDI resources
        try:
            if self._hdc_mem and self._h_old_bitmap:
                win32gui.SelectObject(self._hdc_mem, self._h_old_bitmap)
            if self._h_bitmap:
                win32gui.DeleteObject(self._h_bitmap)
            if self._hdc_mem:
                win32gui.DeleteDC(self._hdc_mem)
            if self._hdc_screen:
                win32gui.ReleaseDC(0, self._hdc_screen)
            if self.hwnd:
                win32gui.DestroyWindow(self.hwnd)
        except Exception:
            pass

    def _render_and_present(self) -> None:
        """Draws supersampled frame and updates layered window with 32-bit alpha."""
        if not HAS_WIN32 or not self.hwnd or not self._p_bits:
            return

        w, h = self.width, self.height
        W, H = w * self.SCALE, h * self.SCALE
        CX, CY = W / 2.0, H / 2.0
        now = self._anim_time

        # 1. Pillow 2x Supersampled Canvas
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 2. Smooth Sinusoidal Breathing Border Color Calculation
        level = max(0.0, min(1.0, self.audio_level))

        if self.current_state == "recording":
            pulse = 0.5 + 0.5 * math.sin(now * 3.4)
            base_col = interpolate_tuple(BORDER_LOW_RGBA, BORDER_HIGH_RGBA, pulse)
            if level > 0.08:
                sp_f = min(1.0, (level - 0.08) * 2.2)
                border_col = interpolate_tuple(base_col, BORDER_SPEECH_RGBA, sp_f)
                border_w = int(3.6 + 1.2 * sp_f)
            else:
                border_col = base_col
                border_w = int(3.4 + 0.6 * pulse)

        elif self.current_state == "transcribing":
            pulse = 0.5 + 0.5 * math.sin(now * 5.2)
            border_col = interpolate_tuple(BORDER_LOW_RGBA, BORDER_HIGH_RGBA, pulse)
            border_w = int(3.4 + 0.6 * pulse)

        elif self.current_state in ("merging", "success"):
            progress = min(1.0, (time.perf_counter() - self._merge_start_time) / 0.35) if self.current_state == "merging" else 1.0
            border_col = interpolate_tuple(BORDER_HIGH_RGBA, BORDER_SUCCESS_RGBA, progress)
            border_w = int(3.6)

        else:
            border_col = BORDER_LOW_RGBA
            border_w = int(3.6)

        # 3. Draw Outer Dark Graphite Squircle
        outer_pad = 4
        draw.rounded_rectangle(
            [outer_pad, outer_pad, W - outer_pad, H - outer_pad],
            radius=30,
            fill=BG_OUTER_RGBA,
            outline=border_col,
            width=border_w,
        )

        # 4. Draw Inset Grey Accent
        inner_pad = 12
        draw.rounded_rectangle(
            [inner_pad, inner_pad, W - inner_pad, H - inner_pad],
            radius=22,
            fill=BG_INNER_RGBA,
            outline=None,
        )

        # 5. Draw State Icons
        if self.current_state == "recording":
            # 3 vertical capsule lines (wave microphone)
            bar_xs = [CX - 17, CX, CX + 17]
            bar_w = 6.4

            # Smooth wave heights
            h0 = 16.0 + 5.0 * math.sin(now * 3.6) + level * 24.0
            h1 = 28.0 + 7.0 * math.sin(now * 3.6 + 1.2) + level * 36.0
            h2 = 16.0 + 5.0 * math.sin(now * 3.6 + 2.4) + level * 24.0

            heights = [max(8.0, min(50.0, h0)), max(10.0, min(58.0, h1)), max(8.0, min(50.0, h2))]
            icon_col = interpolate_tuple(ICON_BASE_RGBA, ICON_ACTIVE_RGBA, min(1.0, level * 2.2))

            for i in range(3):
                bx = bar_xs[i]
                bh = heights[i]
                draw.rounded_rectangle(
                    [bx - bar_w / 2.0, CY - bh / 2.0, bx + bar_w / 2.0, CY + bh / 2.0],
                    radius=bar_w / 2.0,
                    fill=icon_col,
                )

        elif self.current_state == "transcribing":
            # 3 generic circular loading dots bouncing one by one
            dot_xs = [CX - 17, CX, CX + 17]
            r = 6.4
            y_base = CY + 2.5

            for i in range(3):
                phase = now * 5.8 - i * 0.82
                s = math.sin(phase)
                dy = -11.0 * (s ** 1.4) if s > 0 else 0.0
                y = y_base + dy
                x = dot_xs[i]
                draw.ellipse([x - r, y - r, x + r, y + r], fill=ICON_BASE_RGBA)

        elif self.current_state == "merging":
            # Smooth inward glide and swell into single big dot
            t_raw = min(1.0, (time.perf_counter() - self._merge_start_time) / 0.35)
            t = t_raw * t_raw * (3.0 - 2.0 * t_raw)  # Smoothstep

            x0 = (CX - 17) * (1.0 - t) + CX * t
            x1 = CX
            x2 = (CX + 17) * (1.0 - t) + CX * t

            r_outer = max(0.01, 6.4 * (1.0 - t))
            r_center = 6.4 * (1.0 - t) + 15.0 * t
            icon_col = interpolate_tuple(ICON_BASE_RGBA, ICON_ACTIVE_RGBA, t)

            draw.ellipse([x0 - r_outer, CY - r_outer, x0 + r_outer, CY + r_outer], fill=icon_col)
            draw.ellipse([x1 - r_center, CY - r_center, x1 + r_center, CY + r_center], fill=icon_col)
            draw.ellipse([x2 - r_outer, CY - r_outer, x2 + r_outer, CY + r_outer], fill=icon_col)

            if t_raw >= 1.0:
                self.current_state = "success"
                self._success_start_time = time.perf_counter()

        elif self.current_state == "success":
            # Single big dot only with subtle breathing pulse
            pulse = math.sin((time.perf_counter() - self._success_start_time) * 4.2)
            r = 15.0 + 1.2 * pulse
            draw.ellipse([CX - r, CY - r, CX + r, CY + r], fill=ICON_ACTIVE_RGBA)

        # 6. Downsample 2x to 1x with high-quality Lanczos antialiasing
        img_down = img.resize((w, h), Image.Resampling.LANCZOS)

        # 7. Convert to Pre-multiplied 32-bit BGRA buffer for Windows DWM
        arr = np.array(img_down, dtype=np.uint8)
        r = arr[:, :, 0].astype(np.uint16)
        g = arr[:, :, 1].astype(np.uint16)
        b = arr[:, :, 2].astype(np.uint16)
        a = arr[:, :, 3].astype(np.uint16)

        bgra = np.empty_like(arr)
        bgra[:, :, 0] = (b * a // 255).astype(np.uint8)
        bgra[:, :, 1] = (g * a // 255).astype(np.uint8)
        bgra[:, :, 2] = (r * a // 255).astype(np.uint8)
        bgra[:, :, 3] = a.astype(np.uint8)

        # Copy pixels into DIB Section memory
        ctypes.memmove(self._p_bits, bgra.tobytes(), w * h * 4)

        # 8. Calculate Position and Call UpdateLayeredWindow
        x, y = self._calculate_position()
        pt_dest = wintypes.POINT(x, y)
        sz = wintypes.SIZE(w, h)
        pt_src = wintypes.POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

        ctypes.windll.user32.UpdateLayeredWindow(
            self.hwnd,
            self._hdc_screen,
            ctypes.byref(pt_dest),
            ctypes.byref(sz),
            self._hdc_mem,
            ctypes.byref(pt_src),
            0,
            ctypes.byref(blend),
            ULW_ALPHA
        )

        if not self._is_visible:
            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
            self._is_visible = True

    def _calculate_position(self) -> Tuple[int, int]:
        """Calculates window screen coordinates with bottom-right default."""
        if HAS_WIN32:
            try:
                screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
                screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            except Exception:
                screen_w, screen_h = 1920, 1080
        elif self.root:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
        else:
            screen_w, screen_h = 1920, 1080

        if self.position_mode == "bottom_right":
            x = screen_w - self.width - 28
            y = screen_h - self.height - 48
            x = max(12, min(x, screen_w - self.width - 12))
            y = max(12, min(y, screen_h - self.height - 12))
            return x, y

        elif self.position_mode == "near_cursor":
            cur = get_cursor_pos()
            if cur:
                self._last_cursor_pos = cur
            cx, cy = self._last_cursor_pos
            x = cx + 20
            y = cy + 26
            if x + self.width > screen_w - 12:
                x = cx - self.width - 12
            if y + self.height > screen_h - 12:
                y = cy - self.height - 12
            x = max(12, min(x, screen_w - self.width - 12))
            y = max(12, min(y, screen_h - self.height - 12))
            return x, y

        elif self.position_mode == "bottom_center":
            x = (screen_w - self.width) // 2
            y = screen_h - self.height - 65
            return x, y

        elif self.position_mode == "top_center":
            x = (screen_w - self.width) // 2
            y = 45
            return x, y

        else:
            x = screen_w - self.width - 28
            y = screen_h - self.height - 48
            return x, y

    def _hide_window(self) -> None:
        """Hides the overlay cleanly."""
        if HAS_WIN32 and self.hwnd:
            win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
        self._is_visible = False

    # =========================================================================
    # Public Thread-Safe API
    # =========================================================================

    def show_recording(self, level: Optional[float] = None) -> None:
        """Displays the recording HUD with 3 wave microphone lines."""
        if not self._enabled:
            return

        def _action():
            self._auto_hide_deadline = 0.0
            self.current_state = "recording"
            if level is not None:
                self.audio_level = float(level)

        self._queue.put(_action)

    def update_audio_level(self, level: float) -> None:
        """Updates the microphone audio level for live visual feedback."""
        if not self._enabled or self.current_state != "recording":
            return

        def _action():
            self.audio_level = float(level)

        self._queue.put(_action)

    def show_transcribing(self, text: Optional[str] = None) -> None:
        """Displays the generic 3-dots wave loader."""
        if not self._enabled:
            return

        def _action():
            self._auto_hide_deadline = 0.0
            self.current_state = "transcribing"

        self._queue.put(_action)

    def show_success(self, text: Optional[str] = None, duration_ms: int = 1100) -> None:
        """Smoothly merges 3 dots into a single big dot before auto-fading."""
        if not self._enabled:
            return

        def _action():
            self.current_state = "merging"
            self._merge_start_time = time.perf_counter()
            self._auto_hide_deadline = time.perf_counter() + (duration_ms / 1000.0)

        self._queue.put(_action)

    def hide(self) -> None:
        """Hides the overlay immediately."""
        def _action():
            self._auto_hide_deadline = 0.0
            self.current_state = "idle"
            self._hide_window()

        self._queue.put(_action)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not self._enabled:
            self.hide()

    def set_position_mode(self, mode: str) -> None:
        def _action():
            self.position_mode = mode

        self._queue.put(_action)

    def set_hud_style(self, style: str) -> None:
        def _action():
            self.hud_style = "pill" if style == "pill" else "square"
            self.width = self.SQUARE_SIZE if self.hud_style == "square" else self.PILL_WIDTH
            self.height = self.SQUARE_SIZE if self.hud_style == "square" else self.PILL_HEIGHT

        self._queue.put(_action)

    def open_history(self, history_manager=None) -> None:
        """Opens the History dialog safely in a dedicated UI thread."""
        def _run_history():
            try:
                from src.history_dialog import HistoryDialog
                dlg = HistoryDialog(parent=None, history_manager=history_manager)
                dlg.show()
            except Exception as exc:
                print(f"[HudOverlay] Error opening history dialog: {exc}")

        t = threading.Thread(target=_run_history, daemon=True, name="HistoryDialogThread")
        t.start()

    def stop(self) -> None:
        """Stops the HUD overlay cleanly."""
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
