import sys
import unittest
from unittest.mock import MagicMock

# Mock PyQt6 before importing transient_analyzer to avoid GUI dependencies
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtGui"] = MagicMock()
sys.modules["PyQt6.QtWidgets"] = MagicMock()
sys.modules["pyqtgraph"] = MagicMock()

import numpy as np
import pywt
from src.gui.widgets.transient_analyzer import TransientAnalyzer

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.callbacks = {}

    def register_callback(self, callback):
        cid = 1
        self.callbacks[cid] = callback
        return cid

    def unregister_callback(self, cid):
        if cid in self.callbacks:
            del self.callbacks[cid]

class TestTransientAnalyzerAnalysis(unittest.TestCase):
    def setUp(self):
        self.audio_engine = MockAudioEngine()
        self.analyzer = TransientAnalyzer(self.audio_engine)

    def test_analyze_empty_data(self):
        """Test that analyze returns None when no data is present."""
        self.analyzer.final_data = None
        times, freqs, mag = self.analyzer.analyze()
        self.assertIsNone(times)
        self.assertIsNone(freqs)
        self.assertIsNone(mag)

        self.analyzer.final_data = np.array([])
        times, freqs, mag = self.analyzer.analyze()
        self.assertIsNone(times)
        self.assertIsNone(freqs)
        self.assertIsNone(mag)

    def test_analyze_sine_wave(self):
        """Test CWT analysis on a simple sine wave."""
        fs = 48000
        duration = 1.0
        t = np.linspace(0, duration, int(fs * duration), endpoint=False)
        f_sig = 1000
        sig = np.sin(2 * np.pi * f_sig * t)

        self.analyzer.final_data = sig
        self.analyzer.fs = fs
        # Set frequency range to include the signal frequency
        self.analyzer.min_anal_freq = 100
        self.analyzer.max_anal_freq = 2000

        times, freqs, mag = self.analyzer.analyze()

        # Check dimensions
        self.assertIsNotNone(times)
        self.assertEqual(len(times), len(sig))
        self.assertEqual(len(freqs), 120) # Hardcoded num_scales in analyze()
        self.assertEqual(mag.shape, (120, len(sig)))

        # Check content: Frequency detection
        # Find peak frequency at middle of signal to avoid edge effects
        mid_idx = len(sig) // 2
        spectrum_at_mid = mag[:, mid_idx]
        peak_idx = np.argmax(spectrum_at_mid)
        peak_freq = freqs[peak_idx]

        # Allow generous error margin (10%) due to wavelet resolution and scale discretization
        # The default wavelet 'cmor1.5-1.0' might have specific bandwidth properties
        self.assertTrue(900 < peak_freq < 1100, f"Peak frequency {peak_freq} not close to 1000 Hz")

    def test_analyze_frequency_limits(self):
        """Test that frequency limits are respected."""
        self.analyzer.final_data = np.zeros(1000)
        self.analyzer.fs = 48000
        self.analyzer.min_anal_freq = 500
        self.analyzer.max_anal_freq = 1500

        times, freqs, mag = self.analyzer.analyze()

        self.assertTrue(np.all(freqs >= 500))
        # max_freq might be adjusted slightly due to linspace, but should be close
        self.assertTrue(np.all(freqs <= 1500))
        self.assertEqual(len(freqs), 120)
