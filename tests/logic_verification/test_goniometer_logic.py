import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

class MockAudioEngine:
    def register_callback(self, cb):
        return 1
    def unregister_callback(self, id):
        pass

class TestGoniometerLogic(unittest.TestCase):
    def setUp(self):
        # Create a patcher for sys.modules
        self.modules_patcher = patch.dict(sys.modules, {"sounddevice": MagicMock()})
        self.modules_patcher.start()

        # We need to ensure src.core.localization is NOT mocked globally if it exists,
        # or we mock it locally if we must.
        # But wait, other tests failed because we mocked it globally.
        # If we remove the global mock, we should check if Goniometer can import it.
        # Goniometer uses `from src.core.localization import tr`.
        # If localization relies on something else, we might need to mock that.
        # But let's assume sounddevice is the main issue.

    def tearDown(self):
        self.modules_patcher.stop()

    def test_goniometer_logic(self):
        # Import inside the test to use the patched sys.modules
        from src.gui.widgets.goniometer import Goniometer

        engine = MockAudioEngine()
        gonio = Goniometer(engine)

        print("Testing Goniometer Logic...")

        # 1. Mono (In-Phase)
        frames = 1024
        left = np.sin(np.linspace(0, 100, frames))
        right = left.copy()
        data = np.column_stack((left, right))

        # Call callback manually
        outdata = np.zeros_like(data)
        gonio._callback(data, outdata, frames, 0, None)

        print(f"Mono Correlation: {gonio.correlation:.4f} (Expected 1.0)")
        self.assertTrue(np.isclose(gonio.correlation, 1.0, atol=0.01))

        # 2. Inverted (Anti-Phase)
        right = -left
        data = np.column_stack((left, right))
        gonio._callback(data, outdata, frames, 0, None)

        print(f"Inverted Correlation: {gonio.correlation:.4f} (Expected -1.0)")
        self.assertTrue(np.isclose(gonio.correlation, -1.0, atol=0.01))

        # 3. Left Only
        right = np.zeros_like(left)
        data = np.column_stack((left, right))
        gonio._callback(data, outdata, frames, 0, None)

        print(f"Left Only Correlation: {gonio.correlation:.4f} (Expected 0.0)")
        self.assertTrue(np.isclose(gonio.correlation, 0.0, atol=0.01))

        # 4. Stereo (Random)
        # Random noise should be close to 0 correlation on average
        np.random.seed(42)
        left = np.random.randn(frames)
        right = np.random.randn(frames)
        data = np.column_stack((left, right))
        gonio._callback(data, outdata, frames, 0, None)

        print(f"Random Stereo Correlation: {gonio.correlation:.4f} (Expected ~0.0)")
        self.assertTrue(abs(gonio.correlation) < 0.1) # Should be low

        print("All tests passed!")

if __name__ == "__main__":
    unittest.main()
