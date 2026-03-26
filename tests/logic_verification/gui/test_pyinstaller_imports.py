import ast
import os
import unittest

class TestPyInstallerImports(unittest.TestCase):
    def test_imports_parse_correctly(self):
        """Verify that pyinstaller_imports.py has valid syntax and imports resolve."""
        # Calculate path to pyinstaller_imports.py
        current_dir = os.path.dirname(__file__)
        filepath = os.path.abspath(os.path.join(
            current_dir, '..', '..', '..', 'src', 'gui', 'pyinstaller_imports.py'
        ))

        with open(filepath, 'r') as f:
            source = f.read()

        # Verify valid syntax by parsing AST
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            self.fail(f"Syntax error in pyinstaller_imports.py: {e}")

        # Extract all ImportFrom nodes
        imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]

        self.assertTrue(len(imports) > 0, "No ImportFrom nodes found in pyinstaller_imports.py")

        # Verify the modules exist in the filesystem
        base_dir = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))

        for imp in imports:
            module_name = imp.module
            if module_name is None:
                continue

            # Convert module name (e.g., 'src.gui.widgets.bnim_meter') to path
            module_path = module_name.replace('.', os.sep)

            py_file = os.path.join(base_dir, f"{module_path}.py")
            init_file = os.path.join(base_dir, module_path, "__init__.py")

            # Check if either a module file or a package directory exists
            exists = os.path.exists(py_file) or os.path.exists(init_file)
            self.assertTrue(
                exists,
                f"Imported module '{module_name}' not found at '{py_file}' or '{init_file}'"
            )
