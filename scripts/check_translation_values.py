#!/usr/bin/env python3
"""
Script to check for potential translation leaks (untranslated values) in language files.
This complements check_trn_keys.py by verifying the *content* of translations, not just the keys.
"""

import glob
import os
import sys

from translation_utils import LANG_DIR, load_json


def main():
    print("=== Translation Content Check (Value Verification) ===\n")

    json_files = glob.glob(os.path.join(LANG_DIR, "*.json"))
    has_error = False

    # Technical terms or common untranslated strings to ignore in warnings
    # These are valid to be identical in many languages (e.g. units, acronyms)
    IGNORED_IDENTICALS = {
        # Units
        "Hz", "kHz", "MHz", "dB", "dBFS", "dBV", "dBu", "V", "mV", "FS",
        "s", "ms", "μs", "ns", "%", "ppm", "deg", "Ω",

        # Modulation / Signals
        "AM", "FM", "PM", "ΦM", "DSB", "SSB", "LSB", "USB", "LO", "CW",
        "SINAD", "THD", "THD+N", "IMD", "SNR", "ENOB", "SFDR",
        "RMS", "Pk", "pp", "CF", "Lp", "Leq", "SEL", "SPL", "dB SPL",
        "LUFS", "LUFS (M)", "LUFS (S)", "LUFS (I)",
        "SMPTE", "CCIF", "DIN", "ISO", "IEC", "ITU-R", "EBU",
        "1/f", "White", "Pink", "Brown",

        # Hardware / Software
        "CPU", "RAM", "GPU", "OS", "GUI", "API", "ASIO", "WASAPI", "ALSA", "JACK",
        "PCI", "LAN", "IP", "TCP", "UDP",
        "1 PPS", "10 MHz", "NCO", "DDS", "DAC", "ADC", "FPGA", "DSP",
        "FIR", "IIR", "SOS", "FFT", "DFT", "PDF", "CDF",
        "L", "R", "M", "S", "X", "Y", "Z", "I", "Q",
        "CH1", "CH2", "Ch 1", "Ch 2", "Ch 1 (L)", "Ch 2 (R)",
        "Stereo", "Mono", "Left", "Right", "Mid", "Side",
        "Input", "Output", "I/O", "Ref", "Meas", "Trig", "Gate",

        # UI Common
        "OK", "Cancel", "Apply", "Reset", "Save", "Load", "Import", "Export",
        "Start", "Stop", "Pause", "Resume", "Run", "Ready", "Idle", "Busy",
        "Error", "Warning", "Info", "System", "Settings", "Help", "About",
        "Name", "Value", "Type", "Mode", "Status", "Time", "Date",
        "Min", "Max", "Avg", "Mean", "Std Dev", "Count", "Rate", "Speed",
        "Gain", "Phase", "Freq", "Level", "Offset", "Delay", "Width", "Depth",
        "Buffer", "Sample Rate", "Bit Depth", "Channels",
        "General", "Audio", "Appearance", "Language", "Theme",
        "Dark", "Light", "Auto", "Manual", "Custom", "Default",
        "N/A", "-", "--", "---", "..."
    }

    # Dynamic heuristics for valid identicals
    # - Starts with '{' (format string)
    # - Is a number or simple symbol
    # - Is short upper case (Acronym)

    for jf in sorted(json_files):
        fname = os.path.basename(jf)
        if fname == 'en.json':
            continue

        try:
            data = load_json(jf)
        except Exception as e:
            print(f"Error loading {fname}: {e}")
            has_error = True
            continue

        empty_values = []
        identical_values = []

        for k, v in data.items():
            # Check for empty values (Critical)
            # Skip empty key "" if it maps to empty value "" (placeholder)
            if v == "" and k != "":
                empty_values.append(k)

            # Check for identical values (Warning)
            if k == v:
                # Filter out known ignored terms
                if k in IGNORED_IDENTICALS:
                    continue

                # Heuristic: Format strings
                if k.startswith("{") or "{" in k:
                    continue

                # Heuristic: Numbers and symbols
                clean_k = k.replace(".", "").replace("-", "").replace(":", "").replace(" ", "").replace("/", "")
                if clean_k.isdigit():
                    continue

                # Heuristic: Short acronyms (upto 4 chars)
                if len(k) <= 4 and k.isupper():
                    continue

                # Heuristic: Ends with colon (common in forms) -> check if base word is ignored
                if k.endswith(":") and k[:-1] in IGNORED_IDENTICALS:
                    continue

                identical_values.append(k)

        if empty_values:
            print(f"FAIL: {fname} has {len(empty_values)} EMPTY values (Missing Translation):")
            for k in empty_values:
                print(f"  - \"{k}\"")
            has_error = True

        if identical_values:
            print(f"WARNING: {fname} has {len(identical_values)} potentially untranslated values (Key == Value):")
            for k in identical_values[:10]:
                print(f"  - \"{k}\"")
            if len(identical_values) > 10:
                print(f"  ... and {len(identical_values)-10} more.")

        if not empty_values and not identical_values:
            print(f"OK: {fname}")
        elif not empty_values:
            print(f"PASS (with warnings): {fname}")
        print("-" * 40)

    print("\n=== Result ===")
    if has_error:
        print("TEST FAILED: Critical translation issues found.")
        sys.exit(1)
    else:
        print("TEST PASSED: No critical issues found.")
        sys.exit(0)

if __name__ == "__main__":
    main()
