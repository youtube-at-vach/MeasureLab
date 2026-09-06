import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gui import main_window
from src.gui.module_registry import MODULE_REGISTRY


def test_import_module_calls_use_literal_paths():
    source = Path(main_window.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    import_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "import_module"
    ]

    assert import_calls
    assert all(
        call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)
        for call in import_calls
    )


def test_lazy_class_loaders_match_registry():
    registered_classes = {
        (registration.module_path, registration.class_name) for registration in MODULE_REGISTRY.values()
    }
    utility_classes = {
        ("src.gui.widgets.routing", "RoutingWidget"),
        ("src.gui.widgets.remote_audio_io", "RemoteAudioIOWidget"),
        ("src.gui.widgets.settings", "SettingsWidget"),
        ("src.gui.widgets.welcome", "WelcomeWidget"),
    }

    assert set(main_window._CLASS_LOADERS) == registered_classes | utility_classes


@pytest.mark.parametrize(
    ("module_path", "class_name"),
    [
        ("untrusted.module", "InjectedClass"),
        ("src.gui.widgets.settings", "InjectedClass"),
    ],
)
def test_load_class_rejects_unregistered_module_and_class(module_path, class_name, monkeypatch):
    import_module = pytest.fail
    monkeypatch.setattr(main_window, "import_module", import_module)

    with pytest.raises(ValueError, match="Class not in allowlist"):
        main_window._load_class(module_path, class_name)


def test_load_class_uses_literal_module_loader(monkeypatch):
    sentinel = type("Sentinel", (), {})
    imported_paths = []

    def fake_import_module(module_path):
        imported_paths.append(module_path)
        return SimpleNamespace(SettingsWidget=sentinel)

    monkeypatch.setattr(main_window, "import_module", fake_import_module)

    assert main_window._load_class("src.gui.widgets.settings", "SettingsWidget") is sentinel
    assert imported_paths == ["src.gui.widgets.settings"]
