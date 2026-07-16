import numpy as np

from src.core.realtime_sss_core import RealtimeSSSEngine, LatencyCalibrator
from src.core.nonlinear_analyzer_core import apply_fractional_delay, find_subsample_peak, deconvolve_signal


class MockAudioEngine:
    def __init__(self, sample_rate=48000, block_size=1024):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.callback = None

    def register_callback(self, cb):
        self.callback = cb
        return 0

    def unregister_callback(self, cid):
        self.callback = None


def test_engine_init_and_prepare():
    engine = RealtimeSSSEngine(
        sample_rate=48000,
        sweep_duration=1.0,
        start_freq=50,
        end_freq=15000,
        output_amplitude=0.5,
        max_harmonic=3,
    )
    assert engine.sweep_duration == 1.0
    engine.prepare_sweep()
    assert engine.sweep_samples > 0
    assert len(engine.out_sig) == engine.sweep_samples
    assert engine.out_sig is not None


def test_engine_process_block():
    engine = RealtimeSSSEngine(48000, 1.0, 50, 15000, 0.5, 3)
    engine.prepare_sweep()
    engine.set_latency(12.5)

    frames = 1024
    outdata = np.zeros((frames, 1))
    indata = np.zeros((frames, 1))

    f_mid, results = engine.process_block(indata, outdata, 0)
    assert f_mid > 0
    assert len(results) == 3
    # Check output buffer contains SSS signal
    assert np.any(outdata != 0.0)


def test_latency_calibrator_simulation():
    audio_engine = MockAudioEngine(48000, 1024)
    calibrator = LatencyCalibrator(audio_engine, start_freq=100.0, end_freq=5000.0, duration=0.25)

    # Apply a known fractional sample delay
    target_delay = 85.45  # samples

    # Pad the sweep with zeros to total_samples before applying fractional delay
    # to simulate linear delay without wrap-around inside the sweep range.
    padded_sss = np.pad(calibrator.sss, (0, calibrator.total_samples - len(calibrator.sss)))
    delayed_sss = apply_fractional_delay(padded_sss, target_delay)

    # Process block-by-block and feed simulated inputs
    frames = audio_engine.block_size
    total_len = calibrator.total_samples
    num_blocks = int(np.ceil(total_len / frames))

    for i in range(num_blocks):
        out_block = np.zeros((frames, 1))
        in_block = np.zeros((frames, 1))

        start_idx = i * frames
        chunk_len = min(frames, total_len - start_idx)

        if chunk_len > 0:
            in_block[:chunk_len, 0] = delayed_sss[start_idx : start_idx + chunk_len]

        calibrator.callback(in_block, out_block, frames, None, None)

    assert calibrator.finished.is_set()

    # Verify that deconvolution + peak detection correctly retrieves the delay (using default regularization)
    ir = deconvolve_signal(calibrator.recorded_data, calibrator.sss)
    estimated_delay = find_subsample_peak(ir)

    # Assert delay is within 0.05 sample accuracy threshold
    assert np.abs(estimated_delay - target_delay) < 0.05


def test_engine_process_block_xfer():
    # Initialize engine
    engine = RealtimeSSSEngine(48000, 1.0, 50, 15000, 0.5, 3)
    engine.prepare_sweep()
    engine.set_latency(0)

    frames = 1024
    outdata = np.zeros((frames, 1))

    # Generate the sweep output first
    engine.process_block(np.zeros((frames, 1)), outdata, 0)

    # Simulate loopback signals: REF is scaled by 0.8, SIG is scaled by 0.4
    ref_block = outdata * 0.8
    sig_block = outdata * 0.4

    # Reset filter states
    engine.reset_filter_states()

    # Process with XFER reference channel
    f_mid, results = engine.process_block(sig_block, outdata, 0, ref_in_block=ref_block)

    assert f_mid > 0
    assert len(results) == 3
    # Ratio should converge to 0.4 / 0.8 = 0.5 for fundamental component
    assert np.abs(results[0]) > 0.0
    assert np.abs(np.abs(results[0]) - 0.5) < 1e-3


