#!/usr/bin/env python3
"""
Script to automatically update translation files with missing keys.
This script scans the entire src/ directory for tr() calls and updates all language files.
"""

import glob
import os

from translation_utils import (
    LANG_DIR,
    PROJECT_ROOT,
    SRC_DIR,
    extract_tr_keys,
    load_json,
    save_json,
)


def main():
    print("=== Translation Update Script ===\n")

    # 1. Scan Source Code for Keys
    print(f"Scanning {SRC_DIR} for translation keys...")
    code_keys = set()
    file_count = 0

    # Recursive scan of src/ directory
    for root, _dirs, files in os.walk(SRC_DIR):
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                keys = extract_tr_keys(filepath)
                code_keys.update(keys)
                file_count += 1

    # Also include main_gui.py in root
    main_gui = os.path.join(PROJECT_ROOT, "main_gui.py")
    if os.path.exists(main_gui):
        keys = extract_tr_keys(main_gui)
        code_keys.update(keys)
        file_count += 1

    print(f"Found {len(code_keys)} unique keys in {file_count} files.\n")

    # 2. Update en.json (Source of Truth)
    en_path = os.path.join(LANG_DIR, "en.json")
    en_data = load_json(en_path)

    en_added = 0
    en_removed = 0

    # Add missing keys
    for key in code_keys:
        if key not in en_data:
            en_data[key] = key
            en_added += 1
            print(f"[en] Added: '{key}'")

    # Remove unused keys
    keys_to_remove = [k for k in en_data.keys() if k not in code_keys]
    for key in keys_to_remove:
        del en_data[key]
        en_removed += 1
        print(f"[en] Removed: '{key}'")

    if en_added > 0 or en_removed > 0:
        save_json(en_path, en_data)
        print(f"✓ Updated en.json: +{en_added} / -{en_removed}\n")
    else:
        print("✓ en.json is up to date.\n")

    # 3. Update other language files
    lang_files = glob.glob(os.path.join(LANG_DIR, "*.json"))

    for lang_path in lang_files:
        filename = os.path.basename(lang_path)
        if filename == "en.json":
            continue

        print(f"Updating {filename}...")
        lang_data = load_json(lang_path)
        added = 0
        removed = 0

        # Sync with en.json keys
        # Add missing keys (use English as placeholder)
        for key in en_data.keys():
            if key not in lang_data:
                lang_data[key] = en_data[key]  # Use English value
                added += 1
                # print(f"  Added: '{key}'")

        # Remove keys not in en.json
        keys_to_remove = [k for k in lang_data.keys() if k not in en_data]
        for key in keys_to_remove:
            del lang_data[key]
            removed += 1
            # print(f"  Removed: '{key}'")

        if added > 0 or removed > 0:
            save_json(lang_path, lang_data)
            print(f"✓ Updated {filename}: +{added} / -{removed}")
        else:
            print(f"✓ {filename} is up to date.")

    print("\n=== Update Complete ===")


if __name__ == "__main__":
    main()
