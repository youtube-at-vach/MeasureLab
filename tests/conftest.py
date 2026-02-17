from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest


# Ensure the repository root is importable so tests can do `import src...`.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Set Qt platform to offscreen for headless testing
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Mock sounddevice if not available or fails to initialize (no PortAudio)
try:
    import sounddevice # noqa: F401
except (OSError, ImportError):
    sd = MagicMock()
    sd.query_devices.return_value = []
    sd.query_hostapis.return_value = []
    sd.default.device = [-1, -1]
    sd.CallbackFlags = MagicMock(return_value=0)
    sd.check_input_settings = MagicMock(return_value=True)
    sd.check_output_settings = MagicMock(return_value=True)
    sys.modules["sounddevice"] = sd


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_config():
    yield
    if os.path.exists("test_config.json"):
        os.remove("test_config.json")

def pytest_addoption(parser):
    parser.addoption(
        "--hardware",
        action="store_true",
        default=False,
        help="run hardware benchmark tests (requires physical hardware)",
    )




def pytest_collection_modifyitems(config, items):
    if config.getoption("--hardware"):
        # --hardware given: skip everything EXCEPT hardware tests
        skip_non_hardware = pytest.mark.skip(reason="skipping non-hardware tests because --hardware is set")
        for item in items:
            if not item.get_closest_marker("hardware"):
                item.add_marker(skip_non_hardware)
        return

    # --hardware NOT given: skip hardware tests
    skip_hardware = pytest.mark.skip(reason="need --hardware option to run")
    for item in items:
        if item.get_closest_marker("hardware"):
            item.add_marker(skip_hardware)


def pytest_configure(config):
    """
    Auto-enable json-report if --hardware is used.
    """
    if config.getoption("--hardware"):
        # Check if --json-report option exists (plugin installed)
        if not hasattr(config.option, "json_report"):
            print("WARNING: --hardware flag used but pytest-json-report plugin seems missing (no --json-report option).")
            return

        # Enable json-report if not explicitly disabled or configured?
        # We just force enable it if not already set.
        
        # Verify if user already passed --json-report
        if not config.option.json_report:
            # print("Notice: Auto-enabling --json-report for hardware tests.")
            config.option.json_report = True
            
        # Verify if user already passed --json-report-file
        # If not set (None) or set to default hidden file, enforce 'report.json'
        # The plugin default is typically none or .report.json depending on version
        current_file = getattr(config.option, 'json_report_file', None)
        if not current_file or current_file == '.report.json':
             config.option.json_report_file = 'report.json'

        # Set default indentation for readability if not specified
        if not getattr(config.option, 'json_report_indent', None):
            config.option.json_report_indent = 4
