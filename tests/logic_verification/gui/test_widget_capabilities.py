from importlib import import_module, reload

import pytest
from PyQt6.QtWidgets import QWidget

from src.core.module_constants import ALL_MODULE_KEYS
from src.gui.module_registry import CapabilityStatus, MODULE_REGISTRY, WidgetCapabilities
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.gui.widgets.comparable_interface import ComparableWidgetInterface
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper
from src.gui.widgets.splittable_interface import SplittableWidgetInterface
from scripts.generate_widget_feature_matrix import MATRIX_PATH, generate_document


INTERFACES = {
    "compact": (CompactableWidgetInterface, ("update_compact_layout",)),
    "compare": (ComparableWidgetInterface, ("get_comparable_data",)),
    "split": (
        SplittableWidgetInterface,
        ("get_display_widget", "get_control_widget", "restore_split_panels"),
    ),
}


def test_registry_covers_every_module_in_sidebar_order():
    assert list(MODULE_REGISTRY) == ALL_MODULE_KEYS
    assert len(MODULE_REGISTRY) == 42


def test_declared_capability_counts_match_reviewed_matrix():
    assert sum(spec.capabilities.compact.is_supported for spec in MODULE_REGISTRY.values()) == 14
    assert sum(spec.capabilities.split.is_supported for spec in MODULE_REGISTRY.values()) == 11
    assert sum(spec.capabilities.compare.is_supported for spec in MODULE_REGISTRY.values()) == 5


def test_exclusion_reasons_are_valid_for_each_capability():
    allowed = {
        "split": {CapabilityStatus.SUPPORTED, CapabilityStatus.EXCLUDED_A, CapabilityStatus.EXCLUDED_F},
        "compact": {CapabilityStatus.SUPPORTED, CapabilityStatus.EXCLUDED_A, CapabilityStatus.EXCLUDED_E},
        "compare": {
            CapabilityStatus.SUPPORTED,
            CapabilityStatus.EXCLUDED_A,
            CapabilityStatus.EXCLUDED_B,
            CapabilityStatus.EXCLUDED_C,
            CapabilityStatus.EXCLUDED_D,
        },
    }
    for module_key, spec in MODULE_REGISTRY.items():
        for capability_name, valid_statuses in allowed.items():
            decision = getattr(spec.capabilities, capability_name)
            assert decision in valid_statuses, f"{module_key}: invalid {capability_name} exclusion reason"


def test_widget_feature_matrix_generated_sections_are_current():
    current = MATRIX_PATH.read_text(encoding="utf-8")
    assert generate_document(current) == current


@pytest.mark.parametrize(("module_key", "spec"), MODULE_REGISTRY.items(), ids=MODULE_REGISTRY.keys())
def test_capability_declarations_match_widget_interfaces(module_key, spec):
    module = import_module(spec.module_path)
    widget_class = getattr(module, spec.widget_class_name)
    if not isinstance(widget_class, type):
        # A legacy recorder test imports this module with mocked Qt modules and
        # leaves the resulting module cached. Reload it against the restored
        # runtime before checking the real widget contract.
        module = reload(module)
        widget_class = getattr(module, spec.widget_class_name)

    for capability_name, (interface, required_methods) in INTERFACES.items():
        decision = getattr(spec.capabilities, capability_name)
        implements_interface = issubclass(widget_class, interface)
        assert implements_interface == decision.is_supported, (
            f"{module_key}: {capability_name} declaration does not match {widget_class.__name__}"
        )
        if decision.is_supported:
            for method_name in required_methods:
                assert method_name in widget_class.__dict__, (
                    f"{module_key}: {widget_class.__name__} must override {method_name}"
                )
        else:
            assert decision is not CapabilityStatus.SUPPORTED


class _CompactContent(QWidget, CompactableWidgetInterface):
    def __init__(self):
        QWidget.__init__(self)
        CompactableWidgetInterface.__init__(self)

    def update_compact_layout(self):
        pass


def test_wrapper_rejects_capability_declaration_mismatch(qtbot):
    content = _CompactContent()
    qtbot.addWidget(content)
    declared_without_compact = WidgetCapabilities(
        split=CapabilityStatus.EXCLUDED_F,
        compact=CapabilityStatus.EXCLUDED_E,
        compare=CapabilityStatus.EXCLUDED_D,
    )

    with pytest.raises(TypeError, match="compact"):
        DetachableWidgetWrapper(
            content,
            "Capability Mismatch",
            capabilities=declared_without_compact,
        )
