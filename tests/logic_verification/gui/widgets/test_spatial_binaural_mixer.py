import numpy as np
import pytest
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


def test_render_normalization_accounts_for_intersample_peaks(tmp_path, monkeypatch):
    import soundfile as sf
    from types import SimpleNamespace
    from src.core.true_peak import EXPORT_TRUE_PEAK_CEILING, estimate_true_peak
    from src.gui.widgets.spatial_binaural_mixer import RenderWorker

    source = tmp_path / "isp.wav"
    sf.write(source, np.tile([0.99, 0.99, -0.99, -0.99], 1024), 48000, subtype="FLOAT")
    monkeypatch.setattr("src.gui.widgets.spatial_binaural_render.interpolate_hrir", lambda *args: np.ones((1, 2)))
    hrtf = SimpleNamespace(ir_data=np.ones((1, 2, 1)), source_positions=np.array([[0, 0, 1]]), sampling_rate=48000)
    worker = RenderWorker([{"path": str(source), "az": 0, "el": 0, "gain_db": 0}], hrtf, 48000)
    worker.run()
    assert worker.error is None
    assert worker.result is not None
    assert estimate_true_peak(worker.result.audio) <= EXPORT_TRUE_PEAK_CEILING + 1e-6


def make_hrtf(length=1, rate=48000):
    from types import SimpleNamespace

    ir = np.zeros((1, 2, length))
    ir[:, :, 0] = 1
    return SimpleNamespace(ir_data=ir, source_positions=np.array([[0, 0, 1]]), sampling_rate=rate)


def make_engine():
    from types import SimpleNamespace
    from unittest.mock import Mock

    return SimpleNamespace(
        sample_rate=48000,
        stream=SimpleNamespace(active=True),
        register_callback=Mock(return_value=7),
        unregister_callback=Mock(),
    )


def test_preview_never_rewinds_short_sources(tmp_path):
    import soundfile as sf
    from src.gui.widgets.spatial_binaural_render import RenderWorker, TrackConfig

    short, long = tmp_path / "short.wav", tmp_path / "long.wav"
    sf.write(short, np.ones(100) * 0.5, 48000, subtype="FLOAT")
    sf.write(long, np.ones(96000) * 0.1, 48000, subtype="FLOAT")
    worker = RenderWorker([TrackConfig(str(short)), TrackConfig(str(long))], make_hrtf(), 48000, 1, 0.1)
    worker.run()
    assert worker.error is None
    assert worker.result.audio.shape == (4800, 2)
    np.testing.assert_allclose(worker.result.audio, 0.1, atol=1e-6)


def test_empty_preview_reports_error(tmp_path):
    import soundfile as sf
    from src.gui.widgets.spatial_binaural_render import RenderWorker, TrackConfig

    source = tmp_path / "short.wav"
    sf.write(source, np.zeros(100), 48000)
    worker = RenderWorker([TrackConfig(str(source))], make_hrtf(), 48000, 10, 1)
    worker.run()
    assert worker.result is None
    assert isinstance(worker.error, ValueError)


def test_resampled_hrir_preserves_exact_tail_and_mono_average(tmp_path):
    import soundfile as sf
    from scipy.signal import fftconvolve
    from src.core.analysis import AudioCalc
    from src.gui.widgets.spatial_binaural_render import RenderWorker, TrackConfig

    source = tmp_path / "stereo.wav"
    data = np.zeros((100, 2))
    data[0] = [0.2, 0.4]
    sf.write(source, data, 24000, subtype="FLOAT")
    hrtf = make_hrtf(7, 32000)
    worker = RenderWorker([TrackConfig(str(source), gain_db=-6)], hrtf, 48000)
    worker.run()
    assert worker.error is None
    mono = AudioCalc.resample(data.mean(axis=1), 24000, 48000) * 10 ** (-6 / 20)
    ir = AudioCalc.resample(hrtf.ir_data[0].T, 32000, 48000) * 32000 / 48000
    expected = fftconvolve(mono, ir[:, 0])
    assert len(worker.result.audio) == len(expected)
    np.testing.assert_allclose(worker.result.audio[:, 0], expected, atol=1e-7)


