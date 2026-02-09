import time
import numpy as np
from src.core.audio_engine import AudioEngine
from src.core.config_manager import ConfigManager

def test_offline_mode(tmp_path):
    config_file = tmp_path / "test_config.json"
    config = ConfigManager(str(config_file))

    # Force offline mode in config
    config.set_offline_mode(True)
    config.set_offline_sample_rate(44100)

    engine = AudioEngine()
    engine.set_offline_mode(config.is_offline_mode())
    engine.set_sample_rate(config.get_offline_sample_rate())

    # Start stream by registering a callback that checks for input
    output_signal_gen = False
    input_signal_detected = False

    def signal_checker_callback(indata, outdata, frames, time, status):
        nonlocal input_signal_detected, output_signal_gen
        # Generate some noise on output
        noise = np.random.uniform(-0.1, 0.1, (frames, outdata.shape[1])).astype(np.float32)
        outdata[:] = noise
        output_signal_gen = True

        # Check if input has signal (loopback)
        if np.max(np.abs(indata)) > 0.001:
            input_signal_detected = True

    cid = engine.register_callback(signal_checker_callback)

    # Wait for a few blocks
    # We loop briefly to allow callback to fire
    start_time = time.time()
    while time.time() - start_time < 2.0:
        if output_signal_gen and input_signal_detected:
            break
        time.sleep(0.1)

    status = engine.get_status()

    engine.unregister_callback(cid)
    engine.set_offline_mode(False)

    assert status["offline_mode"], "Engine is not in offline mode!"
    assert output_signal_gen, "Callback was never called (no output generated)."
    assert input_signal_detected, "No signal detected on input! Loopback might be missing."
