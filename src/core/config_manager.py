import locale
import json
import logging
import os
import threading
import atexit
import weakref
from copy import deepcopy

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

    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.logger = logging.getLogger(self.__class__.__name__)
        self.config_dir = os.path.dirname(os.path.abspath(self.config_path)) or os.getcwd()
        self.config = self.load_config()
        self._save_timer = None
        self._save_lock = threading.Lock()

        self._instances.add(self)
        if not ConfigManager._atexit_registered:
            atexit.register(ConfigManager._flush_all)
            ConfigManager._atexit_registered = True

    @classmethod
    def _flush_all(cls):
        """Flushes all active ConfigManager instances."""
        for instance in cls._instances:
            try:
                instance.shutdown()
            except Exception:
                pass

    def load_config(self):
        """Loads configuration from JSON file."""
        if not os.path.exists(self.config_path):
            self.logger.info("No config file found, creating default.")
            config = self._create_initial_config()
        else:
            try:
                with open(self.config_path, "r") as f:
                    loaded = json.load(f)
                config = self._merge_with_defaults(loaded)
            except Exception as e:
                self.logger.error(f"Failed to load config: {e}")
                config = self._default_config()

        self._ensure_screenshot_dir(config)
        return config

    def _create_initial_config(self):
        """Creates default configuration with auto-detected language."""
        config = self._default_config()
        # Auto-detect language on first run
        detected_lang = self._detect_system_language()
        if detected_lang:
            config["language"] = detected_lang
            self.logger.info(f"Auto-detected language: {detected_lang}")
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
                except Exception:
                    pass

                self.logger.info("Config saved.")
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
        """Detects the system locale and returns a supported language code, or None."""
        try:
            # getlocale() returns (language_code, encoding), e.g., ('ja_JP', 'UTF-8')
            # It may return (None, None) if not set.
            loc = locale.getlocale()
            if not loc or not loc[0]:
                # Fallback to getdefaultlocale() which might work even if setlocale wasn't called
                loc = locale.getdefaultlocale()

            if not loc or not loc[0]:
                return None

            lang_str = loc[0]

            # 1. Check explicit Windows mapping first
            # "Japanese_Japan" -> "Japanese" -> "ja"
            base_lang = lang_str.split("_")[0].lower()
            if base_lang in WINDOWS_LOCALE_MAP:
                lang_code = WINDOWS_LOCALE_MAP[base_lang]
            else:
                lang_code = base_lang

            # Checks if this language is supported
            # We check if src/assets/lang/{lang_code}.json exists
            lang_file = resource_path(f"src/assets/lang/{lang_code}.json")
            if os.path.exists(lang_file):
                return lang_code

            # Fallback for standard locales if not in map but file exists (e.g. ja_JP -> ja -> check file)
            # Already covered by else block above roughly, but let's be safe for cases like "en_US"
            # Split and try again if the map check failed or returned something invalid

            # If lang_code is still "Japanese" (because it wasn't in map for some reason) it fails check above.

            return None
        except Exception as e:
            self.logger.warning(f"Failed to detect system language: {e}")
            return None
