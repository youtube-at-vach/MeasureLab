import numpy as np
from PyQt6.QtCore import Qt

from src.core.localization import tr
from src.gui.widgets.hrtf_player import HRTFData
from src.gui.widgets.spatial_binaural_mixer import SpatialBinauralMixer, interpolate_hrir


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
    track_ui.remove_btn.click()  # Simulate remove click

    assert len(widget.tracks) == 0


def test_spatial_mixer_controls_expose_accessible_names_and_label_buddies(qtbot):
    module = SpatialBinauralMixer(None)
    widget = module.get_widget()
    qtbot.addWidget(widget)

    assert widget.tracks_area.accessibleName() == tr("Tracks")
    assert widget.start_label.buddy() is widget.start_sec_spin
    assert widget.duration_label.buddy() is widget.duration_sec_spin
    assert widget.start_sec_spin.accessibleName() == tr("Start:")
    assert widget.duration_sec_spin.accessibleName() == tr("Duration:")
    assert widget.prev_btn.accessibleName() == tr("Previous Preview Segment")
    assert widget.next_btn.accessibleName() == tr("Next Preview Segment")
    assert widget.play_btn.accessibleName() == tr("Render & Monitor")
    assert widget.stop_btn.accessibleName() == tr("Stop Monitor")
    assert widget.export_btn.accessibleName() == tr("Render to WAV")

    widget.add_track()
    track = widget.tracks[0]
    assert track.az_label.buddy() is track.az_spin
    assert track.el_label.buddy() is track.el_spin
    assert track.gain_label.buddy() is track.gain_spin
    assert track.az_spin.accessibleName() == tr("Azimuth:")
    assert track.el_spin.accessibleName() == tr("Elevation:")
    assert track.gain_spin.accessibleName() == tr("Gain:")
    assert track.name_label.accessibleName() == tr("Loaded audio file")
    assert track.remove_btn.accessibleName() == tr("Remove Track")

    widget.add_track()
    second_track = widget.tracks[1]
    assert widget.add_track_btn.nextInFocusChain() is track.load_btn
    assert track.remove_btn.nextInFocusChain() is second_track.load_btn
    assert second_track.remove_btn.nextInFocusChain() is widget.preview_cb


def test_spatial_mixer_icon_controls_support_keyboard_activation(qtbot):
    module = SpatialBinauralMixer(None)
    widget = module.get_widget()
    qtbot.addWidget(widget)
    widget.show()

    widget.preview_cb.setChecked(True)
    widget.start_sec_spin.setValue(20.0)
    widget.duration_sec_spin.setValue(5.0)

    widget.prev_btn.setFocus()
    qtbot.keyClick(widget.prev_btn, Qt.Key.Key_Space)
    assert widget.start_sec_spin.value() == 15.0

    widget.next_btn.setFocus()
    qtbot.keyClick(widget.next_btn, Qt.Key.Key_Space)
    assert widget.start_sec_spin.value() == 20.0

    widget.add_track()
    track = widget.tracks[0]
    track.remove_btn.setFocus()
    qtbot.keyClick(track.remove_btn, Qt.Key.Key_Space)
    assert widget.tracks == []


def test_interpolate_hrir_exact_match():
    pos = np.array([[0.0, 0.0, 1.0], [90.0, 0.0, 1.0]])
    ir_data = np.zeros((2, 2, 10))
    ir_data[0, :, 0] = 1.0
    ir_data[1, :, 1] = 1.0

    hrtf_data = HRTFData(
        source_positions=pos,
        ir_data=ir_data,
        sampling_rate=48000.0,
        itd=np.zeros(2),
        ild=np.zeros(2),
        energy_high=np.zeros((2, 2)),
        group_delay_peak=np.zeros((2, 2)),
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
        source_positions=pos,
        ir_data=ir_data,
        sampling_rate=48000.0,
        itd=np.zeros(2),
        ild=np.zeros(2),
        energy_high=np.zeros((2, 2)),
        group_delay_peak=np.zeros((2, 2)),
    )

    res = interpolate_hrir(hrtf_data, target_az=45.0, target_el=0.0, k=2, p=2.0)
    expected = np.zeros((10, 2))
    expected[:, :] = 1.5
    assert np.allclose(res, expected)
