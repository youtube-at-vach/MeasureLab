import unittest
import numpy as np
import threading
from src.core.analysis import AudioCalc, _get_shared_buffers


class TestOptimizationBuffers(unittest.TestCase):
    def test_buffer_reuse(self):
        """Verify that optimize_frequency reuses the same buffer objects."""
        sr = 48000
        N = 1000
        t = np.arange(N) / sr
        freq = 100.0
        signal = np.sin(2 * np.pi * freq * t)

        # Call 1
        ret1 = AudioCalc.optimize_frequency(signal, sr, freq, return_full=True)
        self.assertTrue(len(ret1) == 3)
        M1 = ret1[2]

        # Call 2
        ret2 = AudioCalc.optimize_frequency(signal, sr, freq, return_full=True)
        M2 = ret2[2]

        # Get from cache directly
        M_cached, _, _ = _get_shared_buffers(N, t.dtype)

        self.assertIs(M1, M_cached)
        self.assertIs(M2, M_cached)

    def test_buffer_reallocation_on_size_change(self):
        """Verify that buffers are reallocated if size N changes."""
        sr = 48000

        # Size 1
        N1 = 1000
        signal1 = np.zeros(N1)
        ret1 = AudioCalc.optimize_frequency(signal1, sr, 100.0, return_full=True)
        M1 = ret1[2]

        # Size 2
        N2 = 2000
        signal2 = np.zeros(N2)
        ret2 = AudioCalc.optimize_frequency(signal2, sr, 100.0, return_full=True)
        M2 = ret2[2]

        self.assertIsNot(M1, M2)
        self.assertEqual(M1.shape[0], N1)
        self.assertEqual(M2.shape[0], N2)

    def test_ones_column_integrity(self):
        """Verify that the constant column of ones is preserved/restored."""
        sr = 48000
        N = 1000
        signal = np.zeros(N)

        # Get buffers directly (to inspect before)
        M_before, _, _ = _get_shared_buffers(N, np.float64)

        # Check initialization
        np.testing.assert_array_equal(M_before[:, 2], np.ones(N))

        # Run optimization
        AudioCalc.optimize_frequency(signal, sr, 100.0)

        # Get buffers again (should be same object if N matches)
        # Note: _get_shared_buffers updates M[:, 2] in place to 1.0
        M_after, _, _ = _get_shared_buffers(N, np.float64)

        # Verify it is the same object
        # assertIs checks identity (id(a) == id(b)).
        # If numpy array was reallocated or view changed, this fails.
        # But wait, M_before content in the assertion error looks like it HAS garbage data.
        # So M_before IS being modified in place.
        # The failure says "array(...) is not array(...)".
        # This implies they are DIFFERENT objects? Or just repr is confusing?
        # If they were the same object, then `M_before` would ALSO have the reset 1.0 column!

        # If M_before holds the reference to the array *before* modification.
        # Then we modify it in place.
        # Then M_after gets reference to the SAME array.
        # So M_before and M_after should point to the same data.

        # However, the error message shows DIFFERENT content.
        # M_before has garbage (from the optimization run).
        # M_after has clean 1.0s (from the reset in _get_shared_buffers).
        # This implies M_after IS the reset array.
        # If they are the same object, M_before should ALSO see the reset values!

        # UNLESS `_get_shared_buffers` returned a NEW array for M_after?
        # If so, caching failed.

        # Let's check IDs explicitly in the test to be sure.
        self.assertEqual(id(M_before), id(M_after))

        # Verify content is correct
        np.testing.assert_array_equal(M_after[:, 2], np.ones(N))

    def test_thread_isolation(self):
        """Verify that different threads get different buffers."""
        results = {}

        def thread_task(thread_id):
            N = 100
            M, _, _ = _get_shared_buffers(N, np.float64)
            results[thread_id] = M

        t1 = threading.Thread(target=thread_task, args=(1,))
        t2 = threading.Thread(target=thread_task, args=(2,))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertNotEqual(id(results[1]), id(results[2]))


if __name__ == "__main__":
    unittest.main()
