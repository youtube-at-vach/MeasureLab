#!/usr/bin/env python3
"""
Script to automatically update translation files with missing keys.
This script adds missing keys from the check_trn_keys.py output to all language files.
"""

import json
import os

# Configuration
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG_DIR = os.path.join(PROJECT_ROOT, "src", "assets", "lang")

# Missing keys in en.json (from check_trn_keys.py output)
MISSING_EN_KEYS = [
    "Bit Depth & Quantization Analysis",
    "ENOB: -- bits",
    "Measure Bit Depth...",
    "Quantization Step (Delta) Distribution",
    "Time (Frames)"
]

# Keys to remove (unused in code)
UNUSED_KEYS = [
    "Bit Depth Analyzer",
    "Log Time",
    "Quantization Step Distribution"
]

# Missing keys in other language files (de, es, fr, ja, ko, pt, ru, zh)
MISSING_OTHER_KEYS = MISSING_EN_KEYS

def load_json(path):
    """Load JSON file preserving order"""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    """Save JSON file with proper formatting"""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.write('\n')  # Add trailing newline

def update_en_json():
    """Add missing keys to en.json and remove unused ones"""
    en_path = os.path.join(LANG_DIR, 'en.json')
    print(f"Updating {en_path}...")

    data = load_json(en_path)
    added = 0
    removed = 0

    # Add missing
    for key in MISSING_EN_KEYS:
        if key not in data:
            data[key] = key  # For English, key = value
            added += 1
            print(f"  Added: '{key}'")

    # Remove unused
    for key in UNUSED_KEYS:
        if key in data:
            del data[key]
            removed += 1
            print(f"  Removed: '{key}'")

    if added > 0 or removed > 0:
        save_json(en_path, data)
        print(f"✓ Added {added} keys, removed {removed} keys in en.json")
    else:
        print("✓ No changes needed for en.json")

    return added, removed

def update_other_lang_files():
    """Add missing keys and remove unused keys in other language files"""
    lang_files = ['de.json', 'es.json', 'fr.json', 'ja.json', 'ko.json', 'pt.json', 'ru.json', 'zh.json']

    # Load en.json to get all current keys
    en_path = os.path.join(LANG_DIR, 'en.json')
    en_data = load_json(en_path)

    total_added = 0
    total_removed = 0

    for lang_file in lang_files:
        lang_path = os.path.join(LANG_DIR, lang_file)
        if not os.path.exists(lang_path):
            print(f"⚠ {lang_file} not found, skipping...")
            continue

        print(f"\nUpdating {lang_file}...")
        data = load_json(lang_path)
        added = 0
        removed = 0

        # Add all missing keys from en.json
        for key in en_data.keys():
            if key not in data:
                # For non-English files, use the English value as placeholder
                data[key] = en_data[key]
                added += 1
                print(f"  Added: '{key}'")

        # Remove keys that are no longer in en.json
        keys_to_remove = [k for k in data.keys() if k not in en_data]
        for key in keys_to_remove:
            del data[key]
            removed += 1
            print(f"  Removed: '{key}'")

        if added > 0 or removed > 0:
            save_json(lang_path, data)
            print(f"✓ Added {added} keys, removed {removed} keys in {lang_file}")
            total_added += added
            total_removed += removed
        else:
            print(f"✓ No changes needed for {lang_file}")

    return total_added, total_removed

def main():
    print("=== Translation File Update Script ===\n")

    # Update en.json first
    en_added, en_removed = update_en_json()

    # Update other language files
    print("\n" + "="*50)
    other_added, other_removed = update_other_lang_files()

    print("\n" + "="*50)
    print("\n✓ Update complete!")
    print(f"  - en.json: Added {en_added}, Removed {en_removed}")
    print(f"  - Other files: Added {other_added}, Removed {other_removed}")
    print("\nNote: Non-English translations use English as placeholder.")
    print("Please review and translate them appropriately.")

if __name__ == "__main__":
    main()
