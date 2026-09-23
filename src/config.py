"""
Orvo Configuration Management Module.
Handles schema validation, sane defaults, comment-tolerant JSON parsing,
thread-safe persistence, and hot-reloading for user settings.
"""

import json
import os
import re
import threading
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, Callable, List

logger = logging.getLogger("Orvo.Config")

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.abspath(os.path.join(_SRC_DIR, ".."))
_ROOT_CONFIG = os.path.join(_ROOT_DIR, "config.json")
_SRC_CONFIG = os.path.join(_SRC_DIR, "config.json")

# Primary configuration file path is root config.json; fall back to src if only src exists
if os.path.exists(_ROOT_CONFIG):
    CONFIG_FILE_PATH = _ROOT_CONFIG
elif os.path.exists(_SRC_CONFIG):
    CONFIG_FILE_PATH = _SRC_CONFIG
else:
    CONFIG_FILE_PATH = _ROOT_CONFIG


def strip_json_comments(text: str) -> str:
    """
    Strips single-line (// and #) and multi-line (/* ... */) comments from JSON text
    without modifying string literals (e.g. URLs).
    """
    # Remove multi-line comments
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)

    # Process line-by-line for single-line comments
    cleaned_lines = []
    for line in text.splitlines():
        in_string = False
        escape = False
        res = []
        i = 0
        while i < len(line):
            ch = line[i]
            if escape:
                res.append(ch)
                escape = False
            elif ch == '\\' and in_string:
                res.append(ch)
                escape = True
            elif ch == '"':
                in_string = not in_string
                res.append(ch)
            elif not in_string and (line[i:i+2] == '//' or ch == '#'):
                break
            else:
                res.append(ch)
            i += 1
        cleaned_lines.append(''.join(res))
    return '\n'.join(cleaned_lines)


DEFAULT_CONFIG_DOCUMENTED = """{
    // =========================================================================
    // Orvo - User Configuration
    // =========================================================================

    // Hotkey and trigger settings
    "hotkey": {
        // Hotkey string: e.g. "<alt>+<grave>", "<ctrl>+<alt>+<space>", "F8", "<alt>+<space>"
        "key": "<alt>+<grave>",
        // Mode: "push_to_talk" (hold while speaking) or "toggle" (press to start/stop)
        "mode": "toggle",
        // Rapid bounce debounce threshold in milliseconds
        "debounce_ms": 150
    },

    // Microphone and audio capture settings
    "audio": {
        // Device index (null uses Windows default recording device)
        "device_index": null,
        // Audio sample rate (Whisper model requires 16000 Hz)
        "sample_rate": 16000,
        // Mono audio channels
        "channels": 1,
        // Synthesized sound effects (start/stop beeps)
        "sound_effects": false,
        // Trim leading and trailing silence before Whisper inference
        "silence_trim": true,
        // Silence threshold in decibels (-48.0 ensures soft speech/consonants are not cut)
        "silence_threshold_db": -48.0,
        // Padding in ms retained around speech
        "pad_duration_ms": 350,
        // Normalize peak volume
        "normalize_audio": true
    },

    // Speech-to-text inference engine and model
    "model": {
        // Backend: "local" (faster-whisper), "groq" (cloud), or "openai" (cloud)
        "backend": "local",
        // Local model: "tiny.en", "base.en", "small.en", "medium.en"
        "local_model": "base.en",
        // Compute quantization: "int8", "float16", "float32"
        "compute_type": "int8",
        // Compute device: "auto", "cpu", "cuda"
        "device": "auto",
        // Beam search size (5 provides superior sentence accuracy and context)
        "beam_size": 5,
        // Initial conditioning prompt to guide sentence formatting and coherence
        "initial_prompt": "Hello, welcome to Orvo voice dictation. Please speak clearly, with proper punctuation.",
        // Built-in VAD filter in faster-whisper (false allows full speech capture)
        "vad_filter": false,
        // Cloud API keys
        "groq_api_key": "",
        "groq_model": "whisper-large-v3-turbo",
        "openai_api_key": "",
        "openai_model": "whisper-1",
        // Language code: "en" or null for auto-detect
        "language": "en"
    },

    // Text formatting and paste injection
    "text": {
        // Automatically capitalize first letter of transcriptions
        "auto_capitalize": true,
        // Automatically ensure sentence punctuation
        "auto_punctuate": true,
        // Intelligent sentence formation and context restructuring
        "smart_sentence_formation": true,
        // Clean speech hesitation fillers (um, uh, erm)
        "remove_fillers": true,
        // Remove repetition stutters from hesitations
        "fix_disfluencies": true,
        // Convert spoken voice commands (e.g. "new line", "period", "bullet point")
        "voice_commands": true,
        // Delay in ms for target window WM_PASTE processing before restoring clipboard
        "paste_delay_ms": 120,
        // Direct keystroke typing fallback if clipboard is locked
        "fallback_to_typing": true
    },

    // User Interface and HUD Overlay
    "ui": {
        // Show floating HUD overlay
        "show_hud": true,
        // HUD style: "square" (minimalist black square with white border and status icon)
        "hud_style": "square",
        // HUD position: "near_cursor", "bottom_right", "bottom_center", "top_center"
        "hud_position": "near_cursor",
        // Audio feedback chime toggle
        "sound_feedback": false,
        // Windows balloon tray notifications
        "tray_notifications": false,
        // Maximum dictations retained in history log
        "history_limit": 100,
        // Start minimized to system tray
        "start_minimized_to_tray": true
    }
}
"""


