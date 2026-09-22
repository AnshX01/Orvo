"""
Orvo - Audio Recorder Module.
Provides high-performance, non-blocking audio capture with a circular pre-roll buffer,
real-time VU metering, pleasant synthesized sound cues, and audio preprocessing
tailored for Whisper speech-to-text models.
"""

import collections
import io
import logging
import math
import threading
import time
import wave
from typing import Any, Dict, List, Optional, Union

import numpy as np
import sounddevice as sd

# Optional import of winsound (standard on Windows)
try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

# Import AudioConfig if available
try:
    from src.config import AudioConfig
except ImportError:
    AudioConfig = None  # type: ignore

logger = logging.getLogger(__name__)

__all__ = [
    "AudioRecorder",
    "list_input_devices",
    "get_default_input_device",
    "trim_silence",
    "normalize_peak",
    "save_wav",
]


def list_input_devices() -> List[Dict[str, Any]]:
    """
    List all available audio input devices.

    Returns:
        A list of dictionaries with device details:
        [
            {
                'index': int,
                'name': str,
                'hostapi': str,
                'channels': int,
                'default_samplerate': float,
                'is_default': bool
            },
            ...
        ]
    """
    devices_list: List[Dict[str, Any]] = []
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        default_in = sd.default.device[0]

        for idx, dev in enumerate(devices):
            max_in = dev.get("max_input_channels", 0)
            if max_in > 0:
                hostapi_idx = dev.get("hostapi", 0)
                hostapi_name = hostapis[hostapi_idx]["name"] if hostapi_idx < len(hostapis) else "Unknown"
                is_default = (idx == default_in)
                devices_list.append({
                    "index": idx,
                    "name": dev.get("name", f"Device {idx}"),
                    "hostapi": hostapi_name,
                    "channels": max_in,
                    "default_samplerate": dev.get("default_samplerate", 16000.0),
                    "is_default": is_default
                })
    except Exception as exc:
        logger.error("Failed to query audio devices: %s", exc)
    return devices_list


def get_default_input_device() -> Optional[Dict[str, Any]]:
    """
    Return the default audio input device dictionary, or None if not found.
    """
    devices = list_input_devices()
    for dev in devices:
        if dev["is_default"]:
            return dev
    return devices[0] if devices else None


def trim_silence(
    audio: np.ndarray,
    sample_rate: int = 16000,
    threshold_db: float = -48.0,
    frame_duration_ms: int = 20,
    pad_duration_ms: int = 350
) -> np.ndarray:
    """
    Automatically trim leading and trailing silence from an audio array.

    Args:
        audio: 1D numpy array of float32 audio samples.
        sample_rate: Audio sampling frequency in Hz (default: 16000).
        threshold_db: Energy/RMS threshold in decibels below which audio is
                      considered silence (default: -40.0 dB).
        frame_duration_ms: Duration in milliseconds for each analysis frame (default: 20ms).
        pad_duration_ms: Padding in milliseconds to retain around voiced segments
                         to prevent clipping consonants (default: 100ms).

    Returns:
        Trimmed 1D numpy array. Returns empty float32 array if audio is pure silence.
    """
    if audio is None or len(audio) == 0:
        return np.zeros(0, dtype=np.float32)

    # Convert dB threshold to linear amplitude RMS
    threshold_amp = 10.0 ** (threshold_db / 20.0)
    frame_len = max(1, int(sample_rate * frame_duration_ms / 1000))
    pad_len = int(sample_rate * pad_duration_ms / 1000)

    num_frames = len(audio) // frame_len
    if num_frames == 0:
        overall_rms = float(np.sqrt(np.mean(audio ** 2)))
        return audio if overall_rms >= threshold_amp else np.zeros(0, dtype=np.float32)

    # Compute RMS energy for each frame
    frames = audio[: num_frames * frame_len].reshape(num_frames, frame_len)
    rms_per_frame = np.sqrt(np.mean(frames ** 2, axis=1))

    voiced_indices = np.where(rms_per_frame >= threshold_amp)[0]
    if len(voiced_indices) == 0:
        # All frames below silence threshold
        return np.zeros(0, dtype=np.float32)

    first_voiced_frame = voiced_indices[0]
    last_voiced_frame = voiced_indices[-1] + 1

    start_sample = max(0, first_voiced_frame * frame_len - pad_len)
    end_sample = min(len(audio), last_voiced_frame * frame_len + pad_len)

    return audio[start_sample:end_sample].astype(np.float32)


