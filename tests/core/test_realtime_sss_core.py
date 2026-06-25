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
        lpf_factor=0.08,
        max_harmonic=3,
    )
    assert engine.sweep_duration == 1.0
    engine.prepare_sweep()
    assert engine.sweep_samples > 0
    assert len(engine.out_sig) == engine.sweep_samples
    assert engine.out_sig is not None


def test_engine_process_block():
    engine = RealtimeSSSEngine(48000, 1.0, 50, 15000, 0.5, 0.08, 3)
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
    engine = RealtimeSSSEngine(48000, 1.0, 50, 15000, 0.5, 0.08, 3)
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
    engine = RealtimeSSSEngine(48000, 1.0, 50, 15000, 0.5, 0.08, 3)
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
    engine = RealtimeSSSEngine(48000, 4.0, 20, 20000, 0.5, 0.07, 3)
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
    engine = RealtimeSSSEngine(48000, 1.0, 50, 15000, 0.5, 0.08, 3)
    # Enforces non-negative latency
    engine.set_latency(-100.5)
    assert engine.latency_samples == 0.0
    engine.set_latency(45.2)
    assert engine.latency_samples == 45.2
