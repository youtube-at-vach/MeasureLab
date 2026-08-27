from unittest.mock import MagicMock

import numpy as np
from PyQt6.QtWidgets import QBoxLayout

from src.core.module_constants import MODULE_RECORDER_PLAYER
from src.gui.module_registry import MODULE_REGISTRY
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.gui.widgets.recorder_player import LoadedAudioInfo, RecorderPlayer, RecorderPlayerWidget


class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.register_callback = MagicMock(return_value=1)
        self.unregister_callback = MagicMock()


def make_widget(qtbot):
    module = RecorderPlayer(MockAudioEngine())
    widget = RecorderPlayerWidget(module)
    qtbot.addWidget(widget)
    return module, widget


def load_test_audio(module, widget):
    module.set_playback_data(np.zeros((96000, 2), dtype=np.float32))
    widget._loaded_info = LoadedAudioInfo(
        path="/tmp/test-tone.wav",
        source_sample_rate=44100,
        playback_sample_rate=48000,
        channels=2,
        duration_seconds=2.0,
    )
    widget.update_ui()


def test_initial_state_explains_unavailable_actions(qtbot):
    _module, widget = make_widget(qtbot)

    assert not widget.play_btn.isEnabled()
    assert not widget.pos_slider.isEnabled()
    assert not widget.save_btn.isEnabled()
    assert not widget.sync_check.isEnabled()
    assert "Load" in widget.play_btn.toolTip()
    assert "recording" in widget.save_btn.toolTip().lower()


def test_loaded_file_enables_transport_and_structures_metadata(qtbot):
    module, widget = make_widget(qtbot)
    load_test_audio(module, widget)

    assert widget.play_btn.isEnabled()
    assert widget.pos_slider.isEnabled()
    assert widget.sync_check.isEnabled()
    assert widget.file_label.text() == "test-tone.wav"
    assert "48000" in widget.file_meta_label.text()
    assert "44100" in widget.file_meta_label.text()
    assert widget.total_label.text() == "00:02.00"


def test_compact_mode_keeps_critical_state_and_controls(qtbot):
    module, widget = make_widget(qtbot)
    load_test_audio(module, widget)
    module.playback_pos = 24000
    module.is_playing = True
    module.is_recording = True
    module.recorded_samples = 12000
    widget._has_unsaved_recording = True
    widget.update_ui()

    assert isinstance(widget, CompactableWidgetInterface)
    widget.set_compact_mode(True)

    assert widget.full_container.isHidden()
    assert not widget.compact_container.isHidden()
    assert widget.compact_play_btn.isVisibleTo(widget)
    assert widget.compact_rec_btn.isVisibleTo(widget)
    assert widget.compact_pos_slider.isVisibleTo(widget)
    assert "Stereo" in widget.compact_conditions_label.text()
    assert module.is_playing
    assert module.is_recording
    assert module.playback_pos == 24000

    widget.set_compact_mode(False)
    assert not widget.full_container.isHidden()
    assert widget.compact_container.isHidden()
    assert module.is_playing
    assert module.is_recording

    module.is_playing = False
    module.is_recording = False


def test_unsaved_recording_is_visible_and_saveable_in_compact(qtbot):
    module, widget = make_widget(qtbot)
    module.recorded_samples = 48000
    widget._has_unsaved_recording = True
    widget.update_ui()
    widget.set_compact_mode(True)

    assert widget.recording_status_label.text() == "Unsaved"
    assert widget.save_btn.isEnabled()
    assert not widget.compact_save_btn.isHidden()
    assert widget.compact_save_btn.isEnabled()


def test_gain_slider_and_direct_input_share_one_model_value(qtbot):
    module, widget = make_widget(qtbot)

    widget.gain_spin.setValue(-6.5)
    assert module.playback_gain_db == -6.5
    assert widget.gain_slider.value() == -13

    widget.gain_slider.setValue(6)
    assert module.playback_gain_db == 3.0
    assert widget.gain_spin.value() == 3.0


def test_responsive_layout_switches_by_card_not_by_scaling(qtbot):
    _module, widget = make_widget(qtbot)
    widget.show()

    widget.resize(700, 500)
    qtbot.wait(20)
    assert widget.cards_layout.direction() == QBoxLayout.Direction.TopToBottom

    widget.resize(900, 500)
    qtbot.wait(20)
    assert widget.cards_layout.direction() == QBoxLayout.Direction.LeftToRight


def test_registry_declares_compact_without_split_or_comparison():
    capabilities = MODULE_REGISTRY[MODULE_RECORDER_PLAYER].capabilities

    assert capabilities.compact_mode.is_supported
    assert not capabilities.split_window.is_supported
    assert not capabilities.comparison.is_supported
