import os
import sys

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.core.config_manager import ConfigManager


def test_config_persistence():
    config_path = "test_config.json"

    # Clean up previous test
    if os.path.exists(config_path):
        os.remove(config_path)

    print("Initializing ConfigManager...")
    cm = ConfigManager(config_path)

    print("Checking default values...")
    audio = cm.get_audio_config()
    in_dev = audio.get("input_device")
    out_dev = audio.get("output_device")
    if in_dev is not None or out_dev is not None:
        print("FAILED: Default devices should be None")
        return

    print("Setting devices...")
    audio = cm.get_audio_config()
    cm.set_audio_config(
        input_name="My Mic",
        output_name="My Speaker",
        sample_rate=audio.get("sample_rate", 48000),
        block_size=audio.get("block_size", 1024),
        in_ch=audio.get("input_channels", "stereo"),
        out_ch=audio.get("output_channels", "stereo"),
    )

    print("Verifying in-memory update...")
    audio = cm.get_audio_config()
    in_dev = audio.get("input_device")
    out_dev = audio.get("output_device")
    if in_dev != "My Mic" or out_dev != "My Speaker":
        print(f"FAILED: In-memory update failed. Got {in_dev}, {out_dev}")
        return

    # Flush pending writes
    print("Flushing config...")
    cm.shutdown()

    print("Verifying file persistence...")
    # Create new instance to load from file
    cm2 = ConfigManager(config_path)
    audio2 = cm2.get_audio_config()
    in_dev = audio2.get("input_device")
    out_dev = audio2.get("output_device")
    if in_dev != "My Mic" or out_dev != "My Speaker":
        print(f"FAILED: File persistence failed. Got {in_dev}, {out_dev}")
        return

    print("Cleaning up...")
    if os.path.exists(config_path):
        os.remove(config_path)

    print("Test Complete.")

if __name__ == "__main__":
    test_config_persistence()
