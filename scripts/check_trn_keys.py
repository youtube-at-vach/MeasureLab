import argparse
import glob
import os
import sys

from translation_utils import (
    LANG_DIR,
    MAIN_GUI_FILE,
    SRC_DIR,
    extract_tr_keys,
    load_json,
    save_json,
)

# Helpers
def get_json_files():
    return glob.glob(os.path.join(LANG_DIR, "*.json"))

def find_duplicate_keys(path):
    """
    Scans a JSON file for duplicate keys using simple line matching.
    This finds strict exact duplicates in the file text.
    """
    keys = set()
    duplicates = set()
    import re
    # Regex to find "key": at the start of a line (ignoring whitespace)
    # This assumes standard formatting like "key": "value"
    pattern = re.compile(r'^\s*"((?:[^"\\]|\\.)+)"\s*:')

    with open(path, 'r', encoding='utf-8') as f:
        for _line_num, line in enumerate(f, 1):
            match = pattern.search(line)
            if match:
                key = match.group(1)
                # Unescape escaped quotes if necessary (basic handling)
                key = key.replace('\\"', '"')
                if key in keys:
                    duplicates.add(key)
                keys.add(key)
    return list(duplicates)

def main():
    parser = argparse.ArgumentParser(description="Check translation keys consistency.")
    parser.add_argument("--lax", action="store_true", help="Do not fail even if unused keys are found in en.json")
    parser.add_argument("--fix", action="store_true", help="Remove unused keys from all translation files")
    args = parser.parse_args()

    print("=== Translation Check Script ===")

    # 1. Load EN JSON (Source of Truth)
    en_path = os.path.join(LANG_DIR, 'en.json')
    if not os.path.exists(en_path):
        print(f"Error: en.json not found at {en_path}")
        sys.exit(1)

    en_data = load_json(en_path)
    en_keys = set(en_data.keys())
    print(f"Loaded {len(en_keys)} keys from en.json")

    # 2. Extract keys from Code
    files_to_scan = []
    # Recursive scan of src/ directory
    for root, _dirs, files in os.walk(SRC_DIR):
        for file in files:
            if file.endswith(".py"):
                files_to_scan.append(os.path.join(root, file))

    # Main GUI
    if os.path.exists(MAIN_GUI_FILE):
        files_to_scan.append(MAIN_GUI_FILE)

    code_keys = set()
    for fp in files_to_scan:
        file_keys = extract_tr_keys(fp)
        code_keys.update(file_keys)

    print(f"Found {len(code_keys)} unique tr() keys in {len(files_to_scan)} source files.")

    # 3. Check: Code Keys exist in en.json
    missing_in_en = []
    for k in code_keys:
        if k not in en_keys:
            missing_in_en.append(k)

    # 4. Check: Unused keys in en.json (Defined but not used in code)
    unused_in_code = []
    for k in en_keys:
        if k not in code_keys:
            unused_in_code.append(k)

    # 5. Fix: Remove unused keys if requested
    if args.fix and unused_in_code:
        print(f"\n--- Fixing: Removing {len(unused_in_code)} unused keys ---")
        json_files = get_json_files()
        for jf in json_files:
            data = load_json(jf)
            original_len = len(data)
            for k in unused_in_code:
                if k in data:
                    del data[k]
            if len(data) < original_len:
                save_json(jf, data)
                print(f"  Updated {os.path.basename(jf)}: removed {original_len - len(data)} keys.")

        # Re-load en_keys after fix
        en_data = load_json(en_path)
        en_keys = set(en_data.keys())
        unused_in_code = [] # Cleared after fix

    # 6. Check: Other JSONs have all keys from en.json
    json_files = get_json_files()
    missing_translations = {} # filename -> list of missing keys

    for jf in json_files:
        fname = os.path.basename(jf)
        if fname == 'en.json':
            continue

        data = load_json(jf)
        local_keys = set(data.keys())
        diff = en_keys - local_keys
        if diff:
            missing_translations[fname] = list(diff)

    # 7. Check Duplicates (Warning only)
    duplicates_map = {}
    for jf in json_files:
        dups = find_duplicate_keys(jf)
        if dups:
            duplicates_map[os.path.basename(jf)] = dups

    # Reporting
    has_error = False

    print("\n--- Check 1: Missing keys in en.json (Used in Code) ---")
    if missing_in_en:
        has_error = True
        print(f"FAIL: {len(missing_in_en)} keys used in code but missing in en.json:")
        for k in sorted(missing_in_en):
            print(f"  - \"{k}\"")
    else:
        print("OK")

    print("\n--- Check 2: Unused keys in en.json (Not used in Code) ---")
    if unused_in_code:
        if args.lax:
            print(f"WARNING: {len(unused_in_code)} keys defined in en.json but NOT used in code:")
        else:
            has_error = True
            print(f"FAIL: {len(unused_in_code)} keys defined in en.json but NOT used in code:")

        for k in sorted(unused_in_code)[:10]:
            print(f"  - \"{k}\"")
        if len(unused_in_code) > 10:
            print(f"  ... and {len(unused_in_code)-10} more.")
    else:
        print("OK")

    print("\n--- Check 3: Missing translations in other languages (Compared to en.json) ---")
    if missing_translations:
        has_error = True
        for fname, keys in missing_translations.items():
            print(f"FAIL: {fname} is missing {len(keys)} keys:")
            # Show first 10
            for k in sorted(keys)[:10]:
                print(f"  - \"{k}\"")
            if len(keys) > 10:
                print(f"  ... and {len(keys)-10} more.")
    else:
        print("OK")

    print("\n--- Check 4: Duplicate Keys (Warning) ---")
    if duplicates_map:
        for fname, keys in duplicates_map.items():
            print(f"WARNING: {fname} has duplicate keys:")
            for k in keys:
                print(f"  - \"{k}\"")
    else:
        print("OK")

    print("\n=== Result ===")
    if has_error:
        print("TEST FAILED")
        sys.exit(1)
    else:
        print("TEST PASSED")
        sys.exit(0)

if __name__ == "__main__":
    main()
