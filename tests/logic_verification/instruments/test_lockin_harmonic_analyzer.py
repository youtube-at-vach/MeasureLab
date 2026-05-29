import numpy as np

from src.gui.widgets.lockin_harmonic_analyzer import LockInHarmonicAnalyzer, LockInHarmonicWidget


class MockAudioEngine:
    def __init__(self, sample_rate=48000):
        self.sample_rate = sample_rate
        self.callbacks = {}
        self.callback_counter = 0

    def register_callback(self, cb):
        self.callback_counter += 1
        self.callbacks[self.callback_counter] = cb
        return self.callback_counter

    def unregister_callback(self, cb_idx):
        if cb_idx in self.callbacks:
            del self.callbacks[cb_idx]


def test_lockin_harmonic_analyzer_math():
    engine = MockAudioEngine()
    analyzer = LockInHarmonicAnalyzer(engine)

    # Set up conditions
    analyzer.gen_frequency = 1000.0
    analyzer.buffer_size = 48000  # 1 second
    analyzer.start_analysis()

    fs = engine.sample_rate
    t = np.arange(analyzer.buffer_size) / fs

    # Fundamental = 1000 Hz, Amplitude = 1.0 (0 dBFS peak, meaning 1.0 peak)
    # 2nd Harmonic = 2000 Hz, Amplitude = 0.1 (-20 dBc)
    # 3rd Harmonic = 3000 Hz, Amplitude = 0.01 (-40 dBc)
    f0 = 1000.0

    # Signal
    sig = 1.0 * np.sin(2 * np.pi * f0 * t)
    sig += 0.1 * np.sin(2 * np.pi * 2 * f0 * t + np.pi / 4)
    sig += 0.01 * np.cos(2 * np.pi * 3 * f0 * t)  # cos = sin(+pi/2), amplitude 0.01

    # Reference (pure fundamental)
    ref = 1.0 * np.sin(2 * np.pi * f0 * t)

    # Inject data
    indata = np.column_stack((sig, ref))
    outdata = np.zeros_like(indata)

    # Run callback
    for cb in engine.callbacks.values():
        cb(indata, outdata, len(indata), None, None)

    # Process
    analyzer.process()

    # Check results
    assert np.isclose(analyzer.measured_freq, 1000.0, rtol=1e-3)

    # 1st harmonic (Fund)
    assert np.isclose(analyzer.harmonics_amp[0], 1.0, rtol=1e-2)
    assert np.isclose(analyzer.harmonics_phase_deg[0], 0.0, atol=2.0)

    # 2nd harmonic
    assert np.isclose(analyzer.harmonics_amp[1], 0.1, rtol=1e-2)
    assert np.isclose(analyzer.harmonics_phase_deg[1], 45.0, atol=2.0)

    # 3rd harmonic
    assert np.isclose(analyzer.harmonics_amp[2], 0.01, rtol=1e-2)
    assert np.isclose(analyzer.harmonics_phase_deg[2], 90.0, atol=2.0)

    # THD calculation math
    # pure thd_sq = (0.1/sqrt(2))^2 + (0.01/sqrt(2))^2 / (1.0/sqrt(2))^2
    # amplitudes are peak, so ratio of squares is the same
    expected_thd_sq = (0.1**2 + 0.01**2) / 1.0**2
    expected_thd_pct = np.sqrt(expected_thd_sq) * 100

    assert np.isclose(analyzer.thd_value, expected_thd_pct, rtol=1e-2)

    analyzer.stop_analysis()


def test_lockin_harmonic_analyzer_coherent_bin_centered_mode():
    engine = MockAudioEngine()
    analyzer = LockInHarmonicAnalyzer(engine)

    analyzer.analysis_mode = "coherent"
    analyzer.coherent_cycles = 200
    analyzer.buffer_size = 65536
    analyzer.start_analysis()

    fs = engine.sample_rate
    t = np.arange(analyzer.buffer_size) / fs
    f0 = 997.3

    sig = 0.8 * np.sin(2 * np.pi * f0 * t + 0.2)
    ref = 1.0 * np.sin(2 * np.pi * f0 * t)

    indata = np.column_stack((sig, ref))
    outdata = np.zeros_like(indata)

    for cb in engine.callbacks.values():
        cb(indata, outdata, len(indata), None, None)

    analyzer.process()

    assert analyzer.measured_freq > 0.0
    assert np.isclose(analyzer.harmonics_amp[0], 0.8, rtol=2e-2)
    assert analyzer.harmonics_amp[1] < 5e-3

    analyzer.stop_analysis()


