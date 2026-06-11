import pytest
import numpy as np
from unittest.mock import MagicMock

from src.gui.widgets.response_viewer import (
    ResponseViewer,
    ResponseViewerWidget,
)


@pytest.fixture
def mock_audio_engine():
    engine = MagicMock()
    engine.sample_rate = 48000
    return engine


@pytest.fixture
def dummy_model_data_compressing():
    return {
        "metadata": {
            "sample_rate": 48000,
            "P": 5,
            "start_freq": 20.0,
            "end_freq": 20000.0,
        },
        "frequency_domain": {
            "freqs": np.array([100.0, 1000.0, 10000.0]),
            "magnitudes_db": {
                # High compression by making h3 very large and out-of-phase (phase = 180)
                "h1": np.array([0.0, 0.0, 0.0]),
                "h2": np.array([-60.0, -60.0, -60.0]),
                "h3": np.array([-10.0, -10.0, -10.0]),
                "h4": np.array([-80.0, -80.0, -80.0]),
                "h5": np.array([-90.0, -90.0, -90.0]),
            },
            "phases_deg": {
                "h1": np.array([0.0, 0.0, 0.0]),
                "h2": np.array([0.0, 0.0, 0.0]),
                "h3": np.array([180.0, 180.0, 180.0]),
                "h4": np.array([0.0, 0.0, 0.0]),
                "h5": np.array([0.0, 0.0, 0.0]),
            }
        },
        "time_domain": {
            "time_ms": np.array([0.0, 1.0, 2.0]),
            "kernels": {
                "h1": np.array([1.0, 0.0, 0.0]),
                "h2": np.array([0.01, 0.0, 0.0]),
                "h3": np.array([-0.316, 0.0, 0.0]),
                "h4": np.array([0.0, 0.0, 0.0]),
                "h5": np.array([0.0, 0.0, 0.0]),
            }
        }
    }


@pytest.fixture
def dummy_model_data_expanding():
    return {
        "metadata": {
            "sample_rate": 48000,
            "P": 5,
            "start_freq": 20.0,
            "end_freq": 20000.0,
        },
        "frequency_domain": {
            "freqs": np.array([100.0, 1000.0, 10000.0]),
            "magnitudes_db": {
                # Gain expansion by making h3 in-phase (phase = 0)
                "h1": np.array([0.0, 0.0, 0.0]),
                "h2": np.array([-60.0, -60.0, -60.0]),
                "h3": np.array([-10.0, -10.0, -10.0]),
                "h4": np.array([-80.0, -80.0, -80.0]),
                "h5": np.array([-90.0, -90.0, -90.0]),
            },
            "phases_deg": {
                "h1": np.array([0.0, 0.0, 0.0]),
                "h2": np.array([0.0, 0.0, 0.0]),
                "h3": np.array([0.0, 0.0, 0.0]),
                "h4": np.array([0.0, 0.0, 0.0]),
                "h5": np.array([0.0, 0.0, 0.0]),
            }
        },
        "time_domain": {
            "time_ms": np.array([0.0, 1.0, 2.0]),
            "kernels": {
                "h1": np.array([1.0, 0.0, 0.0]),
                "h2": np.array([0.01, 0.0, 0.0]),
                "h3": np.array([0.316, 0.0, 0.0]),
                "h4": np.array([0.0, 0.0, 0.0]),
                "h5": np.array([0.0, 0.0, 0.0]),
            }
        }
    }


def test_io_compression_plots_initialization(qtbot, mock_audio_engine):
    analyzer = ResponseViewer(mock_audio_engine)
    widget = ResponseViewerWidget(analyzer)
    qtbot.addWidget(widget)

    # Verify tab exists
    found_tab = False
    for idx in range(widget.tabs.count()):
        if widget.tabs.tabText(idx) in ["I/O & Compression", "入出力特性と圧縮"]:
            found_tab = True
            break
    assert found_tab

    # Verify PlotWidgets exist
    assert widget.io_plot is not None
    assert widget.comp_plot is not None

    # Verify lines are initialized and attached
    assert widget.io_ref_v_line in widget.io_plot.items()
    assert widget.io_ref_h_line in widget.io_plot.items()
    assert widget.io_p1db_v_line in widget.io_plot.items()
    assert widget.io_p1db_h_line in widget.io_plot.items()
    assert widget.io_p1db_marker in widget.io_plot.items()

    assert widget.comp_linear_ref_line in widget.comp_plot.items()
    assert widget.comp_ref_v_line in widget.comp_plot.items()
    assert widget.comp_ref_h_line in widget.comp_plot.items()
    assert widget.comp_1db_limit_line in widget.comp_plot.items()
    assert widget.comp_p1db_v_line in widget.comp_plot.items()
    assert widget.comp_p1db_h_line in widget.comp_plot.items()
    assert widget.comp_p1db_marker in widget.comp_plot.items()


def test_p1db_calculation_compressing(qtbot, mock_audio_engine, dummy_model_data_compressing):
    analyzer = ResponseViewer(mock_audio_engine)
    widget = ResponseViewerWidget(analyzer)
    qtbot.addWidget(widget)

    # Set min/max levels so we capture the compression curve nicely
    widget.min_level_spin.setValue(-40.0)
    widget.max_level_spin.setValue(10.0)

    widget.set_model_data(dummy_model_data_compressing)

    # Verify P1dB is found and plotted
    # Let's inspect the visibility and positions
    assert widget.io_p1db_v_line.isVisible()
    assert widget.io_p1db_h_line.isVisible()
    assert widget.comp_p1db_v_line.isVisible()
    assert widget.comp_p1db_h_line.isVisible()

    p1db_in = widget.io_p1db_v_line.pos().x()
    p1db_out = widget.io_p1db_h_line.pos().y()

    # The input 1dB compression point should be within min/max level
    assert -40.0 <= p1db_in <= 10.0
    # The output level should be roughly 1dB lower than (input + gain)
    # Since linear gain at 1kHz is 0 dB (h1 magnitude_db is 0.0), output should be input - 1dB
    assert np.isclose(p1db_out, p1db_in - 1.0, atol=0.1)


def test_p1db_calculation_expanding_or_linear(qtbot, mock_audio_engine, dummy_model_data_expanding):
    analyzer = ResponseViewer(mock_audio_engine)
    widget = ResponseViewerWidget(analyzer)
    qtbot.addWidget(widget)

    widget.min_level_spin.setValue(-40.0)
    widget.max_level_spin.setValue(10.0)

    widget.set_model_data(dummy_model_data_expanding)

    # Under gain expansion, the error goes positive and never drops below -1.0 dB
    # Thus, P1dB should NOT be found
    assert not widget.io_p1db_v_line.isVisible()
    assert not widget.io_p1db_h_line.isVisible()
    assert not widget.comp_p1db_v_line.isVisible()
    assert not widget.comp_p1db_h_line.isVisible()


def test_io_compression_plots_ref_parameter_sync(qtbot, mock_audio_engine, dummy_model_data_compressing):
    analyzer = ResponseViewer(mock_audio_engine)
    widget = ResponseViewerWidget(analyzer)
    qtbot.addWidget(widget)

    widget.set_model_data(dummy_model_data_compressing)

    # Change reference amplitude
    widget.update_reference_params(1000.0, -12.3)

    # Verify the reference lines on both plots move to the new amplitude
    assert np.isclose(widget.io_ref_v_line.pos().x(), -12.3)
    assert np.isclose(widget.comp_ref_v_line.pos().x(), -12.3)
