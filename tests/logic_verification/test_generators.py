import sys
import unittest
from unittest.mock import MagicMock, patch

# Create mock numpy
mock_numpy = MagicMock()

# Configure numpy mocks for types
mock_numpy.float32 = float
mock_numpy.float64 = float
mock_numpy.int32 = int
mock_numpy.int64 = int

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

mock_numpy.random.randn.return_value = MockArray()
mock_numpy.empty.return_value = MockArray()

# Patch sys.modules BEFORE import
with patch.dict(sys.modules, {"numpy": mock_numpy}):
    from src.core.generators import PinkNoise

class TestPinkNoise(unittest.TestCase):
    def test_init(self):
        """Test initialization of PinkNoise generator."""
        pn = PinkNoise()
        self.assertEqual(pn.b0, 0.0)

    def test_generate_logic(self):
        """Test that generate calls numpy functions and updates state."""
        pn = PinkNoise()
        n = 10

        # When generate is called:
        # white = np.random.randn(n).astype(...) -> returns MockArray
        # out = np.empty(...) -> returns MockArray
        # Loop iterates n times: w = float(white[i]) -> 0.5
        # b0 update: 0.99886*0 + 0.5*0.0555179 -> ~0.027

        pn.generate(n)

        # Verify numpy calls
        mock_numpy.random.randn.assert_called_with(n)
        mock_numpy.empty.assert_called_with(n, dtype=mock_numpy.float32)

        # Verify state updated from 0.0
        # Specifically b0 should be non-zero
        self.assertNotEqual(pn.b0, 0.0)

        # Verify b0 is approximately what we expect for w=0.5
        self.assertGreater(abs(pn.b0), 0.001)

if __name__ == "__main__":
    unittest.main()
