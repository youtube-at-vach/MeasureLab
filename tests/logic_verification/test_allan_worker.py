import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Ensure the repository root is in sys.path
sys.path.insert(0, os.getcwd())

# --- Mock Infrastructure Setup ---

# 1. Mock heavy dependencies (sounddevice, PyQt6, pyqtgraph)
sys.modules["sounddevice"] = MagicMock()
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtGui"] = MagicMock()
sys.modules["PyQt6.QtWidgets"] = MagicMock()
sys.modules["pyqtgraph"] = MagicMock()

# 2. Mock project modules that might be imported
sys.modules["src.core.analysis"] = MagicMock()
sys.modules["src.core.audio_engine"] = MagicMock()
sys.modules["src.core.fft_manager"] = MagicMock()
sys.modules["src.core.localization"] = MagicMock()
sys.modules["src.measurement_modules.base"] = MagicMock()

# 3. Setup QRunnable and QObject mocks for inheritance
class MockQObject:
    def __init__(self, *args, **kwargs): pass

class MockQRunnable:
    def __init__(self, *args, **kwargs): pass

sys.modules["PyQt6.QtCore"].QObject = MockQObject
sys.modules["PyQt6.QtCore"].QRunnable = MockQRunnable

# 4. Mock pyqtSignal
def MockPyqtSignal(*args):
    # Returns a MagicMock that acts as the signal descriptor/instance
    m = MagicMock()
    m.emit = MagicMock()
    return m

sys.modules["PyQt6.QtCore"].pyqtSignal = MockPyqtSignal

# 5. Mock numpy (The big one)
# Only if numpy is missing, OR we force it for testing in restricted env.
# Since we are in a restricted env where numpy is missing, we must mock it.

class MockArray:
    def __init__(self, data):
        if isinstance(data, MockArray):
            self.data = list(data.data)
        else:
            self.data = list(data)

    def __len__(self):
        return len(self.data)

    def __getitem__(self, key):
        if isinstance(key, slice):
            # Handle slice step if needed, but usually simpler here
            return MockArray(self.data[key])
        if isinstance(key, MockArray):
            # Boolean indexing (mask)
            # key.data should be list of booleans
            if len(key.data) != len(self.data):
                raise IndexError(f"Boolean index has wrong length: {len(key.data)} vs {len(self.data)}")
            return MockArray([x for x, m in zip(self.data, key.data) if m])
        if isinstance(key, int):
            return self.data[key]
        raise TypeError(f"Invalid key type: {type(key)}")

    def __gt__(self, other):
        # element > other
        return MockArray([x > other for x in self.data])

    def __lt__(self, other):
        return MockArray([x < other for x in self.data])

    def __and__(self, other):
        # boolean & boolean
        return MockArray([a and b for a, b in zip(self.data, other.data)])

    def __rtruediv__(self, other):
        # other / self (element-wise)
        # Handle division by zero? Test assumes valid data or handles inf?
        # AllanWorker filters finite, so we assume valid here.
        return MockArray([other / x if x != 0 else float('inf') for x in self.data])

    def __pow__(self, other):
        return MockArray([x**other for x in self.data])

    def __mul__(self, other):
        return MockArray([x*other for x in self.data])

    def __rmul__(self, other):
        return self.__mul__(other)

    def reshape(self, *args):
        # Handle both reshape(shape_tuple) and reshape(d1, d2, ...)
        if len(args) == 1 and isinstance(args[0], (list, tuple)):
            shape = args[0]
        else:
            shape = args

        # shape is (-1, m)
        if len(shape) == 2 and shape[0] == -1:
            m = shape[1]
            if m == 0: return MockArray([])
            rows = len(self.data) // m
            new_data = []
            for i in range(rows):
                chunk = self.data[i*m : (i+1)*m]
                new_data.append(MockArray(chunk))
            return MockArray2D(new_data)
        return self

    def mean(self, axis=None):
        if not self.data: return 0.0
        # Flatten if 2D? No, MockArray is 1D.
        return sum(self.data) / len(self.data)

class MockArray2D(MockArray):
    def mean(self, axis=None):
        if axis == 1:
            # Mean along rows (each row is a MockArray)
            return MockArray([row.mean() for row in self.data])
        return super().mean(axis) # Should not happen for 2D in this usage

def mock_asarray(a, dtype=None):
    return MockArray(a)

def mock_isfinite(a):
    if isinstance(a, MockArray):
        d = a.data
    else:
        d = a
    # Check if finite (not inf, not nan)
    import math
    return MockArray([math.isfinite(x) for x in d])

def mock_diff(a):
    if isinstance(a, MockArray):
        d = a.data
    else:
        d = a
    if len(d) < 2:
        return MockArray([])
    return MockArray([d[i+1]-d[i] for i in range(len(d)-1)])

