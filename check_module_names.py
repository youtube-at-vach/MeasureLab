import json
import os

keys_to_check = [
    "Recorder & Player",
    "Oscilloscope",
    "LUFS & Level Meter",
    "Lock-in THD+N",
    "Spectrogram",
    "HRTF Player",
    "Signal Generator",
    "Boxcar Averager",
    "Loopback Finder",
    "Raw Time Series",
    "Inverse Filter",
    "Sound Level Meter",
    "Lock-in Amplifier",
    "Goniometer",
    "Transient Analyzer",
    "BNIM Meter",
    "Network Analyzer",
    "Frequency Counter",
    "Advanced Distortion Meter",
    "Sound Quality Analyzer",
    "Spectrum Analyzer",
    "Distortion Analyzer"
]

with open('src/assets/lang/en.json', 'r') as f:
    en_data = json.load(f)

missing = []
for k in keys_to_check:
    if k not in en_data:
        missing.append(k)

if missing:
    print("Missing keys in en.json:")
    for k in missing:
        print(f"  - {k}")
else:
    print("All module names found in en.json")
