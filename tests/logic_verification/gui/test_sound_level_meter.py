import numpy as np
import scipy.signal
import pytest
from unittest.mock import MagicMock
from src.gui.widgets.sound_level_meter import SoundLevelMeter, SoundLevelMeterWidget
from src.gui.widgets.splittable_interface import SplittableWidgetInterface


class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MagicMock()
        self.calibration.get_spl_offset_db.return_value = 0.0

    def register_callback(self, callback):
        return 1

    def unregister_callback(self, callback_id):
        pass


@pytest.fixture
def slm():
    engine = MockAudioEngine()
    slm = SoundLevelMeter(engine)
    slm.set_channel(0)
    return slm


class TestSoundLevelMeterLogic:
    def test_uncalibrated_display_uses_dbfs(self, qtbot):
        engine = MockAudioEngine()
        engine.calibration.get_spl_offset_db.return_value = None
        module = SoundLevelMeter(engine)
        widget = SoundLevelMeterWidget(module)
        qtbot.addWidget(widget)
        module.is_running = True
        module.results.update({"Lp": -20.0, "Leq": -21.0, "Lmax": -18.0})

        widget.update_display()

        assert widget.disp_lp["unit"].text() == "dBFS"
        assert widget.disp_leq["unit"].text() == "dBFS"
        assert widget.metric_labels["Lmax"].text().endswith(" dBFS")
        assert not widget.calibration_warning.isHidden()
        assert "dBFS" in widget.calibration_warning.text()

    def test_calibrated_display_uses_db_spl(self, qtbot):
        engine = MockAudioEngine()
        engine.calibration.get_spl_offset_db.return_value = 94.0
        module = SoundLevelMeter(engine)
        widget = SoundLevelMeterWidget(module)
        qtbot.addWidget(widget)
        module.is_running = True
        module.results.update({"Lp": -20.0, "Leq": -21.0, "Lmax": -18.0})

        widget.update_display()

        assert widget.disp_lp["unit"].text() == "dB SPL"
        assert widget.disp_lp["label"].text() == "74.0"
        assert widget.metric_labels["Lmax"].text() == "76.0 dB SPL"
        assert widget.calibration_warning.isHidden()

    def test_calibration_warning_updates_while_stopped(self, qtbot):
        engine = MockAudioEngine()
        engine.calibration.get_spl_offset_db.return_value = None
        module = SoundLevelMeter(engine)
        widget = SoundLevelMeterWidget(module)
        qtbot.addWidget(widget)

        assert not widget.calibration_warning.isHidden()

        engine.calibration.get_spl_offset_db.return_value = 94.0
        widget.update_display()

        assert widget.calibration_warning.isHidden()
        assert widget.disp_lp["unit"].text() == "dB SPL"

    def test_sound_level_meter_impulse_logic(self):
        engine = MockAudioEngine()
        slm = SoundLevelMeter(engine)

        # Use Z weighting to avoid A-weighting complications (though 1kHz is 0dB)
        slm.set_freq_weighting("Z")
        # Bandwidth filter is still active (20Hz highpass), so we need AC signal.

        # Test IMPULSE weighting
        slm.set_time_weighting("IMPULSE")
        slm.start_analysis()

        sr = 48000
        frames = 1024

        # 1kHz sine wave
        t = np.linspace(0, frames / sr, frames, endpoint=False)
        sig_1k = np.sin(2 * np.pi * 1000 * t)
        # Stack for stereo
        indata_sine = np.column_stack((sig_1k, sig_1k))

        # Run a few callbacks with silence to settle filters
        for _ in range(10):
            indata = np.zeros((frames, 2))
            slm.callback(indata, None, frames, None, None)

        assert slm.current_sq_val == 0.0 or slm.current_sq_val < 1e-9

        # Inject signal (Sine wave)
        slm.callback(indata_sine, None, frames, None, None)

        # Impulse response should rise
        # value should be > 0
        assert slm.current_sq_val > 1e-6
        val_after_pulse = slm.current_sq_val

        # Silence again
        indata = np.zeros((frames, 2))
        slm.callback(indata, None, frames, None, None)

        # Impulse falls slowly (decay 1.5s) so it should still be high but slightly lower
        # However, since we fed a burst, the "Slow Fall" applies to the peak detector nature.
        # The stored value should decrease with tau=1.5s

        assert slm.current_sq_val < val_after_pulse
        # But shouldn't drop to zero instantly
        assert slm.current_sq_val > val_after_pulse * 0.9

        slm.stop_analysis()

    def test_sound_level_meter_fast_logic(self):
        engine = MockAudioEngine()
        slm = SoundLevelMeter(engine)

        slm.set_time_weighting("FAST")
        slm.start_analysis()

        sr = 48000
        frames = 1024
        t = np.linspace(0, frames / sr, frames, endpoint=False)
        sig_1k = np.sin(2 * np.pi * 1000 * t)
        indata_sine = np.column_stack((sig_1k, sig_1k))

        # Inject signal
        slm.callback(indata_sine, None, frames, None, None)

        assert slm.current_sq_val > 0.0

        slm.stop_analysis()


