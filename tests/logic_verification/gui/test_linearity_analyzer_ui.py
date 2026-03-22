import pytest
from unittest.mock import MagicMock

# Ensure dependencies are present before proceeding
pytest.importorskip("PyQt6")
pg = pytest.importorskip("pyqtgraph")

try:
    from src.gui.widgets.linearity_analyzer import LinearityAnalyzer, LinearityAnalyzerWidget
    from src.core.audio_engine import AudioEngine
except ImportError:
    pytest.skip("Skipping due to import errors (likely missing GUI libs)", allow_module_level=True)


def test_tolerance_lines_presence(qtbot):
    """Verifies that tolerance lines are added to the error plot."""
    # Setup
    audio_engine = MagicMock(spec=AudioEngine)
    audio_engine.sample_rate = 48000

    module = LinearityAnalyzer(audio_engine)
    widget = LinearityAnalyzerWidget(module)
    qtbot.addWidget(widget)

    # Inspect plot items
    plot_widget = widget.error_plot
    plot_item = plot_widget.getPlotItem()
    all_items = plot_item.items

    tolerance_lines = []
    for item in all_items:
        if isinstance(item, pg.InfiniteLine):
            tolerance_lines.append(item)

    # Check if they are at +/- 1.0
    found_plus_1 = False
    found_minus_1 = False

    for line in tolerance_lines:
        # value() returns the position for InfiniteLine
        if line.value() == 1.0:
            found_plus_1 = True
        if line.value() == -1.0:
            found_minus_1 = True

    # Assert that we found them
    assert found_plus_1, "Did not find +1.0 dB tolerance line"
    assert found_minus_1, "Did not find -1.0 dB tolerance line"

    widget.close()
