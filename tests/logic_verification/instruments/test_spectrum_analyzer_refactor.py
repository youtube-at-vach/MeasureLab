
import sys
import os
import pytest
from unittest.mock import MagicMock
import numpy as np

# Mock sounddevice if missing
if 'sounddevice' not in sys.modules:
    sys.modules['sounddevice'] = MagicMock()

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

try:
    from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer, SpectrumAnalyzerWidget
except ImportError:
    pytest.skip("Skipping due to import errors", allow_module_level=True)

class TestSpectrumAnalyzerRefactor:
    @pytest.fixture
    def sa(self):
        mock_engine = MagicMock()
        mock_engine.sample_rate = 48000
        mock_engine.calibration.input_sensitivity = 1.0
        mock_engine.calibration.get_input_offset_db.return_value = 0.0
        mock_engine.calibration.get_spl_offset_db.return_value = None

        sa = SpectrumAnalyzer(mock_engine)
        sa.set_buffer_size(4096)
        sa.is_running = True
        return sa

    def test_constants(self, sa):
        assert hasattr(sa, 'LARGE_BUFFER_THRESHOLD')
        assert sa.LARGE_BUFFER_THRESHOLD == 500000

    def test_apply_octave_smoothing_method(self, sa):
        # Create a simple spectrum
        freqs = np.linspace(20, 20000, 1000)
        magnitude = -20 * np.ones_like(freqs) # -20 dB flat

        # Test 1/3 octave
        smoothed_freqs, smoothed_mags = sa.apply_octave_smoothing(freqs, magnitude, 3)

        assert len(smoothed_freqs) > 0
        assert len(smoothed_mags) == len(smoothed_freqs)
        # Should remain roughly -20 dB
        assert np.allclose(smoothed_mags, -20, atol=1.0)

    def test_get_latest_data_rolling_mode(self, sa):
        # Set small buffer size to trigger rolling mode
        sa.set_buffer_size(100)
        sa.input_data[:] = 1.0 # Fill with ones
        sa.write_head = 50

        # Modify part of buffer to check rotation
        sa.input_data[50:] = 2.0

        # Rolling mode should concatenate [idx:] + [:idx]
        # write_head is 50. So it should take input_data[50:] (2.0) then input_data[:50] (1.0)

        data = sa.get_latest_data()

        assert len(data) == 100
        assert np.all(data[:50] == 2.0) # Oldest data (written most recently? No, write_head points to NEXT write)
        # Wait, ring buffer logic:
        # write_head points to where next sample goes.
        # So sample at write_head is the OLDEST sample in the buffer (overwritten longest ago? No, it's the start of the circular buffer)
        # The logic in get_latest_data is:
        # data = concatenate((input_data[idx:], input_data[:idx]))
        # idx is write_head.
        # input_data[idx:] are the samples from idx to end.
        # input_data[:idx] are the samples from 0 to idx.
        # This reorders buffer to be chronologically sorted?
        # Let's verify standard ring buffer unrolling.
        # If we write 0..99 sequentially. write_head wraps to 0.
        # If we write 50 more samples. write_head is at 50.
        # Buffer: [50..99, 0..49] (indices 0..49 have new data 50..99. indices 50..99 have old data 0..49).
        # We want output [0..99].
        # buffer[idx:] is buffer[50:100] -> old data [0..49]
        # buffer[:idx] is buffer[0:50] -> new data [50..99]
        # Concat gives [0..49, 50..99]. Correct.

        assert np.all(data[:50] == 2.0)
        assert np.all(data[50:] == 1.0)

        # write_head should NOT be reset in rolling mode
        assert sa.write_head == 50

    def test_get_latest_data_snapshot_mode(self, sa):
        # Set large buffer
        sa.set_buffer_size(600000)
        # Threshold is 500000

        # 1. Not full
        sa.write_head = 100
        data = sa.get_latest_data()
        assert data is None
        assert sa.write_head == 100

        # 2. Full
        sa.write_head = 600000
        data = sa.get_latest_data()
        assert data is not None
        assert len(data) == 600000
        assert sa.write_head == 0 # Should reset

    def test_compute_spectrum(self, sa):
        # Prepare data
        sa.set_buffer_size(1024)
        t = np.linspace(0, 1024/48000, 1024, endpoint=False)
        # 1kHz Sine wave
        sig = np.sin(2 * np.pi * 1000 * t)
        sa.input_data[:, 0] = sig
        sa.input_data[:, 1] = sig
        sa.write_head = 0 # Full buffer effectively (idx=0 takes whole buffer)

        results = sa.compute_spectrum()

        assert results is not None
        assert "freqs" in results
        assert "magnitude" in results
        assert "overall_weighted_db" in results
        assert "peak_magnitude" in results

        # Check peak at 1kHz
        freqs = results["freqs"]
        mag = results["magnitude"]

        # Default channel mode is "Average", so magnitude is 1D (Average of L+R)
        # Find peak index
        peak_idx = np.argmax(mag)
        peak_freq = freqs[peak_idx]

        assert 950 < peak_freq < 1050

        # Check overall RMS (Sine wave -3 dBFS peak -> RMS should be consistent)
        # With Hanning window and corrections, should be close to expected.
        # Sine amplitude 1.0 => 0 dBFS Peak. RMS is -3.01 dB.
        # Spectrum Analyzer computes RMS?
        # overall_weighted_db is computed.
        # With Z weighting (default)
        assert -5.0 < results["overall_weighted_db"] < -1.0

    def test_compute_spectrum_not_enough_data(self, sa):
        sa.set_buffer_size(600000) # Snapshot mode
        sa.write_head = 100
        results = sa.compute_spectrum()
        assert results is None