def test_lockin_harmonic_analyzer_clear_buffer():
    engine = MockAudioEngine()
    analyzer = LockInHarmonicAnalyzer(engine)

    # Set some initial dummy data to verify it gets cleared
    analyzer.input_data.fill(1.0)
    analyzer.input_buffer_pos = 100
    analyzer.buffer_filled_samples = 100

    analyzer.measured_freq = 1000.0
    analyzer.thd_value = 1.0
    analyzer.thd_db = -40.0
    analyzer.thdn_value = 1.5
    analyzer.thdn_db = -38.0
    analyzer.residual_rms = 0.5

    analyzer.residual_history.extend([1, 2, 3])
    analyzer.harmonics_amp.fill(0.5)
    analyzer.harmonics_phase_deg.fill(45.0)

    # ensure state like is_running is preserved
    analyzer.is_running = True

    # Call clear_buffer
    analyzer.clear_buffer()

    # Verify state not affected by clear_buffer is preserved
    assert analyzer.is_running is True

    # Verify input buffer states are reset
    assert np.all(analyzer.input_data == 0)
    assert analyzer.input_buffer_pos == 0
    assert analyzer.buffer_filled_samples == 0

    # Verify results are reset
    assert analyzer.measured_freq == 0.0
    assert analyzer.thd_value == 0.0
    assert analyzer.thd_db == -300.0  # DISTORTION_DB_FLOOR
    assert analyzer.thdn_value == 0.0
    assert analyzer.thdn_db == -300.0  # DISTORTION_DB_FLOOR
    assert analyzer.residual_rms == 0.0

    assert len(analyzer.residual_history) == 0
    assert np.all(analyzer.harmonics_amp == 0)
    assert np.all(analyzer.harmonics_phase_deg == 0)


def test_compensation_data_table_shows_50th_when_measurable(qtbot):
    engine = MockAudioEngine(sample_rate=192000)
    analyzer = LockInHarmonicAnalyzer(engine)

    widget = LockInHarmonicWidget(analyzer)
    qtbot.addWidget(widget)

    assert analyzer.max_harmonic == 10
    assert widget.comp_max_spin.maximum() == 10
    assert widget.comp_table.rowCount() == 9

    widget.harmonic_spin.setValue(50)

    assert analyzer.max_harmonic == 50
    assert widget.comp_max_spin.maximum() == 50
    assert widget.comp_table.rowCount() == 49
    assert widget.comp_table.item(48, 0).text().startswith("50")


def test_compensation_order_limit_matches_measurable_harmonics(qtbot):
    engine = MockAudioEngine(sample_rate=48000)
    analyzer = LockInHarmonicAnalyzer(engine)

    widget = LockInHarmonicWidget(analyzer)
    qtbot.addWidget(widget)

    assert analyzer.max_harmonic == 10
    assert widget.harmonic_spin.maximum() == 23
    assert widget.comp_max_spin.maximum() == 10
    assert widget.comp_table.rowCount() == 9

    widget.harmonic_spin.setValue(23)

    assert analyzer.max_harmonic == 23
    assert widget.comp_max_spin.maximum() == 23
    assert widget.comp_table.rowCount() == 22
    assert widget.comp_table.item(21, 0).text().startswith("23")


def test_lockin_harmonic_analyzer_phase_continuity():
    engine = MockAudioEngine()
    analyzer = LockInHarmonicAnalyzer(engine)

    analyzer.gen_frequency = 1000.0
    analyzer.gen_amplitude = 1.0
    analyzer.output_enabled = True
    analyzer.output_channel = 0
    analyzer.start_analysis()

    # Get registered callback
    assert len(engine.callbacks) == 1
    callback = list(engine.callbacks.values())[0]

    # Run first block (frames = 512)
    frames = 512
    indata = np.zeros((frames, 2))
    outdata = np.zeros((frames, 2))
    callback(indata, outdata, frames, None, None)

    # Change frequency for block 2
    analyzer.gen_frequency = 2000.0
    outdata.fill(0)
    callback(indata, outdata, frames, None, None)
    signal2 = outdata[:, 0].copy()

    # Verify that the phase transitions continuously.
    # Block 1 ended with frequency 1000.0 and sample_rate 48000.
    # Total phase accumulated in block 1: frames * 2 * pi * 1000.0 / 48000.0
    phase_step1 = 2 * np.pi * 1000.0 / 48000.0
    expected_start_phase = (frames * phase_step1) % (2 * np.pi)
    expected_start_val = np.sin(expected_start_phase)

    # The first sample of block 2 must perfectly match expected_start_val
    assert np.isclose(signal2[0], expected_start_val, atol=1e-12)

    analyzer.stop_analysis()


