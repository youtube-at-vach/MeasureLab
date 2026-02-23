import sys
import unittest
from unittest.mock import MagicMock
import numpy as np
import importlib

class TestLoopbackFinder(unittest.TestCase):
    def setUp(self):
        # Patch modules
        self._patched_modules = ["PyQt6.QtCore", "PyQt6.QtWidgets", "sounddevice"]
        self._original_modules = {}

        for mod in self._patched_modules:
            if mod in sys.modules:
                self._original_modules[mod] = sys.modules[mod]
            sys.modules[mod] = MagicMock()

        # Specific mocks for PyQt6 to support class definitions
        mock_qt_core = sys.modules["PyQt6.QtCore"]

        # Robust base class mock that accepts any arguments in __init__
        class MockBase:
            def __init__(self, *args, **kwargs):
                pass

        # Make QThread a type so it can be inherited
        mock_qt_core.QThread = type('QThread', (MockBase,), {})
        # pyqtSignal can be a function returning a mock
        mock_qt_core.pyqtSignal = MagicMock(return_value=MagicMock())

        # Mock QWidget
        mock_qt_widgets = sys.modules["PyQt6.QtWidgets"]
        mock_qt_widgets.QWidget = type('QWidget', (MockBase,), {})

        # Import/Reload module under test
        if 'src.gui.widgets.loopback_finder' in sys.modules:
            importlib.reload(sys.modules['src.gui.widgets.loopback_finder'])
        else:
            importlib.import_module('src.gui.widgets.loopback_finder')

        self.module_under_test = sys.modules['src.gui.widgets.loopback_finder']

        # Instantiate LoopbackFinder
        self.mock_audio_engine = MagicMock()
        self.finder = self.module_under_test.LoopbackFinder(self.mock_audio_engine)

    def tearDown(self):
        # Restore modules
        for mod in self._patched_modules:
            if mod in self._original_modules:
                sys.modules[mod] = self._original_modules[mod]
            else:
                if mod in sys.modules:
                    del sys.modules[mod]

        # Remove module under test to ensure clean slate
        if 'src.gui.widgets.loopback_finder' in sys.modules:
            del sys.modules['src.gui.widgets.loopback_finder']

    def test_perform_scan_success(self):
        # Setup mocks
        sd = sys.modules["sounddevice"]
        sd.query_devices.return_value = {"max_output_channels": 2, "max_input_channels": 2}

        # Create a test signal that matches what the finder expects
        # The finder sends 440Hz sine wave.
        sample_rate = 48000
        duration = 0.1
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        test_signal = 0.5 * np.sin(2 * np.pi * 440 * t)

        class MockStream:
            def __init__(self, *args, **kwargs):
                self.callback = kwargs.get('callback')
                self.active = True
                self.calls = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
                
            def abort(self):
                self.active = False

        def stream_side_effect(*args, **kwargs):
            stream = MockStream(*args, **kwargs)
            # We must simulate the callback being called until it raises CallbackStop
            def run_stream():
                frames = 4800 # 0.1s block
                try:
                    while stream.active and stream.calls < 100:  # Prevent infinite loop in test
                        indata = np.zeros((frames, 2), dtype=np.float32)
                        outdata = np.zeros((frames, 2), dtype=np.float32)
                        
                        # Simulate loopback: if outdata channel 0 has signal, put it in indata channel 0
                        # But wait, outdata is written BY the callback.
                        # So we have to call it first, then next block we'll feedback?
                        # Actually, our finder sends outdata and records indata at the SAME time in the real world
                        # For testing, we can pre-fill indata based on expected timing.
                        # The finder tests ch0 then ch1.
                        # Let's just inject the test signal into indata 0 continuously, it will trigger when finder is listening to ch0.
                        indata[:, 0] = test_signal[:frames]
                        
                        stream.callback(indata, outdata, frames, None, None)
                        stream.calls += 1
                except sd.CallbackStop:
                    stream.active = False
                except Exception as e:
                    stream.active = False
                    raise e
                    
            # In real life the callback is in a background thread.
            # Here we just run it synchronously or rely on the main thread loop.
            # But the main thread does `while stream.active: time.sleep(0.1)`
            # We need to run it in a thread or mock the sleep.
            import threading
            t = threading.Thread(target=run_stream)
            t.start()
            return stream

        sd.Stream.side_effect = stream_side_effect
        sd.CallbackStop = Exception

        results = self.finder.perform_scan(device_id=0, sample_rate=sample_rate)

        # Expect loopback: Out 1 -> In 1 (indices 0->0)
        # Because we continuously injected signal into input 0!
        # It should detect it for output 1, and also output 2 (since it's continuously there)
        # We need a better mock if we want to test exact channel isolation.
        self.assertTrue(len(results) > 0)

    def test_perform_scan_no_signal(self):
        sd = sys.modules["sounddevice"]
        sd.query_devices.return_value = {"max_output_channels": 2, "max_input_channels": 2}

        class MockStream:
            def __init__(self, *args, **kwargs):
                self.callback = kwargs.get('callback')
                self.active = True

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
                
            def abort(self):
                self.active = False

        def stream_side_effect(*args, **kwargs):
            stream = MockStream(*args, **kwargs)
            def run_stream():
                frames = 4800
                import time
                try:
                    for _ in range(20): # Run for a bit and stop
                        indata = np.zeros((frames, 2), dtype=np.float32)
                        outdata = np.zeros((frames, 2), dtype=np.float32)
                        stream.callback(indata, outdata, frames, None, None)
                        time.sleep(0.01)
                except Exception:
                    stream.active = False
            import threading
            t = threading.Thread(target=run_stream)
            t.start()
            return stream

        sd.Stream.side_effect = stream_side_effect
        sd.CallbackStop = Exception

        results = self.finder.perform_scan(device_id=0, sample_rate=48000)

        self.assertEqual(len(results), 0)

    def test_perform_scan_device_error(self):
        sd = sys.modules["sounddevice"]
        # Simulate device with 0 inputs
        sd.query_devices.return_value = {"max_output_channels": 2, "max_input_channels": 0}

        with self.assertRaises(Exception) as cm:
            self.finder.perform_scan(device_id=0, sample_rate=48000)
        self.assertIn("does not support both input and output", str(cm.exception))

    def test_perform_scan_playrec_error(self):
        sd = sys.modules["sounddevice"]
        sd.query_devices.return_value = {"max_output_channels": 2, "max_input_channels": 2}
        
        # Make the stream raise an error on creation
        sd.Stream.side_effect = Exception("Audio Error")

        with self.assertRaises(Exception) as cm:
            self.finder.perform_scan(device_id=0, sample_rate=48000)
        self.assertIn("Stream error", str(cm.exception))

    def test_perform_scan_stop(self):
        sd = sys.modules["sounddevice"]
        sd.query_devices.return_value = {"max_output_channels": 10, "max_input_channels": 2}

        class MockStream:
            def __init__(self, *args, **kwargs):
                self.active = True
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
            def abort(self):
                self.active = False

        sd.Stream.return_value = MockStream()

        # Stop immediately
        check_stop = MagicMock(return_value=True)

        results = self.finder.perform_scan(device_id=0, sample_rate=48000, check_stop=check_stop)

        # Should break immediately, so no results
        self.assertEqual(len(results), 0)

    def test_perform_scan_progress(self):
        sd = sys.modules["sounddevice"]
        sd.query_devices.return_value = {"max_output_channels": 2, "max_input_channels": 2}
        
        class MockStream:
            def __init__(self, *args, **kwargs):
                self.callback = kwargs.get('callback')
                self.active = True

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
                
            def abort(self):
                self.active = False

        def stream_side_effect(*args, **kwargs):
            stream = MockStream(*args, **kwargs)
            def run_stream():
                frames = 4800
                try:
                    while stream.active:
                        indata = np.zeros((frames, 2), dtype=np.float32)
                        outdata = np.zeros((frames, 2), dtype=np.float32)
                        stream.callback(indata, outdata, frames, None, None)
                except Exception:
                    stream.active = False
            import threading
            t = threading.Thread(target=run_stream)
            t.start()
            return stream

        sd.Stream.side_effect = stream_side_effect
        sd.CallbackStop = Exception

        progress_cb = MagicMock()

        self.finder.perform_scan(device_id=0, sample_rate=48000, progress_callback=progress_cb)

        # Connection message + 2 channels = 3 calls
        self.assertEqual(progress_cb.call_count, 3)

    def test_perform_scan_tuple_device_id(self):
        sd = sys.modules["sounddevice"]
        # Configure side effect to simulate sd.query_devices failing on tuple
        def query_devices_side_effect(device=None, kind=None):
            if isinstance(device, tuple):
                raise TypeError("Invalid device ID: tuple not allowed")
            if isinstance(device, int):
                if device == 1: # Input
                    return {"max_output_channels": 0, "max_input_channels": 2}
                if device == 2: # Output
                    return {"max_output_channels": 2, "max_input_channels": 0}
            return {"max_output_channels": 2, "max_input_channels": 2}

        sd.query_devices.side_effect = query_devices_side_effect
        
        class MockStream:
            def __init__(self, *args, **kwargs):
                self.active = False # Stop immediately
            def __enter__(self): return self
            def __exit__(self, exc_type, exc_val, exc_tb): pass
        
        sd.Stream.return_value = MockStream()
        sd.CallbackStop = Exception

        device_id = (1, 2)
        sample_rate = 48000

        # Should not raise
        self.finder.perform_scan(device_id, sample_rate)

        # Verify calls
        sd.query_devices.assert_any_call(1)
        sd.query_devices.assert_any_call(2)

if __name__ == '__main__':
    unittest.main()
