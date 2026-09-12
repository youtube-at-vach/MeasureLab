from unittest.mock import MagicMock

import numpy as np
import pytest

from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer, SpectrumAnalyzerWidget
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper
from src.gui.module_registry import MODULE_REGISTRY
from src.core.module_constants import MODULE_SPECTRUM_ANALYZER


@pytest.fixture
def widget(qapp):
    engine = MagicMock()
    engine.sample_rate = 48000
    engine.calibration.get_spl_offset_db.return_value = None
    w = SpectrumAnalyzerWidget(SpectrumAnalyzer(engine))
    w.resize(1180, 690)
    w.show()
    qapp.processEvents()
    yield w
    w.timer.stop()
    w.close()
    w.deleteLater()
    qapp.processEvents()


def data():
    f = np.arange(0, 20001, 10.0)
    y = np.full(len(f), -100.0)
    y[100] = -20
    y[300] = -40
    return f, y


def update(w):
    f, y = data()
    w._update_peak_markers(f, y, f, y)


def test_off_skips_detection_and_does_not_allocate_items(widget, monkeypatch):
    detector = MagicMock(side_effect=AssertionError("Off must skip detection"))
    # Import-isolation tests can replace package attributes; patch the namespace
    # actually used by this widget rather than resolving the module again.
    monkeypatch.setitem(widget._update_peak_markers.__func__.__globals__, "detect_spectrum_peaks", detector)
    update(widget)
    assert not widget._marker_items
    assert widget._marker_symbols is None
    detector.assert_not_called()


def test_rate_limit_and_item_reuse(widget, monkeypatch):
    clock = MagicMock(return_value=10.0)
    monkeypatch.setattr("src.gui.widgets.spectrum_analyzer.time.monotonic", clock)
    widget.marker_mode = "raw"
    update(widget)
    items = tuple(widget._marker_items)
    assert len(items) == 5
    assert widget._marker_symbols.isVisible()
    before = widget._marker_symbols.data.copy()
    f, y = data()
    y[100] = -60
    widget._update_peak_markers(f, y, f, y)
    assert np.array_equal(widget._marker_symbols.data["y"], before["y"])
    clock.return_value = 10.21
    widget._update_peak_markers(f, y, f, y)
    assert tuple(widget._marker_items) == items
    assert sorted(widget._marker_symbols.data["y"]) == [-60, -40]


def test_display_and_raw_sources_are_distinct(widget):
    f, raw = data()
    display = np.full(len(f), -100.0)
    display[200] = -35
    widget.marker_mode = "display"
    widget._update_peak_markers(f, raw, f, display)
    assert list(widget._marker_symbols.data["x"]) == [np.log10(2000)]
    widget.marker_mode = "raw"
    widget._update_peak_markers(f, raw, f, display)
    assert list(widget._marker_symbols.data["x"]) == [np.log10(1000), np.log10(3000)]


def test_dual_psd_units_and_invalid_frame(widget):
    f, y = data()
    widget.module.analysis_mode = "PSD"
    widget.module.channel_mode = "Dual"
    widget.module.display_unit = "dBV"
    widget.marker_mode = "raw"
    dual = np.column_stack((y, y - 3))
    widget._update_peak_markers(f, dual, f, dual)
    assert "dBV/√Hz (Z)" in widget.marker_button.text()
    text = "\n".join(item.textItem.toPlainText() for item in widget._marker_items)
    assert "Left" in text and "Right" in text
    widget._clear_peak_markers()
    widget._update_peak_markers(f, np.full_like(y, np.nan), f, y)
    assert not widget._marker_symbols.isVisible()
    assert not any(item.isVisible() for item in widget._marker_items)


def test_split_compact_and_reattach_keep_overlay_and_settings(widget, qapp):
    widget.marker_mode = "raw"
    update(widget)
    items = tuple(widget._marker_items)
    wrapper = DetachableWidgetWrapper(
        widget, "Spectrum Analyzer", capabilities=MODULE_REGISTRY[MODULE_SPECTRUM_ANALYZER].capabilities
    )
    wrapper.show()
    wrapper.split()
    widget.set_compact_mode(True)
    qapp.processEvents()
    update(widget)
    assert widget.marker_button.isVisible()
    assert not widget.controls_group.isHidden()
    assert widget.marker_mode == "raw"
    assert tuple(widget._marker_items) == items
    wrapper.reattach_all()
    widget.setParent(None)
    wrapper.close()
    wrapper.deleteLater()
    qapp.processEvents()


def test_setting_and_view_changes_clear_stale_markers(widget):
    widget.marker_mode = "raw"
    update(widget)
    widget.unit_combo.setCurrentText("dBV")
    assert not widget._marker_symbols.isVisible()
    assert "dBV" in widget.marker_button.text()
    update(widget)
    widget.plot_widget.setXRange(3.5, 4)
    assert not widget._marker_symbols.isVisible()


