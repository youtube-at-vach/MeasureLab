import os
import sys
from unittest.mock import MagicMock

# Mock sounddevice before importing anything that uses it
sys.modules['sounddevice'] = MagicMock()

import numpy as np

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.gui.widgets.spectrogram import Spectrogram


def test_spectrogram_processing():
    # Mock AudioEngine
    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000

    spec = Spectrogram(mock_engine)
    spec.set_fft_size(1024)
    spec.start_analysis()

    # Simulate Audio Callback
    # Generate a sine wave
    t = np.linspace(0, 1024/48000, 1024, endpoint=False)
    sine = 0.5 * np.sin(2 * np.pi * 1000 * t)
    indata = np.column_stack((sine, sine))
    outdata = np.zeros_like(indata)

    # Run callback
    spec._callback(indata, outdata, 1024, None, None)

    # Check if buffer updated
    # Use get_latest_samples to handle ring buffer logic correctly
    last_samples = spec.get_latest_samples(1024)[:, 0]

    if np.allclose(last_samples, sine):
        print("Buffer Update: PASS")
    else:
        print("Buffer Update: FAIL")

    # Simulate Widget Update (Processing)
    # We can't easily test the widget drawing without a QApplication,
    # but we can test the logic inside update_spectrogram if we extract it or simulate it.

    # Let's manually run the processing logic
    raw_data = spec.get_latest_samples(spec.fft_size)
    sig = raw_data[:, 0]
    window = np.hanning(len(sig))
    sig_win = sig * window

    # Window Correction Factor
    win_correction = 1.0 / np.mean(window)

    fft_res = np.fft.rfft(sig_win)
    mag = np.abs(fft_res)
    mag = mag / len(sig) * 2 * win_correction
    mag_db = 20 * np.log10(mag + 1e-12)

    # Check peak frequency
    freqs = np.fft.rfftfreq(len(sig), 1/48000)
    peak_idx = np.argmax(mag_db)
    peak_freq = freqs[peak_idx]

    print(f"Peak Freq: {peak_freq:.1f} Hz")

    if abs(peak_freq - 1000) < 50:
        print("Frequency Analysis: PASS")
    else:
        print(f"Frequency Analysis: FAIL (Expected 1000, Got {peak_freq})")

    # Update Spectrogram Data
    spec.add_spectrum(mag_db)

    # Check peak amplitude
    # Retrieve latest written data (at ptr - 1)
    last_idx = (spec.spectrogram_ptr - 1) % spec.history_length
    peak_amp = spec.spectrogram_buffer[last_idx].max()
    print(f"Peak Amplitude: {peak_amp:.2f} dB")

    if peak_amp > -10:
        print("Spectrogram Data Update: PASS")
    else:
        print(f"Spectrogram Data Update: FAIL (Signal too weak: {peak_amp:.2f} dB)")

if __name__ == "__main__":
    test_spectrogram_processing()