class TestSoundLevelMeterWeighting:
    def test_a_weighting_response(self, slm):
        """Verify A-weighting frequency response against IEC 61672 standard values."""
        slm.set_freq_weighting("A")
        # Force update filters
        slm._update_filters()

        sos = slm.sos_filter
        assert sos is not None, "A-weighting filter should not be None"

        # Standard A-weighting values (approx from IEC 61672-1:2003)
        # Freq (Hz): Expected Gain (dB)
        test_points = {
            63: -26.2,
            100: -19.1,
            125: -16.1,
            250: -8.6,
            500: -3.2,
            1000: 0.0,
            2000: 1.2,
            4000: 1.0,
            8000: -1.1,
            16000: -6.6,
        }

        fs = slm.audio_engine.sample_rate

        for freq, expected_db in test_points.items():
            w, h = scipy.signal.sosfreqz(sos, worN=[freq], fs=fs)
            measured_db = 20 * np.log10(np.abs(h[0]) + 1e-12)

            # Tolerance: 1.0 dB generally, but 4.0 dB for 16kHz due to digital roll-off near Nyquist
            tol = 4.0 if freq >= 16000 else 1.0

            # Using print for debug if it fails
            if abs(measured_db - expected_db) >= tol:
                print(f"DEBUG: Freq {freq}Hz, Expected {expected_db}, Got {measured_db:.2f}")

            assert abs(measured_db - expected_db) < tol, (
                f"A-Weighting failed at {freq}Hz: Expected {expected_db}, got {measured_db:.2f}"
            )

    def test_c_weighting_response(self, slm):
        """Verify C-weighting frequency response against IEC 61672 standard values."""
        slm.set_freq_weighting("C")
        slm._update_filters()

        sos = slm.sos_filter
        assert sos is not None, "C-weighting filter should not be None"

        test_points = {
            63: -0.8,
            125: -0.2,
            250: 0.0,
            500: 0.0,
            1000: 0.0,
            2000: -0.2,
            4000: -0.8,
            8000: -3.0,
            16000: -8.5,
        }

        fs = slm.audio_engine.sample_rate

        for freq, expected_db in test_points.items():
            w, h = scipy.signal.sosfreqz(sos, worN=[freq], fs=fs)
            measured_db = 20 * np.log10(np.abs(h[0]) + 1e-12)

            tol = 4.0 if freq >= 16000 else 1.0
            assert abs(measured_db - expected_db) < tol, (
                f"C-Weighting failed at {freq}Hz: Expected {expected_db}, got {measured_db:.2f}"
            )

    def test_bw_filter_response(self, slm):
        """Verify bandwidth filter response (20Hz-20kHz)."""
        slm._update_filters()  # Default is 20-20k (Wide)
        sos = slm.bw_filter
        assert sos is not None

        fs = slm.audio_engine.sample_rate

        # Check 100Hz (should be near 0dB)
        w, h = scipy.signal.sosfreqz(sos, worN=[100], fs=fs)
        measured_db = 20 * np.log10(np.abs(h[0]) + 1e-12)
        print(f"DEBUG: BW Filter at 100Hz: {measured_db:.2f} dB")
        assert abs(measured_db) < 0.5, f"BW Filter 100Hz gain error: {measured_db}"

        # Check 1kHz
        w, h = scipy.signal.sosfreqz(sos, worN=[1000], fs=fs)
        measured_db = 20 * np.log10(np.abs(h[0]) + 1e-12)
        assert abs(measured_db) < 0.1

    def test_z_weighting_response(self, slm):
        """Verify Z-weighting is flat (no filter)."""
        slm.set_freq_weighting("Z")
        slm._update_filters()

        # Z weighting usually means flat, so filter might be None or Identity
        # Implementation: self.sos_filter = None
        assert slm.sos_filter is None, "Z-weighting should have no filter (flat)"

    def test_filter_application_via_callback(self, slm):
        """Verify that the frequency weighting is applied during signal processing."""
        slm.set_freq_weighting("A")
        slm.set_time_weighting("FAST")
        slm.start_analysis()

        sr = slm.audio_engine.sample_rate
        duration = 2.0  # seconds (increased to ensure full settling of filters and time weighting)
        frames = int(sr * duration)
        t = np.linspace(0, duration, frames, endpoint=False)

        # 1. Test 1kHz (0dB gain)
        sig_1k = np.sin(2 * np.pi * 1000 * t)
        indata_1k = np.column_stack((sig_1k, sig_1k))

        # Process in chunks
        chunk_size = 1024
        for i in range(0, frames, chunk_size):
            chunk = indata_1k[i : i + chunk_size]
            if len(chunk) < chunk_size:
                break
            slm.callback(chunk, None, len(chunk), None, None)

        level_1k_db = slm.results["Lp"]

        # Reset
        slm.stop_analysis()
        slm.reset_measurements()
        slm.start_analysis()

        # 2. Test 100Hz (A-weighting: -19.1 dB)
        sig_100 = np.sin(2 * np.pi * 100 * t)
        indata_100 = np.column_stack((sig_100, sig_100))

        for i in range(0, frames, chunk_size):
            chunk = indata_100[i : i + chunk_size]
            if len(chunk) < chunk_size:
                break
            slm.callback(chunk, None, len(chunk), None, None)

        level_100_db = slm.results["Lp"]

        # Difference should be approx 19.1 dB
        diff = level_1k_db - level_100_db
        # Expected: 0 - (-19.1) = 19.1

        # Tolerance 1.5 dB because of settling time
        assert abs(diff - 19.1) < 1.5, (
            f"Callback A-weighting check failed. 1kHz: {level_1k_db}, 100Hz: {level_100_db}, Diff: {diff}"
        )


