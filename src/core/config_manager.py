import locale
import json
import logging
import os
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
    },
    "language": "en",
    "theme": "system",
    "screenshot": {
        "output_dir": "screenshots",
    },
}


class ConfigManager:
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.logger = logging.getLogger(self.__class__.__name__)
        self.config_dir = os.path.dirname(os.path.abspath(self.config_path)) or os.getcwd()
        self.config = self.load_config()

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
            return config

        try:
            with open(self.config_path, "r") as f:
                loaded = json.load(f)
            config = self._merge_with_defaults(loaded)
            self._ensure_screenshot_dir(config)
            return config
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            config = self._default_config()
            self._ensure_screenshot_dir(config)
            return config

    def save_config(self):
        """Saves current configuration to JSON file."""
        try:
            with open(self.config_path, "w") as f:
                json.dump(self.config, f, indent=4)
            self.logger.info("Config saved.")
        except Exception as e:
            self.logger.error(f"Failed to save config: {e}")

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
            return path_value
        return os.path.join(self.config_dir, path_value)

    def _ensure_screenshot_dir(self, config):
        out_dir = self._resolve_path(config["screenshot"].get("output_dir", "screenshots"))
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as exc:  # PermissionError, OSError
            self.logger.warning(f"Unable to ensure screenshot directory at {out_dir}: {exc}")
        return out_dir

    def get_audio_config(self):
        """Returns a dictionary of audio configuration."""
        return self.config.get("audio", self._default_config()["audio"])

    # --- Legacy API (kept for backward compatibility with older tests/tools) ---
    def get_last_devices(self):
        audio = self.get_audio_config()
        return audio.get("input_device"), audio.get("output_device")

    def set_last_devices(self, input_name, output_name, input_hostapi=None, output_hostapi=None):
        audio = self.get_audio_config()
        self.set_audio_config(
            input_name=input_name,
            output_name=output_name,
            sample_rate=audio.get("sample_rate", 48000),
            block_size=audio.get("block_size", 1024),
            in_ch=audio.get("input_channels", "stereo"),
            out_ch=audio.get("output_channels", "stereo"),
            input_hostapi=input_hostapi,
            output_hostapi=output_hostapi,
        )

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
        return self._resolve_path(str(out_dir))

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

            lang_code = loc[0].split("_")[0]  # e.g., 'ja' from 'ja_JP'

            # Check if this language is supported
            # We check if src/assets/lang/{lang_code}.json exists
            # We need to be careful about the path. Using resource_path helper.
            lang_file = resource_path(f"src/assets/lang/{lang_code}.json")
            if os.path.exists(lang_file):
                return lang_code

            return None
        except Exception as e:
            self.logger.warning(f"Failed to detect system language: {e}")
            return None
