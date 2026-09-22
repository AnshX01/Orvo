"""
Unit and Integration Tests for TranscriberManager and SafeTextInjector.
"""

import io
import unittest
import numpy as np
import scipy.io.wavfile as wavfile

from src.config import AppConfig, ModelConfig, TextConfig
from src.transcriber import TranscriberManager, HALLUCINATION_BLACKLIST
from src.text_injector import SafeTextInjector, ClipboardBackup


class TestTranscriberTextProcessing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig()
        cls.tm = TranscriberManager(config=cls.config)

    def test_voice_commands_punctuation(self):
        raw = "hello world period how are you question mark this is great exclamation mark"
        processed = self.tm.process_voice_commands(raw)
        formatted = self.tm.format_text(processed, auto_capitalize=True)
        self.assertEqual(formatted, "Hello world. How are you? This is great!")

    def test_voice_commands_newlines_and_bullets(self):
        raw = "here are the items colon new line bullet point first thing new line bullet point second thing"
        processed = self.tm.process_voice_commands(raw)
        formatted = self.tm.format_text(processed, auto_capitalize=True)
        expected = "Here are the items:\n• First thing\n• Second thing"
        self.assertEqual(formatted, expected)

    def test_voice_commands_quotes(self):
        raw = "she said open quote welcome to orvo close quote"
        processed = self.tm.process_voice_commands(raw)
        formatted = self.tm.format_text(processed, auto_capitalize=True)
        self.assertEqual(formatted, 'She said "Welcome to orvo"')

    def test_silence_suppression(self):
        silence = np.zeros(16000, dtype=np.float32)
        res = self.tm.transcribe(silence)
        self.assertEqual(res, "")

    def test_ambient_near_silence_suppression(self):
        # 16000 samples of tiny hiss below 0.002 RMS
        tiny_noise = np.random.normal(0, 0.0005, 16000).astype(np.float32)
        res = self.tm.transcribe(tiny_noise)
        self.assertEqual(res, "")

    def test_repetitive_hallucination_detection(self):
        rep = "thank you. thank you. thank you. thank you."
        self.assertTrue(self.tm._is_repetitive_hallucination(rep))

    def test_in_memory_wav_encoding(self):
        audio = np.random.uniform(-0.5, 0.5, 16000).astype(np.float32)
        pcm16 = np.clip(audio * 32767.0, -32768.0, 32767.0).astype(np.int16)
        buf = io.BytesIO()
        wavfile.write(buf, 16000, pcm16)
        buf.seek(0)
        sr, data = wavfile.read(buf)
        self.assertEqual(sr, 16000)
        self.assertEqual(len(data), 16000)
        self.assertEqual(data.dtype, np.int16)


class TestSafeTextInjector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig()
        cls.injector = SafeTextInjector(config=cls.config)

    def test_empty_injection(self):
        # Injecting empty string should safely return True without error
        res = self.injector.inject("")
        self.assertTrue(res)

    def test_direct_typing(self):
        res = self.injector.type_text("Whisper test")
        self.assertTrue(res)

    def test_full_injection(self):
        res = self.injector.inject("Test transcription injection")
        self.assertTrue(res)


if __name__ == "__main__":
    unittest.main()
