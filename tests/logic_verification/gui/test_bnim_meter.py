import os
import sys
import numpy as np
import pytest
from unittest.mock import MagicMock

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from src.gui.widgets.bnim_meter import BNIMMeter

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
    def register_callback(self, cb):
        return 1
    def unregister_callback(self, cid):
        pass

def _first_idx_above(x: np.ndarray, thresh: float) -> int:
    idx = np.flatnonzero(np.abs(x) > thresh)
    return int(idx[0]) if idx.size else -1

class TestBNIMProcessing:
    def test_bnim_processing(self):
        engine = MockAudioEngine()
        bnim = BNIMMeter(engine)
        bnim.start_analysis()

        # Generate a stereo signal with 0.4ms delay (ITD)
        fs = 48000
        t = np.arange(bnim.fft_size) / fs
        freq_test = 1000.0

        L = np.sin(2 * np.pi * freq_test * t)
        # Delay by 0.4ms
        R = np.sin(2 * np.pi * freq_test * (t - 0.0004))

        # Fill buffer
        bnim.audio_buffer = np.zeros((bnim.fft_size, 2))
        bnim.audio_buffer[:, 0] = L
        bnim.audio_buffer[:, 1] = R

        # Process
        bnim.process_buffer()

        # Check neural map
        neural_map = bnim.neural_map
        assert neural_map is not None

        # Find peak
        freq_idx = np.argmin(np.abs(bnim.frequencies - 1000.0))
        itd_pattern = neural_map[freq_idx]

        peak_itd_idx = np.argmax(itd_pattern)
        peak_itd_ms = bnim.itd_axis[peak_itd_idx]

        # Alignment (peak) occurs when tau = -delay
        assert abs(peak_itd_ms - (-0.4)) < 0.05

        bnim.stop_analysis()

    def test_bnim_mono(self):
        engine = MockAudioEngine()
        bnim = BNIMMeter(engine)
        bnim.start_analysis()

        # Mono signal (L=R)
        fs = 48000
        t = np.arange(bnim.fft_size) / fs
        L = np.sin(2 * np.pi * 1000.0 * t)
        R = L

        bnim.audio_buffer = np.zeros((bnim.fft_size, 2))
        bnim.audio_buffer[:, 0] = L
        bnim.audio_buffer[:, 1] = R

        bnim.process_buffer()

        freq_idx = np.argmin(np.abs(bnim.frequencies - 1000.0))
        itd_pattern = bnim.neural_map[freq_idx]
        peak_itd_ms = bnim.itd_axis[np.argmax(itd_pattern)]

        # Peak should be at 0ms
        assert abs(peak_itd_ms) < 0.1 # Relaxed slightly for resolution

        bnim.stop_analysis()

    def test_bnim_symmetry(self):
        engine = MockAudioEngine()
        bnim = BNIMMeter(engine)
        bnim.start_analysis()

        # Enable ILD for this test
        bnim.enable_ild = True
        bnim.ild_strength = 0.6
        bnim.decay = 0.0 # Instant update

        # Generate random stereo noise
        np.random.seed(42)
        noise_L = np.random.randn(bnim.fft_size).astype(np.float32)
        noise_R = np.random.randn(bnim.fft_size).astype(np.float32) * 0.5 # Make R quieter to have ILD

        # Pass 1: Normal (L, R)
        with bnim._buffer_lock:
            bnim.audio_buffer[-bnim.fft_size:, 0] = noise_L
            bnim.audio_buffer[-bnim.fft_size:, 1] = noise_R
            bnim._buffer_seq += 1 # Force update

        bnim.process_buffer()
        map_normal = bnim.neural_map.copy()

        # Pass 2: Swapped (R, L)
        with bnim._buffer_lock:
            bnim.audio_buffer[-bnim.fft_size:, 0] = noise_R
            bnim.audio_buffer[-bnim.fft_size:, 1] = noise_L
            bnim._buffer_seq += 1

        bnim.process_buffer()
        map_swapped = bnim.neural_map.copy()

        # Expectation: map_swapped should be horizontal flip of map_normal
        # neural_map shape: (freqs, itd)
        # flip along axis 1 (itd)
        map_normal_flipped = np.fliplr(map_normal)

        diff = np.abs(map_swapped - map_normal_flipped)
        max_diff = np.max(diff)

        assert max_diff < 1e-5, f"Asymmetry detected: {max_diff}"

        bnim.stop_analysis()

    def test_bnim_ild_balance(self):
        """Test that ILD weighting shifts energy balance (extracted from test_bnim_meter_logic.py)."""
        engine = MockAudioEngine()
        bnim = BNIMMeter(engine)
        bnim.start_analysis()
        bnim.enable_ild = True
        bnim.ild_strength = 1.0 # Strong ILD effect
        bnim.decay = 0.0

        # Create signal where L is much louder than R
        # ILD is positive (L > R).
        np.random.seed(123)
        noise = np.random.normal(0, 0.1, bnim.fft_size).astype(np.float32)
        L_data = noise * 10.0
        R_data = noise * 0.1

        with bnim._buffer_lock:
            bnim.audio_buffer[-bnim.fft_size:, 0] = L_data
            bnim.audio_buffer[-bnim.fft_size:, 1] = R_data
            bnim._buffer_seq += 1

        bnim.process_buffer()

        # Check energy balance
        mid_idx = bnim.num_itd_bins // 2
        left_energy = np.sum(bnim.neural_map[:, :mid_idx])
        right_energy = np.sum(bnim.neural_map[:, mid_idx:])

        # Expect Left Energy > Right Energy
        assert left_energy > right_energy, \
            f"Expected Left Energy > Right Energy for L > R signal. L={left_energy}, R={right_energy}"

        bnim.stop_analysis()

