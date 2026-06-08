import pytest
import os
import tempfile
import json
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from src.gui.widgets.arbitrary_harmonic_generator import ArbitraryHarmonicWidget, ArbitraryHarmonicGenerator


# We need a QApplication instance to test widgets
@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def temp_json_file():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    yield path
    os.remove(path)


class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.register_module = lambda x: None
        self.unregister_module = lambda x: None


def test_load_compensation_type_validation(qapp, temp_json_file):
    """
    Test that loading a compensation file with invalid types doesn't crash the app
    or cause unexpected behavior due to unvalidated JSON data.
    """
    # Create the widget
    engine = MockAudioEngine()
    module = ArbitraryHarmonicGenerator(engine)
    widget = ArbitraryHarmonicWidget(module)

    with patch("src.gui.widgets.arbitrary_harmonic_generator.QMessageBox.critical") as mock_msg_box:
        # 1. Test fundamental_frequency as string
        data = {
            "format": "MeasureLab_Harmonic_Compensation",
            "fundamental_frequency": "1000",  # Invalid type
            "compensation_coeffs": [],
        }
        with open(temp_json_file, "w") as f:
            json.dump(data, f)

        widget.on_load_compensation(temp_json_file, force_apply=True)

        # Verify the error was caught and displayed
        assert mock_msg_box.called
        args, _ = mock_msg_box.call_args
        assert "fundamental_frequency must be a number" in args[2] or "must be a number" in args[2]

        mock_msg_box.reset_mock()

        # 2. Test compensation_coeffs item not a dict
        data = {
            "format": "MeasureLab_Harmonic_Compensation",
            "fundamental_frequency": 1000.0,
            "compensation_coeffs": ["invalid"],  # Should be dicts
        }
        with open(temp_json_file, "w") as f:
            json.dump(data, f)

        widget.on_load_compensation(temp_json_file, force_apply=True)
        assert mock_msg_box.called

        mock_msg_box.reset_mock()

        # 3. Test real/imag as strings
        data = {
            "format": "MeasureLab_Harmonic_Compensation",
            "fundamental_frequency": 1000.0,
            "compensation_coeffs": [
                {"harmonic": 2, "real": "0.1", "imag": 0.0}  # real is string
            ],
        }
        with open(temp_json_file, "w") as f:
            json.dump(data, f)

        widget.on_load_compensation(temp_json_file, force_apply=True)
        assert mock_msg_box.called
