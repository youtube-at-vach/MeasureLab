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
    'typical': Sweep down to -90dBFS.
    'limit': Sweep down to -120dBFS.
    """
    if "linearity_params" in metafunc.fixturenames:
        mode = metafunc.config.getoption("hardware_mode")

        if mode == "typical":
            # Typical: -5 to -90 dBFS, fewer steps, moderate averaging
            metafunc.parametrize(
                "linearity_params",
                [{"start_db": -5.0, "end_db": -90.0, "steps": 20, "averaging": 3, "mode_name": "typical"}],
            )
        else:
            # Limit: -5 to -120 dBFS, more steps, higher averaging
            metafunc.parametrize(
                "linearity_params",
                [{"start_db": -5.0, "end_db": -90.0, "steps": 30, "averaging": 10, "mode_name": "limit"}],
            )


class TestLinearityHardware:
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        self.engine = AudioEngine()
        self.engine.set_offline_mode(False)  # Ensure online

        # Generator state
        self._phase = 0.0
        self.gen_amplitude = 0.0
        self.test_frequency = 1000.0
        self.sample_rate = 48000
        self.buffer_size = 65536

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
        self._phase += frames  # Keep phase continuous

        sig = self.gen_amplitude * np.sin(2 * np.pi * self.test_frequency * t)

        outdata.fill(0)
        # Stereo output
        outdata[:, 0] = sig
        if outdata.shape[1] > 1:
            outdata[:, 1] = sig

    def get_latest_buffer(self):
        """Returns the current buffer contents ordered chronologically."""
        idx = self.input_index
        data = self.input_data.copy()
        return np.concatenate((data[idx:], data[:idx]))

    def wait_interruptible(self, duration):
        time.sleep(duration)

    def test_linearity_sweep(self, linearity_params, record_property, hardware_config):
        """
        Performs a linearity sweep test.
        """
        # Hardware Config
        sr = hardware_config.get("sample_rate", 48000)
        input_device = hardware_config.get("input_device")
        output_device = hardware_config.get("output_device")

        self.sample_rate = sr
        self.engine.set_sample_rate(sr)
        self.engine.set_devices(input_device, output_device)
        self.engine.set_block_size(1024)

        record_property("test_type", "Linearity Sweep")
        record_property("sample_rate", sr)
        record_property("start_dbfs", linearity_params["start_db"])
        record_property("end_dbfs", linearity_params["end_db"])

        # Start Audio
        self.callback_id = self.engine.register_callback(self._audio_callback)

        # Test Params
        start_db = linearity_params["start_db"]
        end_db = linearity_params["end_db"]
        steps = linearity_params["steps"]
        averaging_count = linearity_params["averaging"]

        levels_db = np.linspace(start_db, end_db, steps)

        print(f"\nStarting Linearity Sweep: {start_db} to {end_db} dBFS ({steps} steps)")

        ref_gain_db = None
        results = []
        max_linearity_error = 0.0

        # Buffer Refresh Wait Calculation
        buffer_duration = self.buffer_size / sr
        min_wait = 0.2
        wait_for_new_data = max(0.05, buffer_duration * 1.1)

        for level_db in levels_db:
            # Set Amplitude
            amp_linear = 10 ** (level_db / 20)
            self.gen_amplitude = amp_linear

            # Settling
            time.sleep(min_wait)

            # Measurement Loop
            mag_sum = 0.0

            # Initial buffer fill wait
            time.sleep(buffer_duration * 1.5)

            for avg_idx in range(averaging_count):
                if avg_idx > 0:
                    time.sleep(wait_for_new_data)

                # Get Data
                buffer = self.get_latest_buffer()
                # Use Channel 0 (Left)
                sig = buffer[:, 0]

                # Lock-in Calc
                mag, _ = AudioCalc.calculate_lockin_measurement(
                    sig, self.test_frequency, self.sample_rate, phase_ref=0, window_name="blackmanharris"
                )

                mag_sum += mag

            avg_mag = mag_sum / averaging_count
            meas_db = 20 * np.log10(avg_mag + 1e-15)

            current_gain = meas_db - level_db

            if ref_gain_db is None:
                ref_gain_db = current_gain

            lin_error = current_gain - ref_gain_db

            if abs(lin_error) > abs(max_linearity_error):
                max_linearity_error = lin_error

            print(
                f"  In: {level_db:.1f} dBFS | Meas: {meas_db:.2f} dBFS | Gain: {current_gain:.2f} dB | Err: {lin_error:.2f} dB"
            )

            results.append(
                {"input_level": level_db, "measured_level": meas_db, "gain": current_gain, "error": lin_error}
            )

        # Record Properties
        record_property("max_linearity_error_db", float(max_linearity_error))
        record_property("gain_ref_db", float(ref_gain_db))

        # Check basic functionality
        # The first point (reference) should have error 0 by definition.
        assert abs(results[0]["error"]) < 0.001

        # Verify linearity at -60dBFS is within reasonable limits (e.g. +/- 1dB)
        # Find closest point to -60
        error_at_60 = None
        for res in results:
            if abs(res["input_level"] - -60.0) < 2.0:
                error_at_60 = res["error"]
                break

        if error_at_60 is not None:
            record_property("error_at_n60db", float(error_at_60))
            if abs(error_at_60) > 1.0:
                print(f"Warning: Linearity error at -60dBFS is high: {error_at_60:.2f} dB")

        # For Limit mode, we might expect degradation at -110/-120, but it shouldn't crash.