def mock_mean(a):
    if isinstance(a, MockArray):
        return a.mean()
    if not a: return 0.0
    return sum(a)/len(a)

def mock_sqrt(val):
    return val**0.5

# Setup numpy mock module
mock_numpy = MagicMock()
mock_numpy.asarray = mock_asarray
mock_numpy.isfinite = mock_isfinite
mock_numpy.diff = mock_diff
mock_numpy.mean = mock_mean
mock_numpy.sqrt = mock_sqrt
sys.modules["numpy"] = mock_numpy

# Now import the class under test
from src.gui.widgets.frequency_counter import AllanWorker

class TestAllanWorker(unittest.TestCase):
    def setUp(self):
        # We don't need to patch signals on the instance because AllanWorker uses
        # self.signals = AllanWorkerSignals() which uses our mocked pyqtSignal.
        pass

    def test_init(self):
        history = [1.0, 2.0, 3.0]
        worker = AllanWorker(history, 100, "frequency")
        self.assertEqual(worker.freq_history, history)
        self.assertEqual(worker.update_interval_ms, 100)
        self.assertEqual(worker.display_mode, "frequency")
        # Check signals
        self.assertTrue(hasattr(worker.signals, 'result'))
        self.assertTrue(hasattr(worker.signals.result, 'emit'))

    def test_run_empty_history(self):
        worker = AllanWorker([], 100, "frequency")
        worker.run()
        worker.signals.result.emit.assert_called_with([], [])

    def test_run_short_history(self):
        # < 10 items
        worker = AllanWorker([1.0]*9, 100, "frequency")
        worker.run()
        worker.signals.result.emit.assert_called_with([], [])

    def test_run_frequency_mode(self):
        # Generate some simple data: constant frequency -> Allan Deviation should be 0
        # But wait, diff of constant is 0, so sigma is 0.
        history = [1000.0] * 20
        worker = AllanWorker(history, 100, "frequency")
        worker.run()

        args, _ = worker.signals.result.emit.call_args
        taus, devs = args

        # Check length
        # N=20. Max m = 10. m=1, 2, 4, 8.
        # So we expect 4 points.
        self.assertEqual(len(taus), 4)
        self.assertEqual(len(devs), 4)

        # Check values
        # Taus: 1*0.1, 2*0.1, 4*0.1, 8*0.1 => 0.1, 0.2, 0.4, 0.8
        self.assertAlmostEqual(taus[0], 0.1)
        self.assertAlmostEqual(taus[3], 0.8)

        # Devs: Should be 0 for constant input
        self.assertAlmostEqual(devs[0], 0.0)
        self.assertAlmostEqual(devs[3], 0.0)

    def test_run_period_mode(self):
        # Input history is frequency (Hz). Display mode is period (s).
        # Data is converted: 1.0 / data
        # If input is 1000 Hz, period is 0.001 s.
        history = [1000.0] * 20
        worker = AllanWorker(history, 100, "period")
        worker.run()

        args, _ = worker.signals.result.emit.call_args
        taus, devs = args

        self.assertEqual(len(taus), 4)
        self.assertEqual(len(devs), 4)
        self.assertAlmostEqual(devs[0], 0.0)

    def test_run_invalid_data(self):
        # Mix of valid and invalid
        # AllanWorker filters valid: (isfinite) & (data > 0)
        history = [1000.0] * 15 + [float('nan'), float('inf'), -10.0, 0.0] + [1000.0] * 5
        # Total 20 valid points
        worker = AllanWorker(history, 100, "frequency")
        worker.run()

        args, _ = worker.signals.result.emit.call_args
        taus, devs = args

        # Should have filtered to 20 points
        # N=20 => 4 points (m=1,2,4,8)
        self.assertEqual(len(taus), 4)
        self.assertEqual(len(devs), 4)

    def test_run_noise(self):
        # Linear drift: 1, 2, 3, ... 20
        # Diff is constant 1.
        # Mean(diff^2) = 1. Sqrt(0.5 * 1) = 0.707
        history = [float(i) for i in range(20)]
        worker = AllanWorker(history, 1000, "frequency") # 1 sec interval
        worker.run()

        args, _ = worker.signals.result.emit.call_args
        taus, devs = args

        # m=1: tau=1. dev=0.707
        self.assertAlmostEqual(taus[0], 1.0)
        self.assertAlmostEqual(devs[0], (0.5)**0.5)

    def test_exception_handling(self):
        # Mocking an exception during calculation
        # We can patch mock_asarray to raise exception
        with patch.object(mock_numpy, 'asarray', side_effect=ValueError("Test Error")):
            worker = AllanWorker([1.0]*20, 100, "frequency")

            # Capture stdout to silence print
            from io import StringIO
            with patch('sys.stdout', new=StringIO()):
                worker.run()

            # Should emit empty lists
            worker.signals.result.emit.assert_called_with([], [])

if __name__ == "__main__":
    unittest.main()
