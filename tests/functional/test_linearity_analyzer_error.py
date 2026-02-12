from unittest.mock import MagicMock, patch
import pytest
from src.gui.widgets.linearity_analyzer import LinearityAnalyzer, LinearityAnalyzerWidget

@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.sample_rate = 48000
    engine.calibration = MagicMock()
    return engine

def test_error_message_box(qtbot, mock_engine):
    """Verifies that on_error displays a critical message box."""
    module = LinearityAnalyzer(mock_engine)
    widget = LinearityAnalyzerWidget(module)
    qtbot.addWidget(widget)

    # Patch QMessageBox.critical in the module where it's used
    with patch('src.gui.widgets.linearity_analyzer.QMessageBox.critical') as mock_critical:
        test_msg = "Test Error Message"
        widget.on_error(test_msg)

        # Assert that critical was called
        mock_critical.assert_called_once()

        # Check arguments
        # Signature: critical(parent, title, text, ...)
        args, _ = mock_critical.call_args
        assert args[0] == widget
        assert "Error" in args[1]
        assert test_msg in args[2]
