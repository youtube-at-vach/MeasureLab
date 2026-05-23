import pytest
from src.gui.main_window import MainWindow

class MockMainWindow:
    def _format_compact_sample_rate(self, sample_rate):
        return MainWindow._format_compact_sample_rate(self, sample_rate)

def test_format_compact_sample_rate():
    mw = MockMainWindow()

    # Test typical audio sample rates that are cleanly divisible by 1000
    assert mw._format_compact_sample_rate(48000) == "48 kHz"
    assert mw._format_compact_sample_rate(96000) == "96 kHz"
    assert mw._format_compact_sample_rate(192000) == "192 kHz"

    # Test audio sample rates that are > 1000 but not cleanly divisible by 1000
    assert mw._format_compact_sample_rate(44100) == "44.1 kHz"
    assert mw._format_compact_sample_rate(44100.0) == "44.1 kHz"

    # Test float sample rates
    assert mw._format_compact_sample_rate(44100.5) == "44.1 kHz"
    assert mw._format_compact_sample_rate(100.5) == "100.5 Hz"

    # Test sample rates < 1000
    assert mw._format_compact_sample_rate(100) == "100 Hz"
    assert mw._format_compact_sample_rate(999) == "999 Hz"

    # Test error/invalid cases
    assert mw._format_compact_sample_rate("invalid") == "invalid"
    assert mw._format_compact_sample_rate(None) == "None"
