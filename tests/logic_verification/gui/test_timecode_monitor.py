import pytest
import sys
from unittest.mock import MagicMock

# Mock numpy if needed for restricted environments
if "numpy" not in sys.modules:
    sys.modules["numpy"] = MagicMock()

from src.gui.widgets.timecode_monitor import TimecodeMonitor, TimecodeMonitorWidget
from src.core.audio_engine import AudioEngine
from src.core.localization import tr


@pytest.fixture
def mock_audio_engine():
    engine = MagicMock(spec=AudioEngine)
    engine.sample_rate = 48000
    return engine


def test_timecode_monitor_initialization(mock_audio_engine):
    monitor = TimecodeMonitor(mock_audio_engine)
    assert monitor.name == "Timecode Monitor & Generator"
    assert monitor.description == tr("LTC (Linear Timecode) Reader and Generator.")
    assert "L" in monitor.channels
    assert "R" in monitor.channels
    assert monitor.channels["L"].fps == 30.0
    assert monitor.channels["R"].fps == 30.0


def test_timecode_monitor_set_fps(mock_audio_engine):
    monitor = TimecodeMonitor(mock_audio_engine)
    monitor.set_fps(24.0)
    assert monitor.fps == 24.0
    assert monitor.detected_fps == 0.0
    assert monitor.channels["L"].fps == 24.0
    assert monitor.channels["R"].fps == 24.0


def test_parse_fps_option():
    # Test the parsing logic handles string parsing with and without 'D'
    fps, drop = TimecodeMonitorWidget._parse_fps_option(None, "29.97D")
    assert fps == 29.97
    assert drop is True

    fps, drop = TimecodeMonitorWidget._parse_fps_option(None, "24.00")
    assert fps == 24.0
    assert drop is False

    fps, drop = TimecodeMonitorWidget._parse_fps_option(None, "invalid")
    assert fps is None
    assert drop is False


def test_format_fps_option():
    # Test the formatting logic correctly appends 'D' when drop_frame is True
    formatted = TimecodeMonitorWidget._format_fps_option(None, 29.97, True)
    assert formatted == "29.97D"

    formatted = TimecodeMonitorWidget._format_fps_option(None, 24.0, False)
    assert formatted == "24.00"

    formatted = TimecodeMonitorWidget._format_fps_option(None, 23.976, False)
    assert formatted == "23.98"
