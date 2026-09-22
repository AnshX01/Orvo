"""
Orvo package.
"""

from src.config import AppConfig, get_config, save_config, ConfigManager
from src.transcriber import TranscriberManager
from src.text_injector import SafeTextInjector, ClipboardBackup

__version__ = "1.0.0"

__all__ = [
    "AppConfig",
    "get_config",
    "save_config",
    "ConfigManager",
    "TranscriberManager",
    "SafeTextInjector",
    "ClipboardBackup",
]
