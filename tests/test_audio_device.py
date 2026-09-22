"""
Orvo - Audio Device Verification Tests.
Tests audio device enumeration, default input device detection,
and AudioRecorder device configuration via sounddevice.
"""

import unittest
import sounddevice as sd

from src.audio_recorder import (
    AudioRecorder,
    list_input_devices,
    get_default_input_device,
)
from src.config import AudioConfig


class TestAudioDevice(unittest.TestCase):
    """Test suite for audio hardware enumeration and recorder configuration."""

    def test_sounddevice_query(self):
        """Verify sounddevice can query system audio devices."""
        devices = sd.query_devices()
        self.assertIsInstance(devices, (list, sd.DeviceList))
        self.assertGreater(len(devices), 0, "Expected at least one audio device to be present.")

    def test_list_input_devices(self):
        """Verify list_input_devices returns well-formed dictionaries."""
        input_devices = list_input_devices()
        self.assertIsInstance(input_devices, list)

        # In any modern PC / VM, there is typically at least one input device
        for dev in input_devices:
            self.assertIn("index", dev)
            self.assertIn("name", dev)
            self.assertIn("hostapi", dev)
            self.assertIn("channels", dev)
            self.assertIn("default_samplerate", dev)
            self.assertIn("is_default", dev)
            self.assertGreater(dev["channels"], 0, f"Device {dev['name']} reported 0 input channels.")
            self.assertIsInstance(dev["index"], int)
            self.assertIsInstance(dev["name"], str)

    def test_default_input_device(self):
        """Verify get_default_input_device retrieves the system default."""
        default_dev = get_default_input_device()
        input_devices = list_input_devices()

        if input_devices:
            self.assertIsNotNone(default_dev, "Expected default device when input devices exist.")
            self.assertIn("index", default_dev)
            self.assertIn("name", default_dev)
            self.assertGreater(default_dev["channels"], 0)
        else:
            self.assertIsNone(default_dev)

    def test_audio_recorder_initialization(self):
        """Verify AudioRecorder initialization and state attributes."""
        cfg = AudioConfig(
            device_index=None,
            sample_rate=16000,
            channels=1,
            sound_effects=False,
            silence_trim=True,
        )
        recorder = AudioRecorder(config=cfg)
        try:
            self.assertEqual(recorder.sample_rate, 16000)
            self.assertEqual(recorder.channels, 1)
            self.assertFalse(recorder.is_recording())
            self.assertEqual(recorder.get_audio_level(), 0.0)
            self.assertEqual(recorder.get_recorded_duration(), 0.0)
        finally:
            recorder.close()

    def test_audio_recorder_device_switching(self):
        """Verify set_device updates device index safely."""
        recorder = AudioRecorder(device_index=None, sound_effects=False)
        try:
            self.assertIsNone(recorder.device_index)
            # Switch device to default explicitly
            recorder.set_device(None)
            self.assertIsNone(recorder.device_index)
        finally:
            recorder.close()


if __name__ == "__main__":
    unittest.main()
