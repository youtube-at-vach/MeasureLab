import ast
from pathlib import Path


def test_pyinstaller_imports_syntax_and_existence():
    """
    Verifies that src/gui/pyinstaller_imports.py can be parsed correctly and
    that all modules it tries to import actually exist in the filesystem.
    """
    file_path = Path("src/gui/pyinstaller_imports.py")
    assert file_path.exists(), f"{file_path} does not exist"

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Verify it has valid Python syntax
    try:
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError as e:
        raise AssertionError(f"Syntax error in {file_path}: {e}") from e

    # Extract all imported modules
    for node in ast.walk(tree):
        module_name = None
        if isinstance(node, ast.ImportFrom):
            module_name = node.module
        elif isinstance(node, ast.Import):
            # For "import src.gui.widgets.welcome" style
            # Test each alias individually (e.g. import a, b, c)
            for alias in node.names:
                module_name = alias.name

                if module_name is None:
                    continue

                # Convert module path to file path
                module_parts = module_name.split(".")
                base_path = Path(*module_parts)

                file_path_py = base_path.with_suffix(".py")
                dir_path = base_path / "__init__.py"

                exists = file_path_py.exists() or dir_path.exists()
                assert exists, (
                    f"Module {module_name} imported in pyinstaller_imports.py does not exist at {file_path_py} or {dir_path}"
                )

            module_name = None  # Reset so we don't process it again below

        if module_name is None:
            continue

        # Convert module path to file path
        module_parts = module_name.split(".")
        base_path = Path(*module_parts)

        file_path_py = base_path.with_suffix(".py")
        dir_path = base_path / "__init__.py"

        exists = file_path_py.exists() or dir_path.exists()
        assert exists, (
            f"Module {module_name} imported in pyinstaller_imports.py does not exist at {file_path_py} or {dir_path}"
        )