class TestSoundLevelMeterSplittable:
    def test_splittable_interface(self, qapp):
        engine = MockAudioEngine()
        slm = SoundLevelMeter(engine)
        widget = SoundLevelMeterWidget(slm)

        assert isinstance(widget, SplittableWidgetInterface)
        display_w = widget.get_display_widget()
        control_w = widget.get_control_widget()

        assert display_w is not None
        assert control_w is not None
        assert display_w == widget.display_widget
        assert control_w == widget.control_widget

        # Test restore_split_panels execution
        widget.restore_split_panels()
        assert not display_w.isHidden()
        assert not control_w.isHidden()


@pytest.mark.parametrize("sample_rate", [44100, 48000])
@pytest.mark.parametrize("weighting", ["FAST", "SLOW", "10ms", "IMPULSE"])
def test_fixed_duration_is_exact_and_independent_of_callback_partition(sample_rate, weighting):
    signal_time = np.arange(sample_rate * 2) / sample_rate
    amplitude = np.where(signal_time < 0.4, 0.1, 0.5)
    signal = (amplitude * np.sin(2 * np.pi * 1000 * signal_time))[:, None]
    snapshots = []
    for block_size in [127, 1024, 8192, len(signal)]:
        engine = MockAudioEngine()
        engine.sample_rate = sample_rate
        meter = SoundLevelMeter(engine)
        meter.set_time_weighting(weighting)
        meter.set_target_duration("1s")
        meter.start_analysis()
        for start in range(0, len(signal), block_size):
            block = signal[start : start + block_size]
            meter.callback(block, None, len(block), None, None)
        assert not meter.is_running
        assert meter.leq_samples == sample_rate
        results, elapsed, history = meter.get_display_snapshot()
        assert elapsed == 1.0
        assert len(history.powers) == 10
        assert results["LE"] == pytest.approx(results["Leq"])
        snapshots.append((results, history.powers))
        meter.stop_analysis()
    for results, powers in snapshots[1:]:
        assert results == pytest.approx(snapshots[0][0], abs=1e-9)
        np.testing.assert_allclose(powers, snapshots[0][1], rtol=1e-10)


