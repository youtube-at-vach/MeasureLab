
import numpy as np
import pytest
from PyQt6.QtCore import QRunnable, QThreadPool, QObject, pyqtSignal

# Import the worker class (to be implemented)
# We use a try-except block or just assume it will be there when running tests after implementation.
try:
    from src.gui.widgets.spectrogram import SpectrogramWorker
except ImportError:
    SpectrogramWorker = None

@pytest.mark.skipif(SpectrogramWorker is None, reason="SpectrogramWorker not yet implemented")
def test_spectrogram_worker_logic():
    # Setup
    fft_size = 1024
    sample_rate = 48000
    # Generate a sine wave at ~1000 Hz
    t = np.linspace(0, fft_size / sample_rate, fft_size, endpoint=False)
    freq = 1000
    # Use float32 to match audio buffer types often used
    raw_data = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    # Make it stereo (duplicate channels)
    raw_data = np.column_stack((raw_data, raw_data))

    window_type = "hann"
    channel_mode = "Left"

    # Create Worker
    worker = SpectrogramWorker(raw_data, window_type, channel_mode)

    # We need to capture the signal emission
    # Since QRunnable.run() is synchronous when called directly, we can mock the signal.

    results = []
    def on_result(mag_db):
        results.append(mag_db)

    # Mock the signal connection
    # The worker should have a 'signals' attribute with 'result' signal
    # We can't easily mock the signal emission if it's a real PyQt signal without an event loop or mock.
    # But we can replace the signal object with a mock or a simple class.

    class MockSignal:
        def emit(self, data):
            results.append(data)

    class MockSignals:
        result = MockSignal()

    worker.signals = MockSignals()

    # Run
    worker.run()

    # Assertions
    assert len(results) == 1
    mag_db = results[0]

    # Check shape: rfft of 1024 points -> 513 bins
    expected_bins = fft_size // 2 + 1
    assert mag_db.shape == (expected_bins,)

    # Check peak frequency
    # 1000 Hz at 48k SR with 1024 FFT
    # Bin resolution = 48000 / 1024 = 46.875 Hz
    # Expected bin = 1000 / 46.875 = 21.33 -> Bin 21
    peak_bin = np.argmax(mag_db)
    assert 20 <= peak_bin <= 22

    # Check magnitude (approximate)
    # Peak should be reasonably high (close to 0 dBFS or -6dBFS depending on normalization)
    peak_val = mag_db[peak_bin]
    assert peak_val > -20.0  # Just ensure it's not silence (-120)

def test_spectrogram_worker_stereo_average():
    if SpectrogramWorker is None:
        pytest.skip("SpectrogramWorker not implemented")

    fft_size = 512
    # Left: 1.0, Right: 0.0 -> Average: 0.5
    raw_data = np.zeros((fft_size, 2), dtype=np.float32)
    raw_data[:, 0] = 1.0

    worker = SpectrogramWorker(raw_data, "boxcar", "Average")

    results = []
    worker.signals = type("MockSignals", (), {"result": type("MockSignal", (), {"emit": lambda s, d: results.append(d)})()})()

    worker.run()

    mag_db = results[0]
    # DC component (bin 0) should be high
    assert mag_db[0] > -10.0
