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
