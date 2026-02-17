import sys
import re

files = [
"tests/logic_verification/core/test_virtual_stream_dummy_time.py",
"tests/logic_verification/generators/test_signal_generator_logic.py",
"tests/logic_verification/generators/test_signal_generator_multitone.py",
"tests/logic_verification/instruments/test_advanced_distortion_meter_mim.py",
"tests/logic_verification/instruments/test_distortion_analyzer_worker.py",
"tests/logic_verification/instruments/test_impedance_analyzer_dynamic_buffer.py",
"tests/logic_verification/instruments/test_lockin_amplifier_logic.py",
"tests/logic_verification/recorder/test_recorder_player_logic.py",
]

for f in files:
    try:
        with open(f, 'r') as fh:
            lines = fh.readlines()

        new_lines = []
        modified = False
        for line in lines:
            if "sys.modules" in line and "sounddevice" in line and "MagicMock" in line:
                if not line.startswith(" ") and not line.startswith("\t"): # Top level
                    print(f"Removing from {f}: {line.strip()}")
                    modified = True
                    continue
            new_lines.append(line)

        if modified:
            with open(f, 'w') as fh:
                fh.writelines(new_lines)

    except FileNotFoundError:
        print(f"File not found: {f}")
