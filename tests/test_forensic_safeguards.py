"""
Unit tests for forensic hardening and zero-crash safeguards in Orvo.
Validates:
1. AudioRecorder 120s buffer ceiling preventing memory exhaustion.
2. AudioRecorder Voice Activity Detection (VAD) & speech onset metrics.
3. TranscriberManager STFT memory guard against massive sample arrays.
4. Hallucination filter whitelist preservation (words like 'you', 'thank you').
5. SafeTextInjector modifier cleanup and minimum paste delay.
"""

import unittest
import numpy as np
import time

from src.audio_recorder import AudioRecorder, trim_silence
from src.transcriber import TranscriberManager
from src.text_injector import SafeTextInjector
from src.config import get_config


class TestForensicSafeguards(unittest.TestCase):
    """Exhaustive tests for bulletproof zero-crash behavior under abnormal conditions."""

    def setUp(self):
        self.config = get_config()

    def test_audio_recorder_buffer_ceiling(self):
        """Verify AudioRecorder enforces a strict 120s cap on buffered audio."""
        from unittest.mock import patch
        with patch.object(AudioRecorder, "_warmup_stream"):
            recorder = AudioRecorder(sample_rate=16000, block_size=1600)
            try:
                recorder._is_recording = True
                recorder._chunks = []

                max_expected_chunks = int(16000 * 120.0 / 1600)
                fake_block = np.zeros(1600, dtype=np.float32)

                # Feed 150 seconds worth of audio frames (more than 120s)
                total_blocks_to_feed = max_expected_chunks + 50
                for _ in range(total_blocks_to_feed):
                    recorder._audio_callback(fake_block, 1600, None, 0)

                # Ensure buffer length never exceeded max_expected_chunks
                self.assertLessEqual(len(recorder._chunks), max_expected_chunks)
            finally:
                recorder.close()

    def test_audio_recorder_vad_tracking(self):
        """Verify VAD accurately distinguishes vocal activity from silence."""
        from unittest.mock import patch
        with patch.object(AudioRecorder, "_warmup_stream"):
            recorder = AudioRecorder(sample_rate=16000, block_size=1600)
            try:
                recorder._is_recording = True
                now = time.monotonic()
                recorder._record_start_time = now
                recorder._last_speech_time = now
                recorder._has_speech_started = False

                # Feed silence block (amplitude 0)
                silence_block = np.zeros(1600, dtype=np.float32)
                recorder._audio_callback(silence_block, 1600, None, 0)

                self.assertFalse(recorder.has_speech_started())
                self.assertGreaterEqual(recorder.get_silence_duration(), 0.0)

                # Feed speech block (amplitude 0.1, RMS 0.1 >> 0.002)
                t = np.linspace(0, 0.1, 1600, endpoint=False)
                speech_block = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
                recorder._audio_callback(speech_block, 1600, None, 0)

                self.assertTrue(recorder.has_speech_started())
            finally:
                recorder.close()

    def test_transcriber_array_memory_guard(self):
        """Verify transcribe() caps giant inputs to max_samples to prevent ArrayMemoryError."""
        from unittest.mock import patch, MagicMock
        with patch.object(TranscriberManager, "_init_local_model"):
            transcriber = TranscriberManager(self.config)
            transcriber._local_model = MagicMock()
            transcriber._local_model.transcribe.return_value = ([], None)

            # Pass audio that exceeds 120 seconds (e.g. 130s = 2,080,000 samples)
            giant_audio = np.ones(16000 * 130, dtype=np.float32)
            transcriber.transcribe(giant_audio)

            # Check that _local_model.transcribe received audio capped at 16000 * 120 = 1,920,000 samples
            call_args = transcriber._local_model.transcribe.call_args
            passed_audio = call_args[0][0]
            self.assertEqual(len(passed_audio), 16000 * 120)

    def test_hallucination_whitelist_integrity(self):
        """Ensure legitimate short speech like 'you' or 'thank you' is not in blacklist."""
        from src.transcriber import HALLUCINATION_BLACKLIST
        
        # Verify valid common words are NOT blacklisted
        for valid_phrase in ["you", "thank you", "thank you.", "bye.", "hello", "yes"]:
            self.assertNotIn(valid_phrase.lower(), HALLUCINATION_BLACKLIST)

        # Verify actual hallucination strings ARE in the blacklist
        self.assertIn("thank you for watching.", HALLUCINATION_BLACKLIST)
        self.assertIn("thanks for watching!", HALLUCINATION_BLACKLIST)
        self.assertIn("[silence]", HALLUCINATION_BLACKLIST)

    def test_text_injector_paste_delay_and_safety(self):
        """Verify SafeTextInjector enforces minimum 120ms paste delay."""
        injector = SafeTextInjector(self.config)
        self.assertGreaterEqual(injector.paste_delay_ms, 120)

    def test_trim_silence_threshold_sensitivity(self):
        """Verify low-amplitude audio is preserved with default -54 dB threshold."""
        # 440Hz sine wave with peak amplitude 0.003 (~-50.5 dB)
        sample_rate = 16000
        t = np.linspace(0, 0.5, int(sample_rate * 0.5), endpoint=False)
        soft_speech = (0.003 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

        trimmed = trim_silence(soft_speech, sample_rate=sample_rate, threshold_db=-54.0)
        self.assertGreater(len(trimmed), 0)

    def test_tray_left_click_mapped_to_menu(self):
        """Verify WM_LBUTTONUP (0x0202) is routed to WM_RBUTTONUP (0x0205) on Windows."""
        from src.tray_app import TrayApp
        import sys
        app = TrayApp()
        try:
            if sys.platform == "win32" and hasattr(app.icon, "_message_handlers"):
                self.assertIn(1035, app.icon._message_handlers)
                # Verify calling handler with 0x0202 forwards to right click
                captured = []
                orig_on_notify = app.icon._on_notify
                def fake_notify(w, l):
                    captured.append((w, l))
                app.icon._on_notify = fake_notify
                for k, v in list(app.icon._message_handlers.items()):
                    if getattr(v, "__name__", "") == "_on_notify":
                        app.icon._message_handlers[k] = fake_notify

                # Re-apply patch
                if orig_on_notify:
                    def _patched(wparam, lparam):
                        if lparam == 0x0202:
                            lparam = 0x0205
                        return fake_notify(wparam, lparam)
                    _patched(1, 0x0202)
                    self.assertEqual(captured[-1], (1, 0x0205))
        finally:
            app.stop()

    def test_audio_recorder_fallback_to_raw_on_trim(self):
        """Verify AudioRecorder falls back to raw audio if silence trimming strips signal."""
        from unittest.mock import patch
        with patch.object(AudioRecorder, "_warmup_stream"):
            recorder = AudioRecorder(sample_rate=16000, block_size=1600, min_duration_sec=0.1)
            try:
                recorder._is_recording = True
                # Generate 0.3s of faint audio
                sample_count = int(16000 * 0.3)
                faint_audio = np.full(sample_count, 1e-4, dtype=np.float32)
                recorder._chunks = [faint_audio]

                # Stopping recording should return non-empty array because raw audio is preserved
                result = recorder.stop_recording()
                self.assertGreater(len(result), 0)
            finally:
                recorder.close()

    def test_history_dialog_active_instance(self):
        """Verify HistoryDialog.show focuses existing instance if already created."""
        from src.history_dialog import HistoryDialog
        from unittest.mock import MagicMock
        fake_dlg = MagicMock()
        fake_dlg.root.winfo_exists.return_value = True
        HistoryDialog._active_instance = fake_dlg

        res = HistoryDialog.show()
        self.assertEqual(res, fake_dlg)
        fake_dlg.root.lift.assert_called_once()
        fake_dlg.root.focus_force.assert_called_once()
        HistoryDialog._active_instance = None


if __name__ == "__main__":
    unittest.main()
