import ast
import os

def check_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
    except Exception as e:
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            has_assert = False
            for child in ast.walk(node):
                if isinstance(child, ast.Assert):
                    has_assert = True
                    break
                # Check for self.assert*
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                    attr_name = child.func.attr
                    if attr_name.startswith("assert"):
                        has_assert = True
                        break
                    if attr_name == "fail":
                        has_assert = True
                        break
            if not has_assert:
                print(f"{filepath}:{node.name}")

for root, _, files in os.walk("tests"):
    for file in files:
        if file.endswith(".py"):
            check_file(os.path.join(root, file))
