import json
import os

PROJECT_ROOT = "/Users/vach/MeasureLab"
WHITELIST_PATH = os.path.join(PROJECT_ROOT, "scripts", "translation_whitelist.json")

# Generic identical keys that must be in the whitelist to prevent false positives in Latin-based languages
LEGITIMATE_IDENTICALS = [
    "Amplitude",
    "Amplitude:",
    "Format:",
    "Fundamental",
    "Integral",
    "Screenshot",
    "Screenshots",
    "Start (s):",
    "Compensation",
    "Configuration",
    "Correction",
    "Distribution",
    "Excellent",
    "Inductance",
    "Triangle"
]

def restore_keys():
    print("--- Restoring legitimate identical keys to translation_whitelist.json ---")
    with open(WHITELIST_PATH, "r", encoding="utf-8") as f:
        wl_data = json.load(f)

    exact_keys = set(wl_data["exact_keys"])
    added = 0
    for k in LEGITIMATE_IDENTICALS:
        if k not in exact_keys:
            exact_keys.add(k)
            added += 1

    wl_data["exact_keys"] = sorted(list(exact_keys))

    print(f"Restored {added} legitimate keys to exact_keys.")

    with open(WHITELIST_PATH, "w", encoding="utf-8") as f:
        json.dump(wl_data, f, ensure_ascii=False, indent=4)
        f.write("\n")
    print("✓ Whitelist updated successfully.")

if __name__ == "__main__":
    restore_keys()
