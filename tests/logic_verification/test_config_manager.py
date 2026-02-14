import os
import tempfile
import pytest
from src.core.config_manager import ConfigManager, DEFAULT_CONFIG

@pytest.fixture
def config_manager():
    """Fixture to provide a ConfigManager instance with a temporary config path."""
    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = os.path.join(temp_dir, "config.json")
        cm = ConfigManager(config_path=config_path)
        yield cm
        cm.shutdown()

def test_merge_with_defaults_none(config_manager):
    """Test that passing None to _merge_with_defaults returns defaults."""
    result = config_manager._merge_with_defaults(None)
    assert result == DEFAULT_CONFIG
    assert result is not DEFAULT_CONFIG  # Should return a copy

def test_merge_with_defaults_empty_dict(config_manager):
    """Test that passing an empty dict returns defaults."""
    result = config_manager._merge_with_defaults({})
    assert result == DEFAULT_CONFIG

def test_merge_with_defaults_audio_valid(config_manager):
    """Test merging valid audio settings."""
    loaded = {"audio": {"sample_rate": 96000, "block_size": 2048}}
    result = config_manager._merge_with_defaults(loaded)

    assert result["audio"]["sample_rate"] == 96000
    assert result["audio"]["block_size"] == 2048
    # Other fields should remain default
    assert result["audio"]["input_channels"] == DEFAULT_CONFIG["audio"]["input_channels"]

def test_merge_with_defaults_audio_partial(config_manager):
    """Test merging partial audio settings."""
    loaded = {"audio": {"sample_rate": 44100}}
    result = config_manager._merge_with_defaults(loaded)

    assert result["audio"]["sample_rate"] == 44100
    assert result["audio"]["block_size"] == DEFAULT_CONFIG["audio"]["block_size"]

def test_merge_with_defaults_audio_invalid_type(config_manager):
    """Test that non-dict audio section falls back to defaults."""
    loaded = {"audio": [1, 2, 3]}  # Invalid type (list)
    result = config_manager._merge_with_defaults(loaded)

    assert result["audio"] == DEFAULT_CONFIG["audio"]

def test_merge_with_defaults_audio_extra_keys(config_manager):
    """Test that extra keys in audio section are ignored."""
    loaded = {"audio": {"sample_rate": 48000, "extra_key": "value"}}
    result = config_manager._merge_with_defaults(loaded)

    assert result["audio"]["sample_rate"] == 48000
    assert "extra_key" not in result["audio"]

def test_merge_with_defaults_language(config_manager):
    """Test merging language setting."""
    loaded = {"language": "ja"}
    result = config_manager._merge_with_defaults(loaded)

    assert result["language"] == "ja"

def test_merge_with_defaults_theme(config_manager):
    """Test merging theme setting."""
    loaded = {"theme": "dark"}
    result = config_manager._merge_with_defaults(loaded)

    assert result["theme"] == "dark"

def test_merge_with_defaults_screenshot_valid(config_manager):
    """Test merging valid screenshot settings."""
    loaded = {"screenshot": {"output_dir": "custom_screens"}}
    result = config_manager._merge_with_defaults(loaded)

    assert result["screenshot"]["output_dir"] == "custom_screens"

def test_merge_with_defaults_screenshot_invalid_type(config_manager):
    """Test that non-dict screenshot section falls back to defaults."""
    loaded = {"screenshot": "invalid"}
    result = config_manager._merge_with_defaults(loaded)

    assert result["screenshot"] == DEFAULT_CONFIG["screenshot"]

def test_merge_with_defaults_screenshot_empty(config_manager):
    """Test that empty screenshot section uses defaults."""
    loaded = {"screenshot": {}}
    result = config_manager._merge_with_defaults(loaded)

    assert result["screenshot"] == DEFAULT_CONFIG["screenshot"]
