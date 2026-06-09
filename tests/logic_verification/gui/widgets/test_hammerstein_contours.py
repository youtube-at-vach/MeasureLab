import pytest
import numpy as np
from unittest.mock import MagicMock

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
            "end_freq": 1000.0,
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
            },
        },
        "time_domain": {
            "time_ms": np.array([0.0, 1.0, 2.0]),
            "kernels": {
                "h1": np.array([1.0, 0.0, 0.0]),
                "h2": np.array([0.01, 0.0, 0.0]),
                "h3": np.array([0.001, 0.0, 0.0]),
                "h4": np.array([0.0, 0.0, 0.0]),
                "h5": np.array([0.0, 0.0, 0.0]),
            },
        },
    }


def test_contour_toggling_visibility(qtbot, mock_audio_engine, dummy_model_data):
    analyzer = HammersteinAnalyzer(mock_audio_engine)
    widget = HammersteinAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    # Set data
    widget.set_model_data(dummy_model_data)

    # Enable contours and draw
    widget.show_contours_chk.setChecked(True)
    widget.update_2d_map()

    # Capture contour items that were created
    assert len(widget.iso_curves) > 0
    contour_items = list(widget.iso_curves)

    # Verify they are in the scene (since parenting to image_item, which is in plot_item)
    for iso in contour_items:
        assert iso.scene() is not None

    # Toggle contours OFF
    widget.show_contours_chk.setChecked(False)
    widget.update_2d_map()

    # Verify lists are empty
    assert len(widget.iso_curves) == 0
    assert len(widget.iso_labels) == 0

    # Verify all previously created contour items are no longer in the scene
    for iso in contour_items:
        assert iso.scene() is None
        assert iso.parentItem() is None


def test_monotonic_contour_drawing_and_label_crossing(qtbot, mock_audio_engine, dummy_model_data):
    analyzer = HammersteinAnalyzer(mock_audio_engine)
    widget = HammersteinAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    # Set data with a low noise floor to trigger non-monotonicity in dBr unit
    widget.set_model_data(dummy_model_data)
    widget.min_level_spin.setValue(-120.0)
    widget.max_level_spin.setValue(0.0)
    widget.harm_unit_combo.setCurrentIndex(widget.harm_unit_combo.findData("dbr"))
    widget.enable_noise_chk.setChecked(True)
    widget.noise_floor_spin.setValue(-90.0)
    widget.show_contours_chk.setChecked(True)

    widget.update_2d_map()

    # Ensure some contours are generated
    assert len(widget.iso_curves) > 0
    assert len(widget.iso_labels) > 0

    # Verify labels correspond to valid Y-coordinates (input amplitude range: -120 to 0)
    for lbl in widget.iso_labels:
        y_pos = lbl.pos().y()
        assert -120.0 <= y_pos <= 0.0

    # Verify that multiple crossings (duplicate labels for the same level) are detected
    label_texts = [lbl.toPlainText() for lbl in widget.iso_labels]
    has_duplicates = any(label_texts.count(x) > 1 for x in set(label_texts))
    assert has_duplicates
