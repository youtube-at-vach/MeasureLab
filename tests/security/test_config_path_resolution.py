import os
import pytest
import tempfile
import json
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

        cm = ConfigManager(config_path=config_path)
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
    with pytest.raises(ValueError, match="Path resolution failed"):
        cm._resolve_path(path)

def test_resolve_path_traversal_absolute(config_manager_instance):
    cm, temp_dir = config_manager_instance
    # Create a path clearly outside temp_dir
    # On many systems temp_dir is in /tmp. Let's use parent of temp_dir.
    outside_dir = os.path.dirname(temp_dir)
    path = os.path.join(outside_dir, "secret.txt")

    with pytest.raises(ValueError, match="Path resolution failed"):
        cm._resolve_path(path)

def test_resolve_complex_traversal(config_manager_instance):
    cm, temp_dir = config_manager_instance
    path = "subdir/../../outside"
    with pytest.raises(ValueError, match="Path resolution failed"):
        cm._resolve_path(path)

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