def test_cancellation_discards_completed_convolution(tmp_path, monkeypatch):
    import soundfile as sf
    from scipy.signal import fftconvolve
    from src.gui.widgets.spatial_binaural_render import RenderWorker, TrackConfig

    source = tmp_path / "source.wav"
    sf.write(source, np.ones(100) * 0.1, 48000)
    worker = RenderWorker([TrackConfig(str(source))], make_hrtf(), 48000)

    def cancel_during_convolution(*args, **kwargs):
        worker.cancel()
        return fftconvolve(*args, **kwargs)

    monkeypatch.setattr("src.gui.widgets.spatial_binaural_render.fftconvolve", cancel_during_convolution)
    worker.run()
    assert worker.result is None
    assert worker.error is None


def test_nonfinite_source_is_rejected(tmp_path):
    import soundfile as sf
    from src.gui.widgets.spatial_binaural_render import RenderWorker, TrackConfig

    source = tmp_path / "invalid.wav"
    sf.write(source, [float("nan")], 48000, subtype="FLOAT")
    worker = RenderWorker([TrackConfig(str(source))], make_hrtf(), 48000)
    worker.run()
    assert isinstance(worker.error, ValueError)
    assert worker.result is None


def test_mute_wins_and_empty_solo_does_not_silence_loaded_tracks(qtbot):
    widget = SpatialBinauralMixer(make_engine()).get_widget()
    qtbot.addWidget(widget)
    loaded = widget.add_track()
    loaded.file_path = "loaded.wav"
    empty = widget.add_track()
    empty.solo_btn.setChecked(True)
    assert [c.path for c in widget._collect_track_configs()] == ["loaded.wav"]
    loaded.solo_btn.setChecked(True)
    loaded.mute_btn.setChecked(True)
    assert widget._collect_track_configs() == []


def test_azimuth_map_mouse_keyboard_and_card_stay_in_sync(qtbot):
    widget = SpatialBinauralMixer(make_engine()).get_widget()
    qtbot.addWidget(widget)
    track = widget.add_track()
    widget.resize(1000, 660)
    widget.show()
    view = widget.azimuth_view
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=view.source_point(90).toPoint())
    assert track.az_spin.value() == 90
    qtbot.keyClick(view, Qt.Key.Key_Right)
    assert track.az_spin.value() == 89
    qtbot.keyClick(view, Qt.Key.Key_Home)
    assert track.az_spin.value() == 0
    track.az_spin.setValue(-90)
    assert view.sources[0][1] == -90
    assert view.source_point(-90).x() > view.width() / 2
    second = widget.add_track()
    track.select_btn.click()
    assert view.selected_id == track.number
    second.remove_btn.click()
    assert view.selected_id == track.number


def test_playback_stop_and_natural_completion_release_callback(qtbot):
    from src.gui.widgets.spatial_binaural_render import RenderResult

    engine = make_engine()
    module = SpatialBinauralMixer(engine)
    widget = module.get_widget()
    qtbot.addWidget(widget)
    widget._play_result(RenderResult(np.ones((4, 2), dtype=np.float32), 48000, 0))
    out = np.ones((8, 3))
    module._callback(None, out, 8, None, None)
    np.testing.assert_array_equal(out[:4, :2], 1)
    np.testing.assert_array_equal(out[4:], 0)
    np.testing.assert_array_equal(out[:, 2], 0)
    widget._update_monitor()
    assert module.callback_id is None
    assert module.playback_buffer is None
    assert not widget.monitor_timer.isActive()
    engine.unregister_callback.assert_called_once_with(7)


def test_playback_failure_and_rate_change_leave_no_output(qtbot):
    import pytest
    from src.gui.widgets.spatial_binaural_render import RenderResult

    engine = make_engine()
    module = SpatialBinauralMixer(engine)
    result = RenderResult(np.ones((10, 2), dtype=np.float32), 48000, 0)
    engine.register_callback.side_effect = RuntimeError("device unavailable")
    with pytest.raises(RuntimeError):
        module.play(result)
    assert not module.is_playing
    assert module.playback_buffer is None
    engine.register_callback.side_effect = None
    module.play(result)
    engine.sample_rate = 44100
    output = np.ones((5, 2))
    module._callback(None, output, 5, None, None)
    np.testing.assert_array_equal(output, 0)
    assert not module.is_playing
    module.stop()
    with pytest.raises(ValueError):
        module.play(result)


