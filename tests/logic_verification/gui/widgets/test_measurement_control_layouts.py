from unittest.mock import MagicMock

from PyQt6.QtWidgets import QScrollArea

from src.gui.widgets.nonlinear_response_analyzer import NonlinearResponseAnalyzer
from src.gui.widgets.response_viewer import ResponseViewer


def _show_at_accessibility_size(widget, qtbot):
    qtbot.addWidget(widget)
    widget.setStyleSheet("font-size: 16px;")
    widget.resize(1100, 690)
    widget.show()
    qtbot.wait(1)


def test_response_viewer_uses_shallow_control_tabs(qtbot):
    engine = MagicMock()
    engine.sample_rate = 48_000
    widget = ResponseViewer(engine).get_widget()

    _show_at_accessibility_size(widget, qtbot)

    assert widget.sidebar_tabs.count() == 4
    assert widget.findChildren(QScrollArea) == []
    assert widget.minimumSizeHint().width() <= 1100
    assert widget.minimumSizeHint().height() <= 690


def test_nonlinear_response_analyzer_uses_shallow_control_tabs(qtbot):
    engine = MagicMock()
    engine.sample_rate = 48_000
    widget = NonlinearResponseAnalyzer(engine).get_widget()

    _show_at_accessibility_size(widget, qtbot)

    assert widget.control_tabs.count() == 3
    assert widget.findChildren(QScrollArea) == []
    assert widget.minimumSizeHint().width() <= 1100
    assert widget.minimumSizeHint().height() <= 690
