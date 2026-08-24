from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
from PyQt6.QtWidgets import QPushButton, QWidget

from src.core.module_constants import MODULE_TRANSMISSION_ANALYZER
from src.gui.module_registry import MODULE_REGISTRY
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper
from src.gui.widgets.distortion_analyzer import DistortionAnalyzerWidget
from src.gui.widgets.lock_in_amplifier import LockInAmplifierWidget
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


def test_distortion_analyzer_exports_frequency_sweep_for_comparison():
    calibration = SimpleNamespace(input_sensitivity=1.0, is_calibrated=False)
    module = SimpleNamespace(
        sweep_results=[
            {"sweep_param": 100.0, "thdn_db": -80.0, "thdn_percent": 0.01},
            {"sweep_param": 1000.0, "thdn_db": -90.0, "thdn_percent": 0.003},
        ],
        audio_engine=SimpleNamespace(calibration=calibration),
        filter_type="none",
    )
    widget = SimpleNamespace(
        module=module,
        mode_combo=MagicMock(currentIndex=MagicMock(return_value=1)),
        sweep_y_unit_combo=MagicMock(currentText=MagicMock(return_value="dB")),
        _get_sweep_x_unit=MagicMock(return_value="Hz"),
        _convert_sweep_x_value=lambda value: value,
    )

    traces = DistortionAnalyzerWidget.get_comparable_data(widget)

    assert len(traces) == 1
    trace = traces[0]
    assert trace.source_module == "Distortion Analyzer"
    assert trace.plot_type == "frequency_response"
    np.testing.assert_allclose(trace.x_data, [100.0, 1000.0])
    np.testing.assert_allclose(trace.y_data, [-80.0, -90.0])
    assert trace.metadata["sweep_type"] == "frequency"


def test_lock_in_amplifier_exports_fra_for_comparison():
    calibration = SimpleNamespace(input_sensitivity=2.0, is_calibrated=True)
    widget = SimpleNamespace(
        fra_freqs=[100.0, 1000.0],
        fra_raw_mags=[0.1, 0.2],
        fra_phases=[-10.0, -20.0],
        module=SimpleNamespace(audio_engine=SimpleNamespace(calibration=calibration)),
        time_combo=MagicMock(currentText=MagicMock(return_value="100 ms")),
        avg_spin=MagicMock(value=MagicMock(return_value=4)),
    )

    traces = LockInAmplifierWidget.get_comparable_data(widget)

    assert len(traces) == 1
    trace = traces[0]
    assert trace.source_module == "Lock-in Amplifier"
    assert trace.plot_type == "frequency_response"
    np.testing.assert_allclose(trace.x_data, [100.0, 1000.0])
    np.testing.assert_allclose(trace.y_data, [0.2, 0.4])
    np.testing.assert_allclose(trace.y2_data, [-10.0, -20.0])
    assert trace.calibration.reference_level == "absolute"
