import pytest
from unittest.mock import MagicMock
import numpy as np

from src.gui.widgets.predistortion_processor import (
    PredistortionProcessor,
    PredistortionProcessorWidget,
)
from src.core.hammerstein_model import set_active_model


@pytest.fixture
def mock_audio_engine():
    engine = MagicMock()
    engine.sample_rate = 48000
    engine.block_size = 512
    return engine


def test_predistortion_processor_sss_source(qtbot, mock_audio_engine):
    # Clear model cache to prevent test interference
    set_active_model(None)

    # 1. Initialize module and widget
    module = PredistortionProcessor(mock_audio_engine)
    widget = PredistortionProcessorWidget(module)
    qtbot.addWidget(widget)

    # By default, controls are disabled until a model is loaded
    assert not widget.spin_sss_start_freq.isEnabled()

    # Mock load model data to enable controls
    dummy_model = {
        "metadata": {
            "sample_rate": 48000,
            "max_order": 3,
            "model_direction": "inverse",
        },
        "time_domain": {
            "kernels": {
                "h1": np.zeros(100).tolist(),
                "h2": np.zeros(100).tolist(),
                "h3": np.zeros(100).tolist(),
            }
        }
    }
    module.applicator.load_model(dummy_model)
    widget.model_data = dummy_model
    widget.update_model_info()
    widget.set_controls_enabled(True)

    assert widget.spin_sss_start_freq.isEnabled()
    assert not widget.sss_widget.isVisible()

    # Change source mode to sss
    widget.combo_source.setCurrentIndex(2)  # "sss"
    assert module.source_mode == "sss"
    assert not widget.sss_widget.isHidden()

    # Set parameters
    widget.spin_sss_start_freq.setValue(50.0)
    widget.spin_sss_end_freq.setValue(15000.0)
    widget.spin_sss_duration.setValue(5.0)
    widget.spin_sss_amp.setValue(-3.0)

    # Sync to module
    widget.on_param_changed()
    assert module.sss_start_freq == 50.0
    assert module.sss_end_freq == 15000.0
    assert module.sss_duration == 5.0
    assert abs(module.sss_amp - 10**(-3.0/20.0)) < 1e-6

    # Verify that the simulation button is disabled in SSS mode
    assert not widget.btn_run_sim.isEnabled()

    # Test running simulation (should return early without doing anything since source is sss)
    widget.on_run_simulation()
    # Check that curves data are NOT populated
    assert widget.curves["in_time"].yData is None or len(widget.curves["in_time"].yData) == 0

    # Switch back to tone generator to check that simulation button becomes enabled
    widget.combo_source.setCurrentIndex(0)  # "tone"
    assert widget.btn_run_sim.isEnabled()
    # Test running simulation in tone mode works
    widget.on_run_simulation()
    assert len(widget.curves["in_time"].yData) > 0