@pytest.mark.parametrize(
    "parameter,value",
    [
        ("freq_weighting", "C"),
        ("time_weighting", "SLOW"),
        ("channel", 1),
        ("bandwidth_mode", "20Hz - 8kHz"),
        ("target_duration", "1s"),
    ],
)
def test_measurement_setting_starts_a_fresh_interval(slm, parameter, value):
    slm.start_analysis()
    signal = np.ones((6000, 2))
    slm.callback(signal, None, len(signal), None, None)
    assert slm.calculate_ln_statistics()
    getattr(slm, f"set_{parameter}")(value)
    results, elapsed, history = slm.get_display_snapshot()
    assert slm.is_running
    assert elapsed == 0
    assert not history.statistics
    assert all(np.isneginf(value) for value in results.values())
    assert slm.current_sq_val == 0


def test_reset_clears_filter_memory_and_restarts_duration(slm):
    slm.set_target_duration("1s")
    slm.start_analysis()
    signal = np.random.default_rng(2).normal(size=(24000, 2)) * 0.1
    slm.callback(signal, None, len(signal), None, None)
    before = slm.get_display_snapshot()
    slm.reset_measurements()
    slm.callback(signal, None, len(signal), None, None)
    after = slm.get_display_snapshot()
    assert after[0] == pytest.approx(before[0])
    np.testing.assert_array_equal(after[2].powers, before[2].powers)
    assert after[1] == 0.5
    assert slm.is_running
    slm.callback(signal, None, len(signal), None, None)
    assert not slm.is_running
    assert slm.leq_samples == 48000


def test_completed_registration_is_released_on_owner_thread_and_old_events_are_ignored(qapp):
    import threading

    engine = MockAudioEngine()
    registered = []
    released = []
    engine.register_callback = lambda callback: registered.append(callback) or len(registered)
    engine.unregister_callback = lambda cid: released.append((cid, threading.get_ident()))
    meter = SoundLevelMeter(engine)
    meter.set_target_duration("1s")
    meter.start_analysis()
    signal = np.ones((48000, 1)) * 0.1
    worker = threading.Thread(target=lambda: registered[0](signal, None, len(signal), None, None))
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert not meter.is_running
    assert released == []
    qapp.processEvents()
    assert released == [(1, threading.get_ident())]
    assert meter.callback_id is None
    meter.start_analysis()
    registered[1](signal, None, len(signal), None, None)
    meter.start_analysis()  # Restart before the queued completion is delivered.
    registered[1](signal, None, len(signal), None, None)  # Stale audio callback.
    qapp.processEvents()
    assert meter.is_running
    assert meter.leq_samples == 0
    assert meter.callback_id == 3
    meter.stop_analysis()
    assert [cid for cid, _ in released] == [1, 2, 3]


def test_stopped_result_calibration_histogram_and_reset_stay_consistent(qtbot):
    engine = MockAudioEngine()
    engine.calibration.get_spl_offset_db.return_value = None
    meter = SoundLevelMeter(engine)
    widget = SoundLevelMeterWidget(meter)
    qtbot.addWidget(widget)
    meter.set_target_duration("1s")
    meter.start_analysis()
    signal = np.sin(2 * np.pi * 1000 * np.arange(48000) / 48000)[:, None] * 0.1
    meter.callback(signal, None, len(signal), None, None)
    widget.update_display()
    assert not widget.btn_start.isChecked()
    assert widget.disp_leq["label"].text() == f"{meter.results['Leq']:.1f}"
    centers = widget.hist_item.opts["x"].copy()
    engine.calibration.get_spl_offset_db.return_value = 94.0
    widget.update_display()
    assert widget.disp_leq["label"].text() == f"{meter.results['Leq'] + 94:.1f}"
    np.testing.assert_allclose(widget.hist_item.opts["x"], centers + 94)
    assert widget.plot_widget.getAxis("bottom").labelUnits == "dB SPL"
    assert widget.ln_labels["L50"].text().endswith("dB SPL")
    meter.reset_measurements()
    widget.update_display()
    assert widget.disp_leq["label"].text() == "--.-"
    assert widget.ln_labels["L50"].text() == "--.- dB SPL"
    assert len(widget.hist_item.opts["x"]) == 0


def test_failed_start_restores_button_and_leaves_no_registration(qtbot):
    engine = MockAudioEngine()
    engine.register_callback = MagicMock(side_effect=RuntimeError("device unavailable"))
    meter = SoundLevelMeter(engine)
    widget = SoundLevelMeterWidget(meter)
    qtbot.addWidget(widget)
    widget.btn_start.click()
    assert not widget.btn_start.isChecked()
    assert widget.btn_start.text() == "Start"
    assert meter.callback_id is None
    assert not meter.is_running
