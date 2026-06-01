import os
import json

PROJECT_ROOT = "/Users/vach/MeasureLab"
JA_PATH = os.path.join(PROJECT_ROOT, "src", "assets", "lang", "ja.json")
EN_PATH = os.path.join(PROJECT_ROOT, "src", "assets", "lang", "en.json")

with open(JA_PATH, "r", encoding="utf-8") as f:
    ja_data = json.load(f)

with open(EN_PATH, "r", encoding="utf-8") as f:
    en_data = json.load(f)

keys = [
    "Amp",
    "Amp (dBFS)",
    "Amp Sweep",
    "Amplitude",
    "Amplitude:",
    "Articulation Index",
    "Audio",
    "Auto",
    "Azimuth:",
    "Bode",
    "Buffer",
    "Burst",
    "Compact",
    "Compensation",
    "Configuration",
    "Correction",
    "Delta",
    "Details",
    "Diff from target",
    "Distribution",
    "Done",
    "Duration",
    "Error",
    "Excellent",
    "Filter",
    "Filter:",
    "Follow Cursor",
    "Format:",
    "Freq",
    "Freq (Hz)",
    "Freq Sweep",
    "Fundamental",
    "Fundamental Tone",
    "Gain",
    "Gate",
    "Gate (dB):",
    "General",
    "Generator",
    "Goniometer",
    "Inductance",
    "Info",
    "Integral",
    "Logs",
    "Loop",
    "Loudness Range",
    "Magnitude",
    "Magnitude (dB)",
    "Magnitude:",
    "Manual",
    "Max",
    "Min",
    "Mode",
    "Modulation",
    "Mono",
    "None",
    "None (Instant)",
    "None (Raw)",
    "Normal",
    "Oscilloscope",
    "Parallel",
    "Pause",
    "Phase",
    "Phase:",
    "Play/Pause",
    "Rate",
    "Residual",
    "Routing",
    "Scan",
    "Screenshot",
    "Screenshots",
    "Secondary Y",
    "Signal",
    "Slot",
    "Solo",
    "Start",
    "Start (s):",
    "Start:",
    "Status",
    "Stereo",
    "Stereo (L+R)",
    "Sweep",
    "System",
    "Total",
    "Traces",
    "Tracks",
    "Triangle",
    "Trigger",
    "Vertical",
    "Zoom",
    "Zoom to Selection",
]

print(f"{'Key':<30} | {'EN Value':<30} | {'JA Translation'}")
print("-" * 90)
for k in keys:
    en_val = en_data.get(k, "(not found)")
    ja_val = ja_data.get(k, "(not found)")
    print(f"{k:<30} | {en_val:<30} | {ja_val}")