def test_dialog_applies_settings_and_cancel_preserves_them(widget, qapp):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QComboBox, QDialog, QDoubleSpinBox

    def apply():
        dialog = qapp.activeModalWidget()
        assert isinstance(dialog, QDialog)
        dialog.findChild(QComboBox).setCurrentIndex(2)
        for control, value in zip(dialog.findChildren(QDoubleSpinBox), [12, 250, -70], strict=True):
            control.setValue(value)
        dialog.accept()

    QTimer.singleShot(0, apply)
    widget.configure_peak_markers()
    assert (widget.marker_mode, widget.marker_prominence, widget.marker_spacing_hz, widget.marker_noise_floor) == (
        "raw",
        12,
        250,
        -70,
    )

    def cancel():
        dialog = qapp.activeModalWidget()
        dialog.findChild(QComboBox).setCurrentIndex(0)
        dialog.reject()

    QTimer.singleShot(0, cancel)
    widget.configure_peak_markers()
    assert widget.marker_mode == "raw"
    update(widget)

    def disable():
        dialog = qapp.activeModalWidget()
        dialog.findChild(QComboBox).setCurrentIndex(0)
        dialog.accept()

    QTimer.singleShot(0, disable)
    widget.configure_peak_markers()
    assert widget.marker_mode == "off"
    assert not widget._marker_symbols.isVisible()


@pytest.mark.parametrize("language", ["de", "en", "es", "fr", "ja", "ko", "pt", "ru", "zh"])
def test_marker_dialog_and_enabled_widget_fit_all_languages(qapp, language):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QDialog, QDoubleSpinBox
    from src.core.localization import get_manager

    manager = get_manager()
    original = manager.language
    manager.load_language(language)
    engine = MagicMock()
    engine.calibration.get_spl_offset_db.return_value = 100.0
    w = SpectrumAnalyzerWidget(SpectrumAnalyzer(engine))
    try:
        w.module.display_unit = "dB SPL"
        w.module.analysis_mode = "PSD"
        w.marker_mode = "display"
        w._update_marker_button()
        w.resize(1180, 690)
        w.show()
        qapp.processEvents()
        assert w.minimumSizeHint().width() <= 1180
        assert w.minimumSizeHint().height() <= 690

        def inspect():
            dialog = qapp.activeModalWidget()
            assert isinstance(dialog, QDialog)
            assert dialog.minimumSizeHint().width() <= 1180
            assert dialog.minimumSizeHint().height() <= 690
            for control in dialog.findChildren(QDoubleSpinBox):
                assert control.width() >= control.minimumSizeHint().width()
            dialog.reject()

        QTimer.singleShot(0, inspect)
        w.configure_peak_markers()
    finally:
        w.timer.stop()
        w.close()
        w.deleteLater()
        qapp.processEvents()
        manager.load_language(original)


def test_rta_integration_uses_band_peaks_and_keeps_raw_separate(widget):
    f, y = data()
    widget.module.is_running = True
    widget.module.rta_mode = True
    widget.module.process_queue = MagicMock()
    widget.module.compute_spectrum = MagicMock(
        return_value=dict(freqs=f, magnitude=y, overall_weighted_db=-20, peak_magnitude=None)
    )
    bands = np.array([100.0, 200.0, 400.0, 800.0, 1600.0])
    levels = np.array([-100.0, -100.0, -35.0, -100.0, -100.0])
    widget.module.apply_octave_smoothing = MagicMock(return_value=(bands, levels))
    widget.marker_mode = "display"
    widget.update_plot()
    assert list(widget._marker_symbols.data["x"]) == [np.log10(400)]
    widget.marker_mode = "raw"
    widget.update_plot()
    assert list(widget._marker_symbols.data["x"]) == [np.log10(1000), np.log10(3000)]


def test_missing_frame_clears_overlay_but_stopped_update_retains_it(widget):
    widget.marker_mode = "raw"
    update(widget)
    widget.module.is_running = False
    widget.update_plot()
    assert widget._marker_symbols.isVisible()
    widget.module.is_running = True
    widget.module.process_queue = MagicMock()
    widget.module.compute_spectrum = MagicMock(return_value=None)
    widget.update_plot()
    assert not widget._marker_symbols.isVisible()


def test_large_raw_fft_reduces_only_marker_refresh_rate(widget, monkeypatch):
    clock = MagicMock(return_value=10.0)
    detector = MagicMock(return_value=[])
    monkeypatch.setattr("src.gui.widgets.spectrum_analyzer.time.monotonic", clock)
    # Import-isolation tests can replace package attributes; patch the namespace
    # actually used by this widget rather than resolving the module again.
    monkeypatch.setitem(widget._update_peak_markers.__func__.__globals__, "detect_spectrum_peaks", detector)
    widget.marker_mode = "raw"
    interval_before = widget.timer.interval()
    f = np.linspace(0, 24000, 2097153)
    y = np.zeros_like(f)
    widget._update_peak_markers(f, y, f, y)
    clock.return_value = 10.3
    widget._update_peak_markers(f, y, f, y)
    assert detector.call_count == 1
    clock.return_value = 11.1
    widget._update_peak_markers(f, y, f, y)
    assert detector.call_count == 2
    assert widget.timer.interval() == interval_before
