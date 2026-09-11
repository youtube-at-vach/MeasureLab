"""IMD controls integrated into the existing distortion sweep tab."""

from pathlib import Path
import uuid

import numpy as np
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QLabel,
    QSpinBox,
    QPushButton,
    QHBoxLayout,
    QFileDialog,
    QWidget,
    QFormLayout,
    QProgressBar,
)

from src.core.comparison_manager import ComparisonTrace, AxisMetadata, CalibrationInfo
from src.core.imd_sweep import PROFILES, SweepSettings, serialize, snapshot_copy, valid_segments
from src.core.localization import tr
from src.gui.widgets.imd_sweep_worker import IMDSweepWorker


class IMDExportWorker(QThread):
    saved = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, snapshot, path, format):
        super().__init__()
        self.snapshot, self.path, self.format = snapshot_copy(snapshot), path, format

    def run(self):
        try:
            # Write a sibling temporary file, then replace; failed saves retain the result.
            import os
            import tempfile

            destination = Path(self.path)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", newline="", delete=False, dir=destination.parent
                ) as output:
                    temporary = output.name
                    output.write(serialize(self.snapshot, self.format))
                os.replace(temporary, destination)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
            self.saved.emit(self.path)
        except Exception as exc:
            self.failed.emit(str(exc))


