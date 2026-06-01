import os
import json
import re

# Setup paths
PROJECT_ROOT = "/Users/vach/MeasureLab"
LANG_DIR = os.path.join(PROJECT_ROOT, "src", "assets", "lang")
WHITELIST_PATH = os.path.join(PROJECT_ROOT, "scripts", "translation_whitelist.json")

# Load English keys (Source of Truth)
en_path = os.path.join(LANG_DIR, "en.json")
with open(en_path, "r", encoding="utf-8") as f:
    en_data = json.load(f)

# Load current whitelist
with open(WHITELIST_PATH, "r", encoding="utf-8") as f:
    wl_data = json.load(f)
    exact_whitelist = wl_data.get("exact_keys", [])
    regex_whitelist = [re.compile(p) for p in wl_data.get("regex_patterns", [])]

# Candidate list of keys to remove from whitelist because they are translatable
translatable_candidates = [
    "Amp", "Amp (dBFS)", "Amp Sweep", "Amplitude", "Amplitude:", "Articulation Index",
    "Audio", "Auto", "Azimuth:", "Bode", "Buffer", "Burst", "Compact", "Compensation",
    "Configuration", "Correction", "Delta", "Details", "Diff from target", "Distribution",
    "Done", "Duration", "Error", "Excellent", "Filter", "Filter:", "Follow Cursor",
    "Format:", "Freq", "Freq (Hz)", "Freq Sweep", "Fundamental", "Fundamental Tone",
    "Gain", "Gate", "Gate (dB):", "General", "Generator", "Goniometer", "IDLE",
    "Inductance", "Info", "Integral", "Logs", "Loop", "Loudness Range", "Magnitude",
    "Magnitude (dB)", "Magnitude:", "Manual", "Max", "Min", "Mode", "Modulation",
    "Mono", "None", "None (Instant)", "None (Raw)", "Normal", "Oscilloscope", "Parallel",
    "Pause", "Phase", "Phase:", "Play/Pause", "Rate", "Residual", "Routing", "Scan",
    "Screenshot", "Screenshots", "Secondary Y", "Signal", "Slot", "Solo", "Start",
    "Start (s):", "Start:", "Status", "Stereo", "Stereo (L+R)", "Sweep", "System",
    "Total", "Traces", "Tracks", "Triangle", "Trigger", "Vertical", "Zoom", "Zoom to Selection"
]

# Ensure they are actually in exact_whitelist
translatable_candidates = [k for k in translatable_candidates if k in exact_whitelist]

print(f"Auditing {len(translatable_candidates)} candidate keys for removal from exact_whitelist.")

# Get all language files except en.json
lang_files = [f for f in os.listdir(LANG_DIR) if f.endswith(".json") and f != "en.json"]

results = {}
untranslated_in_any = set()

for lf in sorted(lang_files):
    lang_code = os.path.splitext(lf)[0]
    path = os.path.join(LANG_DIR, lf)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    results[lang_code] = []
    for k in translatable_candidates:
        en_val = en_data.get(k)
        val = data.get(k)
        if val == en_val:
            results[lang_code].append(k)
            untranslated_in_any.add(k)

print("\n--- Summary of Untranslated Keys (where val == en_val) ---")
for lang_code, keys in results.items():
    print(f"{lang_code}: {len(keys)} untranslated keys out of {len(translatable_candidates)}")
    if keys:
        print(f"  First 10: {keys[:10]}")

print(f"\nTotal unique keys that would cause a failure if removed from whitelist: {len(untranslated_in_any)}")
print("List of keys causing failure:")
for k in sorted(untranslated_in_any):
    print(f"  - \"{k}\"")
