"""
Orvo - End-to-End Pipeline Integration Tests.
Executes complete headless integration:
Hotkey Start -> Audio Capture -> Hotkey Stop -> Whisper Inference ->
Text Injection -> History Persistence -> IDLE transition.
"""

import time
import unittest
import numpy as np

from main import OrvoApp, WhisperAnywhereApp, AppState
from tests.test_whisper_inference import generate_speech_audio


class TestIntegrationPipeline(unittest.TestCase):
    """End-to-end integration test of the Orvo application engine."""

    @classmethod
    def setUpClass(cls):
        # Initialize app in headless mode (no Tkinter window or system tray required)
        cls.app = OrvoApp(headless=True)
        # Generate synthetic speech audio for end-to-end testing
        cls.test_audio = generate_speech_audio("hello world")

    @classmethod
    def tearDownClass(cls):
        cls.app.stop()

    def test_01_initial_state(self):
        """Verify initial state is IDLE."""
        self.assertEqual(self.app.state, AppState.IDLE)
        self.assertFalse(self.app.audio_recorder.is_recording())

    def test_02_full_pipeline_cycle(self):
        """Simulate hotkey press, audio feed, stop, transcription, injection, and history record."""
        # Initial entries count
        initial_entries = len(self.app.history_manager.get_entries())

        # 1. Trigger hotkey start
        self.app._on_hotkey_start()
        self.assertEqual(self.app.state, AppState.RECORDING)
        self.assertTrue(self.app.audio_recorder.is_recording())

        # 2. Inject synthetic speech data into the recorder buffer
        with self.app.audio_recorder._lock:
            self.app.audio_recorder._chunks.append(self.test_audio)

        # 3. Trigger hotkey stop
        self.app._on_hotkey_stop()
        # Immediately transitions to TRANSCRIBING
        self.assertIn(self.app.state, (AppState.TRANSCRIBING, AppState.INJECTING, AppState.IDLE))

        # 4. Wait for background worker thread to complete pipeline (up to 6.0 seconds)
        start_wait = time.time()
        while self.app.state != AppState.IDLE and (time.time() - start_wait) < 6.0:
            time.sleep(0.05)

        self.assertEqual(self.app.state, AppState.IDLE, "Pipeline failed to return to IDLE state.")

        # 5. Verify transcription recorded to HistoryManager
        entries = self.app.history_manager.get_entries()
        self.assertGreater(len(entries), initial_entries, "Expected a new history entry.")

        latest_entry = entries[0]
        print(f"\n[Integration Pipeline] Logged Entry: '{latest_entry.text}' (duration: {latest_entry.duration_s}s)")

        clean_text = latest_entry.text.lower()
        self.assertTrue(
            "hello" in clean_text or "world" in clean_text,
            f"Expected 'hello' or 'world' in transcribed text, got: '{latest_entry.text}'"
        )
        self.assertGreater(latest_entry.duration_s, 0.0)
        self.assertEqual(latest_entry.backend, "local")

    def test_03_silence_pipeline_suppression(self):
        """Verify that pure silence audio does not inject or pollute history."""
        initial_entries = len(self.app.history_manager.get_entries())

        self.app._on_hotkey_start()
        self.assertEqual(self.app.state, AppState.RECORDING)

        # Inject pure silence (zeros)
        with self.app.audio_recorder._lock:
            self.app.audio_recorder._chunks = [np.zeros(16000 * 2, dtype=np.float32)]

        self.app._on_hotkey_stop()

        # Wait for worker to finish
        start_wait = time.time()
        while self.app.state != AppState.IDLE and (time.time() - start_wait) < 4.0:
            time.sleep(0.05)

        self.assertEqual(self.app.state, AppState.IDLE)
        # History count should not increase on silence
        current_entries = len(self.app.history_manager.get_entries())
        self.assertEqual(current_entries, initial_entries, "Silence should not generate history entries.")

    def test_04_rapid_trigger_resilience(self):
        """Verify rapid repeated start triggers are safely debounced/ignored."""
        self.app._on_hotkey_start()
        self.assertEqual(self.app.state, AppState.RECORDING)

        # Immediate secondary start calls should be safely ignored
        self.app._on_hotkey_start()
        self.app._on_hotkey_start()
        self.assertEqual(self.app.state, AppState.RECORDING)

        # Abort cleanly
        self.app._abort_recording()
        self.assertEqual(self.app.state, AppState.IDLE)

    def test_05_toggle_mode_persists_during_silence(self):
        """Verify toggle mode stays active during pauses and does not prematurely auto-stop."""
        self.app._on_hotkey_start()
        self.assertEqual(self.app.state, AppState.RECORDING)

        # Allow VU meter streamer to run for 0.3s with zero speech
        time.sleep(0.3)

        # App must remain in RECORDING state (no premature auto-abort or auto-stop)
        self.assertEqual(self.app.state, AppState.RECORDING)

        # Cleanly stop via user hotkey stop
        self.app._on_hotkey_stop()
        start_wait = time.time()
        while self.app.state != AppState.IDLE and (time.time() - start_wait) < 4.0:
            time.sleep(0.05)
        self.assertEqual(self.app.state, AppState.IDLE)


if __name__ == "__main__":
    unittest.main()
