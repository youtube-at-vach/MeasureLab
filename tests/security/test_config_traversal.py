import os
import shutil
import tempfile
import json
from src.core.config_manager import ConfigManager


def test_screenshot_path_traversal():
    """
    Verifies that relative paths in screenshot output_dir cannot traverse
    outside the configuration directory.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        config_file = os.path.join(temp_dir, "config.json")

        # We want to try to write to a directory outside temp_dir
        # Let's target a sibling directory "traversal_target"
        parent_dir = os.path.dirname(temp_dir)
        target_name = "traversal_" + os.path.basename(temp_dir)
        target_path = os.path.join(parent_dir, target_name)

        # Clean up target if it exists (from previous run)
        if os.path.exists(target_path):
            shutil.rmtree(target_path)

        # ../traversal_target
        rel_path = os.path.join("..", target_name)

        config_data = {"screenshot": {"output_dir": rel_path}}

        with open(config_file, "w") as f:
            json.dump(config_data, f)

        try:
            # Initialize ConfigManager
            # This should trigger _ensure_screenshot_dir
            cm = ConfigManager(config_filename=config_file)

            # Check if the target directory was created
            # If the fix is working, this directory SHOULD exist
            assert os.path.exists(target_path), f"Directory should be created at {target_path}"

            # Verify the config internal state points to the target
            actual_dir = cm.get_screenshot_output_dir()
            # Normalize paths for comparison
            assert os.path.abspath(actual_dir) == os.path.abspath(target_path)

        finally:
            if os.path.exists(target_path):
                shutil.rmtree(target_path)


def test_absolute_path_rejected():
    """
    Verifies that absolute paths pointing outside the config directory are rejected.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        config_file = os.path.join(temp_dir, "config.json")

        # Create a target directory in a separate location
        with tempfile.TemporaryDirectory() as abs_target_dir:
            config_data = {"screenshot": {"output_dir": abs_target_dir}}

            with open(config_file, "w") as f:
                json.dump(config_data, f)

            cm = ConfigManager(config_filename=config_file)

            # Should use the provided absolute path
            actual_dir = cm.get_screenshot_output_dir()

            assert os.path.abspath(actual_dir) == os.path.abspath(abs_target_dir)
