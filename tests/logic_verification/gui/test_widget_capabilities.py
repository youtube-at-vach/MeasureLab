from __future__ import annotations

from collections.abc import Iterator

import pytest
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from src.core.audio_engine import AudioEngine
from src.core.module_constants import ALL_MODULE_KEYS
from src.gui.main_window import _load_module_class
from src.gui.module_registry import (
    CapabilityExclusionReason,
    CapabilityStatus,
    COMPARISON_DEFERRED,
    FeatureCapability,
    MODULE_REGISTRY,
    NO_INDEPENDENT_DISPLAY,
    SPLIT_DEFERRED,
    SUPPORTED,
    WidgetCapabilities,
)
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.gui.widgets.comparable_interface import ComparableWidgetInterface
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper, validate_widget_capabilities
from src.gui.widgets.splittable_interface import SplittableWidgetInterface
from src.measurement_modules.base import MeasurementModule


FULL_CAPABILITIES = WidgetCapabilities(
    split_window=SUPPORTED,
    compact_mode=SUPPORTED,
    comparison=SUPPORTED,
)
NO_CAPABILITIES = WidgetCapabilities(
    split_window=NO_INDEPENDENT_DISPLAY,
    compact_mode=NO_INDEPENDENT_DISPLAY,
    comparison=NO_INDEPENDENT_DISPLAY,
)


@pytest.fixture(scope="module")
def shared_audio_engine() -> Iterator[AudioEngine]:
    yield AudioEngine()


def test_registry_covers_all_module_keys_in_ui_order():
    assert list(MODULE_REGISTRY) == ALL_MODULE_KEYS


@pytest.mark.parametrize("module_key", ALL_MODULE_KEYS)
def test_registered_widget_matches_declared_capabilities(module_key, qapp, shared_audio_engine):
    registration = MODULE_REGISTRY[module_key]
    module_type = _load_module_class(module_key)
    assert issubclass(module_type, MeasurementModule)

    module = module_type(shared_audio_engine)
    widget = module.get_widget()
    assert isinstance(widget, QWidget)

    try:
        contracts = (
            (
                registration.capabilities.compact_mode.is_supported,
                CompactableWidgetInterface,
                ("update_compact_layout",),
            ),
            (
                registration.capabilities.split_window.is_supported,
                SplittableWidgetInterface,
                ("get_display_widget", "get_control_widget", "restore_split_panels"),
            ),
            (
                registration.capabilities.comparison.is_supported,
                ComparableWidgetInterface,
                ("get_comparable_data",),
            ),
        )
        for declared_supported, interface_type, required_methods in contracts:
            assert isinstance(widget, interface_type) is declared_supported
            if declared_supported:
                for method_name in required_methods:
                    assert getattr(type(widget), method_name) is not getattr(interface_type, method_name)

        validate_widget_capabilities(widget, registration.capabilities)
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


class _DuckTypedWidget(QWidget):
    def set_compact_mode(self, enabled: bool) -> None:
        pass

    def get_display_widget(self) -> QWidget:
        return self

    def get_control_widget(self) -> QWidget:
        return self

    def get_comparable_data(self) -> list[object]:
        return []


class _FullyCapableWidget(
    QWidget,
    CompactableWidgetInterface,
    ComparableWidgetInterface,
    SplittableWidgetInterface,
):
    def __init__(self):
        QWidget.__init__(self)
        CompactableWidgetInterface.__init__(self)
        self.display_widget = QWidget()
        self.control_widget = QWidget()
        self.main_layout = QHBoxLayout(self)
        self.main_layout.addWidget(self.display_widget)
        self.main_layout.addWidget(self.control_widget)

    def update_compact_layout(self) -> None:
        self.control_widget.setVisible(not self.is_compact_mode())

    def get_display_widget(self) -> QWidget:
        return self.display_widget

    def get_control_widget(self) -> QWidget:
        return self.control_widget

    def restore_split_panels(self) -> None:
        self.main_layout.addWidget(self.display_widget)
        self.main_layout.addWidget(self.control_widget)

    def get_comparable_data(self) -> list[object]:
        return []


class _MissingCompactOverride(QWidget, CompactableWidgetInterface):
    def __init__(self):
        QWidget.__init__(self)
        CompactableWidgetInterface.__init__(self)


def test_wrapper_uses_declarations_instead_of_duck_typing(qtbot):
    widget = _DuckTypedWidget()
    wrapper = DetachableWidgetWrapper(widget, "Duck Typed", capabilities=NO_CAPABILITIES)
    qtbot.addWidget(wrapper)

    assert wrapper.compact_btn is None
    assert wrapper.split_btn is None
    assert wrapper.compare_btn is None

    wrapper.detach()
    assert wrapper.independent_window is not None
    assert not wrapper.independent_window.supports_compact_mode


def test_supported_declarations_drive_wrapper_and_independent_window(qtbot):
    widget = _FullyCapableWidget()
    wrapper = DetachableWidgetWrapper(widget, "Full", capabilities=FULL_CAPABILITIES)
    qtbot.addWidget(wrapper)

    assert wrapper.compact_btn is not None
    assert wrapper.split_btn is not None
    assert wrapper.compare_btn is not None

    wrapper.detach()
    assert wrapper.independent_window is not None
    assert wrapper.independent_window.supports_compact_mode
    assert wrapper.independent_window.compact_target is widget


def test_capability_mismatches_fail_fast(qtbot):
    fully_capable = _FullyCapableWidget()
    duck_typed = _DuckTypedWidget()
    missing_override = _MissingCompactOverride()
    qtbot.addWidget(fully_capable)
    qtbot.addWidget(duck_typed)
    qtbot.addWidget(missing_override)

    with pytest.raises(ValueError, match="declares compact mode as excluded"):
        validate_widget_capabilities(fully_capable, NO_CAPABILITIES)
    with pytest.raises(ValueError, match="declares compact mode as supported"):
        validate_widget_capabilities(duck_typed, FULL_CAPABILITIES)

    missing_override_capabilities = WidgetCapabilities(
        split_window=SPLIT_DEFERRED,
        compact_mode=SUPPORTED,
        comparison=COMPARISON_DEFERRED,
    )
    with pytest.raises(ValueError, match=r"does not override update_compact_layout\(\)"):
        validate_widget_capabilities(missing_override, missing_override_capabilities)


def test_feature_specific_exclusion_reasons_are_enforced():
    with pytest.raises(ValueError, match="Supported capabilities cannot have an exclusion reason"):
        FeatureCapability(CapabilityStatus.SUPPORTED, CapabilityExclusionReason.COMPACT_DEFERRED)
    with pytest.raises(ValueError, match="Excluded capabilities must have an exclusion reason"):
        FeatureCapability(CapabilityStatus.EXCLUDED)
    with pytest.raises(ValueError, match="not a valid exclusion reason for compact_mode"):
        WidgetCapabilities(
            split_window=SPLIT_DEFERRED,
            compact_mode=COMPARISON_DEFERRED,
            comparison=COMPARISON_DEFERRED,
        )