class IMDSweepUI:
    def _create_imd_controls(self, layout):
        self.imd_profile_combo = QComboBox()
        names = [
            tr("SMPTE stimulus / FFT sideband IMD"),
            tr("DIN stimulus / FFT sideband IMD"),
            tr("CCIF stimulus / d2"),
        ]
        for key, name in zip(PROFILES, names, strict=True):
            self.imd_profile_combo.addItem(name, key)
        self.imd_profile_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.imd_profile_combo.setMinimumContentsLength(16)
        self.imd_controls = []
        for label, control in ((tr("IMD method:"), self.imd_profile_combo),):
            text = QLabel(label)
            layout.addRow(text, control)
            self.imd_controls.extend([text, control])
        self.imd_info = QLabel()
        self.imd_info.setWordWrap(True)
        layout.addRow(self.imd_info)
        self.imd_controls.append(self.imd_info)
        self.imd_advanced = QWidget()
        advanced_layout = QFormLayout(self.imd_advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        self.imd_advanced_toggle = QPushButton()
        self.imd_advanced_toggle.setCheckable(True)
        self.imd_advanced_toggle.toggled.connect(self._toggle_imd_advanced)
        self.imd_controls.append(self.imd_advanced_toggle)
        for attr, label, low, high, default, step in (
            ("imd_settling", tr("Settling (ms):"), 100, 30000, 500, 100),
            ("imd_capture", tr("Record length (ms):"), 200, 2000, 500, 100),
            ("imd_averages", tr("Power averages:"), 1, 32, 4, 1),
            ("imd_fade", tr("Output fade (ms):"), 20, 30000, 20, 10),
        ):
            spin = QSpinBox()
            spin.setRange(low, high)
            spin.setValue(default)
            spin.setSingleStep(step)
            setattr(self, attr, spin)
            text = QLabel(label)
            text.setBuddy(spin)
            spin.setKeyboardTracking(False)
            advanced_layout.addRow(text, spin)
        self.imd_profile_combo.currentIndexChanged.connect(self._imd_description)
        self.imd_capture.valueChanged.connect(self._imd_description)
        self.imd_averages.valueChanged.connect(self._update_imd_advanced_label)
        self._imd_description()
        self.imd_advanced.hide()
        for control in self.imd_controls:
            control.hide()

    def _append_imd_acquisition_controls(self, layout):
        layout.addRow(self.imd_advanced_toggle)
        layout.addRow(self.imd_advanced)

    def _update_imd_advanced_label(self):
        arrow = "▾" if self.imd_advanced_toggle.isChecked() else "▸"
        self.imd_advanced_toggle.setText(
            arrow + " " + tr("Acquisition: {0} ms × {1}").format(self.imd_capture.value(), self.imd_averages.value())
        )

    def _toggle_imd_advanced(self, expanded):
        self.imd_advanced.setVisible(expanded)
        self._update_imd_advanced_label()

    def _imd_description(self):
        self._update_imd_advanced_label()
        p = PROFILES[self.imd_profile_combo.currentData()]
        text = tr("{0} Hz + {1} Hz; {2}:1; dBFS (sum peak). No weighting or frequency correction.").format(
            p.f1, p.f2, p.ratio
        )
        if p.profile_id == "ccif_d2_v1":
            text += " " + tr(
                "CCIF d2 uses the mean carrier amplitude. High-frequency DAC/ADC response is not guaranteed."
            )
        else:
            text += " " + tr(
                "FFT sideband ratio includes noise and FM/PM; not an AM-demodulation compliance measurement."
            )
        summary = f"{p.f1} Hz + {p.f2} Hz · {p.ratio}:1"
        if p.profile_id == "ccif_d2_v1":
            summary += "\n" + tr("High-frequency response unverified")
        try:
            from src.core.imd_sweep import BandPlan

            plan = BandPlan(
                SweepSettings(profile_id=p.profile_id, capture_ms=self.imd_capture.value()),
                float(self.module.audio_engine.sample_rate),
            )
            warning = " / ".join(self._imd_reason(w) for w in plan.warnings)
            if warning:
                summary += "\n" + warning
                text += " " + warning
        except ValueError as exc:
            summary += "\n" + self._imd_reason(str(exc))
            text += " " + self._imd_reason(str(exc))
        self.imd_info.setText(summary)
        self.imd_info.setToolTip(text)
        self.imd_profile_combo.setToolTip(self.imd_profile_combo.currentText() + "\n" + text)
        if hasattr(self, "sweep_plot") and self.mode_combo.currentIndex() == 3:
            self._plot_imd()

    def _create_imd_actions(self, layout):
        self.imd_status = QLabel()
        self.imd_status.setWordWrap(True)
        layout.addWidget(self.imd_status)
        self.imd_progress = QProgressBar()
        self.imd_progress.setRange(0, 20)
        self.imd_progress.setValue(0)
        self.imd_progress.hide()
        layout.addWidget(self.imd_progress)
        self.imd_readout = QLabel()
        self.imd_readout.setWordWrap(True)
        self.imd_readout.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.imd_readout)
        row = QHBoxLayout()
        self.imd_save = QPushButton(tr("Export"))
        self.imd_reset = QPushButton(tr("Reset"))
        self.imd_save.clicked.connect(self._save_imd)
        self.imd_reset.clicked.connect(self._reset_imd)
        row.addWidget(self.imd_save)
        row.addWidget(self.imd_reset)
        layout.addLayout(row)
        self.imd_save.hide()
        self.imd_reset.hide()
        self.imd_export_worker = None
        self.imd_worker = None
        self._imd_close_pending = False

    def _imd_mode_visibility(self, enabled):
        for control in self.imd_controls:
            control.setVisible(enabled)
        self.imd_save.setVisible(enabled)
        self.imd_reset.setVisible(enabled)
        self.imd_status.setVisible(enabled)
        self.imd_progress.setVisible(enabled and bool(self.module.imd_snapshot))
        self.imd_readout.setVisible(enabled)
        self.imd_advanced.setVisible(enabled and self.imd_advanced_toggle.isChecked())
        self.settings_tabs.setTabEnabled(0, not enabled)
        for tab in (0, 1):
            self.tabs.setTabEnabled(tab, not enabled)
        for control in (self.avg_spin, self.filter_combo):
            control.setEnabled(not enabled)
        self.sweep_y_unit_combo.setItemText(0, "dB")
        self.imd_save.setEnabled(bool(self.module.imd_snapshot))
        self.imd_reset.setEnabled(bool(self.module.imd_snapshot))

    def _start_imd(self):
        if self.imd_worker is not None and self.imd_worker.isRunning():
            return
        settings = SweepSettings(
            profile_id=self.imd_profile_combo.currentData(),
            start_dbfs=self.sweep_start_spin.value(),
            end_dbfs=self.sweep_end_spin.value(),
            steps=self.sweep_steps_spin.value(),
            settling_ms=self.imd_settling.value(),
            capture_ms=self.imd_capture.value(),
            averages=self.imd_averages.value(),
            fade_ms=self.imd_fade.value(),
        )
        self.module.imd_snapshot = None
        self.sweep_curve.clear()
        self.imd_readout.clear()
        self.imd_worker = IMDSweepWorker(self.module, settings)
        self.module.imd_cancel = self.imd_worker.stop
        self.imd_worker.snapshot_ready.connect(self._on_imd_snapshot)
        self.imd_worker.finished.connect(self._on_imd_finished)
        self.mode_combo.setEnabled(False)
        self.settings_tabs.setEnabled(False)
        self.imd_save.setEnabled(False)
        self.imd_reset.setEnabled(False)
        self.action_btn.setChecked(True)
        self.action_btn.setText(tr("Cancel"))
        self.imd_progress.show()
        self.imd_progress.setRange(0, settings.steps)
        self.imd_progress.setValue(0)
        self.imd_status.setText(tr("Starting IMD sweep..."))
        self.imd_worker.start()
        self.apply_theme()

    def _on_imd_snapshot(self, snapshot):
        if self.imd_worker is None or snapshot["run_id"] != self.imd_worker.run_id:
            return
        self.module.imd_snapshot = snapshot
        self.imd_progress.show()
        self.imd_progress.setRange(0, snapshot["planned_points"])
        self.imd_progress.setValue(snapshot["acquired_points"])
        self._plot_imd()
        if snapshot["steps"]:
            self._imd_show_point(snapshot["steps"][-1])
        warnings = sorted(
            set(
                snapshot["warnings"]
                + [flag for s in snapshot["steps"] for flag in s["flags"]]
                + ([snapshot["reason"]] if snapshot["reason"] else [])
            )
        )
        state = {
            "running": tr("Running"),
            "completed": tr("Completed"),
            "cancelled": tr("Cancelled"),
            "failed": tr("Failed"),
        }
        if snapshot["status"] != "running" and not snapshot["complete"]:
            state[snapshot["status"]] += " / " + tr("Partial result")
        quality = {"valid": tr("Valid"), "qualified": tr("Qualified"), "invalid": tr("Invalid")}
        self.imd_status.setToolTip(
            tr("{0}: {1}/{2}; {3}. {4}").format(
                state[snapshot["status"]],
                snapshot["acquired_points"],
                snapshot["planned_points"],
                quality[snapshot["quality"]],
                ", ".join(self._imd_reason(flag) for flag in warnings),
            )
        )

        summary = state[snapshot["status"]]
        if snapshot["reason"]:
            summary += " · " + self._imd_reason(snapshot["reason"])
        elif warnings == ["uncalibrated"]:
            summary += " · " + tr("Uncalibrated")
        elif warnings:
            summary += " · " + tr("Warnings") + f": {len(warnings)}"
        self.imd_status.setText(summary)

    @staticmethod
    def _imd_reason(reason):
        reasons = {
            "near_nyquist": tr("Near Nyquist; check measurement bandwidth"),
            "uncalibrated": tr("Uncalibrated: relative results only"),
            "cancelled": tr("Cancelled"),
            "settings_changed": tr("Settings changed; run stopped"),
            "input_full_scale": tr("Input reached full scale; reduce input level"),
            "output_clipping": tr("Output overloaded; reduce output level"),
            "carrier_below_threshold": tr("Carrier missing or too weak"),
            "carrier_not_prominent": tr("Carrier is not distinguishable from noise"),
            "carrier_frequency_mismatch": tr("Carrier frequency mismatch"),
            "xrun": tr("Audio buffer error"),
            "input_discontinuity": tr("Input data missing"),
            "capture_timeout": tr("Audio capture timed out"),
            "nonfinite_input": tr("Non-finite input"),
            "stream_stopped": tr("Audio stream stopped"),
            "output_disabled": tr("Enable output and unmute before starting"),
            "invalid_channel": tr("Selected channel is unavailable"),
            "band_out_of_range": tr("Measurement bands exceed the sample-rate range"),
            "overlapping_bands": tr("Measurement bands overlap"),
            "insufficient_noise_bins": tr("Insufficient reference noise bins"),
            "invalid_level": tr("Use finite levels between -100 and 0 dBFS"),
            "equal_levels": tr("Start and end levels must differ"),
            "invalid_acquisition_settings": tr("Invalid acquisition settings"),
            "invalid_calibration": tr("Invalid calibration"),
            "worker_exception": tr("Measurement failed; inspect saved diagnostics"),
            "callback_exception": tr("Audio callback failed"),
        }
        return reasons.get(reason, tr("Measurement failed; inspect saved diagnostics"))

    def _on_imd_finished(self):
        self.module.imd_cancel = None
        self.mode_combo.setEnabled(True)
        self.settings_tabs.setEnabled(True)
        self.action_btn.setEnabled(True)
        self.action_btn.setChecked(False)
        self.action_btn.setText(tr("Start Measurement"))
        self.imd_save.setEnabled(bool(self.module.imd_snapshot))
        self.imd_reset.setEnabled(bool(self.module.imd_snapshot))
        self.apply_theme()
        if self._imd_close_pending:
            self.close()

    def _plot_imd(self):
        snapshot = self.module.imd_snapshot
        percent = self.sweep_y_unit_combo.currentIndex() == 1
        self.sweep_plot.setLogMode(x=False, y=False)
        self.sweep_plot.setLabel("bottom", tr("Amplitude"), units=tr("dBFS (sum peak)"))
        self.sweep_axis.setTicks(None)
        self.sweep_plot.getPlotItem().getAxis("left").setTicks(None)
        self.sweep_plot.setLabel(
            "left",
            "CCIF d2"
            if (snapshot["metadata"].get("profile_id") if snapshot else self.imd_profile_combo.currentData())
            == "ccif_d2_v1"
            else "FFT IMD",
            units="%" if percent else "dB",
        )
        self.sweep_plot.setTitle(
            self.imd_profile_name(snapshot)
            if snapshot and snapshot["metadata"].get("profile_id") != self.imd_profile_combo.currentData()
            else None
        )
        self.sweep_plot.getPlotItem().getAxis("left").setToolTip(tr("dB relative to reference"))
        for axis in (self.sweep_axis, self.sweep_plot.getPlotItem().getAxis("left")):
            # pyqtgraph 0.14 recalculates a prefix even when disabling it.
            # Empty enable ranges also clear a prefix inherited from THD axes.
            if hasattr(axis, "setSIPrefixEnableRanges"):
                axis.setSIPrefixEnableRanges(())
            axis.enableAutoSIPrefix(False)
        if not snapshot:
            self.sweep_curve.clear()
            self.sweep_plot.setXRange(-40, -3)
            self.sweep_plot.setYRange(0 if percent else -100, 1 if percent else 0)
            return
        points = []
        for segment in valid_segments(snapshot, percent, display_floor=True):
            if points:
                points.append((float("nan"), float("nan")))
            points.extend(segment)
        if points:
            values = np.asarray(points)
            self.sweep_curve.setData(values[:, 0], values[:, 1], connect="finite", symbol="o", symbolSize=5)
            self.sweep_plot.autoRange()
        else:
            self.sweep_curve.clear()

    def _imd_point_clicked(self, curve, points, event):
        if self.mode_combo.currentIndex() != 3 or not points or not self.module.imd_snapshot:
            return
        level = points[0].pos().x()
        for step in self.module.imd_snapshot["steps"]:
            if abs(step["command_dbfs"] - level) < 1e-8:
                self._imd_show_point(step)
                break

    def _imd_show_point(self, step):
        level = f"{step['command_dbfs']:.2f}"
        value = tr("Invalid") if step["ratio"] is None else f"{step['percent']:.5g} %"
        relative = "—" if step["relative_dB"] is None else f"{step['relative_dB']:.3f}"
        self.imd_readout.setText(f"{level} dBFS → {value} / {relative} dB")
        self.imd_readout.setToolTip(
            tr("Point at {0} dBFS (sum peak): {1}; {2} dB relative to reference").format(level, value, relative)
        )

    def imd_profile_name(self, snapshot):
        key = snapshot["metadata"].get("profile_id")
        index = self.imd_profile_combo.findData(key)
        return self.imd_profile_combo.itemText(index) if index >= 0 else tr("IMD amplitude sweep")

    def _imd_comparable(self):
        snapshot = self.module.imd_snapshot
        if not snapshot or snapshot["status"] == "running":
            return []
        percent = self.sweep_y_unit_combo.currentIndex() == 1
        traces = []
        for index, segment in enumerate(valid_segments(snapshot, percent)):
            cal = snapshot["metadata"]["calibration"]
            traces.append(
                ComparisonTrace(
                    id=str(uuid.uuid4()),
                    name=f"{self.imd_profile_name(snapshot)} / {snapshot['status']} / "
                    f"{tr('dB relative to reference')} / {index + 1}"
                    + (" / " + tr("Partial result") if not snapshot["complete"] else ""),
                    source_module="Distortion Analyzer",
                    timestamp=snapshot["started_at"],
                    plot_type="xy_plot",
                    x_axis=AxisMetadata("amplitude", "dBFS_peak_sum", "dBFS (sum peak)"),
                    y_axis=AxisMetadata("distortion", "%" if percent else "dB", "%" if percent else "dB"),
                    x_data=[p[0] for p in segment],
                    y_data=[p[1] for p in segment],
                    calibration=CalibrationInfo(
                        is_calibrated=cal["valid"], input_sensitivity=cal["input_sensitivity_Vpeak_per_FS"] or 1
                    ),
                    metadata=snapshot_copy(snapshot),
                )
            )
        return traces

    def _reset_imd(self):
        if self.imd_worker and self.imd_worker.isRunning():
            return
        self.module.imd_snapshot = None
        self.sweep_curve.clear()
        self.imd_status.clear()
        self.imd_progress.setValue(0)
        self.imd_progress.hide()
        self.imd_readout.clear()
        self.imd_save.setEnabled(False)
        self.imd_reset.setEnabled(False)

    def _save_imd(self):
        if self.imd_export_worker and self.imd_export_worker.isRunning():
            return
        if not self.module.imd_snapshot or self.module.imd_snapshot["status"] == "running":
            return
        path, selected = QFileDialog.getSaveFileName(
            self, tr("Save IMD result"), "imd_sweep.json", "JSON (*.json);;CSV (*.csv)"
        )
        if not path:
            return
        format = "csv" if selected.startswith("CSV") else "json"
        self.imd_export_worker = IMDExportWorker(self.module.imd_snapshot, path, format)
        self.imd_export_worker.saved.connect(lambda p: self.imd_status.setText(tr("Saved: {0}").format(p)))
        self.imd_export_worker.failed.connect(lambda e: self.imd_status.setText(tr("Save failed: {0}").format(e)))
        self.imd_export_worker.finished.connect(self._imd_export_finished)
        self.imd_save.setEnabled(False)
        self.imd_export_worker.start()

    def _imd_export_finished(self):
        self.imd_save.setEnabled(bool(self.module.imd_snapshot))
        if self._imd_close_pending:
            self.close()
