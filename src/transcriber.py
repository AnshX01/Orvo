"""
Orvo Transcriber Module.
Provides dual backends (Local faster-whisper and Cloud Groq / OpenAI),
pre-warming routines, silence/hallucination suppression, and smart text post-processing.
"""

import io
import logging
import os
import re
import threading
import time
from typing import Optional, List, Dict, Any, Tuple

import numpy as np
import scipy.io.wavfile as wavfile
import requests
from faster_whisper import WhisperModel
import ctranslate2

from src.config import AppConfig, get_config

logger = logging.getLogger("Orvo.Transcriber")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

from src.sentence_former import SentenceFormer

# Known Whisper silence hallucinations commonly outputted on near-silent inputs
HALLUCINATION_BLACKLIST = {
    "you",
    "you.",
    "thank you",
    "thank you.",
    "thank you very much.",
    "thanks for watching.",
    "thanks for watching!",
    "thank you for watching.",
    "thank you for watching!",
    "subtitles by",
    "transcribed by",
    "amara.org",
    "please subscribe",
    "please subscribe!",
    "subscribe to my channel",
    "bye.",
    "mbc",
    "the end.",
    "silent",
    "[silence]",
    "[music]",
    "(silence)",
    "(music)",
}


_CUDA_TESTED: bool = False
_CUDA_USABLE: bool = False


