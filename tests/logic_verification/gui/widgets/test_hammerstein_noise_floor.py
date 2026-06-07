import pytest
import numpy as np
from unittest.mock import MagicMock
from PyQt6.QtWidgets import QApplication

from src.gui.widgets.hammerstein_analyzer import (
    HammersteinAnalyzer,
    HammersteinAnalyzerWidget,
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
                "h2": np.array([0.01, 0.0, 0.0]),
                "h3": np.array([0.001, 0.0, 0.0]),
                "h4": np.array([0.0, 0.0, 0.0]),
                "h5": np.array([0.0, 0.0, 0.0]),
            }
        }
    }


def test_noise_floor_ui_toggling(qtbot, mock_audio_engine):
    analyzer = HammersteinAnalyzer(mock_audio_engine)
    widget = HammersteinAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    # Enable parent map_group to test children isEnabled status properly
    widget.map_group.setEnabled(True)

    # Initial state: Noise floor option should be disabled by default
    assert not widget.enable_noise_chk.isChecked()
    assert not widget.noise_floor_spin.isEnabled()
    assert widget.map_type_combo.itemText(widget.map_type_combo.findData("THD")) == "THD Map"

    # Toggle checkbox ON
    widget.enable_noise_chk.setChecked(True)
    assert widget.noise_floor_spin.isEnabled()
    assert widget.map_type_combo.itemText(widget.map_type_combo.findData("THD")) == "THD+N Map"

    # Toggle checkbox OFF
    widget.enable_noise_chk.setChecked(False)
    assert not widget.noise_floor_spin.isEnabled()
    assert widget.map_type_combo.itemText(widget.map_type_combo.findData("THD")) == "THD Map"


def test_noise_floor_calculations(qtbot, mock_audio_engine, dummy_model_data):
    analyzer = HammersteinAnalyzer(mock_audio_engine)
    widget = HammersteinAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    # Set model data
    widget.set_model_data(dummy_model_data)

    # 1. Without Noise Floor (dBFS unit)
    widget.enable_noise_chk.setChecked(False)
    widget.harm_unit_combo.setCurrentIndex(widget.harm_unit_combo.findData("dbfs"))
    widget.update_2d_map()

    # THD at -100 dBFS should be extremely low because there's no noise floor
    # We query the 2D map cache Z. Z shape is (N_A, N_f) where N_A=80 steps from min_level to max_level.
    # Min level is -60.0 dBFS by default, let's change min_level to -120.0 dBFS.
    widget.min_level_spin.setValue(-120.0)
    widget.update_2d_map()

    # The lowest amplitude step (-120.0 dBFS)
    # Z has shape (80, 200). Let's check Z[0, 100] (minimum level amplitude, middle frequency index)
    z_no_noise = widget.cached_Z[0, 100]
    
    # 2. Enable Noise Floor at -90.0 dBFS
    widget.enable_noise_chk.setChecked(True)
    widget.noise_floor_spin.setValue(-90.0)
    widget.update_2d_map()
    
    z_with_noise = widget.cached_Z[0, 100]
    
    # With a -90 dBFS noise floor, the calculated THD+N level at -120 dBFS input
    # should be close to the noise floor (-90 dBFS) instead of being very low
    assert z_with_noise > z_no_noise
    assert np.isclose(z_with_noise, -90.0, atol=1.0)


def test_noise_floor_relative_dbr_convergence(qtbot, mock_audio_engine, dummy_model_data):
    analyzer = HammersteinAnalyzer(mock_audio_engine)
    widget = HammersteinAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    # Set model data
    widget.set_model_data(dummy_model_data)
    widget.min_level_spin.setValue(-120.0)

    # Switch to relative dBr unit
    widget.harm_unit_combo.setCurrentIndex(widget.harm_unit_combo.findData("dbr"))

    # Enable Noise Floor at -90.0 dBFS
    widget.enable_noise_chk.setChecked(True)
    widget.noise_floor_spin.setValue(-90.0)
    widget.update_2d_map()

    # Query the 2D map at the lowest amplitude (-120 dBFS)
    # Since the input signal (-120 dB) is 30 dB below the noise floor (-90 dB),
    # the relative THD+N in dBr should cap near 0 dBr (100% distortion+noise ratio)
    z_dbr_low_sig = widget.cached_Z[0, 100]
    
    # Cap should be close to 0.0 dBr
    assert z_dbr_low_sig <= 0.0
    assert np.isclose(z_dbr_low_sig, 0.0, atol=0.5)

    # Disable Noise Floor: without noise floor, it should drop significantly below 0 dBr
    # because distortion reduces with amplitude
    widget.enable_noise_chk.setChecked(False)
    widget.update_2d_map()
    z_dbr_no_noise_low_sig = widget.cached_Z[0, 100]
    
    assert z_dbr_no_noise_low_sig < -20.0