class TestBNIMClickPlaySignal:
    def test_bnim_click_play_build_and_callback_delay(self):
        mock_engine = MagicMock()
        mock_engine.sample_rate = 48000
        mock_engine.register_callback.return_value = 1

        m = BNIMMeter(mock_engine)
        m.start_analysis()

        # Trigger a 1kHz burst with +0.8ms ITD (left delayed; should localize to the right)
        m.trigger_click_test_playback(freq_hz=1000.0, itd_ms=0.8, on_cycles=10, off_cycles=900, ild_atten_db=0.0)

        # Pull the registered callback
        args, _ = mock_engine.register_callback.call_args
        cb = args[0]

        frames = 480  # 10 cycles @ 1kHz, 48kHz
        indata = np.zeros((frames, 2), dtype=np.float32)
        outdata = np.zeros((frames, 2), dtype=np.float32)

        cb(indata, outdata, frames, None, None)

        # Should output something (not all zeros)
        assert np.any(np.abs(outdata) > 1e-6)

        # Left should start later than right by ~0.8ms (~38.4 samples)
        left = outdata[:, 0]
        right = outdata[:, 1]

        i_l = _first_idx_above(left, 1e-3)
        i_r = _first_idx_above(right, 1e-3)

        assert i_l >= 0 and i_r >= 0

        expected = 0.8e-3 * 48000
        # Allow a couple samples slack due to thresholding and Hann onset
        assert (i_l - i_r) >= int(expected) - 3


    def test_bnim_click_play_ild_ratio(self):
        mock_engine = MagicMock()
        mock_engine.sample_rate = 48000
        mock_engine.register_callback.return_value = 1

        m = BNIMMeter(mock_engine)
        m.start_analysis()

        # Playback ILD attenuation applies to the ITD-delayed ear.
        # For +ITD, left ear is delayed, so left should be attenuated.
        buf = m.build_click_test_burst(freq_hz=1000.0, itd_ms=0.8, on_cycles=10, off_cycles=0, ild_atten_db=20.0)

        # Choose a region where both channels are active (after the ITD delay).
        delay_samples = int(np.round(0.8e-3 * 48000))
        start = delay_samples + 20
        end = start + 200
        left = buf[start:end, 0]
        right = buf[start:end, 1]

        l_rms = float(np.sqrt(np.mean(left * left)))
        r_rms = float(np.sqrt(np.mean(right * right)))

        assert l_rms > 0
        assert r_rms > 0

        ratio = l_rms / r_rms
        # ~ -20 dB => about 0.1
        assert ratio > 0.06
        assert ratio < 0.16


    def test_bnim_click_play_loop_wraps_within_block(self):
        mock_engine = MagicMock()
        mock_engine.sample_rate = 48000
        mock_engine.register_callback.return_value = 1

        m = BNIMMeter(mock_engine)
        m.start_analysis()
        m.play_loop = True

        # Small buffer: 10 cycles @ 1kHz => ~480 samples (+ small pad)
        m.trigger_click_test_playback(freq_hz=1000.0, itd_ms=0.0, on_cycles=10, off_cycles=0, ild_atten_db=0.0)

        args, _ = mock_engine.register_callback.call_args
        cb = args[0]

        frames = 2000  # larger than buffer length; should wrap
        indata = np.zeros((frames, 2), dtype=np.float32)
        outdata = np.zeros((frames, 2), dtype=np.float32)

        cb(indata, outdata, frames, None, None)

        # In loop mode, we should keep outputting after wrap.
        # The end of the buffer should not be all zeros.
        tail = outdata[-200:, 0]
        assert np.any(np.abs(tail) > 1e-6)


    def test_bnim_click_play_loop_live_update_rebuilds_buffer(self):
        mock_engine = MagicMock()
        mock_engine.sample_rate = 48000
        mock_engine.register_callback.return_value = 1

        m = BNIMMeter(mock_engine)
        m.start_analysis()
        m.play_enable_click = True
        m.play_loop = True

        m.play_on_cycles = 10
        m.play_off_cycles = 0
        m.play_ild_atten_db = 0.0

        m.trigger_click_test_playback(freq_hz=1000.0, itd_ms=0.8, on_cycles=m.play_on_cycles, off_cycles=m.play_off_cycles, ild_atten_db=m.play_ild_atten_db)

        with m._play_lock:
            n0 = len(m._play_buffer)

        # Change off_cycles and refresh; buffer should get longer
        m.play_off_cycles = 900
        m.refresh_click_test_playback_if_looping()

        with m._play_lock:
            n1 = len(m._play_buffer)

        assert n1 > n0

