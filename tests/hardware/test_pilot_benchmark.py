import json
import time
import pytest
from pathlib import Path
from src.core.audio_engine import AudioEngine

# Mark this entire module as hardware tests
pytestmark = pytest.mark.hardware


class TestPilotHardwareBenchmark:
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Setup and teardown for hardware tests."""
        self.engine = AudioEngine()
        yield
        if self.engine.is_active():
            self.engine.stop_stream()

    def load_config(self):
        """Load configuration from config.json."""
        config_path = Path("config.json")
        if not config_path.exists():
            pytest.fail("config.json not found. This test requires a valid config.json in the execution directory.")
        
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_hardware_measurement_loop(self, record_property):
        """
        A pilot hardware measurement loop.
        
        This test:
        1. Loads the configuration.
        2. Initializes the AudioEngine with config values.
        3. Starts the audio stream.
        4. Monitors the stream for a short duration to ensure it's running.
        5. basic assertion to ensure callbacks are being processed.
        """
        config = self.load_config()
        audio_config = config.get("audio", {})
        
        # Apply configuration to the engine
        # Note: In a real scenario, we might want to iterate over available devices
        # or properly map the config strings to device IDs. 
        # For this pilot, we assume the config has valid defaults or the engine finds them.
        
        self.engine.set_sample_rate(audio_config.get("sample_rate", 48000))
        self.engine.set_block_size(audio_config.get("block_size", 1024))
        self.engine.set_channel_mode(
            audio_config.get("input_channels", "stereo"),
            audio_config.get("output_channels", "stereo")
        )
        
        # We explicitly want to use HARDWARE, so disable offline mode
        self.engine.set_offline_mode(False) 
        
        # Define a callback to verify data flow
        callback_data = {"frames_processed": 0, "max_amplitude": 0.0}
        
        def test_callback(indata, outdata, frames, time_info, status):
            callback_data["frames_processed"] += frames
            # Simple pass-through or generation could happen here
            # For this test, just measure input
            import numpy as np
            if indata.size > 0:
                current_max = np.max(np.abs(indata))
                callback_data["max_amplitude"] = max(callback_data["max_amplitude"], current_max)
        
        # Register callback
        cid = self.engine.register_callback(test_callback)
        
        # Wait for stream to stabilize
        time.sleep(0.5)
        
        assert self.engine.is_active(), "Audio engine should be active after registering callback"
        
        # Run benchmark loop
        # We simulate a measurement duration
        measurement_duration = 2.0  # seconds
        time.sleep(measurement_duration)
        
        # Verify functionality
        self.engine.unregister_callback(cid)
        
        # Assertions
        assert callback_data["frames_processed"] > 0, "No frames were processed during the test"
        
        # Record properties for JSON report instead of printing
        cpu_load = self.engine.stream.cpu_load if self.engine.stream else 'N/A'
        
        record_property("frames_processed", callback_data["frames_processed"])
        record_property("max_amplitude", callback_data["max_amplitude"])
        record_property("cpu_load", cpu_load)