def normalize_peak(audio: np.ndarray, target_peak: float = 0.95) -> np.ndarray:
    """
    Normalize peak audio level to prevent clipping and optimize Whisper inference accuracy.
    Removes DC offset first.

    Args:
        audio: 1D numpy array of float32 audio samples.
        target_peak: Target peak amplitude in range (0.0, 1.0] (default: 0.95).

    Returns:
        Peak-normalized 1D float32 numpy array.
    """
    if audio is None or len(audio) == 0:
        return np.zeros(0, dtype=np.float32)

    # Remove DC bias
    audio = audio - np.mean(audio)

    peak = float(np.max(np.abs(audio)))
    if peak > 1e-4:
        audio = audio * (target_peak / peak)

    return np.clip(audio, -1.0, 1.0).astype(np.float32)


def save_wav(file_path: str, audio: np.ndarray, sample_rate: int = 16000) -> None:
    """
    Save 1D float32 audio array to a 16-bit PCM mono WAV file.

    Args:
        file_path: Destination file path.
        audio: 1D numpy array of float32 samples in range [-1.0, 1.0].
        sample_rate: Sample rate in Hz (default: 16000).
    """
    # Convert float32 in [-1.0, 1.0] to 16-bit signed PCM
    clipped = np.clip(audio, -1.0, 1.0)
    int16_data = (clipped * 32767.0).astype(np.int16)

    with wave.open(file_path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 2 bytes = 16 bits
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(int16_data.tobytes())


class AudioRecorder:
    """
    High-performance audio recorder for Whisper speech-to-text inference.
    Captures 16kHz mono 16-bit PCM audio in float32 [-1.0, 1.0] non-blocking buffer,
    features instant pre-roll circular buffer, real-time VU meter level feedback,
    audio cue tones, and edge silence trimming.
    """

    def __init__(
        self,
        config: Optional[Any] = None,
        device_index: Optional[int] = None,
        sample_rate: int = 16000,
        channels: int = 1,
        sound_effects: bool = True,
        silence_trim: bool = True,
        silence_threshold_db: float = -40.0,
        normalize_audio: bool = True,
        min_duration_sec: float = 0.2,
        pre_roll_sec: float = 0.25,
        block_size: int = 1024,
    ):
        """
        Initialize the AudioRecorder.

        Args:
            config: Optional AudioConfig instance. If provided, values override defaults.
            device_index: Input device ID (None uses system default).
            sample_rate: Sample rate in Hz (Whisper standard is 16000).
            channels: Number of channels (Whisper standard is 1 = mono).
            sound_effects: Whether to emit pleasant synthesized audio feedback cues.
            silence_trim: Whether to automatically trim silence at the start and end.
            silence_threshold_db: Decibel threshold for silence detection.
            normalize_audio: Whether to normalize peak volume.
            min_duration_sec: Minimum valid speech duration in seconds.
            pre_roll_sec: Seconds of audio kept in rolling circular buffer prior to start.
            block_size: Sounddevice buffer block size (default: 1024 frames).
        """
        # Apply config if provided
        if config is not None:
            self.device_index = getattr(config, "device_index", device_index)
            self.sample_rate = getattr(config, "sample_rate", sample_rate)
            self.channels = getattr(config, "channels", channels)
            self.sound_effects = getattr(config, "sound_effects", False)
            self.silence_trim = getattr(config, "silence_trim", silence_trim)
            self.silence_threshold_db = getattr(config, "silence_threshold_db", -48.0)
            self.pad_duration_ms = getattr(config, "pad_duration_ms", 350)
            self.normalize_audio = getattr(config, "normalize_audio", normalize_audio)
        else:
            self.device_index = device_index
            self.sample_rate = sample_rate
            self.channels = channels
            self.sound_effects = sound_effects
            self.silence_trim = silence_trim
            self.silence_threshold_db = silence_threshold_db
            self.pad_duration_ms = 350
            self.normalize_audio = normalize_audio

        self.min_duration_sec = min_duration_sec
        self.block_size = block_size
        self.pre_roll_sec = max(0.35, pre_roll_sec)

        # Circular pre-roll buffer: keeps last pre_roll_sec frames
        num_pre_roll_blocks = max(1, int(self.pre_roll_sec * self.sample_rate / self.block_size) + 1)
        self._ring_buffer: collections.deque = collections.deque(maxlen=num_pre_roll_blocks)

        # State management
        self._is_recording = False
        self._stream: Optional[sd.InputStream] = None
        self._chunks: List[np.ndarray] = []
        self._lock = threading.RLock()

        # Real-time audio level / VU meter
        self._audio_level: float = 0.0
        self._level_lock = threading.Lock()

        # Recording timestamp
        self._record_start_time: float = 0.0

        # Pre-warm stream for instant low-latency recording
        self._warmup_stream()

    # -------------------------------------------------------------------------
    # Audio Feedback Tones (winsound chirps)
    # -------------------------------------------------------------------------

    def play_beep(self, freq: int, duration_ms: int) -> None:
        """
        Play a synthesized tone asynchronously in a background daemon thread.
        Never blocks the calling thread or audio capture.
        """
        if not self.sound_effects or not HAS_WINSOUND:
            return

        def _beep_worker():
            try:
                winsound.Beep(int(freq), int(duration_ms))
            except Exception as exc:
                logger.debug("Sound cue error: %s", exc)

        threading.Thread(target=_beep_worker, daemon=True, name="AudioCueThread").start()

    def start_sound(self) -> None:
        """Subtle 800Hz 50ms chirp on record start."""
        self.play_beep(800, 50)

    def stop_sound(self) -> None:
        """Subtle 1200Hz 60ms chirp on record stop / complete."""
        self.play_beep(1200, 60)

    def error_sound(self) -> None:
        """Subtle 400Hz 100ms chirp on error or disconnected device."""
        self.play_beep(400, 100)

    # -------------------------------------------------------------------------
    # Audio Stream Callback & Pre-warming
    # -------------------------------------------------------------------------

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: sd.CallbackFlags
    ) -> None:
        """Sounddevice input stream callback. Runs on high-priority audio thread."""
        if status:
            logger.warning("Audio input stream status: %s", status)

        # Flatten indata to 1D float32
        data_1d = indata.flatten().astype(np.float32)

        # Store in buffer
        with self._lock:
            if self._is_recording:
                self._chunks.append(data_1d.copy())
            else:
                self._ring_buffer.append(data_1d.copy())

        # Compute RMS energy for VU meter
        rms = float(np.sqrt(np.mean(data_1d ** 2)))
        if rms > 1e-5:
            db = 20.0 * math.log10(rms)
            # Map decibel range [-50 dB, -5 dB] to normalized [0.0, 1.0]
            normalized = (db + 50.0) / 45.0
            normalized = max(0.0, min(1.0, normalized))
        else:
            normalized = 0.0

        # Smooth VU meter level with fast attack and gentle decay
        with self._level_lock:
            if normalized > self._audio_level:
                self._audio_level = 0.7 * normalized + 0.3 * self._audio_level
            else:
                self._audio_level = 0.25 * normalized + 0.75 * self._audio_level

    def _warmup_stream(self) -> bool:
        """Initialize and start background input stream for zero-latency capture."""
        with self._lock:
            if self._stream is not None and self._stream.active:
                return True

            self._cleanup_stream()
            try:
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype="float32",
                    device=self.device_index,
                    callback=self._audio_callback,
                    blocksize=self.block_size
                )
                self._stream.start()
                logger.info("Audio stream warmed up successfully (device=%s, rate=%dHz)",
                            self.device_index, self.sample_rate)
                return True
            except Exception as exc:
                logger.warning("Failed to warmup audio stream (device=%s): %s", self.device_index, exc)
                self._cleanup_stream()

                # Fallback to default device
                if self.device_index is not None:
                    try:
                        logger.info("Attempting warmup on default audio device...")
                        self._stream = sd.InputStream(
                            samplerate=self.sample_rate,
                            channels=self.channels,
                            dtype="float32",
                            device=None,
                            callback=self._audio_callback,
                            blocksize=self.block_size
                        )
                        self._stream.start()
                        logger.info("Warmup on default audio device succeeded.")
                        return True
                    except Exception as fallback_exc:
                        logger.error("Default audio warmup also failed: %s", fallback_exc)
                        self._cleanup_stream()
                return False

    # -------------------------------------------------------------------------
    # Recording Control
    # -------------------------------------------------------------------------

    def start_recording(self) -> bool:
        """
        Start audio capture instantly.
        Pre-seeds recording with recent circular buffer audio so speech onsets are not clipped.

        Returns:
            True if recording started successfully, False otherwise.
        """
        with self._lock:
            if self._is_recording:
                logger.warning("AudioRecorder: start_recording called while already recording.")
                return True

            # Ensure stream is active
            if self._stream is None or not self._stream.active:
                if not self._warmup_stream():
                    self.error_sound()
                    return False

            # Seed chunks with circular pre-roll buffer
            self._chunks = list(self._ring_buffer)
            self._ring_buffer.clear()

            self._is_recording = True
            self._record_start_time = time.monotonic()

            # Play start cue tone
            self.start_sound()
            logger.info("Recording started instantly with %d pre-roll blocks", len(self._chunks))
            return True

    def stop_recording(self) -> np.ndarray:
        """
        Stop audio capture and return the processed audio array.

        Returns:
            1D numpy array of float32 samples at 16,000 Hz in [-1.0, 1.0].
            Returns empty array np.zeros(0, dtype=np.float32) if recording
            was pure silence or shorter than min_duration_sec.
        """
        with self._lock:
            if not self._is_recording:
                logger.warning("AudioRecorder: stop_recording called while not recording.")
                return np.zeros(0, dtype=np.float32)

            self._is_recording = False

            # Reset VU meter level
            with self._level_lock:
                self._audio_level = 0.0

            # Play stop cue tone
            self.stop_sound()

            # Gather chunks
            if not self._chunks:
                logger.info("Recorded 0 chunks.")
                return np.zeros(0, dtype=np.float32)

            raw_audio = np.concatenate(self._chunks, axis=0).astype(np.float32)
            self._chunks.clear()

        duration = len(raw_audio) / self.sample_rate
        logger.info("Raw audio captured: %.2f seconds (%d samples)", duration, len(raw_audio))

        # Check raw minimum duration
        if duration < self.min_duration_sec:
            logger.info("Audio duration (%.2fs) below minimum threshold (%.2fs), discarding.",
                        duration, self.min_duration_sec)
            return np.zeros(0, dtype=np.float32)

        # Apply silence trimming if enabled
        processed = raw_audio
        if self.silence_trim:
            processed = trim_silence(
                processed,
                sample_rate=self.sample_rate,
                threshold_db=self.silence_threshold_db,
                frame_duration_ms=20,
                pad_duration_ms=getattr(self, "pad_duration_ms", 350)
            )
            trimmed_duration = len(processed) / self.sample_rate
            logger.info("Trimmed silence: %.2f seconds remaining (%d samples)",
                        trimmed_duration, len(processed))

            # If trimmed audio is shorter than minimum speech duration, verify raw RMS before discarding
            if trimmed_duration < self.min_duration_sec:
                raw_rms = float(np.sqrt(np.mean(raw_audio ** 2))) if len(raw_audio) > 0 else 0.0
                if raw_rms >= 0.002:
                    logger.info("Trimmed below min duration, but raw audio has speech energy (RMS=%.5f); retaining raw audio.", raw_rms)
                    processed = raw_audio
                else:
                    logger.info("Audio below minimum duration and energy, discarding.")
                    return np.zeros(0, dtype=np.float32)

        # Apply peak normalization if enabled
        if self.normalize_audio:
            processed = normalize_peak(processed, target_peak=0.95)

        return processed

    def _cleanup_stream(self) -> None:
        """Safely stop and close the sounddevice stream."""
        if self._stream is not None:
            try:
                if self._stream.active:
                    self._stream.stop()
                self._stream.close()
            except Exception as exc:
                logger.debug("Exception closing audio stream: %s", exc)
            finally:
                self._stream = None

    def close(self) -> None:
        """Clean shutdown of the recorder and audio stream."""
        with self._lock:
            self._is_recording = False
            self._cleanup_stream()
            self._chunks.clear()
            self._ring_buffer.clear()
            logger.info("AudioRecorder closed.")

    # -------------------------------------------------------------------------
    # State & Getters
    # -------------------------------------------------------------------------

    def is_recording(self) -> bool:
        """Check if recording is currently in progress."""
        with self._lock:
            return self._is_recording

    def get_audio_level(self) -> float:
        """
        Get current smoothed audio level (0.0 to 1.0) for VU meter visualization.
        Provides live microphone feedback.
        """
        with self._level_lock:
            return float(self._audio_level)

    def get_recorded_duration(self) -> float:
        """Return the duration in seconds of current recording session."""
        with self._lock:
            if not self._is_recording:
                return 0.0
            return time.monotonic() - self._record_start_time

    # -------------------------------------------------------------------------
    # Configuration Update Methods
    # -------------------------------------------------------------------------

    def set_device(self, device_index: Optional[int]) -> None:
        """Update the audio input device and restart the stream."""
        with self._lock:
            was_recording = self._is_recording
            self.device_index = device_index
            logger.info("AudioRecorder device index set to %s", device_index)
            self._warmup_stream()
            if was_recording:
                self._is_recording = True

    def set_sound_effects(self, enabled: bool) -> None:
        """Toggle synthesized audio cue chirps."""
        self.sound_effects = enabled

    def update_config(self, config: Any) -> None:
        """Update settings from an AudioConfig instance."""
        with self._lock:
            new_device = getattr(config, "device_index", self.device_index)
            self.sample_rate = getattr(config, "sample_rate", self.sample_rate)
            self.channels = getattr(config, "channels", self.channels)
            self.sound_effects = getattr(config, "sound_effects", self.sound_effects)
            self.silence_trim = getattr(config, "silence_trim", self.silence_trim)
            self.silence_threshold_db = getattr(config, "silence_threshold_db", self.silence_threshold_db)
            self.normalize_audio = getattr(config, "normalize_audio", self.normalize_audio)

            if new_device != self.device_index:
                self.set_device(new_device)
        logger.info("AudioRecorder configuration updated successfully.")