def test_engine_process_block_xfer_zero_ref():
    # Verify that near-zero or zero reference channel input does not cause NaN or Inf
    engine = RealtimeSSSEngine(48000, 1.0, 50, 15000, 0.5, 3)
    engine.prepare_sweep()
    engine.set_latency(0)

    frames = 1024
    outdata = np.zeros((frames, 1))

    # Generate sweep output
    engine.process_block(np.zeros((frames, 1)), outdata, 0)

    # 1. True zero reference input
    ref_block_zero = np.zeros((frames, 1))
    sig_block = outdata * 0.4
    engine.reset_filter_states()
    f_mid, results_zero = engine.process_block(sig_block, outdata, 0, ref_in_block=ref_block_zero)
    assert not np.any(np.isnan(results_zero))
    assert not np.any(np.isinf(results_zero))

    # 2. Extremely small / phase-cancelling reference input
    ref_block_small = np.ones((frames, 1)) * -1e-12
    engine.reset_filter_states()
    f_mid, results_small = engine.process_block(sig_block, outdata, 0, ref_in_block=ref_block_small)
    assert not np.any(np.isnan(results_small))
    assert not np.any(np.isinf(results_small))


def test_engine_ls_extractor_rejects_linear_loopback_harmonic_artifact():
    engine = RealtimeSSSEngine(48000, 4.0, 20, 20000, 0.5, 3)
    engine.prepare_sweep()
    engine.set_latency(0)

    frames = 1024
    h2_db = []
    h3_db = []

    for block_index in range(int(np.ceil(engine.sweep_samples / frames))):
        outdata = np.zeros((frames, 1))
        indata = np.zeros((frames, 1))

        start = block_index * frames
        chunk = min(frames, engine.sweep_samples - start)
        if chunk > 0:
            indata[:chunk, 0] = engine.out_sig[start : start + chunk]

        f_mid, results = engine.process_block(indata, outdata, block_index)
        if 140.0 <= f_mid <= 700.0:
            h2_db.append(20 * np.log10(abs(results[1]) + 1e-15))
            h3_db.append(20 * np.log10(abs(results[2]) + 1e-15))

    assert h2_db
    assert h3_db
    assert np.max(h2_db) < -180.0
    assert np.max(h3_db) < -180.0


def test_latency_clamping():
    engine = RealtimeSSSEngine(48000, 1.0, 50, 15000, 0.5, 3)
    # Enforces non-negative latency
    engine.set_latency(-100.5)
    assert engine.latency_samples == 0.0
    engine.set_latency(45.2)
    assert engine.latency_samples == 45.2


def test_engine_ls_extractor_early_samples_zero_check():
    # Test that LS mode doesn't return zeros at the beginning of a sweep due to D clipping/sample count checks
    engine = RealtimeSSSEngine(
        sample_rate=48000,
        sweep_duration=1.0,
        start_freq=50,
        end_freq=15000,
        output_amplitude=0.5,
        max_harmonic=3,
    )
    engine.prepare_sweep()
    engine.set_latency(0)

    # Use a small block size (e.g. 128) where decimation D=10 would otherwise starve the sample count
    frames = 128
    outdata = np.zeros((frames, 1))
    indata = np.zeros((frames, 1))

    assert engine.out_sig is not None
    indata[:frames, 0] = engine.out_sig[:frames]

    f_mid, results = engine.process_block(indata, outdata, 0)

    # Fundamental harmonic (results[0]) should have a valid non-zero amplitude
    assert abs(results[0]) > 0.0, "Result should not be zero; D should have been scaled down to prevent starvation"


