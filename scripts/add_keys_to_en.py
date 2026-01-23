import json
import os

filepath = 'src/assets/lang/en.json'

with open(filepath, 'r', encoding='utf-8') as f:
    data = json.load(f)

new_keys = [
    "Recorder & Player",
    "LUFS & Level Meter",
    "Lock-in THD+N",
    "{0} dBFS",
    "{0} dBV",
    "{0} dBu",
    "{0} V",
    "{0} mV",
    "{0} FS",
    "{0} deg"
]

for key in new_keys:
    if key not in data:
        data[key] = key
        print(f"Added: {key}")
    else:
        print(f"Exists: {key}")

with open(filepath, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=4)
    f.write('\n')