@dataclass
class HotkeyConfig:
    key: str = "<alt>+<grave>"
    mode: str = "toggle"  # "push_to_talk" or "toggle"
    debounce_ms: int = 150

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HotkeyConfig":
        key = str(data.get("key", "<alt>+<grave>")).strip() or "<alt>+<grave>"
        raw_mode = str(data.get("mode", "toggle")).strip().lower()
        mode = "push_to_talk" if raw_mode == "push_to_talk" else "toggle"
        try:
            debounce_ms = max(0, int(data.get("debounce_ms", 150)))
        except (ValueError, TypeError):
            debounce_ms = 150
        return cls(key=key, mode=mode, debounce_ms=debounce_ms)


@dataclass
class AudioConfig:
    device_index: Optional[int] = None
    sample_rate: int = 16000
    channels: int = 1
    sound_effects: bool = False
    silence_trim: bool = True
    silence_threshold_db: float = -48.0
    pad_duration_ms: int = 350
    normalize_audio: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AudioConfig":
        raw_dev = data.get("device_index", None)
        device_index = None
        if raw_dev is not None:
            try:
                device_index = int(raw_dev)
            except (ValueError, TypeError):
                device_index = None

        try:
            sample_rate = int(data.get("sample_rate", 16000))
        except (ValueError, TypeError):
            sample_rate = 16000

        try:
            channels = max(1, int(data.get("channels", 1)))
        except (ValueError, TypeError):
            channels = 1

        sound_effects = bool(data.get("sound_effects", False))
        silence_trim = bool(data.get("silence_trim", True))

        try:
            silence_threshold_db = float(data.get("silence_threshold_db", -48.0))
        except (ValueError, TypeError):
            silence_threshold_db = -48.0

        try:
            pad_duration_ms = max(50, int(data.get("pad_duration_ms", 350)))
        except (ValueError, TypeError):
            pad_duration_ms = 350

        normalize_audio = bool(data.get("normalize_audio", True))

        return cls(
            device_index=device_index,
            sample_rate=sample_rate,
            channels=channels,
            sound_effects=sound_effects,
            silence_trim=silence_trim,
            silence_threshold_db=silence_threshold_db,
            pad_duration_ms=pad_duration_ms,
            normalize_audio=normalize_audio,
        )


