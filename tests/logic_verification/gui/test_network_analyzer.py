import numpy as np

from src.gui.widgets.network_analyzer import NetworkAnalyzer, NetworkAnalyzerWidget


class MockCalibration:
    output_gain = 1.0
    input_sensitivity = 1.0


class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MockCalibration()
        self.stream = None
        self.offline_mode = True

    def register_callback(self, callback):
        return 1

    def unregister_callback(self, callback_id):
        pass


def _make_widget(qtbot):
    widget = NetworkAnalyzerWidget(NetworkAnalyzer(MockAudioEngine()))
    qtbot.addWidget(widget)
    return widget


def _curve_len(values):
    return 0 if values is None else len(values)


def test_update_ir_plot_updates_etc_curve(qtbot):
    widget = _make_widget(qtbot)

    time_ms = np.arange(8, dtype=float)
    ir_values = np.array([1.0, 0.5, 0.25, 0.125, 0.0625, 0.0, 0.0, 0.0])

    widget.update_ir_plot(time_ms, ir_values)

    etc_x, etc_y = widget.etc_curve.getData()
    assert np.array_equal(etc_x, time_ms)
    assert len(etc_y) == len(ir_values)
    assert np.max(etc_y) == 0.0
    assert np.min(etc_y) < -3.0
    assert np.all(etc_y <= 0.0)


def test_update_ir_plot_clears_etc_for_empty_or_silent_ir(qtbot):
    widget = _make_widget(qtbot)

    widget.update_ir_plot(np.array([]), np.array([]))
    etc_x, etc_y = widget.etc_curve.getData()
    assert _curve_len(etc_x) == 0
    assert _curve_len(etc_y) == 0

    widget.update_ir_plot(np.arange(4, dtype=float), np.zeros(4))
    etc_x, etc_y = widget.etc_curve.getData()
    assert _curve_len(etc_x) == 0
    assert _curve_len(etc_y) == 0
