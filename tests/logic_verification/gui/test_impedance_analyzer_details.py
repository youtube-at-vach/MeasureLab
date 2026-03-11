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

def test_impedance_results_widget_toggle_details(qapp, qtbot):
    widget = ImpedanceResultsWidget()
    qtbot.addWidget(widget)

    # In PyQt, child widgets might not return True for isVisible()
    # unless their parent is visible. So we show the parent widget first.
    widget.show()
    qtbot.waitExposed(widget)

    # Check initial state
    assert widget.is_detailed is False
    assert widget.detail_widget.isVisible() is False
    assert widget.detail_btn.text() == "Show Details"

    # Toggle to true via clicking the button
    # Mocking tr for language-agnostic testing
    with patch('src.gui.widgets.impedance_analyzer.tr', side_effect=lambda x: x):
        widget.detail_btn.click()
        assert widget.is_detailed is True
        assert widget.detail_widget.isVisible() is True
        assert widget.detail_btn.text() == "Hide Details"

        # Toggle to false via clicking the button again
        widget.detail_btn.click()
        assert widget.is_detailed is False
        assert widget.detail_widget.isVisible() is False
        assert widget.detail_btn.text() == "Show Details"
