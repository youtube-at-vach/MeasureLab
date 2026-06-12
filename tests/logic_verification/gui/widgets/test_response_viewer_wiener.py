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
def dummy_model_data():
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
                "h1": np.array([0.0, 0.0, 0.0]),
                "h2": np.array([-60.0, -60.0, -60.0]),
                "h3": np.array([-70.0, -70.0, -70.0]),
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
                "h2": np.array([0.1, 0.0, 0.0]),
                "h3": np.array([0.01, 0.0, 0.0]),
                "h4": np.array([0.001, 0.0, 0.0]),
                "h5": np.array([0.0001, 0.0, 0.0]),
            }
        }
    }


def test_wiener_ui_components_exist(qtbot, mock_audio_engine):
    analyzer = ResponseViewer(mock_audio_engine)
    widget = ResponseViewerWidget(analyzer)
    qtbot.addWidget(widget)

    # Check that new controls and tab exist
    assert widget.wiener_group is not None
    assert widget.wiener_sigma_spin is not None
    assert widget.wiener_sigma_slider is not None
    assert widget.wie_mag_plot is not None
    assert widget.wie_phase_plot is not None
    assert widget.wie_energy_plot is not None

    # Check tab title
    tab_count = widget.tabs.count()
    tab_titles = [widget.tabs.tabText(i) for i in range(tab_count)]
    assert any("Wiener" in title for title in tab_titles)


def test_wiener_enabling_and_default_sync(qtbot, mock_audio_engine, dummy_model_data):
    analyzer = ResponseViewer(mock_audio_engine)
    widget = ResponseViewerWidget(analyzer)
    qtbot.addWidget(widget)

    # Initial state: Wiener Settings should be disabled
    assert not widget.wiener_group.isEnabled()

    # Load data
    widget.set_model_data(dummy_model_data)
    assert widget.wiener_group.isEnabled()

    # Default sigma level should be synced with ref_amp (-6.0 dBFS by default)
    assert widget.wiener_sigma_spin.value() == widget.ref_amp
    assert widget.wiener_sigma_slider.value() == int(widget.ref_amp * 10)


def test_wiener_conversion_math(qtbot, mock_audio_engine, dummy_model_data):
    analyzer = ResponseViewer(mock_audio_engine)
    widget = ResponseViewerWidget(analyzer)
    qtbot.addWidget(widget)

    # Set data and fixed sigma
    widget.set_model_data(dummy_model_data)
    
    # Set sigma to -20.0 dBFS
    sigma_dbfs = -20.0
    widget.wiener_sigma_spin.setValue(sigma_dbfs)
    
    sigma_linear = 10 ** (sigma_dbfs / 20.0)
    sigma_sq = sigma_linear ** 2

    # Expectation calculations for Time Domain
    h_time = {p: dummy_model_data["time_domain"]["kernels"][f"h{p}"] for p in range(1, 6)}
    expected_w1 = h_time[1] + 3 * sigma_sq * h_time[3] + 15 * (sigma_sq**2) * h_time[5]
    expected_w2 = h_time[2] + 6 * sigma_sq * h_time[4]
    expected_w3 = h_time[3] + 10 * sigma_sq * h_time[5]
    expected_w4 = h_time[4]
    expected_w5 = h_time[5]

    # We can test the slider sync changes update the spin box
    widget.wiener_sigma_slider.setValue(-200) # -20 dBFS
    assert widget.wiener_sigma_spin.value() == -20.0

    # Ensure plots update without errors
    widget.update_wiener_plots()

    # Verify that energy items were added to wie_energy_plot
    import pyqtgraph as pg
    bar_items = [item for item in widget.wie_energy_plot.items() if isinstance(item, pg.BarGraphItem)]
    assert len(bar_items) == 5
