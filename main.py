"""
Orvo - Central Application Orchestrator.
Unites AudioRecorder, HotkeyManager, TranscriberManager, SafeTextInjector,
HudOverlay, TrayApp, and HistoryManager into a resilient, production-grade system.
"""

import concurrent.futures
from enum import Enum
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import sys
import threading
import time
from typing import Optional

# Guard against None stdout/stderr when running as windowless process (e.g. pythonw.exe)
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# Ensure project root is in sys.path
_PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.config import get_config, ConfigManager, AppConfig
from src.audio_recorder import AudioRecorder
from src.hotkey_manager import HotkeyManager
from src.transcriber import TranscriberManager
from src.text_injector import SafeTextInjector
from src.hud_overlay import HudOverlay
from src.tray_app import TrayApp
from src.history_dialog import HistoryManager, HistoryDialog


# =============================================================================
# Logging Setup
# =============================================================================

def setup_logging() -> logging.Logger:
    """Configures both console and rotating file logging."""
    logs_dir = os.path.join(_PROJECT_ROOT, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_file = os.path.join(logs_dir, "orvo.log")

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File Handler (5 MB per file, 3 backups)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Root / App Logger
    logger = logging.getLogger("Orvo")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.addHandler(file_handler)

    # Console Handler (only if stdout is connected and non-null)
    try:
        if sys.stdout is not None and hasattr(sys.stdout, "write"):
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
    except Exception:
        pass

    # Reduce noisy external libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)

    return logger


logger = setup_logging()


# =============================================================================
# Application States
# =============================================================================

class AppState(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    INJECTING = "injecting"


# =============================================================================
# Central Orchestrator
# =============================================================================

class OrvoApp:
    """
    Central application engine managing state transitions, audio capture,
    Whisper inference, paste injection, and UI/HUD coordination.
    """

    def __init__(self, headless: bool = False):
        self.headless = headless
        self._state = AppState.IDLE
        self._state_lock = threading.RLock()
        self._stop_event = threading.Event()

        # Configuration
        self.config_manager = ConfigManager()
        self.config = self.config_manager.get()

        logger.info("Initializing Orvo components...")

        # History Manager
        self.history_manager = HistoryManager()

        # Audio Recorder
        self.audio_recorder = AudioRecorder(config=self.config.audio)

        # Transcriber Manager (Local / Cloud)
        self.transcriber = TranscriberManager(config=self.config)

        # Safe Text Injector
        self.text_injector = SafeTextInjector(config=self.config)

        # Gemini Floating HUD Overlay
        self.hud_overlay: Optional[HudOverlay] = None
        if not self.headless:
            self.hud_overlay = HudOverlay(position_mode=self.config.ui.hud_position)
            self.hud_overlay.set_enabled(self.config.ui.show_hud)
            self.hud_overlay.start()

        # System Tray App
        self.tray_app: Optional[TrayApp] = None
        if not self.headless:
            self.tray_app = TrayApp(
                config=self.config,
                on_mode_change=self._on_tray_mode_change,
                on_model_change=self._on_tray_model_change,
                on_device_change=self._on_tray_device_change,
                on_sound_toggle=self._on_tray_sound_toggle,
                on_hud_toggle=self._on_tray_hud_toggle,
                on_history_clicked=self._on_tray_history_clicked,
                on_exit=self.stop,
            )

        # Global Hotkey Manager
        self.hotkey_manager = HotkeyManager(
            config=self.config.hotkey,
            on_start=self._on_hotkey_start,
            on_stop=self._on_hotkey_stop,
        )

        # Worker thread pool for background speech-to-text processing
        self._worker_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="TranscriptionWorker"
        )

        # VU meter streaming thread
        self._vu_stop_event = threading.Event()
        self._vu_thread: Optional[threading.Thread] = None

        # Hot-reloading watcher thread
        self._watcher_thread: Optional[threading.Thread] = None

    # -------------------------------------------------------------------------
    # State Machine Transitions
    # -------------------------------------------------------------------------

    @property
    def state(self) -> AppState:
        with self._state_lock:
            return self._state

    def _set_state(self, new_state: AppState) -> bool:
        with self._state_lock:
            if self._state == new_state:
                return False
            old_state = self._state
            self._state = new_state
            logger.info("State transition: %s -> %s", old_state.value.upper(), new_state.value.upper())
            return True

    # -------------------------------------------------------------------------
    # Hotkey Event Handlers
    # -------------------------------------------------------------------------

    def _on_hotkey_start(self) -> None:
        """Invoked when hotkey is triggered to start speech recording."""
        with self._state_lock:
            if self._state != AppState.IDLE:
                logger.debug("Ignoring hotkey start: currently in %s", self._state.value)
                return

            if not self._set_state(AppState.RECORDING):
                return

        # Update UI: Tray & HUD
        if self.tray_app:
            self.tray_app.update_state("recording")

        if self.hud_overlay:
            self.hud_overlay.show_recording(level=0.0)

        # Start capturing audio
        success = self.audio_recorder.start_recording()
        if not success:
            logger.error("AudioRecorder failed to start stream.")
            self._abort_recording()
            return

        # Start live VU meter feedback stream
        self._start_vu_meter_streaming()

    def _on_hotkey_stop(self) -> None:
        """Invoked when hotkey is released or toggled to finish speech capture."""
        with self._state_lock:
            if self._state != AppState.RECORDING:
                logger.debug("Ignoring hotkey stop: not in RECORDING state (in %s)", self._state.value)
                return

            self._set_state(AppState.TRANSCRIBING)

        # Stop live VU meter
        self._stop_vu_meter_streaming()

        # Synchronize hotkey manager internal state
        if hasattr(self, "hotkey_manager") and self.hotkey_manager:
            self.hotkey_manager.reset_state()

        # Update UI: Tray & HUD
        if self.tray_app:
            self.tray_app.update_state("transcribing")

        if self.hud_overlay:
            self.hud_overlay.show_transcribing("Transcribing...")

        # Stop audio recorder and retrieve captured PCM
        audio_data = self.audio_recorder.stop_recording()

        # Offload transcription and injection to background worker thread
        self._worker_executor.submit(self._process_transcription_and_inject, audio_data)

    def _abort_recording(self) -> None:
        """Aborts recording and returns to IDLE cleanly."""
        self._stop_vu_meter_streaming()
        if hasattr(self, "hotkey_manager") and self.hotkey_manager:
            self.hotkey_manager.reset_state()
        if self.audio_recorder.is_recording():
            self.audio_recorder.stop_recording()
        if self.hud_overlay:
            self.hud_overlay.hide()
        if self.tray_app:
            self.tray_app.update_state("idle")
        self._set_state(AppState.IDLE)

    # -------------------------------------------------------------------------
    # Audio VU Meter Streaming to Gemini HUD
    # -------------------------------------------------------------------------

    def _start_vu_meter_streaming(self) -> None:
        """Spawns lightweight daemon thread streaming audio volume to HUD visualizer."""
        self._vu_stop_event.clear()

        def _vu_loop():
            while not self._vu_stop_event.is_set():
                if self._state != AppState.RECORDING:
                    break
                level = self.audio_recorder.get_audio_level()
                if self.hud_overlay:
                    self.hud_overlay.update_audio_level(level)

                # Safeguard 1: Hard 120s duration cap across all modes
                duration = self.audio_recorder.get_recording_duration()
                if duration >= 120.0:
                    logger.warning("Recording reached maximum duration safety limit (120s). Auto-stopping.")
                    threading.Thread(target=self._on_hotkey_stop, daemon=True, name="SafetyStopThread").start()
                    break

                # Safeguard 2: Smart VAD auto-stop / auto-abort for toggle mode
                if getattr(self.hotkey_manager, "mode", "toggle") == "toggle":
                    has_speech = self.audio_recorder.has_speech_started()
                    silence_dur = self.audio_recorder.get_silence_duration()

                    # Speech finished: trailing silence after speech registered
                    if has_speech and silence_dur >= 2.5 and duration >= 1.0:
                        logger.info("Speech pause detected (%.1fs trailing silence in toggle mode). Auto-finishing dictation.", silence_dur)
                        threading.Thread(target=self._on_hotkey_stop, daemon=True, name="AutoStopThread").start()
                        break
                    # Zero speech registered after 8.0s of toggle mode: abort cleanly
                    elif not has_speech and duration >= 8.0:
                        logger.info("No speech detected after %.1fs in toggle mode. Auto-aborting recording.", duration)
                        threading.Thread(target=self._abort_recording, daemon=True, name="AutoAbortThread").start()
                        break

                time.sleep(0.033)  # ~30 Hz smooth refresh

        self._vu_thread = threading.Thread(target=_vu_loop, daemon=True, name="VuMeterStreamer")
        self._vu_thread.start()

    def _stop_vu_meter_streaming(self) -> None:
        """Stops the audio VU meter streaming thread."""
        self._vu_stop_event.set()
        if self._vu_thread and self._vu_thread.is_alive():
            if threading.current_thread() != self._vu_thread:
                self._vu_thread.join(timeout=0.2)
        self._vu_thread = None

    # -------------------------------------------------------------------------
    # Background Transcription & Paste Pipeline
    # -------------------------------------------------------------------------

    def _process_transcription_and_inject(self, audio_data) -> None:
        """
        Executes Whisper speech-to-text inference, displays success feedback,
        injects text atomically into the active window, and records history.
        Runs entirely in background worker thread.
        """
        try:
            if audio_data is None or len(audio_data) == 0:
                logger.info("Silence or sub-threshold audio captured. Suppressing injection.")
                self._finish_pipeline(None)
                return

            duration_s = float(len(audio_data)) / float(self.audio_recorder.sample_rate)
            logger.info("Transcribing %.2fs of captured audio...", duration_s)

            # Perform speech-to-text inference
            transcribed_text = self.transcriber.transcribe(audio_data)
            clean_text = (transcribed_text or "").strip()

            if not clean_text:
                logger.info("No speech detected or hallucination filtered.")
                self._finish_pipeline(None)
                return

            logger.info("Transcription result: '%s'", clean_text)

            with self._state_lock:
                self._set_state(AppState.INJECTING)

            # Show green success feedback on HUD
            if self.hud_overlay:
                preview = f"✓ {clean_text[:24]}..." if len(clean_text) > 24 else f"✓ {clean_text}"
                self.hud_overlay.show_success(preview, duration_ms=900)

            # Inject text atomically into active foreground window
            injected = self.text_injector.inject(clean_text)
            if not injected and self.config.text.fallback_to_typing:
                logger.info("Clipboard paste fallback: using direct simulated typing.")
                self.text_injector.type_text(clean_text)

            # Record dictation in history
            active_backend = self.config.model.backend
            active_model = (
                self.config.model.local_model
                if active_backend == "local"
                else self.config.model.groq_model
            )
            self.history_manager.add_entry(
                text=clean_text,
                duration_s=duration_s,
                backend=active_backend,
                model=active_model,
            )

            self._finish_pipeline(clean_text)

        except Exception as exc:
            logger.error("Unexpected error in transcription/injection pipeline: %s", exc, exc_info=True)
            self._finish_pipeline(None)

    def _finish_pipeline(self, result_text: Optional[str]) -> None:
        """Completes dictation lifecycle and transitions state back to IDLE."""
        if not result_text and self.hud_overlay:
            self.hud_overlay.hide()

        if self.tray_app:
            self.tray_app.update_state("idle")

        with self._state_lock:
            self._set_state(AppState.IDLE)

    # -------------------------------------------------------------------------
    # Tray Event Callbacks
    # -------------------------------------------------------------------------

    def _on_tray_mode_change(self, mode: str) -> None:
        logger.info("Dictation mode changed via tray to '%s'", mode)
        self.hotkey_manager.set_mode(mode)
        self.config.hotkey.mode = mode

    def _on_tray_model_change(self, model_name: str, backend: str) -> None:
        logger.info("Transcription model changed via tray to '%s' (%s)", model_name, backend)
        self.config.model.backend = backend
        if backend == "local":
            self.config.model.local_model = model_name
        elif backend == "groq":
            self.config.model.groq_model = model_name

        def _reload_worker():
            self.transcriber.reload_model(model_name=model_name)
            logger.info("Model reload completed successfully.")

        threading.Thread(target=_reload_worker, daemon=True, name="ModelReloadThread").start()

    def _on_tray_device_change(self, device_index: Optional[int]) -> None:
        logger.info("Microphone device index changed via tray to %s", device_index)
        self.config.audio.device_index = device_index
        self.audio_recorder.set_device(device_index)

    def _on_tray_sound_toggle(self, enabled: bool) -> None:
        logger.info("Sound effects toggled via tray: %s", enabled)
        self.config.audio.sound_effects = enabled
        self.audio_recorder.set_sound_effects(enabled)

    def _on_tray_hud_toggle(self, enabled: bool) -> None:
        logger.info("HUD overlay toggled via tray: %s", enabled)
        self.config.ui.show_hud = enabled
        if self.hud_overlay:
            self.hud_overlay.set_enabled(enabled)

    def _on_tray_history_clicked(self) -> None:
        logger.info("Opening dictation history dialog...")
        if self.hud_overlay:
            self.hud_overlay.open_history()
        else:
            def _launch():
                HistoryDialog.show()
            threading.Thread(target=_launch, daemon=True).start()

    # -------------------------------------------------------------------------
    # Hot-Reloading Watcher Loop
    # -------------------------------------------------------------------------

    def _start_config_watcher(self) -> None:
        """Monitors config.json for external modifications."""
        def _watch_loop():
            while not self._stop_event.is_set():
                try:
                    if self.config_manager.check_and_reload():
                        new_cfg = self.config_manager.get()
                        self.config = new_cfg
                        self.audio_recorder.update_config(new_cfg.audio)
                        self.hotkey_manager.update_config(new_cfg.hotkey)
                        self.transcriber.update_config(new_cfg)
                        if self.hud_overlay:
                            self.hud_overlay.set_enabled(new_cfg.ui.show_hud)
                            self.hud_overlay.set_position_mode(new_cfg.ui.hud_position)
                        logger.info("Applied reloaded configuration to active components.")
                except Exception as exc:
                    logger.debug("Config watcher exception: %s", exc)
                time.sleep(2.0)

        self._watcher_thread = threading.Thread(target=_watch_loop, daemon=True, name="ConfigWatcher")
        self._watcher_thread.start()

    # -------------------------------------------------------------------------
    # Lifecycle Control
    # -------------------------------------------------------------------------

    def start(self) -> None:
        """Starts all components and begins background listening."""
        logger.info("=========================================================")
        logger.info(" Orvo v1.0.0 - Voice Dictation Everywhere")
        logger.info(" Hotkey: %s | Mode: %s | Backend: %s (%s)",
                    self.config.hotkey.key, self.config.hotkey.mode,
                    self.config.model.backend, self.config.model.local_model)
        logger.info("=========================================================")

        # Start hotkey listener
        self.hotkey_manager.start()

        # Start background config watcher
        self._start_config_watcher()

        # Start tray icon in detached thread
        if self.tray_app:
            self.tray_app.run_detached()

        logger.info("Orvo is running in the background. Press %s to speak!",
                    self.config.hotkey.key)

        # Show brief startup HUD confirmation so the user visually sees Orvo is ready
        if self.hud_overlay and self.config.ui.show_hud:
            try:
                self.hud_overlay.show_success(duration_ms=1800)
            except Exception as exc:
                logger.debug("Startup HUD visual confirmation: %s", exc)

    def run(self) -> None:
        """Runs the application until interrupted."""
        self.start()
        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(timeout=0.5)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutdown signal received.")
        finally:
            self.stop()

    def stop(self) -> None:
        """Clean shutdown of all subsystems."""
        if self._stop_event.is_set():
            return
        logger.info("Shutting down Orvo...")
        self._stop_event.set()

        # Stop VU meter
        self._stop_vu_meter_streaming()

        # Stop hotkey listener
        try:
            self.hotkey_manager.stop()
        except Exception as e:
            logger.debug("Error stopping hotkey manager: %s", e)

        # Close audio stream
        try:
            self.audio_recorder.close()
        except Exception as e:
            logger.debug("Error closing audio recorder: %s", e)

        # Stop HUD overlay
        if self.hud_overlay:
            try:
                self.hud_overlay.stop()
            except Exception as e:
                logger.debug("Error stopping HUD: %s", e)

        # Stop Tray App
        if self.tray_app:
            try:
                self.tray_app.stop()
            except Exception as e:
                logger.debug("Error stopping TrayApp: %s", e)

        # Shutdown worker threads
        self._worker_executor.shutdown(wait=False)

        logger.info("Orvo shut down cleanly.")


# Backward compatibility alias
WhisperAnywhereApp = OrvoApp


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    try:
        from src.single_instance import SingleInstanceLock
    except ImportError:
        from single_instance import SingleInstanceLock

    lock = SingleInstanceLock()
    if not lock.acquire():
        logger.info("Existing Orvo instance detected. Exiting new process cleanly.")
        print("[Orvo] An instance of Orvo is already running in the background.")
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    0,
                    "Orvo is already running in the background.\n\n"
                    "• Press Alt + ` (Backtick) anywhere to dictate\n"
                    "• Check your system tray (near the taskbar clock) for settings",
                    "Orvo",
                    0x40 | 0x10000,
                )
            except Exception:
                pass
        sys.exit(0)

    app = OrvoApp()

    # Wire up OS signal handlers for graceful exit
    def _sig_handler(signum, frame):
        logger.info("Received signal %s, initiating clean exit...", signum)
        app.stop()
        lock.release()

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    app.run()


if __name__ == "__main__":
    main()
