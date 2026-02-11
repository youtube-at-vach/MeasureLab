import unittest
from unittest.mock import MagicMock, patch, mock_open
import os
from src.core.config_manager import ConfigManager

class TestConfigManagerLifecycle(unittest.TestCase):
    def setUp(self):
        self.config_path = "test_config.json"
        self.mock_logger = MagicMock()

        # Patch logger to avoid cluttering output
        self.logger_patcher = patch('src.core.config_manager.logging.getLogger', return_value=self.mock_logger)
        self.logger_patcher.start()

        # Prevent actual file IO
        self.open_patcher = patch('os.open', return_value=123)
        self.mock_open_fd = self.open_patcher.start()

        self.fdopen_patcher = patch('os.fdopen')
        self.mock_fdopen = self.fdopen_patcher.start()

        self.chmod_patcher = patch('os.chmod')
        self.mock_chmod = self.chmod_patcher.start()

    def tearDown(self):
        self.chmod_patcher.stop()
        self.fdopen_patcher.stop()
        self.open_patcher.stop()
        self.logger_patcher.stop()
        if os.path.exists(self.config_path):
            os.remove(self.config_path)

        # Clear instances to prevent atexit from flushing them to disk
        ConfigManager._instances.clear()

    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.os.makedirs')
    @patch('src.core.config_manager.locale.getlocale')
    def test_load_defaults_when_file_missing(self, mock_getlocale, mock_makedirs, mock_exists):
        """Test that default config is loaded when file does not exist."""
        mock_exists.return_value = False
        # Mock locale to avoid non-deterministic behavior based on system
        mock_getlocale.return_value = ('en_US', 'UTF-8')

        cm = ConfigManager(self.config_path)

        # Check defaults are loaded
        self.assertEqual(cm.config['audio']['sample_rate'], 48000)
        # Check screenshot dir ensured
        mock_makedirs.assert_called()
        cm.shutdown()

    @patch('src.core.config_manager.os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data='{"audio": {"sample_rate": 96000}}')
    @patch('src.core.config_manager.os.makedirs')
    def test_load_valid_file(self, mock_makedirs, mock_file, mock_exists):
        """Test loading a valid configuration file."""
        mock_exists.return_value = True

        cm = ConfigManager(self.config_path)

        self.assertEqual(cm.config['audio']['sample_rate'], 96000)
        # Verify defaults are merged (e.g. block_size should still be default)
        self.assertEqual(cm.config['audio']['block_size'], 1024)
        cm.shutdown()

    @patch('src.core.config_manager.os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data='{invalid_json')
    @patch('src.core.config_manager.os.makedirs')
    def test_load_corrupt_file(self, mock_makedirs, mock_file, mock_exists):
        """Test fallback to defaults when JSON is invalid."""
        mock_exists.return_value = True
        # Make json.load raise JSONDecodeError.
        # mock_open read_data handles the read, but we need json.load to fail.
        # Easier to mock json.load directly or let it parse the invalid string.
        # The mock_open read_data string '{invalid_json' will cause json.load to fail naturally.

        cm = ConfigManager(self.config_path)

        # Verify fallback to default
        self.assertEqual(cm.config['audio']['sample_rate'], 48000)
        self.mock_logger.error.assert_called()
        cm.shutdown()

    @patch('src.core.config_manager.threading.Timer')
    @patch('src.core.config_manager.os.path.exists', return_value=False)
    @patch('src.core.config_manager.os.makedirs')
    def test_save_config_debounced(self, mock_makedirs, mock_exists, mock_timer_cls):
        """Test that save_config starts a timer instead of writing immediately."""
        cm = ConfigManager(self.config_path)
        mock_timer_inst = MagicMock()
        mock_timer_cls.return_value = mock_timer_inst

        # Call save without force_sync
        cm.save_config(force_sync=False)

        # Verify timer started
        mock_timer_cls.assert_called_with(1.0, cm._flush_config)
        mock_timer_inst.start.assert_called_once()

        # Verify subsequent save cancels previous timer
        cm.save_config(force_sync=False)
        mock_timer_inst.cancel.assert_called_once()
        cm.shutdown()

    @patch('src.core.config_manager.os.path.exists', return_value=False)
    @patch('src.core.config_manager.os.makedirs')
    @patch('src.core.config_manager.os.open')
    @patch('src.core.config_manager.os.fdopen')
    @patch('src.core.config_manager.os.chmod')
    def test_save_config_force_sync(self, mock_chmod, mock_fdopen, mock_open, mock_makedirs, mock_exists):
        """Test that force_sync writes immediately."""
        # Setup mocks
        mock_open.return_value = 123
        mock_file_handle = MagicMock()
        mock_fdopen.return_value.__enter__.return_value = mock_file_handle

        cm = ConfigManager(self.config_path)

        cm.config['audio']['sample_rate'] = 88200
        cm.save_config(force_sync=True)

        # Verify os.open called with correct flags and mode
        # 0o600 = 384
        expected_flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mock_open.assert_called_with(self.config_path, expected_flags, 0o600)

        # Verify os.fdopen called
        mock_fdopen.assert_called_with(123, 'w')

        # Verify chmod called
        mock_chmod.assert_called_with(self.config_path, 0o600)

        cm.shutdown()

    @patch('src.core.config_manager.os.path.exists', return_value=False)
    @patch('src.core.config_manager.os.makedirs')
    def test_resolve_path_security(self, mock_makedirs, mock_exists):
        """Test path traversal prevention."""
        cm = ConfigManager(self.config_path)

        # Assume config_dir is where self.config_path is (relative or absolute)
        # For this test, we can mock os.path.abspath to control the base dir logic
        # but it's easier to rely on real path logic if we are careful.
        # Or better, just test that '..' raises ValueError.

        with self.assertRaises(ValueError):
            cm._resolve_path("../outside_dir")

        with self.assertRaises(ValueError):
            cm._resolve_path("subdir/../../etc/passwd")

        # Valid path
        try:
            path = cm._resolve_path("screenshots")
            self.assertTrue(path.endswith("screenshots"))
        except ValueError:
            self.fail("_resolve_path raised ValueError on valid path")
        cm.shutdown()

    @patch('src.core.config_manager.os.path.exists', return_value=False)
    @patch('src.core.config_manager.os.makedirs')
    @patch('src.core.config_manager.threading.Timer')
    def test_setters_trigger_save(self, mock_timer, mock_makedirs, mock_exists):
        """Test that setters update config and trigger save."""
        cm = ConfigManager(self.config_path)

        cm.set_language('fr')
        self.assertEqual(cm.config['language'], 'fr')
        mock_timer.return_value.start.assert_called()

        mock_timer.reset_mock()
        cm.set_theme('dark')
        self.assertEqual(cm.config['theme'], 'dark')
        mock_timer.return_value.start.assert_called()

        mock_timer.reset_mock()
        cm.set_audio_config("In", "Out", 44100, 512, "stereo", "stereo")
        self.assertEqual(cm.config['audio']['sample_rate'], 44100)
        mock_timer.return_value.start.assert_called()

        cm.shutdown()

    @patch('src.core.config_manager.os.path.exists', return_value=False)
    @patch('src.core.config_manager.os.makedirs')
    def test_screenshot_dir_fallback(self, mock_makedirs, mock_exists):
        """Test fallback for screenshot directory."""
        cm = ConfigManager(self.config_path)

        # Inject invalid path traversal into config (e.g. if loaded from malicious file)
        cm.config['screenshot']['output_dir'] = "../bad_path"

        # Verify getter returns default safe path
        out_dir = cm.get_screenshot_output_dir()
        # Should fall back to <config_dir>/screenshots
        expected = os.path.join(cm.config_dir, "screenshots")
        self.assertEqual(out_dir, expected)
        cm.shutdown()

    @patch('src.core.config_manager.os.path.exists', return_value=False)
    @patch('src.core.config_manager.os.makedirs')
    def test_shutdown_flushes_config(self, mock_makedirs, mock_exists):
        """Test that shutdown flushes pending config."""
        cm = ConfigManager(self.config_path)

        # Start a save timer
        with patch('src.core.config_manager.threading.Timer') as mock_timer_cls:
            mock_timer = MagicMock()
            mock_timer_cls.return_value = mock_timer
            cm.save_config(force_sync=False)

            # Shutdown
            with patch('src.core.config_manager.os.open') as mock_open, \
                 patch('src.core.config_manager.os.fdopen') as mock_fdopen, \
                 patch('src.core.config_manager.os.chmod') as mock_chmod:

                 mock_open.return_value = 123

                 cm.shutdown()

                 # Timer cancelled
                 mock_timer.cancel.assert_called()
                 # File written
                 mock_open.assert_called()
                 mock_fdopen.assert_called()
                 mock_chmod.assert_called()

    @patch('src.core.config_manager.os.path.exists', return_value=False)
    @patch('src.core.config_manager.os.makedirs')
    @patch('src.core.config_manager.os.open')
    def test_flush_config_os_error(self, mock_open, mock_makedirs, mock_exists):
        """Test error handling when file open fails during save."""
        # Setup mocks
        mock_open.side_effect = OSError("Permission denied")

        cm = ConfigManager(self.config_path)

        # Trigger save
        cm.save_config(force_sync=True)

        # Verify error logged
        self.mock_logger.error.assert_called_with("Failed to save config: Permission denied")
        cm.shutdown()

    def test_flush_all_logs_exception(self):
        """Test that _flush_all logs exceptions from instance shutdown."""
        mock_instance = MagicMock()
        mock_instance.config_path = "test_path.json"
        exception = Exception("Crash")
        mock_instance.shutdown.side_effect = exception

        # Manually add to _instances
        ConfigManager._instances.add(mock_instance)
        try:
            ConfigManager._flush_all()
        finally:
            if mock_instance in ConfigManager._instances:
                ConfigManager._instances.remove(mock_instance)

        expected_msg = f"Error shutting down ConfigManager (path=test_path.json): {exception}"
        self.mock_logger.error.assert_called_with(expected_msg)

    @patch('src.core.config_manager.os.path.exists', return_value=False)
    @patch('src.core.config_manager.os.makedirs')
    @patch('src.core.config_manager.os.open')
    @patch('src.core.config_manager.os.fdopen')
    @patch('src.core.config_manager.os.chmod')
    def test_flush_config_chmod_failure_logging(self, mock_chmod, mock_fdopen, mock_open, mock_makedirs, mock_exists):
        """Test that chmod failure in _flush_config is logged."""
        # Setup mocks
        mock_open.return_value = 123
        mock_file_handle = MagicMock()
        mock_fdopen.return_value.__enter__.return_value = mock_file_handle

        # Make chmod raise an exception
        mock_chmod.side_effect = OSError("Permission denied for chmod")

        cm = ConfigManager(self.config_path)

        # Trigger save
        cm.save_config(force_sync=True)

        # Verify warning logged
        self.mock_logger.warning.assert_called()
        # Verify the message content (approximate match)
        found = False
        for call in self.mock_logger.warning.call_args_list:
            args, _ = call
            if "Unable to set secure permissions for config file" in args[0]:
                found = True
                break
        self.assertTrue(found, "Expected warning log not found")
        cm.shutdown()

if __name__ == '__main__':
    unittest.main()