def test_engine_ls_extractor_decimation_continuity():
    # Test that LS mode output is continuous and doesn't exhibit sudden spikes/discontinuities when D changes
    engine = RealtimeSSSEngine(
        sample_rate=48000,
        sweep_duration=2.0,  # 2 seconds
        start_freq=40,
        end_freq=400,
        output_amplitude=0.5,
        max_harmonic=3,
    )
    engine.prepare_sweep()
    engine.set_latency(0)

    # We feed the clean output sweep directly back as input
    frames = 256
    num_blocks = int(np.ceil(engine.sweep_samples / frames))

    results_list = []
    d_values = []

    for i in range(num_blocks):
        outdata = np.zeros((frames, 1))
        indata = np.zeros((frames, 1))

        start = i * frames
        chunk = min(frames, engine.sweep_samples - start)
        if chunk > 0:
            assert engine.out_sig is not None
            indata[:chunk, 0] = engine.out_sig[start : start + chunk]

        # Manually compute D that the engine will use to track transitions
        # (mirroring the logic inside _process_block_ls)
        n_mid = start + frames / 2.0
        if 0 <= n_mid < engine.sweep_samples:
            f1 = engine.start_freq / 1.3
            f_mid = f1 * np.exp((n_mid / engine.sample_rate) / engine.L_param)
        else:
            f_mid = engine.start_freq

        max_d = int(np.floor(engine.sample_rate / (5.0 * engine.max_harmonic * max(1.0, f_mid))))
        D = int(np.clip(max_d, 1, 10))
        d_values.append(D)

        f_mid_ret, results = engine.process_block(indata, outdata, i)
        results_list.append(results[0])  # store fundamental

    # Filter out initial zeros and limit to active sweep range before Tukey fade-out (first 97%)
    results_mag = np.array([abs(r) for r in results_list])
    active_limit = int(0.97 * num_blocks)
    valid_indices = np.array([idx for idx in np.flatnonzero(results_mag > 1e-5) if idx < active_limit])

    # Check that adjacent differences in magnitude are small
    # Especially at D boundary changes.
    valid_mag = results_mag[valid_indices]
    valid_d = np.array(d_values)[valid_indices]

    diffs = np.abs(np.diff(valid_mag))

    # Let's find index where D changed
    d_changes = np.flatnonzero(np.diff(valid_d) != 0)

    for idx in d_changes:
        # Check diff around the change. It shouldn't be a sudden jump.
        # Without smooth fc, the jump in magnitude at D transition can be quite large (e.g. > 0.05).
        # We enforce that the jump is small (e.g., < 0.015).
        assert diffs[idx] < 0.015, (
            f"Discontinuity detected at D change index {idx} (D changed from {valid_d[idx]} to {valid_d[idx + 1]}): jump was {diffs[idx]:.5f}"
        )


def test_engine_parameter_derivation():
    # 1. Test default parameter derivation (analysis_cycles = 12.0)
    # With start_freq=20.0, end_freq=20000.0, min_freq is 20.0.
    # max_analysis_window should be 12.0 / (4.0 * 20.0) = 0.15.
    # max_fitting_samples should be int(12.0 * 170) = 2040.
    engine = RealtimeSSSEngine(
        sample_rate=48000,
        sweep_duration=1.0,
        start_freq=20.0,
        end_freq=20000.0,
        output_amplitude=0.5,
        max_harmonic=3,
        analysis_cycles=12.0,
    )
    assert np.isclose(engine.max_analysis_window, 0.15)
    assert engine.max_fitting_samples == 2040

    # 2. Test parameter derivation with custom analysis_cycles
    engine_custom = RealtimeSSSEngine(
        sample_rate=48000,
        sweep_duration=1.0,
        start_freq=40.0,
        end_freq=20000.0,
        output_amplitude=0.5,
        max_harmonic=3,
        analysis_cycles=8.0,
    )
    # min_freq = 40.0 -> max_analysis_window = 8.0 / (4.0 * 40.0) = 0.05
    # max_fitting_samples = int(8.0 * 170) = 1360
    assert np.isclose(engine_custom.max_analysis_window, 0.05)
    assert engine_custom.max_fitting_samples == 1360

    # 3. Test legacy override compatibility
    engine_override = RealtimeSSSEngine(
        sample_rate=48000,
        sweep_duration=1.0,
        start_freq=20.0,
        end_freq=20000.0,
        output_amplitude=0.5,
        max_harmonic=3,
        analysis_cycles=12.0,
        max_analysis_window=0.5,
        max_fitting_samples=4096,
    )
    assert engine_override.max_analysis_window == 0.5
    assert engine_override.max_fitting_samples == 4096

    # 4. Test parameter derivation with very large analysis_cycles (512.0)
    # With start_freq=20.0, end_freq=20000.0, min_freq is 20.0.
    # max_analysis_window should be 512.0 / (4.0 * 20.0) = 6.4.
    # max_fitting_samples should be clipped to 65536.
    engine_large = RealtimeSSSEngine(
        sample_rate=192000,
        sweep_duration=20.0,
        start_freq=20.0,
        end_freq=20000.0,
        output_amplitude=0.5,
        max_harmonic=3,
        analysis_cycles=512.0,
    )
    assert np.isclose(engine_large.max_analysis_window, 6.4)
    assert engine_large.max_fitting_samples == 65536

    # 5. Test parameter derivation with extremely large analysis_cycles (2048.0)
    # With start_freq=20.0, end_freq=20000.0, min_freq is 20.0.
    # max_analysis_window should be 2048.0 / (4.0 * 20.0) = 25.6.
    # max_fitting_samples should be clipped to 65536.
    engine_extreme = RealtimeSSSEngine(
        sample_rate=192000,
        sweep_duration=20.0,
        start_freq=20.0,
        end_freq=20000.0,
        output_amplitude=0.5,
        max_harmonic=3,
        analysis_cycles=2048.0,
    )
    assert np.isclose(engine_extreme.max_analysis_window, 25.6)
    assert engine_extreme.max_fitting_samples == 65536


