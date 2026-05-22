import os
import sys
from unittest.mock import MagicMock

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer, SpectrumAnalyzerWidget
from src.gui.widgets.raw_time_series import RawTimeSeries, RawTimeSeriesWidget
from src.gui.widgets.bnim_meter import BNIMMeter, BNIMMeterWidget
from src.gui.widgets.sound_level_meter import SoundLevelMeter, SoundLevelMeterWidget
from src.gui.widgets.noise_profiler import NoiseProfiler, NoiseProfilerWidget
from src.gui.widgets.compactable_interface import CompactableWidgetInterface


class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MagicMock()
        self.calibration.input_sensitivity = 1.0
        self.calibration.get_input_offset_db.return_value = 0.0
        self.calibration.get_spl_offset_db.return_value = None

    def register_callback(self, cb):
        return 1

    def unregister_callback(self, cid):
        pass


def test_spectrum_analyzer_compact_mode(qtbot):
    engine = MockAudioEngine()
    module = SpectrumAnalyzer(engine)
    widget = SpectrumAnalyzerWidget(module)
    qtbot.addWidget(widget)

    assert isinstance(widget, CompactableWidgetInterface)
    assert not widget.is_compact_mode()
    assert not widget.controls_group.isHidden()
    assert not widget.overall_label.isHidden()
    assert not widget.cursor_label.isHidden()

    widget.set_compact_mode(True)
    assert widget.is_compact_mode()
    assert widget.controls_group.isHidden()
    assert widget.overall_label.isHidden()
    assert widget.cursor_label.isHidden()

    widget.set_compact_mode(False)
    assert not widget.is_compact_mode()
    assert not widget.controls_group.isHidden()
    assert not widget.overall_label.isHidden()
    assert not widget.cursor_label.isHidden()


def test_raw_time_series_compact_mode(qtbot):
    engine = MockAudioEngine()
    module = RawTimeSeries(engine)
    widget = RawTimeSeriesWidget(module)
    qtbot.addWidget(widget)

    assert isinstance(widget, CompactableWidgetInterface)
    assert not widget.is_compact_mode()
    assert not widget.right_widget.isHidden()

    widget.set_compact_mode(True)
    assert widget.is_compact_mode()
    assert widget.right_widget.isHidden()

    widget.set_compact_mode(False)
    assert not widget.is_compact_mode()
    assert not widget.right_widget.isHidden()


def test_bnim_meter_compact_mode(qtbot):
    engine = MockAudioEngine()
    module = BNIMMeter(engine)
    widget = BNIMMeterWidget(module)
    qtbot.addWidget(widget)

    assert isinstance(widget, CompactableWidgetInterface)
    assert not widget.is_compact_mode()
    assert not widget.controls_group.isHidden()

    widget.set_compact_mode(True)
    assert widget.is_compact_mode()
    assert widget.controls_group.isHidden()

    widget.set_compact_mode(False)
    assert not widget.is_compact_mode()
    assert not widget.controls_group.isHidden()


def test_sound_level_meter_compact_mode(qtbot):
    from PyQt6.QtWidgets import QMainWindow
    engine = MockAudioEngine()
    module = SoundLevelMeter(engine)
    widget = SoundLevelMeterWidget(module)

    # Attach to a parent QMainWindow to mock and test adjustSize
    parent_win = QMainWindow()
    parent_win.adjustSize = MagicMock()
    widget.setParent(parent_win)
    qtbot.addWidget(widget)

    assert isinstance(widget, CompactableWidgetInterface)
    assert not widget.is_compact_mode()
    assert not widget.sidebar.isHidden()
    assert not widget.tabs.isHidden()

    widget.set_compact_mode(True)
    assert widget.is_compact_mode()
    assert widget.sidebar.isHidden()
    assert widget.tabs.isHidden()

    # Wait for the singleShot timer of 50ms to fire and check if adjustSize was called
    qtbot.wait(100)
    assert parent_win.adjustSize.called

    parent_win.adjustSize.reset_mock()

    widget.set_compact_mode(False)
    assert not widget.is_compact_mode()
    assert not widget.sidebar.isHidden()
    assert not widget.tabs.isHidden()

    # Wait for singleShot timer
    qtbot.wait(100)
    assert parent_win.adjustSize.called

    parent_win.deleteLater()


def test_noise_profiler_compact_mode(qtbot):
    engine = MockAudioEngine()
    module = NoiseProfiler(engine)
    widget = NoiseProfilerWidget(module)
    qtbot.addWidget(widget)

    assert isinstance(widget, CompactableWidgetInterface)
    assert not widget.is_compact_mode()
    assert not widget.sidebar.isHidden()

    widget.set_compact_mode(True)
    assert widget.is_compact_mode()
    assert widget.sidebar.isHidden()

    widget.set_compact_mode(False)
    assert not widget.is_compact_mode()
    assert not widget.sidebar.isHidden()
