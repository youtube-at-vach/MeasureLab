import ast
import os
import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


def discover_modules(directory: str, base_module_path: str) -> Dict[str, Tuple[str, str]]:
    """
    Scans the given directory for Python files containing classes that inherit from MeasurementModule.

    Args:
        directory: The filesystem path to scan.
        base_module_path: The python module path corresponding to the directory (e.g., 'src.gui.widgets').

    Returns:
        A dictionary mapping module name (from .name property) to (module_dotted_path, class_name).
    """
    registry = {}

    if not os.path.exists(directory):
        logger.error(f"Directory not found: {directory}")
        return registry

    for filename in os.listdir(directory):
        if not filename.endswith(".py") or filename.startswith("__"):
            continue

        filepath = os.path.join(directory, filename)
        module_name = filename[:-3]
        module_dotted_path = f"{base_module_path}.{module_name}"

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=filepath)

            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    # Check inheritance
                    is_measurement_module = False
                    for base in node.bases:
                        if isinstance(base, ast.Name) and base.id == "MeasurementModule":
                            is_measurement_module = True
                            break
                        # Handle attribute access if imported as module (e.g. base.MeasurementModule)
                        elif isinstance(base, ast.Attribute) and base.attr == "MeasurementModule":
                            is_measurement_module = True
                            break

                    if is_measurement_module:
                        # Find 'name' property
                        module_human_name = _extract_name_property(node)
                        if module_human_name:
                            registry[module_human_name] = (module_dotted_path, node.name)

        except Exception as e:
            logger.warning(f"Failed to parse {filename}: {e}")

    return registry


def _extract_name_property(class_node: ast.ClassDef) -> str:
    """Extracts the string literal returned by the 'name' property."""
    for item in class_node.body:
        if isinstance(item, ast.FunctionDef) and item.name == "name":
            # Check for @property decorator
            is_property = False
            for dec in item.decorator_list:
                if isinstance(dec, ast.Name) and dec.id == "property":
                    is_property = True
                    break

            if is_property:
                # Look for return statement
                for stmt in item.body:
                    if isinstance(stmt, ast.Return):
                        # Case 1: return "String"
                        if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                            return stmt.value.value

                        # Case 2: return tr("String")
                        # This assumes 'tr' is used for translation but the key is the string literal we want.
                        # However, based on codebase exploration, the name property returns raw english strings
                        # like "Signal Generator" which matches MODULE_KEYS.
                        pass
    return None
