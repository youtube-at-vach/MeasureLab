import sys
import time
import logging

# Ensure we can import src
sys.path.append("/Users/vach/MeasureLab")

# Setup clean basic logging to stdout
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test_transmission_live")

from src.core.audio_engine import AudioEngine  # noqa: E402
from src.gui.widgets.transmission_analyzer import TransmissionAnalyzer  # noqa: E402


def run_live_test():
    logger.info("Initializing AudioEngine...")
    engine = AudioEngine()

    # Configure ZOOM UAC-232 (Index 3)
    # ZOOM UAC-232 has 2 input channels, 2 output channels.
    engine.set_devices(input_device_id=3, output_device_id=3)
    engine.set_sample_rate(48000)
    engine.set_block_size(1024)
    engine.set_channel_mode("stereo", "stereo")

    logger.info("Initializing TransmissionAnalyzer...")
    analyzer = TransmissionAnalyzer(engine)

    # We will test Analog Mode because user mentioned analog loopback / ZOOM UAC-232 physical loopback.
    analyzer.mode = "Analog"
    analyzer.pattern_mode = "PRBS-15"
    analyzer.bit_depth = 24
    analyzer.input_channel_idx = 0  # Left Channel

    logger.info("Starting analysis...")
    analyzer.start_analysis()

    logger.info("Running real-time processing loop for 30 seconds...")
    try:
        start_time = time.time()
        step = 0
        while time.time() - start_time < 30.0:
            time.sleep(0.2)  # Process at 5Hz just like the UI QTimer
            step += 1

            res = analyzer.process_data()
            if res is not None:
                logger.info(
                    f"Step {step:03d} | Locked: {res['locked']} | "
                    f"Delay: {res.get('delay_samples', 0)} samples ({res.get('delay_ms', 0.0):.2f} ms) | "
                    f"Jitter: {res.get('jitter_samples', 0.0):+.3f} samples | "
                    f"EVM: {res.get('evm', 0.0):.3f} % | "
                    f"Crosstalk: {res.get('crosstalk_db', -120.0):.1f} dB | "
                    f"Reason: {res.get('reason')}"
                )
            else:
                # None means not enough samples or lost lock
                logger.info(f"Step {step:03d} | Locked: {analyzer.is_locked} | Reason: {analyzer.results['reason']}")
    except KeyboardInterrupt:
        logger.info("Test interrupted by user.")
    finally:
        logger.info("Stopping analysis...")
        analyzer.stop_analysis()
        engine.stop_stream()
        logger.info("Done.")


if __name__ == "__main__":
    run_live_test()
