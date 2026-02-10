import sys
import unittest
from unittest.mock import MagicMock
import importlib

# Ensure numpy and pywt are fully loaded before we start messing with sys.modules
import numpy as np  # noqa: E402

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
        # Manually patch sys.modules to avoid blanket restore that removes C-extensions
        self._patched_modules = ["PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "pyqtgraph"]
        self._original_modules = {}

        for mod in self._patched_modules:
            if mod in sys.modules:
                self._original_modules[mod] = sys.modules[mod]
            sys.modules[mod] = MagicMock()

        # Import/Reload module under test inside the patch to pick up mocks
        import src.gui.widgets.transient_analyzer
        importlib.reload(src.gui.widgets.transient_analyzer)
        self.module_under_test = src.gui.widgets.transient_analyzer

        self.np = np

        self.audio_engine = MockAudioEngine()
        self.analyzer = self.module_under_test.TransientAnalyzer(self.audio_engine)

    def tearDown(self):
        # Restore patched modules
        for mod in self._patched_modules:
            if mod in self._original_modules:
                sys.modules[mod] = self._original_modules[mod]
            else:
                if mod in sys.modules:
                    del sys.modules[mod]

        # Clean up the module under test to ensure subsequent tests reload the real module if needed
        if 'src.gui.widgets.transient_analyzer' in sys.modules:
            del sys.modules['src.gui.widgets.transient_analyzer']

    def test_analyze_empty_data(self):
        """Test that analyze returns None when no data is present."""
        self.analyzer.final_data = None
        times, freqs, mag = self.analyzer.analyze()
        self.assertIsNone(times)
        self.assertIsNone(freqs)
        self.assertIsNone(mag)

        self.analyzer.final_data = self.np.array([])
        times, freqs, mag = self.analyzer.analyze()
        self.assertIsNone(times)
        self.assertIsNone(freqs)
        self.assertIsNone(mag)

    def test_analyze_sine_wave(self):
        """Test CWT analysis on a simple sine wave."""
        fs = 48000
        duration = 1.0
        t = self.np.linspace(0, duration, int(fs * duration), endpoint=False)
        f_sig = 1000
        sig = self.np.sin(2 * self.np.pi * f_sig * t)

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
        peak_idx = self.np.argmax(spectrum_at_mid)
        peak_freq = freqs[peak_idx]

        # Allow generous error margin (10%) due to wavelet resolution and scale discretization
        self.assertTrue(900 < peak_freq < 1100, f"Peak frequency {peak_freq} not close to 1000 Hz")

    def test_analyze_frequency_limits(self):
        """Test that frequency limits are respected."""
        self.analyzer.final_data = self.np.zeros(1000)
        self.analyzer.fs = 48000
        self.analyzer.min_anal_freq = 500
        self.analyzer.max_anal_freq = 1500

        times, freqs, mag = self.analyzer.analyze()

        self.assertTrue(self.np.all(freqs >= 500))
        self.assertTrue(self.np.all(freqs <= 1500))
        self.assertEqual(len(freqs), 120)
