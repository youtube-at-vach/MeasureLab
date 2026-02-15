#!/usr/bin/env python3
"""
Script to automatically update translation files with missing keys.
This script scans the entire src/ directory for tr() calls and updates all language files.
"""

import ast
import glob
import json
import os
import sys

# Configuration
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
LANG_DIR = os.path.join(SRC_DIR, "assets", "lang")


class TrVisitor(ast.NodeVisitor):
    def __init__(self):
        self.keys = set()

    def visit_Call(self, node):
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        if func_name == 'tr':
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                self.keys.add(node.args[0].value)

        self.generic_visit(node)

    def visit_Assign(self, node):
        # Look for self._module_keys = [...] or _module_keys = [...]
        target_name = None
        for target in node.targets:
            if isinstance(target, ast.Attribute) and target.attr == '_module_keys':
                target_name = '_module_keys'
            elif isinstance(target, ast.Name) and target.id == '_module_keys':
                target_name = '_module_keys'

        if target_name == '_module_keys':
            if isinstance(node.value, ast.List):
                for elt in node.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        self.keys.add(elt.value)

        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        # Look for @property def name(self) -> str: return "..."
        is_property = False
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == 'property':
                is_property = True
                break
            if isinstance(decorator, ast.Attribute) and decorator.attr == 'property':
                is_property = True
                break

        if is_property and node.name == 'name':
            # Look for return "some string"
            for stmt in node.body:
                if isinstance(stmt, ast.Return):
                    if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                        self.keys.add(stmt.value.value)

        self.generic_visit(node)


def extract_tr_keys(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=filepath)
        visitor = TrVisitor()
        visitor.visit(tree)
        return visitor.keys
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")
        return set()


def load_json(path):
    """Load JSON file preserving order"""
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    """Save JSON file with proper formatting"""
    # Sort keys alphabetically to ensure deterministic output
    sorted_data = dict(sorted(data.items()))
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(sorted_data, f, ensure_ascii=False, indent=4)
        f.write('\n')  # Add trailing newline


def main():
    print("=== Translation Update Script ===\n")

    # 1. Scan Source Code for Keys
    print(f"Scanning {SRC_DIR} for translation keys...")
    code_keys = set()
    file_count = 0

    # Recursive scan of src/ directory
    for root, dirs, files in os.walk(SRC_DIR):
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
    en_path = os.path.join(LANG_DIR, 'en.json')
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
        if filename == 'en.json':
            continue

        print(f"Updating {filename}...")
        lang_data = load_json(lang_path)
        added = 0
        removed = 0

        # Sync with en.json keys
        # Add missing keys (use English as placeholder)
        for key in en_data.keys():
            if key not in lang_data:
                lang_data[key] = en_data[key] # Use English value
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
