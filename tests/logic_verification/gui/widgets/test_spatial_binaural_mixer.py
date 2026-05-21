

from src.gui.widgets.spatial_binaural_mixer import SpatialBinauralMixer

def test_spatial_binaural_mixer_instantiation(qtbot):
    """Smoke test to ensure the widget can be instantiated without crashing."""
    module = SpatialBinauralMixer(None)

    widget = module.get_widget()
    qtbot.addWidget(widget)

    assert widget is not None
    assert widget.layout() is not None

def test_add_remove_track(qtbot):
    module = SpatialBinauralMixer(None)

    widget = module.get_widget()
    qtbot.addWidget(widget)

    # Initially 0 tracks
    assert widget.tracks_inner_layout.count() == 0

    # Add track
    widget.add_track()
    # Now there should be one track UI + stretch
    assert len(widget.tracks) == 1

    # Remove track
    track_ui = widget.tracks[0]
    track_ui.remove_btn.click() # Simulate remove click

    assert len(widget.tracks) == 0

import numpy as np
from src.gui.widgets.hrtf_player import HRTFData
from src.gui.widgets.spatial_binaural_mixer import interpolate_hrir

def test_interpolate_hrir_exact_match():
    pos = np.array([[0.0, 0.0, 1.0], [90.0, 0.0, 1.0]])
    ir_data = np.zeros((2, 2, 10))
    ir_data[0, :, 0] = 1.0
    ir_data[1, :, 1] = 1.0

    hrtf_data = HRTFData(
        source_positions=pos, ir_data=ir_data, sampling_rate=48000.0,
        itd=np.zeros(2), ild=np.zeros(2), energy_high=np.zeros((2, 2)), group_delay_peak=np.zeros((2, 2))
    )

    res = interpolate_hrir(hrtf_data, target_az=90.0, target_el=0.0, k=2, p=2.0)
    assert res.shape == (10, 2)
    assert np.allclose(res[:, 0], ir_data[1, 0, :])
    assert np.allclose(res[:, 1], ir_data[1, 1, :])

def test_interpolate_hrir_idw_blending():
    pos = np.array([[0.0, 0.0, 1.0], [90.0, 0.0, 1.0]])
    ir_data = np.zeros((2, 2, 10))
    ir_data[0, :, :] = 1.0
    ir_data[1, :, :] = 2.0

    hrtf_data = HRTFData(
        source_positions=pos, ir_data=ir_data, sampling_rate=48000.0,
        itd=np.zeros(2), ild=np.zeros(2), energy_high=np.zeros((2, 2)), group_delay_peak=np.zeros((2, 2))
    )

    res = interpolate_hrir(hrtf_data, target_az=45.0, target_el=0.0, k=2, p=2.0)
    expected = np.zeros((10, 2))
    expected[:, :] = 1.5
    assert np.allclose(res, expected)
