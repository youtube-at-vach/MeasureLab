import os
import sys
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PyQt6")

if "sounddevice" not in sys.modules:
    sys.modules["sounddevice"] = MagicMock()

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6 import sip

from src.core.module_constants import MODULE_SPECTROGRAM
from src.gui.module_registry import MODULE_REGISTRY
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper
from src.gui.widgets.spectrogram import Spectrogram, SpectrogramWidget
from src.gui.widgets.splittable_interface import SplittableWidgetInterface


@pytest.fixture
def spectrogram_widget():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    engine = MagicMock()
    engine.sample_rate = 48000
    widget = SpectrogramWidget(Spectrogram(engine))

    yield widget

    if not sip.isdeleted(widget):
        widget.close()
        widget.deleteLater()


def test_spectrogram_implements_split_interface(spectrogram_widget):
    assert isinstance(spectrogram_widget, SplittableWidgetInterface)
    assert isinstance(spectrogram_widget.get_display_widget(), QWidget)
    assert isinstance(spectrogram_widget.get_control_widget(), QWidget)
    assert spectrogram_widget.get_display_widget() is spectrogram_widget.display_widget
    assert spectrogram_widget.get_control_widget() is spectrogram_widget.controls_group


def test_spectrogram_split_and_reattach_restores_vertical_layout(spectrogram_widget):
    wrapper = DetachableWidgetWrapper(
        spectrogram_widget,
        "Spectrogram",
        capabilities=MODULE_REGISTRY[MODULE_SPECTROGRAM].capabilities,
    )

    assert wrapper.is_splittable
    assert wrapper.split_btn is not None
    assert wrapper.split_btn.isEnabled()

    wrapper.split()

    assert wrapper.is_split
    assert wrapper.split_display_window is not None
    assert wrapper.split_control_window is not None
    assert spectrogram_widget.display_widget.parent() is wrapper.split_display_window
    assert spectrogram_widget.controls_group.parent() is wrapper.split_control_window

    spectrogram_widget.set_compact_mode(True)
    assert not spectrogram_widget.controls_group.isHidden()

    wrapper.reattach_all()

    layout = spectrogram_widget.layout()
    assert not wrapper.is_split
    assert spectrogram_widget.display_widget.parent() is spectrogram_widget
    assert spectrogram_widget.controls_group.parent() is spectrogram_widget
    assert layout.itemAt(0).widget() is spectrogram_widget.controls_group
    assert layout.itemAt(1).widget() is spectrogram_widget.display_widget
