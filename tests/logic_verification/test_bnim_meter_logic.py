import sys
import unittest
from unittest.mock import MagicMock
import numpy as np
import importlib

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

class TestBNIMMeterLogic(unittest.TestCase):
    def setUp(self):
        # Patch modules
        self._patched_modules = [
            "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "pyqtgraph",
            "src.core.fft_manager"
        ]
        self._original_modules = {}

        for mod in self._patched_modules:
            if mod in sys.modules:
                self._original_modules[mod] = sys.modules[mod]
            sys.modules[mod] = MagicMock()

        # Mock fft_manager specifically to use numpy.fft
        # We need to mock the module 'src.core.fft_manager' so that
        # when bnim_meter imports 'fft_manager' from it, it gets our mock object.
        mock_fft_module = sys.modules["src.core.fft_manager"]
        self.mock_fft_manager_instance = MagicMock()
        self.mock_fft_manager_instance.rfft = np.fft.rfft
        self.mock_fft_manager_instance.rfftfreq = np.fft.rfftfreq
        mock_fft_module.fft_manager = self.mock_fft_manager_instance

        # Mock QtWidgets explicitly if needed, but MagicMock usually handles it.
        # However, for QWidget inheritance (BNIMMeterWidget), we need a class, not an instance.
        # BNIMMeter doesn't inherit QWidget, but BNIMMeterWidget does.
        # bnim_meter.py imports QWidget.
        # mock.QWidget needs to be a type.
        mock_qt_widgets = sys.modules["PyQt6.QtWidgets"]
        mock_qt_widgets.QWidget = MagicMock
        mock_qt_widgets.QGroupBox = MagicMock
        mock_qt_widgets.QLabel = MagicMock
        mock_qt_widgets.QPushButton = MagicMock
        mock_qt_widgets.QCheckBox = MagicMock
        mock_qt_widgets.QSlider = MagicMock
        mock_qt_widgets.QComboBox = MagicMock
        mock_qt_widgets.QSpinBox = MagicMock
        mock_qt_widgets.QDoubleSpinBox = MagicMock
        mock_qt_widgets.QHBoxLayout = MagicMock
        mock_qt_widgets.QVBoxLayout = MagicMock

        # Import module under test
        import src.gui.widgets.bnim_meter
        importlib.reload(src.gui.widgets.bnim_meter)
        self.bnim_module = src.gui.widgets.bnim_meter

        self.audio_engine = MockAudioEngine()
        self.meter = self.bnim_module.BNIMMeter(self.audio_engine)

    def tearDown(self):
        # Restore
        for mod in self._patched_modules:
            if mod in self._original_modules:
                sys.modules[mod] = self._original_modules[mod]
            else:
                if mod in sys.modules:
                    del sys.modules[mod]

        if 'src.gui.widgets.bnim_meter' in sys.modules:
            del sys.modules['src.gui.widgets.bnim_meter']

    def test_process_buffer_silence(self):
        self.meter.start_analysis()
        # buffer is zero by default
        self.meter.process_buffer()
        # neural_map should be all zeros (or close due to eps)
        # log1p(0) = 0
        if self.meter.neural_map is not None:
             self.assertTrue(np.allclose(self.meter.neural_map, 0, atol=1e-5))

    def test_process_buffer_correlated_noise(self):
        self.meter.start_analysis()
        # Create correlated noise
        noise = np.random.normal(0, 0.1, self.meter.fft_size).astype(np.float32)

        # Fill buffer
        with self.meter._buffer_lock:
            self.meter.audio_buffer[-self.meter.fft_size:, 0] = noise
            self.meter.audio_buffer[-self.meter.fft_size:, 1] = noise
            self.meter._buffer_seq += 1

        self.meter.process_buffer()

        # Check neural map
        # Peak should be at ITD = 0 (middle index)
        mid_idx = self.meter.num_itd_bins // 2

        # Check if peak is near center for most frequencies
        # Sum across frequencies to get overall ITD profile
        itd_profile = np.sum(self.meter.neural_map, axis=0)
        peak_idx = np.argmax(itd_profile)

        self.assertTrue(abs(peak_idx - mid_idx) < 5, f"Peak not centered: {peak_idx} vs {mid_idx}")

    def test_process_buffer_delayed_signal(self):
        self.meter.start_analysis()
        sr = 48000
        fft_size = self.meter.fft_size

        # Delay in samples (positive ITD: left delayed relative to right?)
        # Let's check convention.
        # In BNIMMeter:
        # if itd_ms >= 0: left = delayed, right = x
        # So positive ITD means Left is delayed.

        delay_samples = 10
        delay_ms = (delay_samples / sr) * 1000.0 # approx 0.208 ms

        # Create signal where L is delayed relative to R
        # L[t] = s(t - tau)
        # R[t] = s(t)

        sig = np.random.normal(0, 1.0, fft_size + 20).astype(np.float32)

        # R gets signal starting at index 10
        R_data = sig[10 : 10 + fft_size]
        # L gets signal starting at index 0 (which is "earlier" in the source array? No wait)
        # s(t) is at sig[t].
        # L[0] should be s(0 - tau). If tau > 0, we need past history.
        # Let's say s(t) corresponds to index t in sig.
        # R[i] = sig[i + offset]
        # L[i] = sig[i + offset - delay_samples]

        offset = 15
        R_data = sig[offset : offset + fft_size]
        L_data = sig[offset - delay_samples : offset + fft_size - delay_samples]

        with self.meter._buffer_lock:
            self.meter.audio_buffer[-fft_size:, 0] = L_data
            self.meter.audio_buffer[-fft_size:, 1] = R_data
            self.meter._buffer_seq += 1

        self.meter.process_buffer()

        # Find peak
        itd_profile = np.sum(self.meter.neural_map, axis=0)
        peak_idx = np.argmax(itd_profile)

        # Convert index to ms
        itd_axis = self.meter.itd_axis
        measured_itd = itd_axis[peak_idx]

        # We expect peak at +delay_ms because L is delayed.
        # Let's verify sign convention in code:
        # phase_diff = phase_L - phase_R
        # phase_diff_model = -2*pi*f * delay_model
        # coincidence max when phase_diff = phase_diff_model
        # If L is delayed by tau: L(t) = R(t - tau).
        # Fourier: F_L = F_R * exp(-j*w*tau)
        # phase_L = phase_R - w*tau
        # phase_diff = -w*tau.
        # phase_diff_model = -w*delay_model.
        # match when delay_model = tau.
        # delay_model corresponds to itd_axis values.
        # So we expect peak at +tau.

        self.assertTrue(abs(measured_itd - delay_ms) < 0.1,
                        f"Expected ITD ~{delay_ms:.3f} ms, got {measured_itd:.3f} ms")

    def test_process_buffer_ild(self):
        self.meter.start_analysis()
        self.meter.enable_ild = True
        self.meter.ild_strength = 1.0 # Strong ILD effect

        # Create signal where L is much louder than R
        noise = np.random.normal(0, 0.1, self.meter.fft_size).astype(np.float32)
        L_data = noise * 10.0
        R_data = noise * 0.1
        # ILD is positive (L > R).

        with self.meter._buffer_lock:
            self.meter.audio_buffer[-self.meter.fft_size:, 0] = L_data
            self.meter.audio_buffer[-self.meter.fft_size:, 1] = R_data
            self.meter._buffer_seq += 1

        self.meter.process_buffer()

        # Code logic:
        # ild_db > 0.
        # ild_sign > 0.
        # lateral = 1.0 + strength * band_weight * (-itd_norm) * ild_sign.
        # lateral = 1.0 + K * (-itd_norm).
        # if itd_norm is negative (left side), -itd_norm is positive -> lateral > 1.0 (Boost).
        # if itd_norm is positive (right side), -itd_norm is negative -> lateral < 1.0 (Attenuate).
        # So peak should shift towards negative ITD (Left) or negative side should be boosted.

        # Since input has ITD=0 (same noise, just scaled), original peak is at 0.
        # With ILD weighting, left side (negative ITD) is boosted.
        # Right side is attenuated.
        # So center of mass or peak might shift slightly left, or at least left side energy > right side energy.

        # Check energy balance
        mid_idx = self.meter.num_itd_bins // 2
        left_energy = np.sum(self.meter.neural_map[:, :mid_idx])
        right_energy = np.sum(self.meter.neural_map[:, mid_idx:])

        # Expect Left Energy > Right Energy
        self.assertTrue(left_energy > right_energy,
                        f"Expected Left Energy > Right Energy for L > R signal. L={left_energy}, R={right_energy}")
