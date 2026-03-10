import pytest
from PyQt6.QtWidgets import QApplication
from unittest.mock import patch
from src.gui.widgets.impedance_analyzer import ImpedanceResultsWidget

@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

def test_impedance_results_widget_toggle_details(qapp):
    widget = ImpedanceResultsWidget()

    # In PyQt, child widgets might not return True for isVisible()
    # unless their parent is visible. So we show the parent widget first.
    widget.show()

    # Check initial state
    assert widget.is_detailed is False
    assert widget.detail_widget.isVisible() is False
    assert widget.detail_btn.text() == "Show Details"

    # Toggle to true
    # Mocking tr for language-agnostic testing
    with patch('src.gui.widgets.impedance_analyzer.tr', side_effect=lambda x: x):
        widget.toggle_details(True)
        assert widget.is_detailed is True
        assert widget.detail_widget.isVisible() is True
        assert widget.detail_btn.text() == "Hide Details"

        # Toggle to false
        widget.toggle_details(False)
        assert widget.is_detailed is False
        assert widget.detail_widget.isVisible() is False
        assert widget.detail_btn.text() == "Show Details"
