"""
Convenience wrapper for importing config from root.
"""
from src.config import get_config, save_config, AppConfig, ConfigManager, CONFIG_FILE_PATH, HotkeyConfig, AudioConfig, ModelConfig, TextConfig, UIConfig

__all__ = ["get_config", "save_config", "AppConfig", "ConfigManager", "CONFIG_FILE_PATH", "HotkeyConfig", "AudioConfig", "ModelConfig", "TextConfig", "UIConfig"]
