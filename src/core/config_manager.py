import locale
import json
import logging
import os
import sys
import threading
import atexit
import weakref
from copy import deepcopy
from pathlib import Path

# Use QLocale for robust language detection on all platforms, including macOS
from PyQt6.QtCore import QLocale

from src.core.utils import resource_path

# Default configuration used for initialization and validation
DEFAULT_CONFIG = {
    "audio": {
        "input_device": None,
        "input_hostapi": None,
        "output_device": None,
        "output_hostapi": None,
        "sample_rate": 48000,
        "block_size": 1024,
        "input_channels": "stereo",
        "output_channels": "stereo",
        "pipewire_jack_resident": False,
        "offline_mode": False,
        "offline_sample_rate": 48000,
        "dithering_enabled": False,
        "dithering_bit_depth": "24",
    },
    "language": "en",
    "theme": "system",
    "screenshot": {
        "output_dir": "screenshots",
    },
}



# Mapping of Windows-specific language names to ISO 639-1 codes
# Windows getlocale() often returns full English names like "Japanese_Japan"
WINDOWS_LOCALE_MAP = {
    "japanese": "ja",
    "english": "en",
    "french": "fr",
    "german": "de",
    "spanish": "es",
    "chinese": "zh",
    "korean": "ko",
    "portuguese": "pt",
    "russian": "ru",
    # Add more as needed
}

