import numpy as np
import pytest
from PyQt6.QtCore import QObject, pyqtSignal

from src.gui.widgets.distortion_analyzer import DistortionAnalysisWorker

def test_distortion_worker_thd_mode(qtbot):
    # Setup
    sample_rate = 48000
    buffer_size = 1024
    t = np.arange(buffer_size) / sample_rate
    freq = 1000.0
    input_data = 0.5 * np.sin(2 * np.pi * freq * t)

    worker = DistortionAnalysisWorker(
        input_data=input_data,
        sample_rate=sample_rate,
        signal_type="sine",
        window_type="hann",
        gen_frequency=freq,
        imd_params={},
        buffer_size=buffer_size
    )

    # Connect signals
    results = []
    def on_result(res, sig_type, freqs, mag_linear, input_level):
        results.append((res, sig_type, freqs, mag_linear, input_level))

    worker.signals.result.connect(on_result)

    with qtbot.waitSignal(worker.signals.finished, timeout=5000):
        worker.run()

    assert len(results) == 1
    res, sig_type, freqs, mag_linear, input_level = results[0]

    assert sig_type == "sine"
    assert "thdn_db" in res
    assert len(freqs) == buffer_size // 2 + 1
    assert len(mag_linear) == len(freqs)
    # Check input level is approx -6 dBFS (0.5 amplitude)
    # 20*log10(0.5/sqrt(2)) = 20*log10(0.3535) = -9.03 dBFS rms relative to 1.0 rms?
    # No, typically 1.0 amplitude sine is -3.01 dBFS (1/sqrt(2) RMS).
    # 0.5 amplitude is -6dB lower, so -9.03 dBFS.
    assert -9.5 < input_level < -8.5

def test_distortion_worker_imd_mode(qtbot):
    # Setup
    sample_rate = 48000
    buffer_size = 1024
    t = np.arange(buffer_size) / sample_rate
    f1, f2 = 60.0, 7000.0
    input_data = 0.4 * np.sin(2 * np.pi * f1 * t) + 0.1 * np.sin(2 * np.pi * f2 * t)

    worker = DistortionAnalysisWorker(
        input_data=input_data,
        sample_rate=sample_rate,
        signal_type="smpte",
        window_type="hann",
        gen_frequency=1000.0,
        imd_params={"f1": f1, "f2": f2},
        buffer_size=buffer_size
    )

    # Connect signals
    results = []
    def on_result(res, sig_type, freqs, mag_linear, input_level):
        results.append((res, sig_type, freqs, mag_linear, input_level))

    worker.signals.result.connect(on_result)

    with qtbot.waitSignal(worker.signals.finished, timeout=5000):
        worker.run()

    assert len(results) == 1
    res, sig_type, freqs, mag_linear, input_level = results[0]

    assert sig_type == "smpte"
    assert "imd" in res
    assert len(freqs) == buffer_size // 2 + 1
    assert len(mag_linear) == len(freqs)
