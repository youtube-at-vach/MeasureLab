import sys
from unittest.mock import MagicMock

import numpy as np

sys.modules["sounddevice"] = MagicMock()

import src.gui.widgets.waveform_loop_player as waveform_loop_player  # noqa: E402
from src.core.audio_engine import AudioEngine  # noqa: E402
from src.gui.widgets.waveform_loop_player import WaveformLoopPlayer, make_waveform_display_data  # noqa: E402


def _make_player(sample_rate=10):
    audio_engine = MagicMock(spec=AudioEngine)
    audio_engine.sample_rate = sample_rate
    audio_engine.register_callback.return_value = "callback-id"
    return WaveformLoopPlayer(audio_engine)


def test_selection_loop_repeats_only_selected_region():
    player = _make_player(sample_rate=10)
    data = np.arange(20, dtype=np.float32).reshape(10, 2)
    player.set_playback_data(data)
    player.set_selection_seconds(0.2, 0.5)  # samples 2, 3, 4
    player.start_playback()

    outdata = np.zeros((7, 2), dtype=np.float32)
    player.audio_callback(None, outdata, len(outdata), None, None)

    expected = np.vstack([data[2:5], data[2:5], data[2:3]])
    np.testing.assert_array_equal(outdata, expected)
    assert player.is_playing
    assert player.playback_pos == 3


def test_selection_without_loop_stops_and_zero_fills_tail():
    player = _make_player(sample_rate=10)
    data = np.ones((10, 2), dtype=np.float32)
    player.set_playback_data(data)
    player.set_selection_seconds(0.1, 0.4)  # 3 frames
    player.loop_selection = False
    player.start_playback()

    outdata = np.full((5, 2), -1.0, dtype=np.float32)
    player.audio_callback(None, outdata, len(outdata), None, None)

    np.testing.assert_array_equal(outdata[:3], np.ones((3, 2), dtype=np.float32))
    np.testing.assert_array_equal(outdata[3:], np.zeros((2, 2), dtype=np.float32))
    assert not player.is_playing


def test_output_modes_and_gain_are_applied():
    player = _make_player(sample_rate=10)
    data = np.array([[1.0, 0.5], [0.25, -0.25]], dtype=np.float32)
    player.set_playback_data(data)
    player.set_selection_seconds(0.0, 0.2)
    player.output_mode = "Mono"
    player.playback_gain_db = -6.0
    player.start_playback()

    outdata = np.zeros((2, 2), dtype=np.float32)
    player.audio_callback(None, outdata, len(outdata), None, None)

    gain = 10 ** (-6.0 / 20.0)
    mono = np.mean(data, axis=1) * gain
    expected = np.column_stack((mono, mono))
    np.testing.assert_allclose(outdata, expected, rtol=1e-6)


def test_make_waveform_display_data_decimates_visible_raw_range_for_zoom():
    data = np.array([0.0, -0.5, 0.25, 1.0, -1.0, 0.2], dtype=np.float32)

    x, y = make_waveform_display_data(data, sample_rate=6, max_points=4)

    np.testing.assert_allclose(x, np.array([0.0, 2.0 / 6.0, 4.0 / 6.0], dtype=np.float32))
    np.testing.assert_allclose(y, np.array([0.0, 0.25, -1.0], dtype=np.float32))


def test_make_waveform_display_data_uses_min_max_envelope_for_large_ranges(monkeypatch):
    monkeypatch.setattr(waveform_loop_player, "RAW_WAVEFORM_POINT_LIMIT", 4)
    data = np.array([0.0, -0.5, 0.25, 1.0, -1.0, 0.2], dtype=np.float32)

    x, y = make_waveform_display_data(data, sample_rate=6, max_points=6)

    np.testing.assert_allclose(x[0:3], np.array([1.0 / 6.0, 1.0 / 6.0, np.nan], dtype=np.float32))
    np.testing.assert_allclose(y[0:3], np.array([-0.5, 0.25, np.nan], dtype=np.float32))
    np.testing.assert_allclose(x[3:6], np.array([4.0 / 6.0, 4.0 / 6.0, np.nan], dtype=np.float32))
    np.testing.assert_allclose(y[3:6], np.array([-1.0, 1.0, np.nan], dtype=np.float32))