@dataclass
class ModelConfig:
    backend: str = "local"  # "local", "groq", "openai"
    local_model: str = "base.en"  # "tiny.en", "base.en", "small.en", "medium.en"
    compute_type: str = "int8"  # "int8", "float16", "float32"
    device: str = "auto"  # "auto", "cpu", "cuda"
    beam_size: int = 5
    initial_prompt: str = "Orvo dictation: accurate transcription of spoken English into clear, coherent, well-structured sentences with proper grammar and punctuation."
    vad_filter: bool = False
    groq_api_key: str = ""
    groq_model: str = "whisper-large-v3-turbo"
    openai_api_key: str = ""
    openai_model: str = "whisper-1"
    language: str = "en"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelConfig":
        raw_backend = str(data.get("backend", "local")).strip().lower()
        backend = raw_backend if raw_backend in ("local", "groq", "openai") else "local"

        local_model = str(data.get("local_model", "base.en")).strip() or "base.en"
        raw_compute = str(data.get("compute_type", "int8")).strip().lower()
        compute_type = raw_compute if raw_compute in ("int8", "float16", "float32", "auto") else "int8"

        raw_device = str(data.get("device", "auto")).strip().lower()
        device = raw_device if raw_device in ("auto", "cpu", "cuda") else "auto"

        try:
            beam_size = max(1, int(data.get("beam_size", 5)))
        except (ValueError, TypeError):
            beam_size = 5

        initial_prompt = str(data.get(
            "initial_prompt",
            "Orvo dictation: accurate transcription of spoken English into clear, coherent, well-structured sentences with proper grammar and punctuation."
        ))
        vad_filter = bool(data.get("vad_filter", False))

        groq_api_key = str(data.get("groq_api_key", "")).strip()
        groq_model = str(data.get("groq_model", "whisper-large-v3-turbo")).strip() or "whisper-large-v3-turbo"
        openai_api_key = str(data.get("openai_api_key", "")).strip()
        openai_model = str(data.get("openai_model", "whisper-1")).strip() or "whisper-1"
        language = str(data.get("language", "en")).strip() or "en"

        return cls(
            backend=backend,
            local_model=local_model,
            compute_type=compute_type,
            device=device,
            beam_size=beam_size,
            initial_prompt=initial_prompt,
            vad_filter=vad_filter,
            groq_api_key=groq_api_key,
            groq_model=groq_model,
            openai_api_key=openai_api_key,
            openai_model=openai_model,
            language=language,
        )


@dataclass
class TextConfig:
    auto_capitalize: bool = True
    auto_punctuate: bool = True
    smart_sentence_formation: bool = True
    remove_fillers: bool = True
    fix_disfluencies: bool = True
    voice_commands: bool = True
    paste_delay_ms: int = 120
    fallback_to_typing: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TextConfig":
        auto_capitalize = bool(data.get("auto_capitalize", True))
        auto_punctuate = bool(data.get("auto_punctuate", True))
        smart_sentence_formation = bool(data.get("smart_sentence_formation", True))
        remove_fillers = bool(data.get("remove_fillers", True))
        fix_disfluencies = bool(data.get("fix_disfluencies", True))
        voice_commands = bool(data.get("voice_commands", True))
        try:
            paste_delay_ms = max(0, int(data.get("paste_delay_ms", 120)))
        except (ValueError, TypeError):
            paste_delay_ms = 120
        fallback_to_typing = bool(data.get("fallback_to_typing", True))

        return cls(
            auto_capitalize=auto_capitalize,
            auto_punctuate=auto_punctuate,
            smart_sentence_formation=smart_sentence_formation,
            remove_fillers=remove_fillers,
            fix_disfluencies=fix_disfluencies,
            voice_commands=voice_commands,
            paste_delay_ms=paste_delay_ms,
            fallback_to_typing=fallback_to_typing,
        )


@dataclass
class UIConfig:
    show_hud: bool = True
    hud_style: str = "square"  # "square" (Gemini squircle with smooth colorful border), "pill"
    hud_position: str = "bottom_right"  # "bottom_right", "near_cursor", "bottom_center", "top_center"
    sound_feedback: bool = False
    tray_notifications: bool = False
    history_limit: int = 100
    start_minimized_to_tray: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UIConfig":
        show_hud = bool(data.get("show_hud", True))
        raw_style = str(data.get("hud_style", "square")).strip().lower()
        hud_style = "pill" if raw_style == "pill" else "square"

        raw_pos = str(data.get("hud_position", "bottom_right")).strip().lower()
        valid_positions = {"near_cursor", "bottom_right", "bottom_center", "top_center"}
        hud_position = raw_pos if raw_pos in valid_positions else "bottom_right"

        sound_feedback = bool(data.get("sound_feedback", False))
        tray_notifications = bool(data.get("tray_notifications", False))

        try:
            history_limit = max(1, min(1000, int(data.get("history_limit", 100))))
        except (ValueError, TypeError):
            history_limit = 100

        start_minimized_to_tray = bool(data.get("start_minimized_to_tray", True))

        return cls(
            show_hud=show_hud,
            hud_style=hud_style,
            hud_position=hud_position,
            sound_feedback=sound_feedback,
            tray_notifications=tray_notifications,
            history_limit=history_limit,
            start_minimized_to_tray=start_minimized_to_tray,
        )