def test_engine_process_block_xfer_mixed_reference():
    # Verify that mixing None and non-None reference inputs does not raise IndexError
    engine = RealtimeSSSEngine(48000, 1.0, 50, 15000, 0.5, 3)
    engine.prepare_sweep()
    engine.set_latency(0)

    frames = 512
    outdata = np.zeros((frames, 1))

    # Process first block with no reference
    engine.process_block(np.zeros((frames, 1)), outdata, 0, ref_in_block=None)

    # Process second block with reference
    ref_block = outdata * 0.8
    sig_block = outdata * 0.4
    f_mid, results = engine.process_block(sig_block, outdata, 1, ref_in_block=ref_block)

    # We expect results to be corrected (0.4 / 0.8 = 0.5)
    # If the bug is present, this will either raise IndexError or return uncorrected 0.4
    assert np.abs(results[0]) > 0.0
    assert np.abs(np.abs(results[0]) - 0.5) < 1e-2


def test_engine_reset_analysis_history():
    engine = RealtimeSSSEngine(
        sample_rate=48000,
        sweep_duration=1.0,
        start_freq=50,
        end_freq=15000,
        output_amplitude=0.5,
        max_harmonic=3,
    )

    # Inject mock data
    engine._hist_n = [np.array([1, 2, 3])]
    engine._hist_theta = [np.array([0.1, 0.2, 0.3])]
    engine._hist_signal = [np.array([0.5, 0.6, 0.7])]
    engine._hist_ref = [np.array([0.8, 0.9, 1.0])]

    # Call the method
    engine.reset_analysis_history()

    # Verify lists are empty
    assert engine._hist_n == []
    assert engine._hist_theta == []
    assert engine._hist_signal == []
    assert engine._hist_ref == []

def test_engine_generate_output_block():
    engine = RealtimeSSSEngine(
        sample_rate=48000,
        sweep_duration=1.0,
        start_freq=50,
        end_freq=15000,
        output_amplitude=0.5,
        max_harmonic=3,
    )
    engine.prepare_sweep()
    engine.set_latency(0)

    frames = 1024
    outdata_block = np.zeros((frames, 2))  # 2 channels

    # 1. Early block containing sweep data
    engine.generate_output_block(outdata_block, 0)

    # Check that outdata_block is not empty
    assert np.any(np.abs(outdata_block) > 0)

    # Check that it was copied to both channels
    assert np.array_equal(outdata_block[:, 0], outdata_block[:, 1])

    # 2. Boundary block partially spanning sweep data and silence
    # block index where the sweep ends
    boundary_block_index = engine.sweep_samples // frames
    engine.generate_output_block(outdata_block, boundary_block_index)

    out_samples_written = min(frames, engine.sweep_samples - boundary_block_index * frames)

    if out_samples_written > 0:
        assert np.any(np.abs(outdata_block[:out_samples_written, :]) > 0)
    if out_samples_written < frames:
        assert np.all(outdata_block[out_samples_written:, :] == 0.0)

    # 3. Post-sweep blocks containing only silence
    post_sweep_index = engine.sweep_samples // frames + 1
    outdata_block.fill(1.0) # fill with ones so we can see if it was zeroed
    engine.generate_output_block(outdata_block, post_sweep_index)
    assert np.all(outdata_block == 0.0)
