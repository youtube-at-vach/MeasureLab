import sys
import re

files = [
"tests/logic_verification/core/test_audio_engine_logic.py",
"tests/logic_verification/core/test_virtual_stream_dummy_time.py",
"tests/logic_verification/core/test_virtual_stream_timing.py",
"tests/logic_verification/generators/test_signal_generator_logic.py",
"tests/logic_verification/generators/test_signal_generator_multitone.py",
"tests/logic_verification/instruments/test_advanced_distortion_meter_mim.py",
"tests/logic_verification/instruments/test_distortion_analyzer_worker.py",
"tests/logic_verification/instruments/test_impedance_analyzer_dynamic_buffer.py",
"tests/logic_verification/instruments/test_linearity_analyzer_logic.py",
"tests/logic_verification/instruments/test_linearity_buffer_optimization.py",
"tests/logic_verification/instruments/test_lockin_amplifier_logic.py",
"tests/logic_verification/instruments/test_spectrum_analyzer_logic.py",
"tests/logic_verification/recorder/test_recorder_player_logic.py",
]

for f in files:
    try:
        with open(f, 'r') as fh:
            lines = fh.readlines()
            for i, line in enumerate(lines):
                if "sys.modules" in line and "sounddevice" in line and "MagicMock" in line:
                    if not line.startswith(" ") and not line.startswith("\t"): # Top level
                        print(f"{f}:{i+1}: {line.strip()}")
    except FileNotFoundError:
        pass
