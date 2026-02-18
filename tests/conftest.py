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


@pytest.fixture(scope="session")
def hardware_config():
    """
    Loads hardware configuration from config.json.
    Returns a dictionary with audio settings.
    """
    import json
    config_path = _REPO_ROOT / "config.json"
    
    default_config = {
        "audio": {
            "input_device": "system", 
            "output_device": "system",
            "sample_rate": 48000,
            "block_size": 1024,
            "input_channels": "stereo",
            "output_channels": "stereo"
        }
    }

    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
                # Merge with default (shallow merge for 'audio' key)
                if "audio" in user_config:
                    default_config["audio"].update(user_config["audio"])
        except Exception as e:
            print(f"Warning: Failed to load config.json: {e}")
            
    return default_config["audio"]

def pytest_addoption(parser):
    parser.addoption(
        "--hardware",
        action="store_true",
        default=False,
        help="run hardware benchmark tests (requires physical hardware)",
    )
    parser.addoption(
        "--hardware-mode",
        action="store",
        default="typical",
        choices=["typical", "limit"],
        help="hardware test mode: typical (fixed params) or limit (matrix test)",
    )




def pytest_collection_modifyitems(config, items):
    if config.getoption("--hardware"):
        # --hardware given: skip everything EXCEPT hardware tests
        # This ensuring that non-hardware benchmarks are also skipped
        skip_non_hardware = pytest.mark.skip(reason="skipping non-hardware tests/benchmarks because --hardware is set")
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


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """
    Generate a simplified measurement report after tests finish.
    """
    if not config.getoption("--hardware"):
        return

    # Check if report.json exists
    report_file = getattr(config.option, 'json_report_file', 'report.json')
    if not os.path.exists(report_file):
        terminalreporter.write_line(f"Warning: {report_file} not found. Cannot generate measurement report.")
        return

    import json
    
    try:
        with open(report_file, 'r') as f:
            full_report = json.load(f)
    except Exception as e:
        terminalreporter.write_line(f"Error reading {report_file}: {e}")
        return

    simplified_tests = []
    
    for test in full_report.get('tests', []):
        # We only care about tests with user_properties (metrics)
        if 'user_properties' not in test:
            continue
            
        # Extract properties
        props = {k: v for d in test['user_properties'] for k, v in d.items()}
        
        # Determine test ID and Type
        # Default ID is the function name
        nodeid = test.get('nodeid', '')
        func_name = nodeid.split('::')[-1] if '::' in nodeid else nodeid
        
        # Default Type from props or basic mapping
        test_type = props.get('test_type', func_name)
        
        # Remove metadata from metrics
        metrics = props.copy()
        if 'test_type' in metrics:
            del metrics['test_type']
            
        test_entry = {
            "id": func_name,
            "type": test_type,
            "metrics": metrics
        }
        
        simplified_tests.append(test_entry)

    # Construct final report
    
    # Reload config to get device info for the report header
    # We could reuse hardware_config fixture logic but it's cleaner to just read here
    # or rely on what tests reported. But user wants specific top-level fields.
    
    config_path = _REPO_ROOT / "config.json"
    audio_conf = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                c = json.load(f)
                audio_conf = c.get("audio", {})
        except:
            pass
            
    input_dev = audio_conf.get("input_device", "System Default")
    output_dev = audio_conf.get("output_device", "System Default")
    input_hostapi = audio_conf.get("input_hostapi", "Unknown")
    output_hostapi = audio_conf.get("output_hostapi", "Unknown")
    sr = audio_conf.get("sample_rate", 48000)
    bs = audio_conf.get("block_size", 1024)
    
    hardware_mode = config.getoption("--hardware-mode")
    
    device_str = f"{input_dev} / {output_dev} (Loaded from config.json)"

    final_report = {
        "device": device_str,
        "mode": hardware_mode,
        "configuration": {
            "sample_rate": sr,
            "block_size": bs,
            "input_device": input_dev,
            "output_device": output_dev,
            "input_hostapi": input_hostapi,
            "output_hostapi": output_hostapi
        },
        "tests": simplified_tests
    }
    
    out_file = "measurement_report.json"
    try:
        with open(out_file, 'w') as f:
            json.dump(final_report, f, indent=2)
        terminalreporter.write_line(f"\nGenerated simplified measurement report: {out_file}")
    except Exception as e:
        terminalreporter.write_line(f"Error writing {out_file}: {e}")
