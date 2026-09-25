from PyQt6.QtWidgets import QPushButton, QWidget

from src.core.module_constants import MODULE_TRANSMISSION_ANALYZER
from src.gui.module_registry import MODULE_REGISTRY
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper
from src.gui.widgets.transmission_analyzer import TransmissionAnalyzerWidget


def test_transmission_analyzer_compact_mode_through_wrapper(qtbot):
    widget = TransmissionAnalyzerWidget.__new__(TransmissionAnalyzerWidget)
    QWidget.__init__(widget)
    CompactableWidgetInterface.__init__(widget)
    widget.left_panel = QWidget(widget)
    widget.btn_toggle = QPushButton(widget)
    widget.btn_toggle.setCheckable(True)
    wrapper = DetachableWidgetWrapper(
        widget,
        "Transmission Analyzer",
        capabilities=MODULE_REGISTRY[MODULE_TRANSMISSION_ANALYZER].capabilities,
    )
    qtbot.addWidget(wrapper)

    wrapper.detach()
    assert wrapper.compact_btn is not None
    assert wrapper.compact_btn.isEnabled()

    wrapper.compact_btn.click()
    assert widget.is_compact_mode()
    assert widget.left_panel.isHidden()

    wrapper.reattach()
    assert not widget.is_compact_mode()
    assert not widget.left_panel.isHidden()
