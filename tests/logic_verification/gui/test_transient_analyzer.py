import sys
import unittest
import numpy as np
import pytest
import os

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from PyQt6.QtWidgets import QApplication
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
    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls.app = QApplication(sys.argv + ['-platform', 'offscreen'])
        else:
            cls.app = QApplication.instance()

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
        self.assertTrue(900 < peak_freq < 1100, f"Peak frequency {peak_freq} not close to 1000 Hz")

    def test_analyze_frequency_limits(self):
        """Test that frequency limits are respected."""
        self.analyzer.final_data = np.zeros(1000)
        self.analyzer.fs = 48000
        self.analyzer.min_anal_freq = 500
        self.analyzer.max_anal_freq = 1500

        times, freqs, mag = self.analyzer.analyze()

        self.assertTrue(np.all(freqs >= 500))
        self.assertTrue(np.all(freqs <= 1500))
        self.assertEqual(len(freqs), 120)

class TestTransientAnalyzerTrigger:
    @pytest.fixture
    def analyzer(self):
        engine = MockAudioEngine()
        analyzer = TransientAnalyzer(engine)
        # Default settings
        analyzer.trigger_enabled = True
        analyzer.trigger_level = 0.5
        analyzer.trigger_slope = "Rising"
        analyzer._prev_trigger_sample = None
        return analyzer

    def test_find_trigger_index_none_or_empty(self, analyzer):
        assert analyzer._find_trigger_index(None) is None
        assert analyzer._find_trigger_index(np.array([])) is None

    def test_find_trigger_index_rising_simple(self, analyzer):
        # 0.0 -> 1.0 crossing at index 0->1.
        # Index returned should be 1 (the sample causing the trigger).
        sig = np.array([0.0, 1.0, 0.0])
        idx = analyzer._find_trigger_index(sig)
        assert idx == 1

    def test_find_trigger_index_falling_simple(self, analyzer):
        analyzer.trigger_slope = "Falling"
        # 1.0 -> 0.0 crossing at index 0->1.
        sig = np.array([1.0, 0.0, 1.0])
        idx = analyzer._find_trigger_index(sig)
        assert idx == 1

    def test_find_trigger_index_rising_with_prev(self, analyzer):
        # Previous sample was 0.0 (<= 0.5), current sig starts with 1.0 (> 0.5).
        # Should trigger at index 0.
        analyzer._prev_trigger_sample = 0.0
        sig = np.array([1.0, 0.5])
        idx = analyzer._find_trigger_index(sig)
        assert idx == 0

    def test_find_trigger_index_falling_with_prev(self, analyzer):
        analyzer.trigger_slope = "Falling"
        # Previous sample was 1.0 (>= 0.5), current sig starts with 0.0 (< 0.5).
        # Should trigger at index 0.
        analyzer._prev_trigger_sample = 1.0
        sig = np.array([0.0, 0.5])
        idx = analyzer._find_trigger_index(sig)
        assert idx == 0

    def test_find_trigger_index_no_crossing(self, analyzer):
        # Signal always below trigger level
        sig = np.array([0.0, 0.1, 0.2, 0.3, 0.4])
        assert analyzer._find_trigger_index(sig) is None

        # Signal always above trigger level
        sig = np.array([0.6, 0.7, 0.8, 0.9, 1.0])
        assert analyzer._find_trigger_index(sig) is None

    def test_find_trigger_index_not_enough_samples(self, analyzer):
        # Only 1 sample, and no prev sample to trigger.
        sig = np.array([0.0])
        assert analyzer._find_trigger_index(sig) is None

    def test_find_trigger_index_multiple_crossings(self, analyzer):
        # Rising edge at 0->1 (idx 1) and 2->3 (idx 3).
        # Should return first one (1).
        sig = np.array([0.0, 1.0, 0.0, 1.0])
        idx = analyzer._find_trigger_index(sig)
        assert idx == 1

    def test_find_trigger_index_exact_match_rising(self, analyzer):
        # Condition: prev <= level and curr > level.
        # 0.5 (== level) -> 0.6 (> level). Should trigger.
        sig = np.array([0.5, 0.6])
        idx = analyzer._find_trigger_index(sig)
        assert idx == 1

        # 0.4 (< level) -> 0.5 (== level). Should NOT trigger.
        sig = np.array([0.4, 0.5])
        assert analyzer._find_trigger_index(sig) is None

    def test_find_trigger_index_exact_match_falling(self, analyzer):
        analyzer.trigger_slope = "Falling"
        # Condition: prev >= level and curr < level.
        # 0.5 (== level) -> 0.4 (< level). Should trigger.
        sig = np.array([0.5, 0.4])
        idx = analyzer._find_trigger_index(sig)
        assert idx == 1

        # 0.6 (> level) -> 0.5 (== level). Should NOT trigger.
        sig = np.array([0.6, 0.5])
        assert analyzer._find_trigger_index(sig) is None

    def test_find_trigger_index_prev_no_crossing(self, analyzer):
        # Prev sample set, but no crossing between prev and sig[0].
        analyzer._prev_trigger_sample = 0.0
        sig = np.array([0.2, 0.3]) # Still below 0.5
        assert analyzer._find_trigger_index(sig) is None

    def test_find_trigger_index_prev_crossing_rising_exact(self, analyzer):
        # Prev = 0.5 (== level), Sig[0] = 0.6 (> level). Trigger at 0.
        analyzer._prev_trigger_sample = 0.5
        sig = np.array([0.6])
        idx = analyzer._find_trigger_index(sig)
        assert idx == 0

    def test_find_trigger_index_prev_crossing_falling_exact(self, analyzer):
        analyzer.trigger_slope = "Falling"
        # Prev = 0.5 (== level), Sig[0] = 0.4 (< level). Trigger at 0.
        analyzer._prev_trigger_sample = 0.5
        sig = np.array([0.4])
        idx = analyzer._find_trigger_index(sig)
        assert idx == 0

if __name__ == '__main__':
    unittest.main()
