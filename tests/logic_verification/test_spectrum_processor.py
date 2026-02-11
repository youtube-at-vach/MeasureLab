import pytest
import numpy as np
from src.core.spectrum_processor import SpectrumProcessor

class TestSpectrumProcessor:
    @pytest.fixture
    def processor(self):
        return SpectrumProcessor()

    def test_initialization(self, processor):
        assert processor._avg_magnitude is None

    def test_process_simple_sine(self, processor):
        # Generate sine wave: 1kHz at 48kHz sampling rate
        sr = 48000
        t = np.arange(1024) / sr
        freq = 1000
        # Amplitude 1.0 (0 dBFS peak)
        data = np.sin(2 * np.pi * freq * t)
        # Stereo
        data_stereo = np.column_stack((data, data))

        config = {
            "window_type": "rect", # No window for easy peak check
            "analysis_mode": "Spectrum",
            "channel_mode": "Average",
            "multitaper_enabled": False,
            "averaging": 0.0,
            "weighting": "Z",
            "display_unit": "dBFS",
            "peak_hold": False,
            "octave_smoothing": "None",
        }

        results = processor.process(data_stereo, sr, config)

        assert "freqs" in results
        assert "magnitude" in results
        assert "overall_weighted_db" in results

        freqs = results["freqs"]
        mags = results["magnitude"]

        # Find peak
        peak_idx = np.argmax(mags)
        peak_freq = freqs[peak_idx]
        peak_mag = mags[peak_idx]

        # FFT bin resolution = 48000 / 1024 = 46.875 Hz
        # 1000 / 46.875 = 21.33
        # Closest bin index: 21 (984.375 Hz)
        assert 900 < peak_freq < 1100

        # Peak should be close to 0 dBFS (since input is 1.0 amplitude sine and window is rect)
        # Due to spectral leakage (non-integer cycles), it might be slightly lower.
        assert peak_mag > -6.0

    def test_averaging(self, processor):
        sr = 48000
        data = np.zeros((1024, 2)) # Silence

        config = {
            "averaging": 0.5,
            "window_type": "hanning",
            "analysis_mode": "Spectrum",
            "channel_mode": "Average",
            "multitaper_enabled": False,
            "weighting": "Z",
            "display_unit": "dBFS",
            "peak_hold": False,
            "octave_smoothing": "None",
        }

        # First pass: Silence -> very low dB
        processor.process(data, sr, config)

        # Second pass: High signal (constant 1.0)
        # Use constant signal to be deterministic
        data_high = np.ones((1024, 2))
        processor.process(data_high, sr, config)

        # Let's verify processor state
        assert processor._avg_magnitude is not None

    def test_reset(self, processor):
        processor._avg_magnitude = np.array([1, 2, 3])
        processor.reset()
        assert processor._avg_magnitude is None

    def test_spectrum_analyzer_instantiation(self):
        from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer
        from src.core.spectrum_processor import SpectrumProcessor
        from unittest.mock import MagicMock

        mock_engine = MagicMock()
        sa = SpectrumAnalyzer(mock_engine)
        assert sa.processor is not None
        assert isinstance(sa.processor, SpectrumProcessor)