class ConfigManager:
    _instances: weakref.WeakSet["ConfigManager"] = weakref.WeakSet()
    _atexit_registered = False

    def __init__(self, config_filename="config.json"):
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Determine the best path for the configuration file
        self.config_path = self._resolve_config_path(config_filename)
        self.config_dir = os.path.dirname(os.path.abspath(self.config_path))
        
        
        self.logger.info(f"Using config file at: {self.config_path}")

        self._save_timer = None
        self._save_lock = threading.Lock()
        self.config = self.load_config()

        self._instances.add(self)
        if not ConfigManager._atexit_registered:
            atexit.register(ConfigManager._flush_all)
            ConfigManager._atexit_registered = True

    @staticmethod
    def get_user_data_dir() -> str:
        """Returns the platform-specific user data directory for the application."""
        app_name = "MeasureLab"
        home = Path.home()

        if sys.platform == "win32":
            return os.path.join(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")), app_name)
        elif sys.platform == "darwin":
            return os.path.join(home, "Library", "Application Support", app_name)
        else:
            # Linux / Unix (XDG)
            xdg_config = os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))
            return os.path.join(xdg_config, app_name)

    def _resolve_config_path(self, filename: str) -> str:
        """
        Resolves the configuration file path.
        Priority:
        1. Existing file in current working directory (Portable mode).
        2. Platform-specific user data directory.
        """
        cwd_path = os.path.abspath(filename)
        if os.path.exists(cwd_path):
            return cwd_path
        
        # If explicit path provided (containing separators), use it directly
        if os.path.dirname(filename):
            return os.path.abspath(filename)

        # Otherwise, use user data directory
        user_dir = ConfigManager.get_user_data_dir()
        try:
            os.makedirs(user_dir, exist_ok=True)
        except OSError as e:
            self.logger.warning(f"Failed to create user data directory {user_dir}: {e}")
            # Fallback to CWD if we can't write to user dir
            return cwd_path
            
        return os.path.join(user_dir, filename)

    @classmethod
    def _flush_all(cls):
        """Flushes all active ConfigManager instances."""
        logger = logging.getLogger(cls.__name__)
        for instance in cls._instances:
            try:
                instance.shutdown()
            except Exception:
                logger.exception("Error during shutdown")

    def load_config(self):
        """Loads configuration from JSON file."""
        if not os.path.exists(self.config_path):
            self.logger.info("No config file found, creating default.")
            config = self._default_config()

            # Auto-detect language on first run
            detected_lang = self._detect_system_language()
            if detected_lang:
                config["language"] = detected_lang
                self.logger.info(f"Auto-detected language: {detected_lang}")

            self._ensure_screenshot_dir(config)
            # Save the new default config to disk immediately
            self.config = config
            self.save_config(force_sync=True)
            return config

        try:
            with open(self.config_path, "r") as f:
                loaded = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            self.logger.error(f"Failed to load config: {e}")
            config = self._default_config()
            self._ensure_screenshot_dir(config)
            return config

        config = self._merge_with_defaults(loaded)
        self._ensure_screenshot_dir(config)
        return config

    def _flush_config(self):
        """Internal method to immediately write config to disk."""
        with self._save_lock:
            try:
                # Use os.open to ensure secure permissions (600) on creation
                fd = os.open(self.config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as f:
                    json.dump(self.config, f, indent=4)

                # Ensure permissions on existing files (best effort)
                try:
                    os.chmod(self.config_path, 0o600)
                except Exception as e:
                    self.logger.warning(f"Failed to set secure permissions for config file: {e}")

                self.logger.debug("Config saved.")
                self._save_timer = None
            except Exception as e:
                self.logger.error(f"Failed to save config: {e}")

    def shutdown(self):
        """Cancels pending saves and writes immediately."""
        if self._save_timer:
            self._save_timer.cancel()
        self._flush_config()

    def save_config(self, force_sync=False):
        """Saves current configuration to JSON file.

        Args:
            force_sync (bool): If True, write immediately. If False, debounces write.
        """
        if force_sync:
            self.shutdown()
            return

        if self._save_timer:
            self._save_timer.cancel()

        self._save_timer = threading.Timer(1.0, self._flush_config)
        self._save_timer.start()

    def _default_config(self):
        return deepcopy(DEFAULT_CONFIG)

    def _merge_with_defaults(self, loaded_config):
        if not isinstance(loaded_config, dict):
            self.logger.warning("Config file root is not a dict; falling back to defaults.")
            return self._default_config()

        config = self._default_config()

        audio_loaded = loaded_config.get("audio", {})
        if isinstance(audio_loaded, dict):
            for key in config["audio"].keys():
                value = audio_loaded.get(key, config["audio"][key])
                config["audio"][key] = value
        else:
            self.logger.warning("'audio' section is missing or invalid; using defaults.")

        language = loaded_config.get("language")
        if isinstance(language, str) and language:
            config["language"] = language

        theme = loaded_config.get("theme")
        if isinstance(theme, str) and theme:
            config["theme"] = theme

        screenshot_loaded = loaded_config.get("screenshot", {})
        if isinstance(screenshot_loaded, dict):
            output_dir = screenshot_loaded.get("output_dir")
            if output_dir:
                config["screenshot"]["output_dir"] = str(output_dir)
        else:
            self.logger.warning("'screenshot' section is missing or invalid; using defaults.")

        return config

    def _resolve_path(self, path_value: str) -> str:
        if os.path.isabs(path_value):
            full_path = os.path.abspath(path_value)
        else:
            full_path = os.path.abspath(os.path.join(self.config_dir, path_value))

        base_dir = os.path.abspath(self.config_dir)

        try:
            if os.path.commonpath([base_dir, full_path]) != base_dir:
                raise ValueError(f"Path traversal detected: {path_value}")
        except ValueError as e:
            raise ValueError(f"Path resolution failed for {path_value}: {e}") from e

        return full_path

    def _ensure_screenshot_dir(self, config):
        try:
            out_dir = self._resolve_path(config["screenshot"].get("output_dir", "screenshots"))
        except ValueError as e:
            self.logger.warning(f"{e}. Reverting to default.")
            out_dir = os.path.join(self.config_dir, "screenshots")

        try:
            os.makedirs(out_dir, mode=0o700, exist_ok=True)
            try:
                os.chmod(out_dir, 0o700)
            except Exception as exc:
                self.logger.warning(f"Unable to set secure permissions for {out_dir}: {exc}")
        except Exception as exc:  # PermissionError, OSError
            self.logger.warning(f"Unable to ensure screenshot directory at {out_dir}: {exc}")
        return out_dir

    def get_audio_config(self):
        """Returns a dictionary of audio configuration."""
        return self.config.get("audio", self._default_config()["audio"])

    def set_audio_config(
        self,
        input_name,
        output_name,
        sample_rate,
        block_size,
        in_ch,
        out_ch,
        input_hostapi=None,
        output_hostapi=None,
    ):
        """Updates the audio configuration."""
        if "audio" not in self.config:
            self.config["audio"] = {}

        self.config["audio"]["input_device"] = input_name
        self.config["audio"]["input_hostapi"] = input_hostapi
        self.config["audio"]["output_device"] = output_name
        self.config["audio"]["output_hostapi"] = output_hostapi
        self.config["audio"]["sample_rate"] = sample_rate
        self.config["audio"]["block_size"] = block_size
        self.config["audio"]["input_channels"] = in_ch
        self.config["audio"]["output_channels"] = out_ch
        self.save_config()

    def get_pipewire_jack_resident(self) -> bool:
        """Returns whether PipeWire/JACK resident mode is enabled."""
        audio = self.get_audio_config()
        return bool(audio.get("pipewire_jack_resident", False))

    def set_pipewire_jack_resident(self, enabled: bool):
        """Enables/disables PipeWire/JACK resident mode."""
        if "audio" not in self.config:
            self.config["audio"] = {}
        self.config["audio"]["pipewire_jack_resident"] = bool(enabled)
        self.save_config()

    def is_offline_mode(self) -> bool:
        """Returns whether offline (virtual) mode is enabled."""
        audio = self.get_audio_config()
        return bool(audio.get("offline_mode", False))

    def set_offline_mode(self, enabled: bool):
        """Enables/disables offline mode."""
        if "audio" not in self.config:
            self.config["audio"] = {}
        self.config["audio"]["offline_mode"] = bool(enabled)
        self.save_config()

    def get_offline_sample_rate(self) -> int:
        """Returns the offline simulation sample rate."""
        audio = self.get_audio_config()
        return int(audio.get("offline_sample_rate", 48000))

    def set_offline_sample_rate(self, rate: int):
        """Sets the offline simulation sample rate."""
        if "audio" not in self.config:
            self.config["audio"] = {}
        self.config["audio"]["offline_sample_rate"] = int(rate)
        self.save_config()

    def is_dithering_enabled(self) -> bool:
        """Returns whether dithering is enabled."""
        audio = self.get_audio_config()
        return bool(audio.get("dithering_enabled", False))

    def set_dithering_enabled(self, enabled: bool):
        """Enables/disables dithering."""
        if "audio" not in self.config:
            self.config["audio"] = {}
        self.config["audio"]["dithering_enabled"] = bool(enabled)
        self.save_config()

    def get_dithering_bit_depth(self) -> str:
        """Returns the dithering bit depth setting ('16' or '24')."""
        audio = self.get_audio_config()
        return str(audio.get("dithering_bit_depth", "24"))

    def set_dithering_bit_depth(self, depth: str):
        """Sets the dithering bit depth."""
        if "audio" not in self.config:
            self.config["audio"] = {}
        self.config["audio"]["dithering_bit_depth"] = str(depth)
        self.save_config()

    def get_language(self):
        """Returns the saved language code, defaults to 'en'."""
        return self.config.get("language", "en")

    def set_language(self, lang_code):
        """Updates the language setting."""
        self.config["language"] = lang_code
        self.save_config()

    def get_theme(self):
        """Returns the saved theme, defaults to 'system'."""
        return self.config.get("theme", "system")

    def set_theme(self, theme_name):
        """Updates the theme setting."""
        self.config["theme"] = theme_name
        self.save_config()

    def get_screenshot_output_dir(self) -> str:
        """Returns the screenshot output directory (relative paths are allowed)."""
        screenshot = self.config.get("screenshot")
        if not isinstance(screenshot, dict):
            return "screenshots"
        out_dir = screenshot.get("output_dir", "screenshots")
        if not out_dir:
            return "screenshots"
        try:
            return self._resolve_path(str(out_dir))
        except ValueError:
            return os.path.join(self.config_dir, "screenshots")

    def set_screenshot_output_dir(self, output_dir: str):
        """Updates the screenshot output directory."""
        if "screenshot" not in self.config or not isinstance(self.config.get("screenshot"), dict):
            self.config["screenshot"] = {}
        self.config["screenshot"]["output_dir"] = str(output_dir)
        self._ensure_screenshot_dir(self.config)
        self.save_config()

    def _detect_system_language(self) -> str | None:
        """
        Detects the system locale using QLocale (primary) and locale module (fallback).
        Returns a supported language code (e.g., 'ja', 'en'), or None if detection fails/unsupported.
        """
        try:
            # 1. Try QLocale first (Most reliable on macOS/Windows)
            sys_locale = QLocale.system()
            lang_code = sys_locale.name().split("_")[0]  # e.g., "ja_JP" -> "ja"
            
            # Verify if we have a translation file for this
            lang_file = resource_path(f"src/assets/lang/{lang_code}.json")
            if os.path.exists(lang_file):
                return lang_code

            # 2. Fallback to standard python locale
            loc = locale.getlocale()
            if not loc or not loc[0]:
                loc = locale.getdefaultlocale()

            if loc and loc[0]:
                lang_str = loc[0]
                base_lang = lang_str.split("_")[0].lower()
                
                # Check Windows mapping
                if base_lang in WINDOWS_LOCALE_MAP:
                    base_lang = WINDOWS_LOCALE_MAP[base_lang]

                lang_file = resource_path(f"src/assets/lang/{base_lang}.json")
                if os.path.exists(lang_file):
                    return base_lang

            return None
        except Exception as e:
            self.logger.warning(f"Failed to detect system language: {e}")
            return None
