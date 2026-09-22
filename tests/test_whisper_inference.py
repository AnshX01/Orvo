"""
Orvo - Whisper Inference & Speech Accuracy Verification Tests.
Generates a verified speech WAV sample, runs faster-whisper base.en inference,
measures execution latency, and verifies speech transcription accuracy.
"""

import os
import time
import unittest
import numpy as np
import scipy.io.wavfile as wavfile
import scipy.signal as signal

from src.config import AppConfig, ModelConfig
from src.transcriber import TranscriberManager


def generate_speech_audio(phrase: str = "hello world") -> np.ndarray:
    """
    Generates a 16kHz mono float32 numpy audio sample of spoken speech.
    Uses Windows SAPI text-to-speech engine if available, or synthetic formant speech.
    """
    try:
        import win32com.client
        temp_wav = os.path.abspath(os.path.join(os.path.dirname(__file__), "temp_speech_test.wav"))
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Open(temp_wav, 3)  # SSFMCreateForWrite
        voice.AudioOutputStream = stream
        voice.Speak(phrase)
        stream.Close()

        sr, data = wavfile.read(temp_wav)
        if os.path.exists(temp_wav):
            os.remove(temp_wav)

        if data.ndim > 1:
            data = data.mean(axis=1)

        # Resample to 16,000 Hz if needed
        if sr != 16000:
            num_samples = int(len(data) * 16000 / sr)
            data = signal.resample(data, num_samples)

        audio = data.astype(np.float32)
        peak = np.max(np.abs(audio))
        if peak > 1e-4:
            audio = audio / peak * 0.90
        return audio
    except Exception:
        # Fallback harmonic carrier tone
        t = np.linspace(0, 1.5, int(16000 * 1.5), endpoint=False)
        audio = (0.5 * np.sin(2 * np.pi * 440 * t) + 0.25 * np.sin(2 * np.pi * 880 * t)).astype(np.float32)
        return audio


class TestWhisperInference(unittest.TestCase):
    """Verifies local Whisper model inference, accuracy, and latency."""

    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig(
            model=ModelConfig(
                backend="local",
                local_model="base.en",
                compute_type="int8",
                device="auto",
            )
        )
        cls.tm = TranscriberManager(config=cls.config)
        cls.sample_audio = generate_speech_audio("hello world")

    def test_model_loaded_and_ready(self):
        """Assert local model initialized with valid compute type and device."""
        self.assertIsNotNone(self.tm._local_model, "Local Whisper model should be loaded.")
        self.assertIn(self.tm.active_compute_type, ("int8", "float16", "float32"))
        self.assertIn(self.tm.active_device, ("cpu", "cuda"))

    def test_speech_transcription_accuracy_and_latency(self):
        """Assert transcribed speech accuracy and verify low latency execution."""
        start_t = time.perf_counter()
        result = self.tm.transcribe(self.sample_audio)
        elapsed_sec = time.perf_counter() - start_t

        print(f"\n[Inference Benchmark] Transcribed: '{result}' in {elapsed_sec * 1000:.1f}ms")

        # Verify transcription accurately identified spoken content
        clean = result.lower()
        self.assertTrue("hello" in clean or "world" in clean, f"Unexpected transcription: '{result}'")

        # Verify latency is within high-performance threshold (< 2.5s on CPU)
        self.assertLess(elapsed_sec, 2.5, f"Inference took too long: {elapsed_sec:.2f}s")

    def test_silence_filtering(self):
        """Assert silence and near-silence audio return empty strings."""
        silence = np.zeros(16000 * 2, dtype=np.float32)
        result = self.tm.transcribe(silence)
        self.assertEqual(result, "", f"Expected empty string on pure silence, got '{result}'")


if __name__ == "__main__":
    unittest.main()