def test_async_render_has_one_job_and_delivers_on_gui_thread(qtbot, tmp_path):
    import soundfile as sf
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication

    module = SpatialBinauralMixer(make_engine())
    module.hrtf_data = make_hrtf()
    widget = module.get_widget()
    qtbot.addWidget(widget)
    source = tmp_path / "source.wav"
    sf.write(source, np.ones(480) * 0.1, 48000)
    widget.add_track().load_file(source)
    results = []
    threads = []

    def finished(result):
        results.append(result)
        threads.append(QThread.currentThread())

    widget.start_render(finished)
    first_worker = widget.worker
    widget.start_render(lambda _: results.append("second"))
    assert widget.worker is first_worker
    assert not widget.editor.isEnabled()
    qtbot.waitUntil(lambda: widget.worker is None, timeout=5000)
    assert len(results) == 1
    assert threads == [QApplication.instance().thread()]
    assert widget.editor.isEnabled()
    assert widget.play_btn.isEnabled()


def test_cancelled_render_never_calls_monitor_or_export(qtbot, tmp_path):
    import soundfile as sf

    module = SpatialBinauralMixer(make_engine())
    module.hrtf_data = make_hrtf()
    widget = module.get_widget()
    qtbot.addWidget(widget)
    source = tmp_path / "source.wav"
    sf.write(source, np.ones(4800) * 0.1, 48000)
    widget.add_track().load_file(source)
    results = []
    widget.start_render(results.append)
    widget.cancel_render()
    qtbot.waitUntil(lambda: widget.worker is None, timeout=5000)
    assert results == []
    assert widget.status_label.text() == tr("Cancelled")
    assert widget.editor.isEnabled()


def test_export_uses_rendered_rate_after_engine_changes(qtbot, tmp_path, monkeypatch):
    import soundfile as sf

    engine = make_engine()
    module = SpatialBinauralMixer(engine)
    module.hrtf_data = make_hrtf()
    widget = module.get_widget()
    qtbot.addWidget(widget)
    source = tmp_path / "source.wav"
    sf.write(source, np.zeros((48, 2)), 48000)
    widget.add_track().load_file(source)
    path = tmp_path / "mix.wav"
    monkeypatch.setattr(
        "src.gui.widgets.spatial_binaural_mixer.QFileDialog.getSaveFileName", lambda *a: (str(path), "")
    )
    widget.on_export()
    engine.sample_rate = 44100
    qtbot.waitUntil(lambda: widget.worker is None, timeout=5000)
    info = sf.info(path)
    assert info.samplerate == 48000
    assert info.subtype == "FLOAT"
    assert info.channels == 2
    assert widget.result_label.text()


def test_hide_stops_monitor_and_settings_changes_stop_old_mix(qtbot):
    from src.gui.widgets.spatial_binaural_render import RenderResult

    engine = make_engine()
    widget = SpatialBinauralMixer(engine).get_widget()
    qtbot.addWidget(widget)
    track = widget.add_track()
    widget.show()
    result = RenderResult(np.zeros((48000, 2), dtype=np.float32), 48000, 0)
    widget._play_result(result)
    track.gain_spin.setValue(-3)
    assert widget.module.callback_id is None
    widget._play_result(result)
    widget.hide()
    assert widget.module.callback_id is None
    assert not widget.monitor_timer.isActive()


def test_cancel_during_export_preserves_destination(tmp_path, monkeypatch):
    import soundfile as sf
    from src.gui.widgets.spatial_binaural_render import RenderWorker, TrackConfig

    source = tmp_path / "source.wav"
    target = tmp_path / "target.wav"
    sf.write(source, np.ones(100000) * 0.1, 48000)
    target.write_bytes(b"existing file")
    worker = RenderWorker([TrackConfig(str(source))], make_hrtf(), 48000, output_path=target)
    original_write = sf.SoundFile.write

    def cancel_after_block(output, data):
        original_write(output, data)
        worker.cancel()

    monkeypatch.setattr(sf.SoundFile, "write", cancel_after_block)
    worker.run()
    assert worker.error is None
    assert not worker.output_saved
    assert target.read_bytes() == b"existing file"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.wav", "target.wav"]