def test_lockin_harmonic_analyzer_calibration_settling_check():
    engine = MockAudioEngine()
    analyzer = LockInHarmonicAnalyzer(engine)

    analyzer.gen_frequency = 1000.0
    analyzer.buffer_size = 8192
    analyzer.max_harmonic = 5
    analyzer.comp_max_harmonic = 2
    analyzer.compensation_enabled = True
    analyzer.start_analysis()

    callback = list(engine.callbacks.values())[0]

    # Start calibration
    analyzer.start_calibration()
    assert analyzer.is_calibrating is True
    assert analyzer.calibration_current_step == 0
    assert analyzer.cal_samples_written == 0

    # 1. Feed partial data (4096 samples < 8192 buffer_size)
    fs = engine.sample_rate
    phase_step = 2 * np.pi * 1000.0 / fs
    t1 = np.arange(4096) / fs
    wt1 = np.arange(4096) * phase_step
    
    # We must provide non-zero signals so ref_rms is high enough and process() doesn't return early
    sig1 = 1.0 * np.sin(wt1)
    ref1 = 1.0 * np.sin(wt1)
    indata1 = np.column_stack((sig1, ref1))
    outdata1 = np.zeros_like(indata1)
    callback(indata1, outdata1, 4096, None, None)

    # Process and verify that calibration did NOT advance because cal_samples_written = 4096 < 8192
    analyzer.process()
    assert analyzer.calibration_current_step == 0
    assert analyzer.compensation_coeffs[1] == 0j

    # 2. Feed the remaining 4096 samples (total 8192 >= buffer_size)
    t2 = np.arange(4096) / fs
    wt2 = 4096 * phase_step + np.arange(4096) * phase_step
    sig2 = 1.0 * np.sin(wt2)
    ref2 = 1.0 * np.sin(wt2)
    indata2 = np.column_stack((sig2, ref2))
    outdata2 = np.zeros_like(indata2)
    callback(indata2, outdata2, 4096, None, None)

    # Process and verify that calibration DID advance
    analyzer.process()
    assert analyzer.calibration_current_step == 1
    assert analyzer.cal_samples_written == 0  # Was reset
    
    analyzer.stop_analysis()


def test_lockin_harmonic_analyzer_calibration_quasi_newton_convergence():
    engine = MockAudioEngine()
    analyzer = LockInHarmonicAnalyzer(engine)

    analyzer.gen_frequency = 1000.0
    analyzer.buffer_size = 8192
    analyzer.max_harmonic = 5
    analyzer.comp_max_harmonic = 2
    analyzer.compensation_enabled = True
    # For a deterministic 1-step Newton convergence in clean simulation, set gamma to 1.0
    analyzer.calibration_gamma = 1.0
    analyzer.start_analysis()

    callback = list(engine.callbacks.values())[0]

    # Inherent distortion: 2nd harmonic amplitude 0.02, phase pi/6.
    # Loopback transfer function: gain 0.8, phase shift 45 degrees.
    fs = engine.sample_rate
    phase_step = 2 * np.pi * 1000.0 / fs
    current_phase = 0.0

    def feed_full_buffer():
        nonlocal current_phase
        # We need to feed 8192 samples. Let's do 8 blocks of 1024 samples.
        frames = 1024
        for _ in range(8):
            t = np.arange(frames) / fs
            wt = current_phase + np.arange(frames) * phase_step
            current_phase = (current_phase + frames * phase_step) % (2 * np.pi)

            # Generated output comp
            c2 = analyzer.compensation_coeffs[1]
            # Simulate the Loopback Path with transfer function G2 = 0.8 * e^(j * pi/4)
            c2_rec_real = 0.8 * (c2.real * np.cos(np.pi/4) + c2.imag * np.sin(np.pi/4))
            c2_rec_imag = 0.8 * (-c2.real * np.sin(np.pi/4) + c2.imag * np.cos(np.pi/4))

            # Input signal = Fundamental + Inherent distortion + loopback-received compensation
            sig = 1.0 * np.sin(wt)
            sig += 0.02 * np.sin(2 * wt + np.pi/6)
            sig += c2_rec_real * np.cos(2 * wt) + c2_rec_imag * np.sin(2 * wt)

            ref = 1.0 * np.sin(wt)
            indata = np.column_stack((sig, ref))
            outdata = np.zeros_like(indata)
            callback(indata, outdata, frames, None, None)

    # Start calibration
    analyzer.start_calibration()

    # Step 0 -> Step 1 (Perturbation Step)
    feed_full_buffer()
    analyzer.process()
    assert analyzer.calibration_current_step == 1
    # Verify that compensation coefficient was perturbed (non-zero)
    c1 = analyzer.compensation_coeffs[1]
    assert c1 != 0j

    # Step 1 -> Step 2 (Quasi-Newton / Secant Step)
    feed_full_buffer()
    analyzer.process()
    assert analyzer.calibration_current_step == 2
    c2 = analyzer.compensation_coeffs[1]
    assert c2 != c1

    # Step 2 -> Step 3 (Verification Step)
    # The Quasi-Newton step should have computed the exact gain and canceled the distortion!
    feed_full_buffer()
    analyzer.process()
    assert analyzer.calibration_current_step == 3

    # Check 2nd harmonic amplitude after convergence.
    # It should be extremely close to 0 (distortion canceled, e.g. < 1e-5 or -100 dBc)
    assert analyzer.harmonics_amp[1] < 1e-5
    
    analyzer.stop_analysis()

