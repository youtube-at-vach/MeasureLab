import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
import numpy as np
import pytest
from src.gui.widgets.transient_analyzer import TransientAnalyzer

# Mock AudioEngine to satisfy dependency
class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.callbacks = {}

    def register_callback(self, callback):
        return 1

    def unregister_callback(self, cid):
        pass

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