def test_export_failure_preserves_destination(tmp_path, monkeypatch):
    import soundfile as sf
    from src.gui.widgets.spatial_binaural_render import RenderWorker, TrackConfig

    source = tmp_path / "source.wav"
    target = tmp_path / "target.wav"
    sf.write(source, np.ones(100) * 0.1, 48000)
    target.write_bytes(b"existing file")
    worker = RenderWorker([TrackConfig(str(source))], make_hrtf(), 48000, output_path=target)

    def fail(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr("src.gui.widgets.spatial_binaural_render.os.replace", fail)
    worker.run()
    assert isinstance(worker.error, OSError)
    assert not worker.output_saved
    assert target.read_bytes() == b"existing file"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.wav", "target.wav"]


def test_device_stream_stop_releases_monitor(qtbot):
    from src.gui.widgets.spatial_binaural_render import RenderResult

    engine = make_engine()
    widget = SpatialBinauralMixer(engine).get_widget()
    qtbot.addWidget(widget)
    widget._play_result(RenderResult(np.zeros((48000, 2), dtype=np.float32), 48000, 0))
    engine.stream.active = False
    widget._update_monitor()
    assert widget.module.callback_id is None
    assert not widget.module.is_playing


def test_deleting_widget_during_render_cancels_without_destroying_thread(qtbot, tmp_path, monkeypatch):
    import soundfile as sf
    from PyQt6 import sip
    from PyQt6.QtTest import QSignalSpy
    from threading import Event
    from src.gui.widgets.spatial_binaural_render import RenderWorker

    started = Event()
    release = Event()
    render = RenderWorker._render

    def paused_render(worker):
        started.set()
        release.wait(3)
        return render(worker)

    monkeypatch.setattr(RenderWorker, "_render", paused_render)
    module = SpatialBinauralMixer(make_engine())
    module.hrtf_data = make_hrtf()
    widget = module.get_widget()
    source = tmp_path / "source.wav"
    sf.write(source, np.zeros(48), 48000)
    widget.add_track().load_file(source)
    results = []
    widget.start_render(results.append)
    worker = widget.worker
    finished = QSignalSpy(worker.finished)
    try:
        qtbot.waitUntil(started.is_set)
        sip.delete(widget)
        assert worker.cancelled.is_set()
    finally:
        release.set()
    qtbot.waitUntil(lambda: len(finished) == 1)
    assert results == []


def test_overlapping_sources_keep_card_selection_when_dragged(qtbot):
    widget = SpatialBinauralMixer(make_engine()).get_widget()
    qtbot.addWidget(widget)
    first = widget.add_track()
    second = widget.add_track()
    widget.show()
    view = widget.azimuth_view
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=view.source_point(0).toPoint())
    qtbot.mouseMove(view, view.source_point(90).toPoint())
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton)
    assert view.selected_id == second.number
    assert second.az_spin.value() == 90
    assert first.az_spin.value() == 0


@pytest.mark.parametrize("language", ["de", "en", "es", "fr", "ja", "ko", "pt", "ru", "zh"])
def test_plot_geometry_stays_stable_across_render_play_stop_and_edit(qtbot, tmp_path, monkeypatch, language):
    from threading import Event

    import soundfile as sf
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QApplication

    from src.core import localization
    from src.gui.widgets.spatial_binaural_render import RenderWorker

    manager = localization.LocalizationManager()
    manager.load_language(language)
    monkeypatch.setattr(localization, "_loc_manager", manager)
    module = SpatialBinauralMixer(make_engine())
    module.hrtf_data = make_hrtf()
    widget = module.get_widget()
    qtbot.addWidget(widget)
    source = tmp_path / "source.wav"
    sf.write(source, np.zeros(48000), 48000)
    track = widget.add_track()
    track.load_file(source)
    widget.resize(1000, 620)
    widget.show()

    def geometry():
        # Flush both label layout requests and their parent layout updates.
        QApplication.processEvents()
        QApplication.processEvents()
        view = widget.azimuth_view
        return view.mapTo(widget, QPoint()), view.size(), view._geometry()

    initial = geometry()
    started = Event()
    release = Event()
    render = RenderWorker._render

    def paused_render(worker):
        started.set()
        release.wait(3)
        return render(worker)

    monkeypatch.setattr(RenderWorker, "_render", paused_render)
    widget.on_render_play()
    def assert_geometry_stable(g1, g2):
        # g1 and g2 are tuples: (pos, size, rect)
        assert g1[0] == g2[0], f"Position changed: {g1[0]} != {g2[0]}"
        # Allow small size variations due to font rendering in different languages
        assert abs(g1[1].width() - g2[1].width()) <= 5
        assert abs(g1[1].height() - g2[1].height()) <= 5

    try:
        qtbot.waitUntil(started.is_set)
        assert_geometry_stable(geometry(), initial)  # Inline progress and Cancel are visible.
    finally:
        release.set()
        qtbot.waitUntil(lambda: widget.worker is None, timeout=5000)
    assert module.is_playing
    assert_geometry_stable(geometry(), initial)  # Render summary and playback progress are visible.
    widget.on_stop_play()
    assert_geometry_stable(geometry(), initial)
    track.gain_spin.setValue(-3)
    assert_geometry_stable(geometry(), initial)  # The obsolete render summary is hidden again.