class TestBNIMFractionalDelay:
    """Tests for BNIMMeter._fractional_delay_zero_padded static method."""

    def test_zero_delay(self):
        """Test that delay_samples=0 returns the original array (copy behavior check)."""
        # Case 1: float32 input - should return same object due to copy=False
        x = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
        y = BNIMMeter._fractional_delay_zero_padded(x, 0.0)
        np.testing.assert_array_equal(y, x)
        assert y is x

        # Case 2: float64 input - should return new float32 array
        x64 = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
        y64 = BNIMMeter._fractional_delay_zero_padded(x64, 0.0)
        np.testing.assert_array_equal(y64, x64.astype(np.float32))
        assert y64.dtype == np.float32
        assert y64 is not x64

    def test_integer_delay(self):
        """Test integer delay shifts the signal correctly."""
        x = np.array([10.0, 20.0, 30.0, 40.0], dtype=np.float32)

        # Delay by 1 sample
        y = BNIMMeter._fractional_delay_zero_padded(x, 1.0)
        expected = np.array([0.0, 10.0, 20.0, 30.0], dtype=np.float32)
        np.testing.assert_array_equal(y, expected)

        # Delay by 2 samples
        y2 = BNIMMeter._fractional_delay_zero_padded(x, 2.0)
        expected2 = np.array([0.0, 0.0, 10.0, 20.0], dtype=np.float32)
        np.testing.assert_array_equal(y2, expected2)

    def test_fractional_delay(self):
        """Test fractional delay (0.5) performs linear interpolation."""
        x = np.array([10.0, 20.0, 30.0, 40.0], dtype=np.float32)
        # Delay by 0.5 samples
        # y[1] corresponds to x at index 0.5 -> avg(x[0], x[1]) = 15
        y = BNIMMeter._fractional_delay_zero_padded(x, 0.5)
        expected = np.array([0.0, 15.0, 25.0, 35.0], dtype=np.float32)
        np.testing.assert_array_almost_equal(y, expected, decimal=5)

    def test_fractional_delay_quarter(self):
        """Test fractional delay (0.25)."""
        x = np.array([0.0, 10.0, 20.0], dtype=np.float32)
        # Delay 0.25
        # y[1]: index 0.75 -> (1-0.75)*x[0] + 0.75*x[1] = 0.25*0 + 0.75*10 = 7.5
        # y[2]: index 1.75 -> (1-0.75)*x[1] + 0.75*x[2] = 0.25*10 + 0.75*20 = 2.5 + 15 = 17.5
        y = BNIMMeter._fractional_delay_zero_padded(x, 0.25)
        expected = np.array([0.0, 7.5, 17.5], dtype=np.float32)
        np.testing.assert_array_almost_equal(y, expected, decimal=5)

    def test_large_delay(self):
        """Test delay >= length returns zeros."""
        x = np.array([1.0, 2.0, 3.0], dtype=np.float32)

        # Exactly length
        y = BNIMMeter._fractional_delay_zero_padded(x, 3.0)
        expected = np.zeros_like(x)
        np.testing.assert_array_equal(y, expected)

        # Much larger
        y2 = BNIMMeter._fractional_delay_zero_padded(x, 10.0)
        np.testing.assert_array_equal(y2, expected)

    def test_negative_delay(self):
        """Test negative delay returns original signal (as implemented)."""
        x = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        y = BNIMMeter._fractional_delay_zero_padded(x, -1.0)
        np.testing.assert_array_equal(y, x)
        assert y is x  # float32 optimization check

    def test_empty_input(self):
        """Test empty input returns empty array."""
        x = np.array([], dtype=np.float32)
        y = BNIMMeter._fractional_delay_zero_padded(x, 1.5)
        assert len(y) == 0
        assert y.dtype == np.float32

    def test_dtype_conversion(self):
        """Test that input is converted to float32."""
        x = np.array([1, 2, 3], dtype=np.int32)
        y = BNIMMeter._fractional_delay_zero_padded(x, 0.5)
        assert y.dtype == np.float32

        # x[0]=1, x[1]=2. interp at 0.5 -> 1.5
        # y[0]=0 (padding), y[1]=1.5, y[2]=2.5
        expected = np.array([0.0, 1.5, 2.5], dtype=np.float32)
        np.testing.assert_array_almost_equal(y, expected)
