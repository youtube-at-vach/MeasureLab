import time
import pytest
import numpy as np
import logging
from src.core.audio_engine import AudioEngine
from src.core.analysis import AudioCalc

# Mark entire module as hardware tests
pytestmark = pytest.mark.hardware

logger = logging.getLogger(__name__)

def pytest_generate_tests(metafunc):
    """
    Generate test cases based on --hardware-mode option.
    'typical': 1kHz only.
    'limit': 100Hz, 1kHz, 10kHz.
    """
    if "crosstalk_params" in metafunc.fixturenames:
        mode = metafunc.config.getoption("hardware_mode")

        if mode == "typical":
            # Typical: 1kHz
            metafunc.parametrize("crosstalk_params", [
                {"freq": 1000.0, "name": "1kHz"}
            ])
        else:
            # Limit: 100Hz, 1kHz, 10kHz
            metafunc.parametrize("crosstalk_params", [
                {"freq": 100.0, "name": "100Hz"},
                {"freq": 1000.0, "name": "1kHz"},
                {"freq": 10000.0, "name": "10kHz"}
            ])

class TestCrosstalkHardware:
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        self.engine = AudioEngine()
        self.engine.set_offline_mode(False) # Ensure online

        # Generator state
        self._phase = 0.0
        self.gen_amplitude = 0.0
        self.test_frequency = 1000.0
        self.sample_rate = 48000
        self.buffer_size = 65536

        self.active_channel = 0 # 0=Left, 1=Right

        # Input buffer
        self.input_data = np.zeros((self.buffer_size, 2))
        self.input_index = 0

        self.callback_id = None

        yield

        # Teardown
        if self.callback_id is not None:
            self.engine.unregister_callback(self.callback_id)

        if self.engine.is_active():
            self.engine.stop_stream()

    def _audio_callback(self, indata, outdata, frames, time_info, status):
        # Input Capture
        new_data = None
        if indata.shape[1] >= 2:
            new_data = indata[:, :2]
        elif indata.shape[1] == 1:
            new_data = np.repeat(indata, 2, axis=1)

        if new_data is not None:
            new_frames = len(new_data)
            if new_frames >= self.buffer_size:
                 self.input_data[:] = new_data[-self.buffer_size :]
                 self.input_index = 0
            else:
                remaining = self.buffer_size - self.input_index
                if new_frames <= remaining:
                    self.input_data[self.input_index : self.input_index + new_frames] = new_data
                    self.input_index += new_frames
                else:
                    self.input_data[self.input_index :] = new_data[:remaining]
                    self.input_data[: (new_frames - remaining)] = new_data[remaining:]
                    self.input_index = new_frames - remaining

                if self.input_index >= self.buffer_size:
                    self.input_index = 0

        # Output Generation
        t = (np.arange(frames) + self._phase) / self.sample_rate
        self._phase += frames # Keep phase continuous

        sig = self.gen_amplitude * np.sin(2 * np.pi * self.test_frequency * t)

        outdata.fill(0)
        # Output to active channel only
        if self.active_channel < outdata.shape[1]:
            outdata[:, self.active_channel] = sig

    def get_latest_buffer(self):
        """Returns the current buffer contents ordered chronologically."""
        idx = self.input_index
        data = self.input_data.copy()
        return np.concatenate((data[idx:], data[:idx]))

    def test_crosstalk(self, crosstalk_params, record_property, hardware_config):
        """
        Performs a crosstalk test using lock-in measurement.
        """
        # Hardware Config
        sr = hardware_config.get("sample_rate", 48000)
        input_device = hardware_config.get("input_device")
        output_device = hardware_config.get("output_device")

        self.sample_rate = sr
        self.engine.set_sample_rate(sr)
        self.engine.set_devices(input_device, output_device)
        self.engine.set_block_size(1024)

        test_freq = crosstalk_params["freq"]
        self.test_frequency = test_freq

        record_property("test_type", "Crosstalk")
        record_property("sample_rate", sr)
        record_property("frequency_hz", test_freq)

        # Start Audio
        self.callback_id = self.engine.register_callback(self._audio_callback)

        # Test Params
        # -6 dBFS output
        output_level_db = -6.0
        self.gen_amplitude = 10 ** (output_level_db / 20)

        # Averaging
        averaging_count = 5

        print(f"\nStarting Crosstalk Test: {test_freq} Hz @ {output_level_db} dBFS")

        channels = [0, 1] # Left, Right
        results = {}

        # Buffer Refresh Wait Calculation
        buffer_duration = self.buffer_size / sr
        wait_for_new_data = max(0.05, buffer_duration * 1.1)

        for source_ch in channels:
            target_ch = 1 - source_ch # The other channel

            # Set Active Channel
            self.active_channel = source_ch

            # Settling Time
            time.sleep(0.5)

            # Measurement Loop
            mag_sum = 0.0

            # Initial buffer fill wait
            time.sleep(buffer_duration * 1.5)

            for avg_idx in range(averaging_count):
                if avg_idx > 0:
                    time.sleep(wait_for_new_data)

                # Get Data
                buffer = self.get_latest_buffer()

                # Analyze Target Channel (Silent one)
                sig = buffer[:, target_ch]

                # Lock-in Calc
                mag, _ = AudioCalc.calculate_lockin_measurement(
                    sig, self.test_frequency, self.sample_rate, phase_ref=0, window_name="blackmanharris"
                )

                mag_sum += mag

            avg_mag = mag_sum / averaging_count
            crosstalk_db = 20 * np.log10(avg_mag + 1e-15)

            # Relative to output level? Usually crosstalk is absolute level or relative to source level.
            # "Crosstalk" usually implies "Signal on Victim / Signal on Source".
            # Since Source is at -6dBFS, we should probably report relative crosstalk (separation) or absolute level.
            # User said "-100dBFS inputs obtained", implying absolute level.
            # I will report absolute level.

            ch_names = ["L", "R"]
            label = f"{ch_names[source_ch]}->{ch_names[target_ch]}"

            print(f"  {label}: {crosstalk_db:.2f} dBFS")

            results[label] = crosstalk_db
            record_property(f"crosstalk_{label}_db", float(crosstalk_db))

        # Assertions / checking
        # Check if crosstalk is reasonably low.
        # User expects ~ -100dBFS.
        # Verify it's better than -40dBFS (safety margin against complete failure/wiring error).

        max_crosstalk = max(results.values())
        if max_crosstalk > -40.0:
            pytest.fail(f"Crosstalk too high! Max: {max_crosstalk:.2f} dBFS")

        if max_crosstalk > -80.0:
            print(f"Warning: Crosstalk is higher than expected (-80dBFS limit). Max: {max_crosstalk:.2f} dBFS")
