import ast
import json
import os

# Configuration
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
LANG_DIR = os.path.join(SRC_DIR, "assets", "lang")
MAIN_GUI_FILE = os.path.join(PROJECT_ROOT, "main_gui.py")

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
