import sys
import threading
from unittest.mock import MagicMock

# Mock unavailable modules for headless testing
sys.modules['PyQt6.QtWidgets'] = MagicMock()
sys.modules['PyQt6.QtCore'] = MagicMock()
sys.modules['src.core.calibration'] = MagicMock()

# Now import the class to test
from src.core.audio_engine import AudioEngine
import sounddevice as sd

def test_audio_engine_sr_detection():
    print("Initializing AudioEngine...")
    engine = AudioEngine()
    
    # Get valid devices (using the ones we verified earlier)
    # 18: default, 19: system (JACK/PipeWire)
    
    input_dev = 18
    output_dev = 18
    
    print(f"Testing with input={input_dev}, output={output_dev}")
    rates = engine.get_supported_sample_rates(input_dev, output_dev)
    print(f"Supported rates for device pair {input_dev},{output_dev}: {rates}")
    
    if 48000 in rates:
        print("SUCCESS: 48000 is supported as expected.")
    else:
        print("FAILURE: 48000 should be supported.")

    # Test with JACK/PipeWire if available
    jack_dev = 19
    print(f"\nTesting with input={jack_dev}, output={jack_dev}")
    rates_jack = engine.get_supported_sample_rates(jack_dev, jack_dev)
    print(f"Supported rates for device pair {jack_dev},{jack_dev}: {rates_jack}")
    
    if 192000 in rates_jack:
        print("SUCCESS: 192000 is supported on JACK/PipeWire as expected.")
    else:
        print("FAILURE: 192000 should be supported on JACK/PipeWire.")

if __name__ == "__main__":
    test_audio_engine_sr_detection()
