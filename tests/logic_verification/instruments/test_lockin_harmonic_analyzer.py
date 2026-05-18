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
