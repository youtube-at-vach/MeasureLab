import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch
import importlib

# --- Mock Infrastructure ---
class MockArray:
    def __init__(self, shape, fill_value=0.0):
        if isinstance(shape, int):
            self.shape = (shape,)
        else:
            self.shape = tuple(shape)
        self.size = 1
        for dim in self.shape:
            self.size *= dim
        self.data = [fill_value] * self.size
        self.ndim = len(self.shape)
        self.dtype = "float32"

    def __len__(self):
        return self.shape[0]

    def __getitem__(self, key):
        if isinstance(key, slice):
            start, stop, step = key.indices(self.shape[0])
            if step is None:
                step = 1
            length = max(0, (stop - start + (step or 1) - 1) // (step or 1))
            new_shape = list(self.shape)
            new_shape[0] = length
            return MockArray(tuple(new_shape))
        if isinstance(key, tuple):
            if isinstance(key[0], slice):
                return self.__getitem__(key[0])
        return 0.0

    def __setitem__(self, key, value):
        pass

    def fill(self, val):
        pass

    def copy(self):
        return MockArray(self.shape)

class TestRecorderPlayerRace(unittest.TestCase):
    def setUp(self):
        self.mock_np = MagicMock()
        self.mock_np.zeros.side_effect = lambda shape, dtype=None: MockArray(shape)
        self.mock_np.array.side_effect = lambda data, dtype=None: MockArray((len(data), len(data[0]) if data else 0))
        self.mock_np.mean.return_value = MockArray((1,))

        self.mock_modules = {
            'numpy': self.mock_np,
            'scipy': MagicMock(),
            'scipy.signal': MagicMock(),
            'scipy.optimize': MagicMock(),
            'sounddevice': MagicMock(),
            'soundfile': MagicMock(),
            'src.core.calibration': MagicMock(),
            'PyQt6': MagicMock(),
            'PyQt6.QtCore': MagicMock(),
            'PyQt6.QtWidgets': MagicMock(),
            'src.core.audio_engine': MagicMock(),
            'src.core.localization': MagicMock(),
        }

        self.patcher = patch.dict(sys.modules, self.mock_modules)
        self.patcher.start()

        # Import and reload the module to ensure it uses the mocks
        import src.gui.widgets.recorder_player
        importlib.reload(src.gui.widgets.recorder_player)
        self.module = src.gui.widgets.recorder_player

    def tearDown(self):
        self.patcher.stop()

    def test_infinite_loop_hang_empty_buffer(self):
        """Verify that an empty buffer doesn't cause an infinite loop."""
        mock_engine = MagicMock()
        mock_engine.sample_rate = 48000
        # Use the class from the reloaded module
        player = self.module.RecorderPlayer(mock_engine)

        player.is_playing = True
        player.loop_playback = True
        player.output_mode = "Stereo"
        player.playback_pos = 0
        player.playback_buffer = MockArray((0, 2))

        indata = MockArray((512, 2))
        outdata = MockArray((512, 2))

        def run_callback():
            player.audio_callback(indata, outdata, 512, None, None)

        t = threading.Thread(target=run_callback)
        t.daemon = True
        t.start()

        t.join(timeout=1.0)

        if t.is_alive():
            self.fail("Audio callback entered infinite loop with empty buffer")

        # Also assert state changed correctly
        self.assertFalse(player.is_playing, "Should stop playing on empty buffer")

    def test_race_condition_pos_exceeds_len(self):
        """Verify handling when playback_pos exceeds buffer length."""
        mock_engine = MagicMock()
        player = self.module.RecorderPlayer(mock_engine)

        player.is_playing = True
        player.loop_playback = True
        player.output_mode = "Stereo"
        player.playback_buffer = MockArray((100, 2))
        player.playback_pos = 9000  # Exceeds 100

        indata = MockArray((512, 2))
        outdata = MockArray((512, 2))

        # This should execute quickly and reset pos to 0 (since loop is True)
        player.audio_callback(indata, outdata, 512, None, None)

        # Check that it didn't crash or hang
        self.assertTrue(True)

        # If loop was False, it should stop
        player.is_playing = True
        player.loop_playback = False
        player.playback_pos = 9000

        player.audio_callback(indata, outdata, 512, None, None)

        self.assertFalse(player.is_playing, "Should stop playing if out of bounds and not looping")
