import sys
import unittest
import importlib
import os
from unittest.mock import MagicMock, patch

# Ensure src can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

class TestPinkNoise(unittest.TestCase):
    def setUp(self):
        # Create mock numpy
        self.mock_numpy = MagicMock()

        # Configure numpy mocks for types
        self.mock_numpy.float32 = float
        self.mock_numpy.float64 = float
        self.mock_numpy.int32 = int
        self.mock_numpy.int64 = int

        # Define mocks for random and empty
        # We need `white` array to return something convertible to float when indexed
        # And `out` array to support item assignment

        class MockArray(MagicMock):
            def __getitem__(self, key):
                # Return a mock that converts to float 0.5
                m = MagicMock()
                m.__float__.return_value = 0.5
                return m

            def __setitem__(self, key, value):
                pass

            def astype(self, dtype):
                return self

        self.mock_numpy.random.randn.return_value = MockArray()
        self.mock_numpy.empty.return_value = MockArray()

    def test_init(self):
        """Test initialization of PinkNoise generator."""
        # Use patch.dict to inject mock numpy for this test
        # We must ensure src.core.generators is loaded with this mock
        with patch.dict(sys.modules, {"numpy": self.mock_numpy}):
            if 'src.core.generators' in sys.modules:
                del sys.modules['src.core.generators']

            from src.core.generators import PinkNoise

            pn = PinkNoise()
            self.assertEqual(pn.b0, 0.0)

        # Cleanup
        if 'src.core.generators' in sys.modules:
            del sys.modules['src.core.generators']

    def test_generate_logic(self):
        """Test that generate calls numpy functions and updates state."""
        n = 10

        # Use patch.dict to inject mock numpy for this test
        with patch.dict(sys.modules, {"numpy": self.mock_numpy}):
            # Force reload to pick up mock numpy
            if 'src.core.generators' in sys.modules:
                del sys.modules['src.core.generators']

            from src.core.generators import PinkNoise

            pn = PinkNoise()
            pn.generate(n)

            # Verify numpy calls
            self.mock_numpy.random.randn.assert_called_with(n)
            self.mock_numpy.empty.assert_called_with(n, dtype=self.mock_numpy.float32)

            # Verify state updated from 0.0
            # Specifically b0 should be non-zero
            self.assertNotEqual(pn.b0, 0.0)

            # Verify b0 is approximately what we expect for w=0.5
            self.assertGreater(abs(pn.b0), 0.001)

        # Cleanup
        if 'src.core.generators' in sys.modules:
            del sys.modules['src.core.generators']

if __name__ == "__main__":
    unittest.main()
