import pytest
from src.core.audio_engine import AudioEngine

# Mark entire module as hardware tests
pytestmark = pytest.mark.hardware

def test_system_configuration(record_property, hardware_config):
    """
    Logs common hardware configuration to the report.
    This test serves as a header/info section for the hardware test suite.
    """
    # Load config
    sr = hardware_config.get("sample_rate", 48000)
    input_device = hardware_config.get("input_device", "system")
    output_device = hardware_config.get("output_device", "system")
    block_size = hardware_config.get("block_size", 1024)
    
    # Try to get more info from AudioEngine if possible
    # We instantiate it briefly to query devices if needed, 
    # but here we just log what is configured.
    
    # Log Properties
    record_property("test_type", "System Configuration")
    record_property("conf_sample_rate", sr)
    record_property("conf_input_device", input_device)
    record_property("conf_output_device", output_device)
    record_property("conf_block_size", block_size)
    
    # Optional: Log Host API if we can deduce it or if it's in config
    # For now, just the basics requested.
    
    print(f"\nSystem Configuration:")
    print(f"  Sample Rate:   {sr}")
    print(f"  Input Device:  {input_device}")
    print(f"  Output Device: {output_device}")
    print(f"  Block Size:    {block_size}")