class TranscriberManager:
    """
    Manages dual-backend transcription (Local faster-whisper & Cloud Groq/OpenAI),
    audio pre-warming, silence filtering, and voice command post-processing.
    """

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or get_config()
        self._lock = threading.Lock()
        self.sentence_former = SentenceFormer(
            enable_smart_formatting=getattr(self.config.text, "smart_sentence_formation", True),
            remove_fillers=getattr(self.config.text, "remove_fillers", True),
            fix_disfluencies=getattr(self.config.text, "fix_disfluencies", True),
            auto_capitalize=getattr(self.config.text, "auto_capitalize", True),
            auto_punctuate=getattr(self.config.text, "auto_punctuate", True),
        )
        self._local_model: Optional[WhisperModel] = None
        self._active_device: str = "cpu"
        self._active_compute_type: str = "int8"
        self._loaded_model_name: str = ""

        # Pre-initialize and pre-warm local model
        self._init_local_model()

    # -------------------------------------------------------------------------
    # Local Model Management & Pre-warming
    # -------------------------------------------------------------------------

    def _init_local_model(self) -> None:
        """
        Initializes the faster-whisper model with intelligent hardware detection,
        CUDA verification with graceful CPU fallback, and pre-warms the inference graph.
        """
        global _CUDA_TESTED, _CUDA_USABLE

        model_name = self.config.model.local_model or "base.en"
        preferred_device = (self.config.model.device or "auto").lower()
        preferred_compute = (self.config.model.compute_type or "int8").lower()

        loaded = False

        # Attempt CUDA if requested or set to auto and hasn't previously failed
        if preferred_device in ("auto", "cuda") and (not _CUDA_TESTED or _CUDA_USABLE):
            try:
                cuda_count = ctranslate2.get_cuda_device_count()
                if cuda_count > 0:
                    compute_type = "float16" if preferred_compute in ("auto", "float16") else preferred_compute
                    logger.info(f"Detected {cuda_count} CUDA device(s). Attempting to load '{model_name}' on CUDA ({compute_type})...")
                    model = WhisperModel(model_name, device="cuda", compute_type=compute_type)

                    # Verify CUDA inference actually works (detect missing cublas/cudnn dlls early)
                    dummy_silence = np.zeros(8000, dtype=np.float32)
                    list(model.transcribe(dummy_silence, beam_size=1)[0])

                    self._local_model = model
                    self._active_device = "cuda"
                    self._active_compute_type = compute_type
                    self._loaded_model_name = model_name
                    loaded = True
                    _CUDA_TESTED = True
                    _CUDA_USABLE = True
                    logger.info(f"Local Whisper model '{model_name}' initialized and pre-warmed on CUDA ({compute_type}).")
            except Exception as e:
                _CUDA_TESTED = True
                _CUDA_USABLE = False
                logger.warning(
                    f"CUDA initialization or inference test failed ({e}). "
                    "Falling back to CPU with int8 quantization."
                )

        # Fallback / explicit CPU initialization
        if not loaded:
            compute_type = "int8" if preferred_compute in ("auto", "float16", "int8") else preferred_compute
            logger.info(f"Loading '{model_name}' on CPU ({compute_type})...")
            try:
                self._local_model = WhisperModel(model_name, device="cpu", compute_type=compute_type)
                # Pre-warming routine: pass 0.5s silence through transcribe
                self._prewarm_model()
                self._active_device = "cpu"
                self._active_compute_type = compute_type
                self._loaded_model_name = model_name
                logger.info(f"Local Whisper model '{model_name}' initialized and pre-warmed on CPU ({compute_type}).")
            except Exception as e:
                logger.error(f"Failed to load local Whisper model '{model_name}' on CPU: {e}")
                self._local_model = None

    def _prewarm_model(self) -> None:
        """
        Runs 0.5s of silent audio through the model to compile kernels, load tokenizers,
        and initialize thread pools so the first user transcription has zero cold-start delay.
        """
        if self._local_model is None:
            return
        try:
            start_t = time.perf_counter()
            # 8000 samples at 16kHz = 0.5s
            dummy_audio = np.zeros(8000, dtype=np.float32)
            segments, _ = self._local_model.transcribe(dummy_audio, beam_size=1, condition_on_previous_text=False)
            _ = list(segments)
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            logger.debug(f"Model pre-warming completed in {elapsed_ms:.1f}ms.")
        except Exception as e:
            logger.warning(f"Model pre-warming warning: {e}")

    def reload_model(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
    ) -> bool:
        """
        Dynamically reload the local model when settings change.
        """
        with self._lock:
            if model_name:
                self.config.model.local_model = model_name
            if device:
                self.config.model.device = device
            if compute_type:
                self.config.model.compute_type = compute_type
            self._init_local_model()
            return self._local_model is not None

    def update_config(self, new_config: AppConfig) -> None:
        """Updates internal configuration and reloads model if backend/model changed."""
        with self._lock:
            old_model = self.config.model.local_model
            old_dev = self.config.model.device
            old_comp = self.config.model.compute_type
            self.config = new_config

            if (
                new_config.model.local_model != old_model
                or new_config.model.device != old_dev
                or new_config.model.compute_type != old_comp
            ):
                self._init_local_model()

    @property
    def active_device(self) -> str:
        return self._active_device

    @property
    def active_compute_type(self) -> str:
        return self._active_compute_type

    # -------------------------------------------------------------------------
    # Transcription Pipeline
    # -------------------------------------------------------------------------

    def transcribe(self, audio_data: np.ndarray) -> str:
        """
        Transcribes the given 16kHz float32 audio array.
        Thread-safe entry point for all transcription requests.

        Args:
            audio_data: 1D numpy float32 array sampled at 16,000 Hz.

        Returns:
            Formatted, post-processed transcription string or empty string on silence/error.
        """
        if audio_data is None or len(audio_data) == 0:
            return ""

        with self._lock:
            # Normalize shape to 1D float32
            if audio_data.ndim > 1:
                audio_data = audio_data.flatten()
            audio_data = audio_data.astype(np.float32)

            # Silence check: calculate RMS energy
            rms = float(np.sqrt(np.mean(audio_data ** 2))) if len(audio_data) > 0 else 0.0
            if rms < 0.002:  # Threshold for pure ambient silence
                logger.debug(f"Suppressed transcription: pure silence detected (RMS={rms:.6f}).")
                return ""

            raw_text = ""
            backend = (self.config.model.backend or "local").lower()

            # Attempt Cloud Backend if selected
            if backend in ("groq", "openai"):
                cloud_text = self._transcribe_cloud(audio_data, backend)
                if cloud_text is not None:
                    raw_text = cloud_text
                else:
                    logger.info(f"Cloud transcription ({backend}) failed or unavailable; falling back to local model.")
                    raw_text = self._transcribe_local(audio_data)
            else:
                raw_text = self._transcribe_local(audio_data)

            # Silence hallucination filtering
            clean_check = raw_text.strip().lower()
            if not clean_check or clean_check in HALLUCINATION_BLACKLIST:
                logger.debug(f"Suppressed hallucination text: '{raw_text}'")
                return ""

            # Check repetitive token loops (e.g. "I'm sorry. I'm sorry. I'm sorry.")
            if self._is_repetitive_hallucination(raw_text):
                logger.debug(f"Suppressed repetitive loop hallucination: '{raw_text}'")
                return ""

            # Post-processing: Voice commands
            if self.config.text.voice_commands:
                raw_text = self.process_voice_commands(raw_text)

            # Post-processing: Smart sentence formation and context restructuring
            if getattr(self.config.text, "smart_sentence_formation", True):
                formatted_text = self.sentence_former.format(raw_text)
            else:
                formatted_text = self.format_text(
                    raw_text,
                    auto_capitalize=self.config.text.auto_capitalize,
                )

            return formatted_text

    def _transcribe_local(self, audio_data: np.ndarray) -> str:
        """Transcribes audio using local faster-whisper model with optimized beam search & prompt."""
        if self._local_model is None:
            logger.error("Local Whisper model is not loaded.")
            return ""

        try:
            start_t = time.perf_counter()
            lang = self.config.model.language if self.config.model.language else None

            beam_size = getattr(self.config.model, "beam_size", 5)
            initial_prompt = getattr(self.config.model, "initial_prompt", None)
            vad_filter = getattr(self.config.model, "vad_filter", False)

            transcribe_kwargs = {
                "language": lang,
                "beam_size": beam_size,
                "vad_filter": vad_filter,
                "condition_on_previous_text": False,
            }
            if vad_filter:
                transcribe_kwargs["vad_parameters"] = dict(min_silence_duration_ms=500, speech_pad_ms=400)
            if initial_prompt:
                transcribe_kwargs["initial_prompt"] = initial_prompt

            segments, info = self._local_model.transcribe(
                audio_data,
                **transcribe_kwargs
            )

            text_parts = []
            for seg in segments:
                # Retain all spoken text; only skip if probability of no speech exceeds 92%
                if seg.no_speech_prob > 0.92:
                    continue
                text_parts.append(seg.text)

            result = " ".join(text_parts).strip()
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            logger.debug(f"Local transcription ({self._active_device}, beam={beam_size}) took {elapsed_ms:.1f}ms: '{result}'")
            return result
        except Exception as e:
            logger.error(f"Local transcription error: {e}", exc_info=True)
            return ""

    def _transcribe_cloud(self, audio_data: np.ndarray, backend: str) -> Optional[str]:
        """
        Encodes audio to 16kHz 16-bit PCM WAV in-memory and sends to Groq or OpenAI API.
        Returns transcribed text or None on failure for fallback.
        """
        try:
            # Prepare WAV bytes buffer
            pcm16 = np.clip(audio_data * 32767.0, -32768.0, 32767.0).astype(np.int16)
            wav_io = io.BytesIO()
            wavfile.write(wav_io, 16000, pcm16)
            wav_bytes = wav_io.getvalue()

            lang = self.config.model.language or "en"

            if backend == "groq":
                api_key = self.config.model.groq_api_key
                if not api_key:
                    logger.warning("Groq backend selected but groq_api_key is empty.")
                    return None

                endpoint = "https://api.groq.com/openai/v1/audio/transcriptions"
                model_name = self.config.model.groq_model or "whisper-large-v3-turbo"
                headers = {"Authorization": f"Bearer {api_key}"}
                files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
                data = {
                    "model": model_name,
                    "response_format": "json",
                    "language": lang,
                    "temperature": "0.0",
                }
                timeout = 7.0

            elif backend == "openai":
                api_key = self.config.model.openai_api_key
                if not api_key:
                    logger.warning("OpenAI backend selected but openai_api_key is empty.")
                    return None

                endpoint = "https://api.openai.com/v1/audio/transcriptions"
                model_name = self.config.model.openai_model or "whisper-1"
                headers = {"Authorization": f"Bearer {api_key}"}
                files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
                data = {
                    "model": model_name,
                    "response_format": "json",
                    "language": lang,
                    "temperature": "0.0",
                }
                timeout = 8.0
            else:
                return None

            start_t = time.perf_counter()
            response = requests.post(endpoint, headers=headers, files=files, data=data, timeout=timeout)
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0

            if response.status_code == 200:
                result_json = response.json()
                text = result_json.get("text", "").strip()
                logger.debug(f"Cloud {backend} transcription succeeded in {elapsed_ms:.1f}ms: '{text}'")
                return text
            else:
                logger.warning(f"Cloud {backend} returned HTTP {response.status_code}: {response.text}")
                return None

        except requests.exceptions.RequestException as e:
            logger.warning(f"Network error during Cloud {backend} transcription: {e}")
            return None
        except Exception as e:
            logger.warning(f"Unexpected error during Cloud {backend} transcription: {e}")
            return None

    # -------------------------------------------------------------------------
    # Text Post-Processing & Normalization
    # -------------------------------------------------------------------------

    @staticmethod
    def process_voice_commands(text: str) -> str:
        """
        Interprets spoken punctuation and formatting commands into actual characters.

        Supports:
            - "new line" / "newline" -> \n
            - "new paragraph" -> \n\n
            - "period" / "full stop" -> .
            - "comma" -> ,
            - "question mark" -> ?
            - "exclamation mark" / "exclamation point" -> !
            - "colon" -> :
            - "semicolon" -> ;
            - "open quote" / "close quote" -> "
            - "bullet point" -> \n• 
        """
        if not text:
            return ""

        # Handle quotes first
        text = re.sub(r'\b(?:open quote|open quotes)\b\s*', '"', text, flags=re.IGNORECASE)
        text = re.sub(r'\s*\b(?:close quote|close quotes)\b', '"', text, flags=re.IGNORECASE)

        # Paragraphs and newlines
        text = re.sub(r'\s*\b(?:new paragraph)\b\s*', '\n\n', text, flags=re.IGNORECASE)
        text = re.sub(r'\s*\b(?:new line|newline)\b\s*', '\n', text, flags=re.IGNORECASE)

        # Bullet points
        text = re.sub(r'(?:^|\n|\s+)\b(?:bullet point)\b\s*', '\n• ', text, flags=re.IGNORECASE)

        # Spoken punctuation: remove preceding whitespace and strip existing duplicate mark
        text = re.sub(r'\s*\b(?:period|full stop)\b\.?', '.', text, flags=re.IGNORECASE)
        text = re.sub(r'\s*\b(?:comma)\b,?', ',', text, flags=re.IGNORECASE)
        text = re.sub(r'\s*\b(?:question mark)\b\??', '?', text, flags=re.IGNORECASE)
        text = re.sub(r'\s*\b(?:exclamation mark|exclamation point)\b!?', '!', text, flags=re.IGNORECASE)
        text = re.sub(r'\s*\b(?:colon)\b:?', ':', text, flags=re.IGNORECASE)
        text = re.sub(r'\s*\b(?:semicolon)\b;?', ';', text, flags=re.IGNORECASE)

        return text.strip()

    @staticmethod
    def format_text(text: str, auto_capitalize: bool = True) -> str:
        """
        Cleans spacing, ensures proper punctuation attachment, and capitalizes sentences.
        """
        if not text:
            return ""

        # Ensure space after punctuation if immediately followed by an alphanumeric character
        # e.g. "hello,world" -> "hello, world"
        text = re.sub(r'([,\.!\?:;])([A-Za-z0-9])', r'\1 \2', text)

        # Normalize multiple horizontal spaces and trim lines
        lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.split('\n')]
        text = '\n'.join(lines)

        # Limit consecutive newlines to maximum 2
        text = re.sub(r'\n{3,}', '\n\n', text)

        if auto_capitalize:
            # Capitalize the very first non-whitespace character
            if len(text) > 0 and text[0].islower():
                text = text[0].upper() + text[1:]

            # Capitalize character right after opening quote if present: e.g. "hello -> "Hello
            text = re.sub(r'(^|\s+)["\']([a-z])', lambda m: m.group(1) + '"' + m.group(2).upper(), text)

            # Capitalize after sentence-ending punctuation (. ! ?) followed by whitespace
            def _cap_match(m: re.Match) -> str:
                return m.group(1) + m.group(2).upper()

            text = re.sub(r'([.!?]\s+)([a-z])', _cap_match, text)

            # Capitalize at start of new line
            text = re.sub(r'(\n\s*)([a-z])', _cap_match, text)

            # Capitalize after bullet point
            text = re.sub(r'(•\s*)([a-z])', _cap_match, text)

        return text.strip()

    @staticmethod
    def _is_repetitive_hallucination(text: str) -> bool:
        """
        Detects hallucination repetition loops (e.g. 'I am sorry. I am sorry. I am sorry.').
        Uses n-gram consecutive repeat detection (1-word, 2-word, and 3-word loops)
        and token uniqueness ratio analysis.
        """
        t = text.strip()
        if len(t) < 8:
            return False

        words = re.findall(r'\b\w+\b', t.lower())
        if len(words) < 3:
            return False

        # Check 1-word, 2-word, and 3-word repeating patterns (3+ repeats)
        for n in (1, 2, 3):
            if len(words) >= n * 3:
                ngrams = [tuple(words[i:i+n]) for i in range(0, len(words) - n + 1, n)]
                cur_streak = 1
                for i in range(1, len(ngrams)):
                    if ngrams[i] == ngrams[i-1]:
                        cur_streak += 1
                        if cur_streak >= 3:
                            return True
                    else:
                        cur_streak = 1

        # Check token uniqueness ratio for longer repetitive texts
        if len(words) >= 6:
            unique_ratio = len(set(words)) / len(words)
            if unique_ratio <= 0.35:
                return True

        return False
