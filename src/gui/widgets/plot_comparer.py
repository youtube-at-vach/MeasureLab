import logging
import numpy as np
import pyqtgraph as pg

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QFileDialog,
    QMessageBox,
    QSplitter,
)

from src.measurement_modules.base import MeasurementModule
from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.core.comparison_manager import ComparisonManager

logger = logging.getLogger(__name__)


class PlotComparer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine

    @property
    def name(self) -> str:
        return "Plot Comparer"

    @property
    def description(self) -> str:
        return tr("Compare plots from different measurements.")

    def get_widget(self):
        return PlotComparerWidget(self)


class PlotComparerWidget(QWidget):
    # Color palette for traces (beautiful neon colors for dark mode, dark rich colors for light mode)
    COLORS_DARK = ["#00ff00", "#00ffff", "#ffff00", "#ff00ff", "#ff8800", "#ff3333", "#3388ff", "#ffffff"]
    COLORS_LIGHT = ["#008800", "#008888", "#888800", "#880088", "#d35400", "#c0392b", "#2980b9", "#2c3e50"]

    def __init__(self, module: PlotComparer):
        super().__init__()
        self.module = module
        self.manager = ComparisonManager.instance()
        self._is_dark_theme = False

        # Trace rendering settings (offset, visibility, color index)
        # trace_id -> dict(visible=bool, offset_db=float, shift=float, color=str)
        self.trace_settings = {}
        self.curve_items = {}  # trace_id -> (y_curve, y2_curve)

        self.init_ui()

        # Connect comparison manager signals
        self.manager.trace_added.connect(self.on_trace_added)
        self.manager.trace_removed.connect(self.on_trace_removed)
        self.manager.cleared.connect(self.on_traces_cleared)

        # Apply initial theme
        self.app = QApplication.instance() if hasattr(QApplication, "instance") else None
        if self.app and hasattr(self.app, "theme_manager"):
            self.app.theme_manager.theme_changed.connect(self.apply_theme)
            self.apply_theme(self.app.theme_manager.get_current_theme())

        # Populate initial traces
        self.refresh_trace_list()
        self.replot()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # Splitter to allow resizing plot vs controls
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter)

        # --- Left Panel: Plot Area ---
        plot_container = QWidget()
        plot_layout = QVBoxLayout(plot_container)
        plot_layout.setContentsMargins(0, 0, 0, 0)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.setLabel("bottom", tr("X Axis"))
        self.plot_widget.setLabel("left", tr("Y Axis"))
        plot_layout.addWidget(self.plot_widget)

        # Setup secondary Y-axis (for phase/distortion)
        self.plot_item = self.plot_widget.plotItem
        self.y2_view = pg.ViewBox()
        self.plot_item.scene().addItem(self.y2_view)
        self.plot_item.getAxis("right").linkToView(self.y2_view)
        self.y2_view.setXLink(self.plot_item)

        # Connect resize event to keep secondary axis synchronized
        self.plot_item.vb.sigResized.connect(self.update_y2_views)

        self.splitter.addWidget(plot_container)

        # --- Right Panel: Controls ---
        controls_widget = QWidget()
        controls_widget.setMinimumWidth(300)
        controls_widget.setMaximumWidth(450)
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(5, 5, 5, 5)

        # Trace List Group
        list_group = QGroupBox(tr("Traces"))
        list_layout = QVBoxLayout(list_group)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list_widget.itemChanged.connect(self.on_item_changed)
        self.list_widget.itemSelectionChanged.connect(self.on_selection_changed)
        list_layout.addWidget(self.list_widget)

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.btn_import = QPushButton(tr("Import File"))
        self.btn_import.clicked.connect(self.import_file)
        self.btn_export = QPushButton(tr("Export Selected"))
        self.btn_export.clicked.connect(self.export_selected)
        self.btn_remove = QPushButton(tr("Delete"))
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear = QPushButton(tr("Clear All"))
        self.btn_clear.clicked.connect(self.clear_all)

        btn_layout.addWidget(self.btn_import)
        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(self.btn_remove)
        btn_layout.addWidget(self.btn_clear)
        list_layout.addLayout(btn_layout)

        controls_layout.addWidget(list_group)

        # Parameter Adjustments Group
        adjust_group = QGroupBox(tr("Trace Adjustments"))
        adjust_layout = QFormLayout(adjust_group)

        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-120.0, 120.0)
        self.offset_spin.setValue(0.0)
        self.offset_spin.setSuffix(" dB")
        self.offset_spin.setDecimals(1)
        self.offset_spin.setSingleStep(1.0)
        self.offset_spin.valueChanged.connect(self.on_offset_changed)
        self.offset_spin.setEnabled(False)
        adjust_layout.addRow(tr("Gain Offset:"), self.offset_spin)

        self.shift_spin = QDoubleSpinBox()
        self.shift_spin.setRange(-10.0, 10.0)
        self.shift_spin.setValue(0.0)
        self.shift_spin.setSuffix(" s")
        self.shift_spin.setDecimals(4)
        self.shift_spin.setSingleStep(0.001)
        self.shift_spin.valueChanged.connect(self.on_shift_changed)
        self.shift_spin.setEnabled(False)
        adjust_layout.addRow(tr("Time Shift:"), self.shift_spin)

        controls_layout.addWidget(adjust_group)

        # Global Options Group
        options_group = QGroupBox(tr("Global Options"))
        options_layout = QVBoxLayout(options_group)

        self.normalize_check = QCheckBox(tr("Normalize (Align Peaks)"))
        self.normalize_check.toggled.connect(self.replot)
        options_layout.addWidget(self.normalize_check)

        controls_layout.addWidget(options_group)
        controls_layout.addStretch()

        self.splitter.addWidget(controls_widget)

        # Default splitter weights
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)

    def update_y2_views(self):
        try:
            self.y2_view.setGeometry(self.plot_item.vb.sceneBoundingRect())
        except Exception:
            pass

    def get_color(self, idx: int) -> str:
        colors = self.COLORS_DARK if self._is_dark_theme else self.COLORS_LIGHT
        return colors[idx % len(colors)]

    def refresh_trace_list(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()

        traces = self.manager.get_all_traces()
        for idx, (tid, trace) in enumerate(traces.items()):
            # Initialize settings if new
            if tid not in self.trace_settings:
                self.trace_settings[tid] = {
                    "visible": True,
                    "offset_db": 0.0,
                    "shift": 0.0,
                    "color": self.get_color(idx),
                }

            item = QListWidgetItem(trace.name)
            item.setData(Qt.ItemDataRole.UserRole, tid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)

            # Set checked state based on settings
            state = Qt.CheckState.Checked if self.trace_settings[tid]["visible"] else Qt.CheckState.Unchecked
            item.setCheckState(state)

            # Set brush color for list hint
            from PyQt6.QtGui import QColor, QBrush
            color = QColor(self.trace_settings[tid]["color"])
            item.setForeground(QBrush(color))

            self.list_widget.addItem(item)

        self.list_widget.blockSignals(False)

    def on_item_changed(self, item: QListWidgetItem):
        tid = item.data(Qt.ItemDataRole.UserRole)
        if not tid:
            return

        # Handle Rename
        trace = self.manager.get_trace(tid)
        if trace and item.text() != trace.name:
            trace.name = item.text()
            logger.info(f"Trace renamed to: {trace.name}")

        # Handle Visibility
        visible = item.checkState() == Qt.CheckState.Checked
        if tid in self.trace_settings:
            self.trace_settings[tid]["visible"] = visible

        self.replot()

    def on_selection_changed(self):
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            self.offset_spin.setEnabled(False)
            self.shift_spin.setEnabled(False)
            return

        tid = selected_items[0].data(Qt.ItemDataRole.UserRole)
        if tid in self.trace_settings:
            self.offset_spin.setEnabled(True)
            self.offset_spin.blockSignals(True)
            self.offset_spin.setValue(self.trace_settings[tid]["offset_db"])
            self.offset_spin.blockSignals(False)

            self.shift_spin.setEnabled(True)
            self.shift_spin.blockSignals(True)
            self.shift_spin.setValue(self.trace_settings[tid]["shift"])
            self.shift_spin.blockSignals(False)
        else:
            self.offset_spin.setEnabled(False)
            self.shift_spin.setEnabled(False)

    def on_offset_changed(self, val):
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return
        tid = selected_items[0].data(Qt.ItemDataRole.UserRole)
        if tid in self.trace_settings:
            self.trace_settings[tid]["offset_db"] = val
            self.replot()

    def on_shift_changed(self, val):
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return
        tid = selected_items[0].data(Qt.ItemDataRole.UserRole)
        if tid in self.trace_settings:
            self.trace_settings[tid]["shift"] = val
            self.replot()

    def on_trace_added(self, trace_id: str):
        self.refresh_trace_list()
        self.replot()

    def on_trace_removed(self, trace_id: str):
        if trace_id in self.trace_settings:
            del self.trace_settings[trace_id]
        self.refresh_trace_list()
        self.replot()

    def on_traces_cleared(self):
        self.trace_settings.clear()
        self.refresh_trace_list()
        self.replot()

    def remove_selected(self):
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return
        tid = selected_items[0].data(Qt.ItemDataRole.UserRole)
        self.manager.remove_trace(tid)

    def clear_all(self):
        self.manager.clear_all_traces()

    def import_file(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, tr("Import Traces"), "", "MeasureLab Comparison Files (*.mlcomp *.json)"
        )
        if filepath:
            imported = self.manager.import_from_file(filepath)
            if imported:
                QMessageBox.information(
                    self, tr("Success"), tr("Successfully imported {0} traces.").format(len(imported))
                )
            else:
                QMessageBox.warning(self, tr("Error"), tr("Failed to import traces from file."))

    def export_selected(self):
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            # If nothing is explicitly selected, export all checked traces
            trace_ids = [
                self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.list_widget.count())
                if self.list_widget.item(i).checkState() == Qt.CheckState.Checked
            ]
        else:
            trace_ids = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items]

        if not trace_ids:
            QMessageBox.warning(self, tr("Export"), tr("Please select or check traces to export."))
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, tr("Export Selected Traces"), "comparison_export.mlcomp", "MeasureLab Comparison Files (*.mlcomp)"
        )
        if filepath:
            ok = self.manager.export_to_file(filepath, trace_ids)
            if ok:
                QMessageBox.information(self, tr("Success"), tr("Traces exported successfully."))
            else:
                QMessageBox.warning(self, tr("Error"), tr("Failed to export traces."))

    def replot(self):
        # 1. Clear current plots
        self.plot_widget.clear()
        self.y2_view.clear()
        self.curve_items.clear()

        traces = self.manager.get_all_traces()
        visible_traces = {
            tid: trace
            for tid, trace in traces.items()
            if tid in self.trace_settings and self.trace_settings[tid]["visible"]
        }

        if not visible_traces:
            self.plot_widget.setLabel("bottom", tr("X Axis"))
            self.plot_widget.setLabel("left", tr("Y Axis"))
            self.plot_item.getAxis("right").setLabel(tr("Secondary Y"))
            return

        # 2. Determine dominant plot style from the first visible trace
        first_tid = list(visible_traces.keys())[0]
        first_trace = visible_traces[first_tid]

        # Apply Axis Settings based on Plot Type
        self.is_log_x = False
        if first_trace.plot_type == "frequency_response":
            self.plot_widget.setLogMode(x=True, y=False)
            self.is_log_x = True
            self.plot_widget.setLabel("bottom", tr(first_trace.x_axis.dimension).capitalize(), units=tr(first_trace.x_axis.display_unit))
            self.plot_widget.setLabel("left", tr(first_trace.y_axis.dimension).capitalize(), units=tr(first_trace.y_axis.display_unit))
            if first_trace.y2_axis:
                self.plot_item.getAxis("right").setLabel(tr(first_trace.y2_axis.dimension).capitalize(), units=tr(first_trace.y2_axis.display_unit))
        elif first_trace.plot_type == "time_series" or first_trace.plot_type == "time_history":
            self.plot_widget.setLogMode(x=False, y=False)
            self.plot_widget.setLabel("bottom", tr(first_trace.x_axis.dimension).capitalize(), units=tr(first_trace.x_axis.display_unit))
            self.plot_widget.setLabel("left", tr(first_trace.y_axis.dimension).capitalize(), units=tr(first_trace.y_axis.display_unit))
            self.plot_item.getAxis("right").setLabel("")
        else:
            # Fallback
            self.plot_widget.setLogMode(x=False, y=False)
            self.plot_widget.setLabel("bottom", "X")
            self.plot_widget.setLabel("left", "Y")

        # 3. Draw each trace
        for tid, trace in visible_traces.items():
            settings = self.trace_settings[tid]

            # Arrays
            x = np.array(trace.x_data, dtype=float)
            y = np.array(trace.y_data, dtype=float)
            y2 = np.array(trace.y2_data, dtype=float) if trace.y2_data is not None else None

            if len(x) == 0 or len(y) == 0:
                continue

            # Apply Time Shift (X Shift)
            if settings["shift"] != 0.0:
                x = x + settings["shift"]

            # Apply Offset (Gain Offset / Amplitude Scaling)
            if settings["offset_db"] != 0.0:
                if trace.y_axis.display_unit in {"dB", "dBFS", "dBV", "dBu"}:
                    # Logarithmic domain addition
                    y = y + settings["offset_db"]
                else:
                    # Linear domain multiplication
                    gain_factor = 10 ** (settings["offset_db"] / 20.0)
                    y = y * gain_factor

            # Normalize (Align Peaks) if requested
            if self.normalize_check.isChecked():
                if trace.y_axis.display_unit in {"dB", "dBFS", "dBV", "dBu"}:
                    y = y - np.max(y)
                else:
                    max_y = np.max(np.abs(y))
                    if max_y > 1e-12:
                        y = y / max_y

            # Convert to display formats (e.g. logX handling)
            # PyQtGraph's setLogMode(x=True) automatically takes log10 of x values.
            # However, for secondary Y axis ViewBox (which doesn't support automatic LogMode link easily),
            # we manually log the X if setLogMode is enabled.
            x_for_y2 = x
            if getattr(self, "is_log_x", False):
                # Avoid log of zero
                valid_mask = x > 0
                x_for_y2 = np.log10(x[valid_mask])
                if y2 is not None:
                    y2 = y2[valid_mask]

            # Draw Y
            pen = pg.mkPen(settings["color"], width=2)
            y_curve = self.plot_widget.plot(x, y, pen=pen, name=trace.name)

            # Draw Y2 (Phase, etc. on secondary axis)
            y2_curve = None
            if y2 is not None and len(y2) == len(x_for_y2):
                pen_y2 = pg.mkPen(settings["color"], width=1, style=Qt.PenStyle.DashLine)
                y2_curve = pg.PlotCurveItem(x_for_y2, y2, pen=pen_y2)
                self.y2_view.addItem(y2_curve)

            self.curve_items[tid] = (y_curve, y2_curve)

        self.update_y2_views()

    def apply_theme(self, theme_name):
        if theme_name == "system" and self.app and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_effective_theme()

        self._is_dark_theme = theme_name == "dark"

        # Update List hint colors dynamically
        self.refresh_trace_list()
        self.replot()

    def closeEvent(self, event):
        # Disconnect signals to prevent memory leaks in Qt
        try:
            self.manager.trace_added.disconnect(self.on_trace_added)
            self.manager.trace_removed.disconnect(self.on_trace_removed)
            self.manager.cleared.disconnect(self.on_traces_cleared)
        except TypeError:
            pass  # Already disconnected
        super().closeEvent(event)