@dataclass
class AppConfig:
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    text: TextConfig = field(default_factory=TextConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        if not isinstance(data, dict):
            return cls()
        return cls(
            hotkey=HotkeyConfig.from_dict(data.get("hotkey", {})),
            audio=AudioConfig.from_dict(data.get("audio", {})),
            model=ModelConfig.from_dict(data.get("model", {})),
            text=TextConfig.from_dict(data.get("text", {})),
            ui=UIConfig.from_dict(data.get("ui", {})),
        )


class ConfigManager:
    """Thread-safe configuration manager with schema validation and hot-reloading."""
    _instance: Optional["ConfigManager"] = None
    _lock = threading.Lock()

    def __new__(cls, config_path: Optional[str] = None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ConfigManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, config_path: Optional[str] = None):
        if self._initialized:
            return
        self.config_path = os.path.abspath(config_path or CONFIG_FILE_PATH)
        self.config = AppConfig()
        self._rw_lock = threading.RLock()
        self._last_mtime: float = 0.0
        self._reload_callbacks: List[Callable[[AppConfig], None]] = []
        self.load()
        self._initialized = True

    def register_on_reload(self, callback: Callable[[AppConfig], None]) -> None:
        """Register callback triggered whenever configuration is reloaded from disk."""
        with self._rw_lock:
            if callback not in self._reload_callbacks:
                self._reload_callbacks.append(callback)

    def load(self) -> AppConfig:
        """Loads configuration from JSON file (comment-tolerant) or writes default if missing."""
        with self._rw_lock:
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path, "r", encoding="utf-8") as f:
                        raw_content = f.read()
                    clean_content = strip_json_comments(raw_content)
                    data = json.loads(clean_content)
                    self.config = AppConfig.from_dict(data)
                    self._last_mtime = os.path.getmtime(self.config_path)
                    logger.info("Loaded configuration from %s", self.config_path)
                except Exception as e:
                    logger.warning("Failed to parse %s (%s). Using safe defaults.", self.config_path, e)
                    self.config = AppConfig()
                    self.save()
            else:
                self.config = AppConfig()
                self._save_default_documented()

            return self.config

    def _save_default_documented(self) -> None:
        """Creates new config.json with complete in-line documentation and comments."""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                f.write(DEFAULT_CONFIG_DOCUMENTED)
            self._last_mtime = os.path.getmtime(self.config_path)
            logger.info("Generated documented configuration at %s", self.config_path)
        except Exception as e:
            logger.error("Error creating default config file: %s", e)

    def save(self) -> None:
        """Saves current configuration to JSON file."""
        with self._rw_lock:
            try:
                os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(self.config.to_dict(), f, indent=4)
                self._last_mtime = os.path.getmtime(self.config_path)
                logger.debug("Configuration saved to %s", self.config_path)
            except Exception as e:
                logger.error("Error saving configuration: %s", e)

    def check_and_reload(self) -> bool:
        """
        Hot-reloading check: If config.json on disk has been modified, reloads it.
        Returns True if reloaded, False otherwise.
        """
        with self._rw_lock:
            if not os.path.exists(self.config_path):
                return False
            try:
                mtime = os.path.getmtime(self.config_path)
                if mtime > self._last_mtime:
                    logger.info("Detected on-disk configuration change. Hot-reloading...")
                    self.load()
                    for cb in self._reload_callbacks:
                        try:
                            cb(self.config)
                        except Exception as exc:
                            logger.error("Error in config reload callback: %s", exc)
                    return True
            except Exception as e:
                logger.debug("Error checking config mtime: %s", e)
        return False

    def get(self) -> AppConfig:
        with self._rw_lock:
            return self.config

    def update(self, **kwargs) -> None:
        """Update top-level configuration sections and persist to disk."""
        with self._rw_lock:
            for k, v in kwargs.items():
                if hasattr(self.config, k):
                    setattr(self.config, k, v)
            self.save()


# Global accessors
def get_config() -> AppConfig:
    return ConfigManager().get()

def save_config() -> None:
    ConfigManager().save()
