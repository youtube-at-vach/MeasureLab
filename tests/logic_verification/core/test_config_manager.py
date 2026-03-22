import os
import sys
import tempfile
import unittest
import json
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        # Patch sys.modules to mock PyQt6 dependencies BEFORE importing ConfigManager
        self.modules_patcher = patch.dict(sys.modules, {"PyQt6": MagicMock(), "PyQt6.QtCore": MagicMock()})
        self.modules_patcher.start()

        from src.core.config_manager import ConfigManager, DEFAULT_CONFIG

        self.ConfigManager = ConfigManager
        self.DEFAULT_CONFIG = DEFAULT_CONFIG

        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "config.json")

        self.mock_logger = MagicMock()
        self.logger_patcher = patch("src.core.config_manager.logging.getLogger", return_value=self.mock_logger)
        self.logger_patcher.start()

        if hasattr(self.ConfigManager, "_instances"):
            self.ConfigManager._instances.clear()

    def tearDown(self):
        self.logger_patcher.stop()
        self.modules_patcher.stop()
        self.temp_dir.cleanup()

    def test_audio_config_getters_setters(self):
        cm = self.ConfigManager(config_filename=self.config_path)

        # Test set_audio_config
        cm.set_audio_config(
            input_name="In1",
            output_name="Out1",
            sample_rate=44100,
            block_size=512,
            in_ch="mono",
            out_ch="stereo",
            input_hostapi="ALSA",
            output_hostapi="ALSA",
        )
        audio_cfg = cm.get_audio_config()
        self.assertEqual(audio_cfg["input_device"], "In1")
        self.assertEqual(audio_cfg["sample_rate"], 44100)

        # Missing audio dict
        cm.config.pop("audio", None)
        cm.set_audio_config("In2", "Out2", 48000, 1024, "stereo", "stereo")
        self.assertEqual(cm.get_audio_config()["input_device"], "In2")

    def test_pipewire_jack_resident(self):
        cm = self.ConfigManager(config_filename=self.config_path)

        self.assertFalse(cm.get_pipewire_jack_resident())

        cm.set_pipewire_jack_resident(True)
        self.assertTrue(cm.get_pipewire_jack_resident())

        cm.config.pop("audio", None)
        cm.set_pipewire_jack_resident(False)
        self.assertFalse(cm.get_pipewire_jack_resident())

    def test_offline_mode(self):
        cm = self.ConfigManager(config_filename=self.config_path)

        self.assertFalse(cm.is_offline_mode())
        cm.set_offline_mode(True)
        self.assertTrue(cm.is_offline_mode())

        cm.config.pop("audio", None)
        cm.set_offline_mode(False)
        self.assertFalse(cm.is_offline_mode())

    def test_offline_sample_rate(self):
        cm = self.ConfigManager(config_filename=self.config_path)

        self.assertEqual(cm.get_offline_sample_rate(), 48000)
        cm.set_offline_sample_rate(96000)
        self.assertEqual(cm.get_offline_sample_rate(), 96000)

        cm.config.pop("audio", None)
        cm.set_offline_sample_rate(44100)
        self.assertEqual(cm.get_offline_sample_rate(), 44100)

    def test_dithering_bit_depth(self):
        cm = self.ConfigManager(config_filename=self.config_path)

        self.assertEqual(cm.get_dithering_bit_depth(), "24")
        cm.set_dithering_bit_depth("16")
        self.assertEqual(cm.get_dithering_bit_depth(), "16")

        cm.config.pop("audio", None)
        cm.set_dithering_bit_depth("24")
        self.assertEqual(cm.get_dithering_bit_depth(), "24")

    def test_theme(self):
        cm = self.ConfigManager(config_filename=self.config_path)

        self.assertEqual(cm.get_theme(), "system")
        cm.set_theme("dark")
        self.assertEqual(cm.get_theme(), "dark")

    def test_screenshot_output_dir_getters(self):
        cm = self.ConfigManager(config_filename=self.config_path)

        cm.config["screenshot"] = {"output_dir": "test_dir"}
        with patch.object(cm, "_resolve_path", return_value="/resolved/test_dir"):
            self.assertEqual(cm.get_screenshot_output_dir(), "/resolved/test_dir")

        cm.config["screenshot"] = "not_a_dict"
        self.assertEqual(cm.get_screenshot_output_dir(), "screenshots")

        cm.config["screenshot"] = {}
        # when dict exists but "output_dir" key is missing, it falls back to "screenshots"
        # which is then passed to _resolve_path
        with patch.object(cm, "_resolve_path", return_value="/resolved/screenshots"):
            self.assertEqual(cm.get_screenshot_output_dir(), "/resolved/screenshots")

        cm.config["screenshot"] = {"output_dir": ""}
        self.assertEqual(cm.get_screenshot_output_dir(), "screenshots")

        cm.config["screenshot"] = {"output_dir": "test_dir"}
        with patch.object(cm, "_resolve_path", side_effect=Exception("Error")):
            with patch.object(cm, "_get_default_screenshot_dir", return_value="/default/dir"):
                self.assertEqual(cm.get_screenshot_output_dir(), "/default/dir")

    def test_resolve_config_path_oserror(self):
        with patch("src.core.config_manager.ConfigManager.get_user_data_dir", return_value="/invalid/dir"):
            with patch("os.makedirs", side_effect=OSError("Permission denied")):
                with patch("os.getcwd", return_value="/fallback/cwd"):
                    cm = self.ConfigManager(config_filename="config.json")
                    self.assertEqual(cm.config_path, os.path.join("/fallback/cwd", "config.json"))
                    self.mock_logger.warning.assert_called()

    def test_flush_all(self):
        cm1 = self.ConfigManager(config_filename=os.path.join(self.temp_dir.name, "c1.json"))
        cm2 = self.ConfigManager(config_filename=os.path.join(self.temp_dir.name, "c2.json"))

        with (
            patch.object(cm1, "shutdown") as mock_sd1,
            patch.object(cm2, "shutdown", side_effect=Exception("Error")) as mock_sd2,
        ):
            self.ConfigManager._flush_all()
            mock_sd1.assert_called_once()
            mock_sd2.assert_called_once()

    def test_load_config_not_dict(self):
        with open(self.config_path, "w") as f:
            json.dump(["not", "a", "dict"], f)

        cm = self.ConfigManager(config_filename=self.config_path)
        self.mock_logger.error.assert_called()
        self.assertIsInstance(cm.config, dict)

    def test_flush_config_chmod_error(self):
        cm = self.ConfigManager(config_filename=self.config_path)

        with patch("os.chmod", side_effect=Exception("Chmod error")):
            cm._flush_config()
            self.mock_logger.warning.assert_called_with("Failed to set secure permissions for config file: Chmod error")

    def test_ensure_screenshot_dir_exceptions(self):
        cm = self.ConfigManager(config_filename=self.config_path)
        cfg = {"screenshot": {"output_dir": "test"}}

        with patch.object(cm, "_resolve_path", side_effect=Exception("Resolve error")):
            with patch.object(cm, "_get_default_screenshot_dir", return_value="/default/shot"):
                with patch("os.makedirs", side_effect=PermissionError("No perm")):
                    out = cm._ensure_screenshot_dir(cfg)
                    self.assertEqual(out, "/default/shot")
                    self.mock_logger.warning.assert_any_call(
                        "Error resolving screenshot path: Resolve error. Reverting to default."
                    )
                    self.mock_logger.warning.assert_any_call(
                        "Unable to ensure screenshot directory at /default/shot: No perm"
                    )


if __name__ == "__main__":
    unittest.main()
