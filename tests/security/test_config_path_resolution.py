import os
import pytest
import tempfile
import json
from unittest.mock import patch
from src.core.config_manager import ConfigManager

@pytest.fixture
def config_manager_instance():
    """
    Creates a temporary directory with a config file and initializes ConfigManager.
    Yields the ConfigManager instance and the temp directory path.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        # Resolve symlinks in temp_dir to avoid path mismatch issues
        temp_dir = os.path.realpath(temp_dir)
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump({}, f)

        cm = ConfigManager(config_filename=config_path)
        yield cm, temp_dir

        # Shutdown to clean up resources (timers, etc.)
        cm.shutdown()

def test_resolve_valid_relative_path(config_manager_instance):
    cm, temp_dir = config_manager_instance
    path = "subdir"
    resolved = cm._resolve_path(path)
    expected = os.path.join(temp_dir, "subdir")
    assert resolved == expected

def test_resolve_valid_absolute_path_inside_root(config_manager_instance):
    cm, temp_dir = config_manager_instance
    path = os.path.join(temp_dir, "subdir")
    resolved = cm._resolve_path(path)
    assert resolved == path

def test_resolve_path_traversal_relative(config_manager_instance):
    cm, temp_dir = config_manager_instance
    path = "../outside"
    # Now allowed
    resolved = cm._resolve_path(path)
    expected = os.path.abspath(os.path.join(temp_dir, "../outside"))
    assert resolved == expected

def test_resolve_path_traversal_absolute(config_manager_instance):
    cm, temp_dir = config_manager_instance
    # Create a path clearly outside temp_dir
    # On many systems temp_dir is in /tmp. Let's use parent of temp_dir.
    outside_dir = os.path.dirname(temp_dir)
    path = os.path.join(outside_dir, "secret.txt")

    # Now allowed
    resolved = cm._resolve_path(path)
    assert resolved == path

def test_resolve_complex_traversal(config_manager_instance):
    cm, temp_dir = config_manager_instance
    path = "subdir/../../outside"
    # Now allowed
    resolved = cm._resolve_path(path)
    expected = os.path.abspath(os.path.join(temp_dir, "subdir/../../outside"))
    assert resolved == expected

def test_resolve_current_directory_reference(config_manager_instance):
    cm, temp_dir = config_manager_instance
    path = "./subdir"
    resolved = cm._resolve_path(path)
    expected = os.path.join(temp_dir, "subdir")
    assert resolved == expected

def test_resolve_parent_directory_reference_safe(config_manager_instance):
    cm, temp_dir = config_manager_instance
    # "subdir/.." should resolve to temp_dir itself, which IS allowed as it is base_dir
    path = "subdir/.."
    resolved = cm._resolve_path(path)
    assert resolved == temp_dir

def test_resolve_base_directory(config_manager_instance):
    cm, temp_dir = config_manager_instance
    # Resolving "." should return base dir
    path = "."
    resolved = cm._resolve_path(path)
    assert resolved == temp_dir

def test_resolve_home_directory_expansion(config_manager_instance):
    cm, temp_dir = config_manager_instance
    path = "~/subdir"

    # Mock expanduser to return a path relative to temp_dir for predictability
    # We choose an absolute path to simulate successful expansion
    expanded_path = os.path.join(temp_dir, "home/user/subdir")

    with patch("os.path.expanduser", return_value=expanded_path) as mock_expand:
        resolved = cm._resolve_path(path)

        # Verify expanduser was called
        mock_expand.assert_called_with(path)

        # Verify result matches expected expanded path
        # Since expanded_path is absolute, _resolve_path should return it as is
        assert resolved == expanded_path

def test_ensure_screenshot_dir_expansion(config_manager_instance):
    cm, temp_dir = config_manager_instance
    config = {"screenshot": {"output_dir": "~/screenshots"}}

    expanded_path = os.path.join(temp_dir, "home/user/screenshots")

    with patch("os.path.expanduser", return_value=expanded_path) as mock_expand:
        # We need to mock makedirs to avoid actual FS operations on non-existent paths
        with patch("os.makedirs"):
             out_dir = cm._ensure_screenshot_dir(config)

        mock_expand.assert_called_with("~/screenshots")
        assert out_dir == expanded_path
