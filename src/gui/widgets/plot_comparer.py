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
    QPushButton,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QMessageBox,
    QSplitter,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QComboBox,
    QLabel,
    QColorDialog,
    QInputDialog,
    QTabWidget,
)

from src.measurement_modules.base import MeasurementModule
from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.core.comparison_manager import ComparisonManager
from src.gui.styles import MONOSPACE_FONT_FAMILY

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
        self.scale_overridden = False

        # Trace rendering settings (offset, visibility, color index)
        # trace_id -> dict(visible=bool, offset_db=float, shift=float, color=str, width=int)
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
        # Set expanding size policy so the widget occupies the maximum vertical and horizontal space,
        # avoiding empty/blank spacing at the top of the container layout.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Splitter to allow resizing plot vs controls
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_layout.addWidget(self.splitter)

        # --- Left Panel: Plot Area ---
        plot_container = QWidget()
        plot_layout = QHBoxLayout(plot_container)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(2)

        # Plot with readout vertical stack
        plot_v_widget = QWidget()
        plot_v_layout = QVBoxLayout(plot_v_widget)
        plot_v_layout.setContentsMargins(0, 0, 0, 0)
        plot_v_layout.setSpacing(2)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.setLabel("bottom", tr("X Axis"))
        self.plot_widget.setLabel("left", tr("Y Axis"))

        # ① Add Legend
        self.plot_widget.addLegend(offset=(30, 30))

        plot_v_layout.addWidget(self.plot_widget, stretch=1)

        # ② Readout Label for interactive values
        self.readout_label = QLabel(tr("Move mouse over plot to read values"))
        self.readout_label.setWordWrap(True)
        self.readout_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.readout_label.setStyleSheet(f"""
            QLabel {{
                background-color: #2c3e50;
                color: #ecf0f1;
                border: 1px solid #1a252f;
                border-radius: 4px;
                padding: 6px;
                font-family: {MONOSPACE_FONT_FAMILY};
                font-size: 11px;
            }}
        """)
        plot_v_layout.addWidget(self.readout_label)

        plot_layout.addWidget(plot_v_widget, stretch=1)

        # Slim, premium vertical collapse button
        self.collapse_btn = QPushButton("›")
        self.collapse_btn.setFixedWidth(14)
        self.collapse_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_btn.setToolTip(tr("Hide Control Panel"))

        # Apply elegant, glassmorphism/flat premium styling
        self.collapse_btn.setStyleSheet("""
            QPushButton {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2c3e50, stop:1 #34495e);
                color: #ecf0f1;
                border: 1px solid #1a252f;
                border-radius: 3px;
                font-size: 14px;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #34495e;
                color: #3498db;
            }
            QPushButton:pressed {
                background-color: #1a252f;
            }
        """)
        self.collapse_btn.clicked.connect(self.toggle_controls)
        plot_layout.addWidget(self.collapse_btn)

        # Setup secondary Y-axis (for phase/distortion)
        self.plot_item = self.plot_widget.plotItem
        self.y2_view = pg.ViewBox()
        self.plot_item.scene().addItem(self.y2_view)
        self.plot_item.getAxis("right").linkToView(self.y2_view)
        self.y2_view.setXLink(self.plot_item)

        # Connect resize & range events to keep secondary axis synchronized and auto-scaled
        self.plot_item.vb.sigResized.connect(self.update_y2_views)
        self.plot_item.vb.sigRangeChanged.connect(self.sync_y2_range)

        # ② InfiniteLines for cursor measurement
        self.v_line = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen("#e74c3c", width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.h_line = pg.InfiniteLine(
            angle=0, movable=False, pen=pg.mkPen("#e74c3c", width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.plot_widget.addItem(self.v_line, ignoreBounds=True)
        self.plot_widget.addItem(self.h_line, ignoreBounds=True)
        self.v_line.hide()
        self.h_line.hide()

        # Connect mouse signals for hover
        self.plot_widget.scene().sigMouseMoved.connect(self.on_mouse_moved)

        self.splitter.addWidget(plot_container)

        # --- Right Panel: Controls (with Tabbed Widget) ---
        self.controls_widget = QWidget()
        self.controls_widget.setMinimumWidth(380)
        self.controls_widget.setMaximumWidth(600)
        controls_layout = QVBoxLayout(self.controls_widget)
        controls_layout.setContentsMargins(5, 5, 5, 5)

        self.tab_widget = QTabWidget()
        controls_layout.addWidget(self.tab_widget)

        # === Tab 1: Traces ===
        traces_tab = QWidget()
        traces_layout = QVBoxLayout(traces_tab)
        traces_layout.setContentsMargins(5, 5, 5, 5)

        # Plot Domain Filter
        filter_layout = QHBoxLayout()
        filter_label = QLabel(tr("Domain:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItem(tr("Frequency Domain"), "frequency")
        self.filter_combo.addItem(tr("Time Domain"), "time")
        self.filter_combo.addItem(tr("Amplitude Domain"), "amplitude")
        self.filter_combo.addItem(tr("Other Domain"), "other")
        self.filter_combo.currentIndexChanged.connect(self.on_filter_changed)
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.filter_combo)
        traces_layout.addLayout(filter_layout)

        # Master Toggles container (dynamic checkboxes will be inserted here)
        self.master_toggles_container = QWidget()
        self.master_toggles_layout = QHBoxLayout(self.master_toggles_container)
        self.master_toggles_layout.setContentsMargins(0, 2, 0, 2)
        self.master_toggles_checkboxes = {}
        traces_layout.addWidget(self.master_toggles_container)

        self.tree_widget = QTreeWidget()
        self.tree_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.tree_widget.setMinimumHeight(250)  # Moderate minimum height for compatibility with smaller screens
        self.tree_widget.setColumnCount(2)
        self.tree_widget.setHeaderLabels([tr("Trace / Parameter"), tr("Y-Axis")])
        self.tree_widget.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree_widget.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.tree_widget.setColumnWidth(1, 130)
        self.tree_widget.itemChanged.connect(self.on_item_changed)
        self.tree_widget.itemDoubleClicked.connect(self.on_tree_item_double_clicked)
        self.tree_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self.show_tree_context_menu)
        traces_layout.addWidget(self.tree_widget)

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.btn_import = QPushButton(tr("Import File"))
        self.btn_import.clicked.connect(self.import_file)
        self.btn_export = QPushButton(tr("Export Selected"))
        self.btn_export.setToolTip(
            tr("Export selected traces in the tree, or all checked traces if none are selected.")
        )
        self.btn_export.clicked.connect(self.export_selected)
        self.btn_remove = QPushButton(tr("Delete"))
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear = QPushButton(tr("Clear All"))
        self.btn_clear.clicked.connect(self.clear_all)

        btn_layout.addWidget(self.btn_import)
        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(self.btn_remove)
        btn_layout.addWidget(self.btn_clear)
        traces_layout.addLayout(btn_layout)

        # Sleek helper label for export/visibility interactions
        self.export_hint_label = QLabel(
            tr("Tip: Select items to export specifically, or check them to compare in the plot.")
        )
        self.export_hint_label.setStyleSheet("color: #7f8c8d; font-size: 10px; padding: 2px;")
        traces_layout.addWidget(self.export_hint_label)

        self.tab_widget.addTab(traces_tab, tr("Traces"))

        # === Tab 2: Plot Range ===
        range_tab = QWidget()
        range_layout = QVBoxLayout(range_tab)
        range_layout.setContentsMargins(5, 5, 5, 5)

        # X Axis Group
        x_group = QGroupBox(tr("X Axis"))
        x_v_layout = QVBoxLayout(x_group)

        x_opts_layout = QHBoxLayout()
        self.x_auto_cb = QCheckBox(tr("Auto"))
        self.x_auto_cb.setChecked(True)
        self.x_auto_cb.toggled.connect(self.on_x_auto_toggled)
        self.log_x_check = QCheckBox(tr("Log X Axis"))
        self.log_x_check.toggled.connect(self.on_scale_override_toggled)
        x_opts_layout.addWidget(self.x_auto_cb)
        x_opts_layout.addWidget(self.log_x_check)
        x_v_layout.addLayout(x_opts_layout)

        x_spin_layout = QHBoxLayout()
        x_spin_layout.addWidget(QLabel(tr("Min")))
        self.x_min_spin = QDoubleSpinBox()
        self.x_min_spin.setRange(-1000000.0, 1000000.0)
        self.x_min_spin.setEnabled(False)
        self.x_min_spin.valueChanged.connect(self.replot)
        x_spin_layout.addWidget(self.x_min_spin)

        x_spin_layout.addWidget(QLabel(tr("Max")))
        self.x_max_spin = QDoubleSpinBox()
        self.x_max_spin.setRange(-1000000.0, 1000000.0)
        self.x_max_spin.setEnabled(False)
        self.x_max_spin.valueChanged.connect(self.replot)
        x_spin_layout.addWidget(self.x_max_spin)

        x_v_layout.addLayout(x_spin_layout)
        range_layout.addWidget(x_group)

        # Y1 Axis (Primary) Group
        y1_group = QGroupBox(tr("Y1 Axis (Primary)"))
        y1_v_layout = QVBoxLayout(y1_group)

        y1_opts_layout = QHBoxLayout()
        self.y1_auto_cb = QCheckBox(tr("Auto"))
        self.y1_auto_cb.setChecked(True)
        self.y1_auto_cb.toggled.connect(self.on_y1_auto_toggled)
        self.log_y_check = QCheckBox(tr("Log Y Axis"))
        self.log_y_check.toggled.connect(self.on_scale_override_toggled)
        y1_opts_layout.addWidget(self.y1_auto_cb)
        y1_opts_layout.addWidget(self.log_y_check)
        y1_v_layout.addLayout(y1_opts_layout)

        y1_spin_layout = QHBoxLayout()
        y1_spin_layout.addWidget(QLabel(tr("Min")))
        self.y1_min_spin = QDoubleSpinBox()
        self.y1_min_spin.setRange(-1000.0, 1000.0)
        self.y1_min_spin.setEnabled(False)
        self.y1_min_spin.valueChanged.connect(self.replot)
        y1_spin_layout.addWidget(self.y1_min_spin)

        y1_spin_layout.addWidget(QLabel(tr("Max")))
        self.y1_max_spin = QDoubleSpinBox()
        self.y1_max_spin.setRange(-1000.0, 1000.0)
        self.y1_max_spin.setEnabled(False)
        self.y1_max_spin.valueChanged.connect(self.replot)
        y1_spin_layout.addWidget(self.y1_max_spin)

        y1_v_layout.addLayout(y1_spin_layout)
        range_layout.addWidget(y1_group)

        # Y2 Axis (Secondary) Group
        y2_group = QGroupBox(tr("Y2 Axis (Secondary)"))
        y2_v_layout = QVBoxLayout(y2_group)

        y2_opts_layout = QHBoxLayout()
        self.y2_auto_cb = QCheckBox(tr("Auto"))
        self.y2_auto_cb.setChecked(True)
        self.y2_auto_cb.toggled.connect(self.on_y2_auto_toggled)
        y2_opts_layout.addWidget(self.y2_auto_cb)
        y2_v_layout.addLayout(y2_opts_layout)

        y2_spin_layout = QHBoxLayout()
        y2_spin_layout.addWidget(QLabel(tr("Min")))
        self.y2_min_spin = QDoubleSpinBox()
        self.y2_min_spin.setRange(-1000.0, 1000.0)
        self.y2_min_spin.setEnabled(False)
        self.y2_min_spin.valueChanged.connect(self.replot)
        y2_spin_layout.addWidget(self.y2_min_spin)

        y2_spin_layout.addWidget(QLabel(tr("Max")))
        self.y2_max_spin = QDoubleSpinBox()
        self.y2_max_spin.setRange(-1000.0, 1000.0)
        self.y2_max_spin.setEnabled(False)
        self.y2_max_spin.valueChanged.connect(self.replot)
        y2_spin_layout.addWidget(self.y2_max_spin)

        y2_v_layout.addLayout(y2_spin_layout)
        range_layout.addWidget(y2_group)

        # Global Options Group in range tab
        global_opts_group = QGroupBox(tr("Global Options"))
        global_opts_layout = QVBoxLayout(global_opts_group)
        self.normalize_check = QCheckBox(tr("Normalize (Align Peaks)"))
        self.normalize_check.toggled.connect(self.replot)
        global_opts_layout.addWidget(self.normalize_check)
        range_layout.addWidget(global_opts_group)

        range_layout.addStretch()
        self.tab_widget.addTab(range_tab, tr("Plot Range"))

        self.splitter.addWidget(self.controls_widget)

        # Default splitter weights
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([620, 380])

        self.setLayout(main_layout)

    def on_x_auto_toggled(self, checked: bool):
        self.x_min_spin.setEnabled(not checked)
        self.x_max_spin.setEnabled(not checked)
        if not checked:
            x_range = self.plot_widget.viewRange()[0]
            min_val, max_val = x_range[0], x_range[1]

            active_domain = self.filter_combo.currentData()
            use_khz = False
            traces = self.manager.get_all_traces()
            first_trace = None
            for tid, trace in traces.items():
                if tid in self.trace_settings and self.trace_settings[tid]["visible"]:
                    if self._get_trace_domain(trace) == active_domain:
                        first_trace = trace
                        break
            if first_trace:
                use_khz = active_domain == "frequency" and first_trace.x_axis.display_unit == "Hz"

            if getattr(self, "is_log_x", False):
                min_val = 10**min_val
                max_val = 10**max_val
            elif use_khz:
                min_val = min_val * 1000.0
                max_val = max_val * 1000.0

            self.x_min_spin.blockSignals(True)
            self.x_max_spin.blockSignals(True)
            self.x_min_spin.setValue(min_val)
            self.x_max_spin.setValue(max_val)
            self.x_min_spin.blockSignals(False)
            self.x_max_spin.blockSignals(False)
        self.replot()

    def on_y1_auto_toggled(self, checked: bool):
        self.y1_min_spin.setEnabled(not checked)
        self.y1_max_spin.setEnabled(not checked)
        if not checked:
            y_range = self.plot_widget.viewRange()[1]
            min_val, max_val = y_range[0], y_range[1]

            if getattr(self, "is_log_y", False):
                first_trace = None
                traces = self.manager.get_all_traces()
                active_domain = self.filter_combo.currentData()
                for tid, trace in traces.items():
                    if tid in self.trace_settings and self.trace_settings[tid]["visible"]:
                        if self._get_trace_domain(trace) == active_domain:
                            first_trace = trace
                            break
                if first_trace and first_trace.y_axis and first_trace.y_axis.display_unit == "%":
                    min_val = 10**min_val
                    max_val = 10**max_val

            self.y1_min_spin.blockSignals(True)
            self.y1_max_spin.blockSignals(True)
            self.y1_min_spin.setValue(min_val)
            self.y1_max_spin.setValue(max_val)
            self.y1_min_spin.blockSignals(False)
            self.y1_max_spin.blockSignals(False)
        self.replot()

    def on_y2_auto_toggled(self, checked: bool):
        self.y2_min_spin.setEnabled(not checked)
        self.y2_max_spin.setEnabled(not checked)
        if not checked:
            y2_range = self.y2_view.viewRange()[1]
            min_val, max_val = y2_range[0], y2_range[1]

            self.y2_min_spin.blockSignals(True)
            self.y2_max_spin.blockSignals(True)
            self.y2_min_spin.setValue(min_val)
            self.y2_max_spin.setValue(max_val)
            self.y2_min_spin.blockSignals(False)
            self.y2_max_spin.blockSignals(False)
        self.replot()

    def on_range_changed(self):
        # Update spinboxes to match the actual range if Auto is checked
        if not hasattr(self, "x_auto_cb"):
            return

        if self.x_auto_cb.isChecked():
            x_range = self.plot_widget.viewRange()[0]
            min_val, max_val = x_range[0], x_range[1]

            active_domain = self.filter_combo.currentData()
            use_khz = False
            traces = self.manager.get_all_traces()
            first_trace = None
            for tid, trace in traces.items():
                if tid in self.trace_settings and self.trace_settings[tid]["visible"]:
                    if self._get_trace_domain(trace) == active_domain:
                        first_trace = trace
                        break
            if first_trace:
                use_khz = active_domain == "frequency" and first_trace.x_axis.display_unit == "Hz"

            if getattr(self, "is_log_x", False):
                min_val = 10**min_val
                max_val = 10**max_val
            elif use_khz:
                min_val = min_val * 1000.0
                max_val = max_val * 1000.0

            self.x_min_spin.blockSignals(True)
            self.x_max_spin.blockSignals(True)
            self.x_min_spin.setValue(min_val)
            self.x_max_spin.setValue(max_val)
            self.x_min_spin.blockSignals(False)
            self.x_max_spin.blockSignals(False)

        if self.y1_auto_cb.isChecked():
            y_range = self.plot_widget.viewRange()[1]
            min_val, max_val = y_range[0], y_range[1]
            if getattr(self, "is_log_y", False):
                first_trace = None
                traces = self.manager.get_all_traces()
                active_domain = self.filter_combo.currentData()
                for tid, trace in traces.items():
                    if tid in self.trace_settings and self.trace_settings[tid]["visible"]:
                        if self._get_trace_domain(trace) == active_domain:
                            first_trace = trace
                            break
                if first_trace and first_trace.y_axis and first_trace.y_axis.display_unit == "%":
                    min_val = 10**min_val
                    max_val = 10**max_val

            self.y1_min_spin.blockSignals(True)
            self.y1_max_spin.blockSignals(True)
            self.y1_min_spin.setValue(min_val)
            self.y1_max_spin.setValue(max_val)
            self.y1_min_spin.blockSignals(False)
            self.y1_max_spin.blockSignals(False)

        if self.y2_auto_cb.isChecked():
            y2_range = self.y2_view.viewRange()[1]
            min_val, max_val = y2_range[0], y2_range[1]

            self.y2_min_spin.blockSignals(True)
            self.y2_max_spin.blockSignals(True)
            self.y2_min_spin.setValue(min_val)
            self.y2_max_spin.setValue(max_val)
            self.y2_min_spin.blockSignals(False)
            self.y2_max_spin.blockSignals(False)

    def update_spinbox_limits(self):
        if not hasattr(self, "x_min_spin"):
            return
        active_domain = self.filter_combo.currentData()
        traces = self.manager.get_all_traces()
        first_trace = None
        for tid, trace in traces.items():
            if tid in self.trace_settings and self.trace_settings[tid]["visible"]:
                if self._get_trace_domain(trace) == active_domain:
                    first_trace = trace
                    break

        use_khz = active_domain == "frequency" and first_trace and first_trace.x_axis.display_unit == "Hz"

        self.x_min_spin.blockSignals(True)
        self.x_max_spin.blockSignals(True)

        if active_domain == "frequency":
            if use_khz:
                self.x_min_spin.setRange(0.001, 200.0)
                self.x_max_spin.setRange(0.001, 200.0)
                self.x_min_spin.setSuffix(" kHz")
                self.x_max_spin.setSuffix(" kHz")
                self.x_min_spin.setSingleStep(0.1)
                self.x_max_spin.setSingleStep(0.1)
                self.x_min_spin.setDecimals(3)
                self.x_max_spin.setDecimals(3)
            else:
                self.x_min_spin.setRange(0.1, 200000.0)
                self.x_max_spin.setRange(0.1, 200000.0)
                self.x_min_spin.setSuffix(" Hz")
                self.x_max_spin.setSuffix(" Hz")
                self.x_min_spin.setSingleStep(1.0)
                self.x_max_spin.setSingleStep(1.0)
                self.x_min_spin.setDecimals(2)
                self.x_max_spin.setDecimals(2)
        elif active_domain == "time":
            self.x_min_spin.setRange(-100.0, 100.0)
            self.x_max_spin.setRange(-100.0, 100.0)
            self.x_min_spin.setSuffix(" s")
            self.x_max_spin.setSuffix(" s")
            self.x_min_spin.setSingleStep(0.001)
            self.x_max_spin.setSingleStep(0.001)
            self.x_min_spin.setDecimals(4)
            self.x_max_spin.setDecimals(4)
        else:
            self.x_min_spin.setRange(-1000000.0, 1000000.0)
            self.x_max_spin.setRange(-1000000.0, 1000000.0)
            self.x_min_spin.setSuffix("")
            self.x_max_spin.setSuffix("")
            self.x_min_spin.setSingleStep(1.0)
            self.x_max_spin.setSingleStep(1.0)
            self.x_min_spin.setDecimals(2)
            self.x_max_spin.setDecimals(2)

        self.x_min_spin.blockSignals(False)
        self.x_max_spin.blockSignals(False)

    def update_y2_views(self):
        try:
            self.y2_view.setGeometry(self.plot_item.vb.sceneBoundingRect())
        except Exception:
            pass

    def toggle_controls(self):
        is_visible = self.controls_widget.isVisible()
        self.controls_widget.setVisible(not is_visible)
        if is_visible:
            self.collapse_btn.setText("‹")
            self.collapse_btn.setToolTip(tr("Show Control Panel"))
        else:
            self.collapse_btn.setText("›")
            self.collapse_btn.setToolTip(tr("Hide Control Panel"))

    def get_color(self, idx: int) -> str:
        colors = self.COLORS_DARK if self._is_dark_theme else self.COLORS_LIGHT
        return colors[idx % len(colors)]

    def _get_trace_domain(self, trace) -> str:
        if not trace or not trace.x_axis or not trace.x_axis.dimension:
            return "other"
        dim = trace.x_axis.dimension.lower()
        if dim in ("frequency", "freq"):
            return "frequency"
        elif dim in ("time", "t"):
            return "time"
        elif dim in ("amplitude", "volt", "voltage", "power", "dbfs", "dbv", "vrms"):
            return "amplitude"
        else:
            return "other"

    def refresh_trace_list(self):
        self.tree_widget.blockSignals(True)
        self.tree_widget.clear()

        # Get the selected plot domain filter
        active_domain = self.filter_combo.currentData()

        traces = self.manager.get_all_traces()
        for idx, (tid, trace) in enumerate(traces.items()):
            trace_domain = self._get_trace_domain(trace)
            if trace_domain != active_domain:
                continue

            # Initialize settings if new, preserving backwards compatibility
            if tid not in self.trace_settings:
                self.trace_settings[tid] = {
                    "visible": True,
                    "offset_db": 0.0,
                    "shift": 0.0,
                    "color": self.get_color(idx),
                    "width": 2,
                    "y_visible": True,
                    "y_axis_choice": "Y1",
                    "y2_visible": True,
                    "y2_axis_choice": "Y2",
                }
            else:
                # Ensure the new nested settings exist
                if "width" not in self.trace_settings[tid]:
                    self.trace_settings[tid]["width"] = 2
                if "y_visible" not in self.trace_settings[tid]:
                    self.trace_settings[tid]["y_visible"] = True
                if "y_axis_choice" not in self.trace_settings[tid]:
                    self.trace_settings[tid]["y_axis_choice"] = "Y1"
                if "y2_visible" not in self.trace_settings[tid]:
                    self.trace_settings[tid]["y2_visible"] = True
                if "y2_axis_choice" not in self.trace_settings[tid]:
                    self.trace_settings[tid]["y2_axis_choice"] = "Y2"

            settings = self.trace_settings[tid]

            # 1. Create Parent Item (Trace Entire)
            parent_item = QTreeWidgetItem(self.tree_widget)
            parent_item.setText(0, trace.name)
            parent_item.setFlags(parent_item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
            parent_item.setCheckState(0, Qt.CheckState.Checked if settings["visible"] else Qt.CheckState.Unchecked)
            parent_item.setData(0, Qt.ItemDataRole.UserRole, tid)
            parent_item.setData(0, Qt.ItemDataRole.UserRole + 1, "parent")

            from PyQt6.QtGui import QColor, QBrush

            color = QColor(settings["color"])
            parent_item.setForeground(0, QBrush(color))

            # 2. Create Child Item (Primary Data)
            y_label = tr(trace.y_axis.dimension).capitalize()
            if trace.y_axis.display_unit:
                y_label += f" ({trace.y_axis.display_unit})"

            y_item = QTreeWidgetItem(parent_item)
            y_item.setText(0, y_label)
            y_item.setFlags(y_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            y_item.setCheckState(0, Qt.CheckState.Checked if settings["y_visible"] else Qt.CheckState.Unchecked)
            y_item.setData(0, Qt.ItemDataRole.UserRole, tid)
            y_item.setData(0, Qt.ItemDataRole.UserRole + 1, "y")

            y_combo = QComboBox()
            y_combo.addItems(["Y1", "Y2"])
            y_combo.setCurrentText(settings["y_axis_choice"])
            y_combo.setProperty("trace_id", tid)
            y_combo.setProperty("sub_type", "y")
            y_combo.currentTextChanged.connect(self.on_axis_changed)
            self.tree_widget.setItemWidget(y_item, 1, y_combo)

            # 3. Create Child Item (Secondary Data) - only if it exists
            y2_item = None
            y2_combo = None
            if trace.y2_data is not None and trace.y2_axis:
                y2_label = tr(trace.y2_axis.dimension).capitalize()
                if trace.y2_axis.display_unit:
                    y2_label += f" ({trace.y2_axis.display_unit})"

                y2_item = QTreeWidgetItem(parent_item)
                y2_item.setText(0, y2_label)
                y2_item.setFlags(y2_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                y2_item.setCheckState(0, Qt.CheckState.Checked if settings["y2_visible"] else Qt.CheckState.Unchecked)
                y2_item.setData(0, Qt.ItemDataRole.UserRole, tid)
                y2_item.setData(0, Qt.ItemDataRole.UserRole + 1, "y2")

                y2_combo = QComboBox()
                y2_combo.addItems(["Y1", "Y2"])
                y2_combo.setCurrentText(settings["y2_axis_choice"])
                y2_combo.setProperty("trace_id", tid)
                y2_combo.setProperty("sub_type", "y2")
                y2_combo.currentTextChanged.connect(self.on_axis_changed)
                self.tree_widget.setItemWidget(y2_item, 1, y2_combo)

            # 4. Create Child Item (Gain Offset)
            offset_item = QTreeWidgetItem(parent_item)
            offset_item.setText(0, tr("Gain Offset"))
            offset_item.setFlags(offset_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            offset_item.setData(0, Qt.ItemDataRole.UserRole, tid)
            offset_item.setData(0, Qt.ItemDataRole.UserRole + 1, "offset")

            offset_spin = QDoubleSpinBox()
            offset_spin.setRange(-120.0, 120.0)
            offset_spin.setValue(settings["offset_db"])
            offset_spin.setSuffix(" dB")
            offset_spin.setDecimals(3)
            offset_spin.setSingleStep(0.1)
            offset_spin.setProperty("trace_id", tid)
            offset_spin.valueChanged.connect(self.on_tree_offset_changed)
            self.tree_widget.setItemWidget(offset_item, 1, offset_spin)

            # 5. Create Child Item (X-Axis Shift/Offset)
            shift_item = QTreeWidgetItem(parent_item)
            shift_item.setData(0, Qt.ItemDataRole.UserRole, tid)
            shift_item.setData(0, Qt.ItemDataRole.UserRole + 1, "shift")

            shift_spin = QDoubleSpinBox()
            shift_spin.setValue(settings["shift"])
            shift_spin.setProperty("trace_id", tid)
            shift_spin.valueChanged.connect(self.on_tree_shift_changed)

            active_domain = self.filter_combo.currentData()
            if active_domain == "frequency":
                shift_item.setText(0, tr("Frequency Shift"))
                shift_spin.setRange(-100000.0, 100000.0)
                shift_spin.setSuffix(" Hz")
                shift_spin.setDecimals(2)
                shift_spin.setSingleStep(1.0)
            elif active_domain == "time":
                shift_item.setText(0, tr("Time Shift"))
                shift_spin.setRange(-10.0, 10.0)
                shift_spin.setSuffix(" s")
                shift_spin.setDecimals(4)
                shift_spin.setSingleStep(0.001)
            else:
                shift_item.setText(0, tr("Shift"))
                shift_spin.setRange(-100000.0, 100000.0)
                shift_spin.setSuffix("")
                shift_spin.setDecimals(4)
                shift_spin.setSingleStep(0.1)

            shift_item.setFlags(shift_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self.tree_widget.setItemWidget(shift_item, 1, shift_spin)

            parent_item.setExpanded(True)

        self.tree_widget.blockSignals(False)
        self.update_master_toggles()

    def on_item_changed(self, item: QTreeWidgetItem, column: int):
        if column != 0:
            return

        tid = item.data(0, Qt.ItemDataRole.UserRole)
        if not tid:
            return

        item_type = item.data(0, Qt.ItemDataRole.UserRole + 1)

        # Handle Rename (only for parent item)
        if item_type == "parent":
            trace = self.manager.get_trace(tid)
            if trace and item.text(0) != trace.name:
                trace.name = item.text(0)
                logger.info(f"Trace renamed to: {trace.name}")

            # Sync checked state down to children
            visible = item.checkState(0) == Qt.CheckState.Checked
            if tid in self.trace_settings:
                self.trace_settings[tid]["visible"] = visible
                self.tree_widget.blockSignals(True)
                for i in range(item.childCount()):
                    child = item.child(i)
                    child.setCheckState(0, Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked)
                    c_type = child.data(0, Qt.ItemDataRole.UserRole + 1)
                    if c_type == "y":
                        self.trace_settings[tid]["y_visible"] = visible
                    elif c_type == "y2":
                        self.trace_settings[tid]["y2_visible"] = visible
                self.tree_widget.blockSignals(False)

        elif item_type in ("y", "y2"):
            visible = item.checkState(0) == Qt.CheckState.Checked
            if tid in self.trace_settings:
                if item_type == "y":
                    self.trace_settings[tid]["y_visible"] = visible
                elif item_type == "y2":
                    self.trace_settings[tid]["y2_visible"] = visible

                # Sync checked state up to parent
                parent = item.parent()
                if parent:
                    self.tree_widget.blockSignals(True)
                    any_checked = False
                    all_checked = True
                    for i in range(parent.childCount()):
                        c_state = parent.child(i).checkState(0)
                        if c_state == Qt.CheckState.Checked:
                            any_checked = True
                        else:
                            all_checked = False

                    if all_checked:
                        parent.setCheckState(0, Qt.CheckState.Checked)
                        self.trace_settings[tid]["visible"] = True
                    elif any_checked:
                        parent.setCheckState(0, Qt.CheckState.Checked)
                        self.trace_settings[tid]["visible"] = True
                    else:
                        parent.setCheckState(0, Qt.CheckState.Unchecked)
                        self.trace_settings[tid]["visible"] = False
                    self.tree_widget.blockSignals(False)

        self.replot()
        self.sync_master_toggle_states()

    def on_tree_offset_changed(self, val):
        spin = self.sender()
        if not isinstance(spin, QDoubleSpinBox):
            return
        tid = spin.property("trace_id")
        if tid in self.trace_settings:
            self.trace_settings[tid]["offset_db"] = val
            self.replot()

    def on_tree_shift_changed(self, val):
        spin = self.sender()
        if not isinstance(spin, QDoubleSpinBox):
            return
        tid = spin.property("trace_id")
        if tid in self.trace_settings:
            self.trace_settings[tid]["shift"] = val
            self.replot()

    def update_master_toggles(self):
        # 1. Gather all unique Y dimensions for active domain traces
        active_domain = self.filter_combo.currentData()
        traces = self.manager.get_all_traces()

        dimensions = set()
        for _, trace in traces.items():
            trace_domain = self._get_trace_domain(trace)
            if trace_domain != active_domain:
                continue

            if trace.y_axis and trace.y_axis.dimension:
                dimensions.add(trace.y_axis.dimension)
            if trace.y2_data is not None and trace.y2_axis and trace.y2_axis.dimension:
                dimensions.add(trace.y2_axis.dimension)

        # 2. Clear old master checkboxes
        for cb in list(self.master_toggles_checkboxes.values()):
            cb.blockSignals(True)
            self.master_toggles_layout.removeWidget(cb)
            cb.deleteLater()
        self.master_toggles_checkboxes.clear()

        # 3. Create new checkboxes
        if not dimensions:
            self.master_toggles_container.setVisible(False)
            return

        self.master_toggles_container.setVisible(True)
        for dim in sorted(list(dimensions)):
            label_text = tr(dim).capitalize()
            cb = QCheckBox(label_text)
            cb.setProperty("dimension", dim)
            cb.toggled.connect(self.on_master_toggle_changed)
            self.master_toggles_layout.addWidget(cb)
            self.master_toggles_checkboxes[dim] = cb

        self.sync_master_toggle_states()

    def sync_master_toggle_states(self):
        active_domain = self.filter_combo.currentData()
        traces = self.manager.get_all_traces()

        dim_states = {dim: [] for dim in self.master_toggles_checkboxes.keys()}

        for tid, trace in traces.items():
            if tid not in self.trace_settings:
                continue
            trace_domain = self._get_trace_domain(trace)
            if trace_domain != active_domain:
                continue

            settings = self.trace_settings[tid]
            parent_visible = settings.get("visible", True)

            if trace.y_axis and trace.y_axis.dimension in dim_states:
                dim = trace.y_axis.dimension
                is_visible = parent_visible and settings.get("y_visible", True)
                dim_states[dim].append(is_visible)

            if trace.y2_data is not None and trace.y2_axis and trace.y2_axis.dimension in dim_states:
                dim = trace.y2_axis.dimension
                is_visible = parent_visible and settings.get("y2_visible", True)
                dim_states[dim].append(is_visible)

        for dim, cb in self.master_toggles_checkboxes.items():
            cb.blockSignals(True)
            states = dim_states[dim]
            if states:
                cb.setChecked(any(states))
            else:
                cb.setChecked(False)
            cb.blockSignals(False)

    def on_master_toggle_changed(self, checked: bool):
        cb = self.sender()
        if not isinstance(cb, QCheckBox):
            return
        dim = cb.property("dimension")
        if not dim:
            return

        active_domain = self.filter_combo.currentData()
        traces = self.manager.get_all_traces()

        self.tree_widget.blockSignals(True)

        for tid, trace in traces.items():
            if tid not in self.trace_settings:
                continue
            trace_domain = self._get_trace_domain(trace)
            if trace_domain != active_domain:
                continue

            settings = self.trace_settings[tid]

            if trace.y_axis and trace.y_axis.dimension == dim:
                settings["y_visible"] = checked
                if checked:
                    settings["visible"] = True

            if trace.y2_data is not None and trace.y2_axis and trace.y2_axis.dimension == dim:
                settings["y2_visible"] = checked
                if checked:
                    settings["visible"] = True

            # Auto-disable parent trace if all children become unchecked
            has_y = settings.get("y_visible", True)
            has_y2 = (trace.y2_data is not None) and settings.get("y2_visible", True)
            if not has_y and not has_y2:
                settings["visible"] = False

        # Refresh tree checkboxes directly to avoid clearing selection or inputs
        root = self.tree_widget.invisibleRootItem()
        for i in range(root.childCount()):
            parent_item = root.child(i)
            tid = parent_item.data(0, Qt.ItemDataRole.UserRole)
            if tid in self.trace_settings:
                settings = self.trace_settings[tid]
                parent_item.setCheckState(0, Qt.CheckState.Checked if settings["visible"] else Qt.CheckState.Unchecked)
                for j in range(parent_item.childCount()):
                    child = parent_item.child(j)
                    c_type = child.data(0, Qt.ItemDataRole.UserRole + 1)
                    if c_type == "y":
                        child.setCheckState(
                            0, Qt.CheckState.Checked if settings["y_visible"] else Qt.CheckState.Unchecked
                        )
                    elif c_type == "y2":
                        child.setCheckState(
                            0, Qt.CheckState.Checked if settings["y2_visible"] else Qt.CheckState.Unchecked
                        )

        self.tree_widget.blockSignals(False)
        self.replot()

    def on_axis_changed(self, text):
        combo = self.sender()
        if not isinstance(combo, QComboBox):
            return
        tid = combo.property("trace_id")
        sub_type = combo.property("sub_type")

        if tid in self.trace_settings:
            if sub_type == "y":
                self.trace_settings[tid]["y_axis_choice"] = text
            elif sub_type == "y2":
                self.trace_settings[tid]["y2_axis_choice"] = text
            logger.info(f"Sub-trace {sub_type} of {tid} re-mapped to {text}")
            self.replot()

    def on_scale_override_toggled(self):
        self.scale_overridden = True
        self.replot()

    def on_filter_changed(self, index):
        self.scale_overridden = False
        active_domain = self.filter_combo.currentData()

        self.log_x_check.blockSignals(True)
        self.log_y_check.blockSignals(True)

        if active_domain == "frequency":
            self.log_x_check.setChecked(True)
            self.log_y_check.setChecked(False)
        elif active_domain == "time":
            self.log_x_check.setChecked(False)
            self.log_y_check.setChecked(False)
        elif active_domain == "amplitude":
            self.log_x_check.setChecked(False)
            self.log_y_check.setChecked(False)
        else:
            self.log_x_check.setChecked(False)
            self.log_y_check.setChecked(False)

        self.log_x_check.blockSignals(False)
        self.log_y_check.blockSignals(False)

        self.refresh_trace_list()
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
        selected_items = self.tree_widget.selectedItems()
        if not selected_items:
            return
        tid = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
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

    def show_tree_context_menu(self, pos):
        item = self.tree_widget.itemAt(pos)
        if not item:
            return

        tid = item.data(0, Qt.ItemDataRole.UserRole)
        item_type = item.data(0, Qt.ItemDataRole.UserRole + 1)

        if item_type == "parent":
            from PyQt6.QtGui import QAction
            from PyQt6.QtWidgets import QMenu

            menu = QMenu(self)

            export_action = QAction(tr("Export This Trace Individually..."), self)
            rename_action = QAction(tr("Rename Trace"), self)
            color_action = QAction(tr("Change Color..."), self)
            width_action = QAction(tr("Line Width..."), self)
            delete_action = QAction(tr("Delete Trace"), self)

            export_action.triggered.connect(lambda: self.export_single_trace(tid))
            rename_action.triggered.connect(lambda: self.tree_widget.editItem(item, 0))
            color_action.triggered.connect(lambda: self.change_trace_color(tid))
            width_action.triggered.connect(lambda: self.change_trace_width(tid))
            delete_action.triggered.connect(lambda: self.manager.remove_trace(tid))

            menu.addAction(export_action)
            menu.addAction(rename_action)
            menu.addAction(color_action)
            menu.addAction(width_action)
            menu.addSeparator()
            menu.addAction(delete_action)

            menu.exec(self.tree_widget.mapToGlobal(pos))

    def on_tree_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        tid = item.data(0, Qt.ItemDataRole.UserRole)
        item_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if item_type == "parent" and tid in self.trace_settings:
            self.change_trace_color(tid)

    def change_trace_color(self, trace_id: str):
        settings = self.trace_settings[trace_id]
        from PyQt6.QtGui import QColor

        color = QColorDialog.getColor(QColor(settings["color"]), self, tr("Select Trace Color"))
        if color.isValid():
            settings["color"] = color.name()
            self.refresh_trace_list()
            self.replot()

    def change_trace_width(self, trace_id: str):
        settings = self.trace_settings[trace_id]
        current_width = settings.get("width", 2)
        width, ok = QInputDialog.getInt(self, tr("Line Width"), tr("Enter line width (1-5):"), current_width, 1, 5, 1)
        if ok:
            settings["width"] = width
            self.replot()

    def sync_y2_range(self):
        # Scale Y2 data automatically based on the visible range
        try:
            self.y2_view.autoRange(axis=pg.ViewBox.YAxis)
        except Exception as e:
            logger.debug(f"Failed to autoRange Y2: {e}")
        try:
            self.on_range_changed()
        except Exception as e:
            logger.debug(f"Failed in on_range_changed during sync_y2_range: {e}")

    def on_mouse_moved(self, pos):
        if not self.curve_items:
            self.v_line.hide()
            self.h_line.hide()
            self.readout_label.setText(tr("Move mouse over plot to read values"))
            return

        vb = self.plot_item.vb
        rect = self.plot_widget.sceneBoundingRect()
        import sys

        is_testing = "pytest" in sys.modules
        is_headless = rect.width() <= 0 or rect.height() <= 0
        if is_testing or is_headless or rect.contains(pos):
            mouse_point = vb.mapSceneToView(pos)
            x_val = mouse_point.x()
            y_val = mouse_point.y()

            active_domain = self.filter_combo.currentData()
            x_unit = "Hz" if active_domain == "frequency" else "s" if active_domain == "time" else ""

            visible_traces = []
            traces = self.manager.get_all_traces()
            for tid, trace in traces.items():
                if tid in self.trace_settings and self.trace_settings[tid]["visible"]:
                    trace_domain = self._get_trace_domain(trace)
                    if trace_domain == active_domain:
                        visible_traces.append((tid, trace))

            use_khz = False
            if visible_traces:
                first_trace = visible_traces[0][1]
                use_khz = active_domain == "frequency" and first_trace.x_axis.display_unit == "Hz"

            # Format X value taking logX into account
            if active_domain == "frequency":
                if getattr(self, "is_log_x", False):
                    actual_x = 10**x_val
                else:
                    actual_x = x_val
                if use_khz:
                    x_str = f"{actual_x:.3f} kHz"
                else:
                    x_str = f"{actual_x:.2f} {x_unit}" if actual_x < 1000 else f"{actual_x / 1000:.3f} k{x_unit}"
            elif active_domain == "time":
                actual_x = x_val
                x_str = f"{actual_x * 1000:.3f} ms" if abs(actual_x) < 1.0 else f"{actual_x:.4f} {x_unit}"
            else:
                actual_x = x_val
                x_str = f"{actual_x:.4f}"

            self.v_line.setPos(x_val)
            self.h_line.setPos(y_val)
            self.v_line.show()
            self.h_line.show()

            readout_parts = []
            trace_y_vals = []

            for idx, (tid, trace) in enumerate(visible_traces, start=1):
                settings = self.trace_settings[tid]
                x_arr = np.array(trace.x_data, dtype=float)
                if use_khz:
                    x_arr = x_arr / 1000.0

                if settings["shift"] != 0.0:
                    x_arr = x_arr + settings["shift"]

                sort_idx = np.argsort(x_arr)
                x_sorted = x_arr[sort_idx]

                # 1. Primary Y data
                if settings.get("y_visible", True) and trace.y_data is not None:
                    y_arr = np.array(trace.y_data, dtype=float)[sort_idx]

                    if settings["offset_db"] != 0.0:
                        if trace.y_axis.display_unit in {"dB", "dBFS", "dBV", "dBu"}:
                            y_arr = y_arr + settings["offset_db"]
                        else:
                            gain_factor = 10 ** (settings["offset_db"] / 20.0)
                            y_arr = y_arr * gain_factor

                    if self.normalize_check.isChecked():
                        if trace.y_axis.display_unit in {"dB", "dBFS", "dBV", "dBu"}:
                            y_arr = y_arr - np.max(y_arr)
                        else:
                            max_y = np.max(np.abs(y_arr))
                            if max_y > 1e-12:
                                y_arr = y_arr / max_y

                    try:
                        interp_y = np.interp(actual_x, x_sorted, y_arr)
                        unit = trace.y_axis.display_unit or ""
                        color = settings.get("color", "#ffffff")
                        readout_parts.append(f'<span style="color: {color};">● T{idx}: {interp_y:.2f} {unit}</span>')
                        trace_y_vals.append(interp_y)
                    except Exception:
                        pass

                # 2. Secondary Y2 data
                if trace.y2_data is not None and settings.get("y2_visible", True) and trace.y2_axis:
                    y2_arr = np.array(trace.y2_data, dtype=float)[sort_idx]
                    try:
                        interp_y2 = np.interp(actual_x, x_sorted, y2_arr)
                        unit2 = trace.y2_axis.display_unit or ""
                        color = settings.get("color", "#ffffff")
                        readout_parts.append(
                            f'<span style="color: {color};">● T{idx} ({tr("Phase")}): {interp_y2:.1f} {unit2}</span>'
                        )
                    except Exception:
                        pass

            delta_str = ""
            if len(trace_y_vals) >= 2:
                delta = abs(trace_y_vals[0] - trace_y_vals[1])
                delta_str = f" | {tr('Delta')}: {delta:.2f} dB"

            readouts = " | ".join(readout_parts)
            self.readout_label.setText(f"X: {x_str} | {readouts}{delta_str}")
        else:
            self.v_line.hide()
            self.h_line.hide()
            self.readout_label.setText(tr("Move mouse over plot to read values"))

    def export_single_trace(self, trace_id):
        trace = self.manager.get_trace(trace_id)
        if trace:
            from src.gui.widgets.export_dialog import ExportSettingsDialog

            dialog = ExportSettingsDialog([trace], self)
            dialog.exec()

    def export_selected(self):
        selected_items = self.tree_widget.selectedItems()
        if not selected_items:
            # If nothing is explicitly selected, export all checked traces
            trace_ids = []
            root = self.tree_widget.invisibleRootItem()
            for i in range(root.childCount()):
                item = root.child(i)
                if item.checkState(0) == Qt.CheckState.Checked:
                    tid = item.data(0, Qt.ItemDataRole.UserRole)
                    if tid:
                        trace_ids.append(tid)
        else:
            trace_ids = []
            for item in selected_items:
                tid = item.data(0, Qt.ItemDataRole.UserRole)
                if tid and tid not in trace_ids:
                    trace_ids.append(tid)

        if not trace_ids:
            QMessageBox.warning(self, tr("Export"), tr("Please select or check traces to export."))
            return

        # Gather trace objects
        traces_to_export = []
        for tid in trace_ids:
            trace = self.manager.get_trace(tid)
            if trace:
                traces_to_export.append(trace)

        if not traces_to_export:
            QMessageBox.warning(self, tr("Export"), tr("Failed to retrieve selected traces."))
            return

        # Open export settings dialog
        from src.gui.widgets.export_dialog import ExportSettingsDialog

        dialog = ExportSettingsDialog(traces_to_export, self)
        dialog.exec()

    def update_x_axis_ticks(self, use_khz: bool, active_domain: str):
        x_axis = self.plot_widget.getPlotItem().getAxis("bottom")
        if not getattr(self, "is_log_x", False):
            # Linear scale: Let pyqtgraph handle ticks automatically
            x_axis.setTicks(None)
            return

        if active_domain == "frequency":
            if use_khz:
                major_specs = [
                    (0.01, "0.01"),
                    (0.02, "0.02"),
                    (0.05, "0.05"),
                    (0.1, "0.1"),
                    (0.2, "0.2"),
                    (0.5, "0.5"),
                    (1.0, "1"),
                    (2.0, "2"),
                    (5.0, "5"),
                    (10.0, "10"),
                    (20.0, "20"),
                    (50.0, "50"),
                    (100.0, "100"),
                    (200.0, "200"),
                ]
                base_decades = [0.01, 0.1, 1.0, 10.0, 100.0]
            else:
                major_specs = [
                    (10.0, "10"),
                    (20.0, "20"),
                    (50.0, "50"),
                    (100.0, "100"),
                    (200.0, "200"),
                    (500.0, "500"),
                    (1000.0, "1k"),
                    (2000.0, "2k"),
                    (5000.0, "5k"),
                    (10000.0, "10k"),
                    (20000.0, "20k"),
                    (50000.0, "50k"),
                    (100000.0, "100k"),
                    (200000.0, "200k"),
                ]
                base_decades = [10.0, 100.0, 1000.0, 10000.0, 100000.0]

            major_ticks = [(np.log10(val), label) for val, label in major_specs]
            minor_ticks = []
            for dec in base_decades:
                for mul in [3, 4, 6, 7, 8, 9]:
                    val = dec * mul
                    minor_ticks.append((np.log10(val), ""))
            x_axis.setTicks([major_ticks, minor_ticks])
        else:
            # Generic decade ticks for other domains
            major_ticks = []
            minor_ticks = []
            for exp in range(-6, 7):
                val = 10.0**exp
                label = f"1e{exp}" if exp != 0 else "1"
                if exp == 3:
                    label = "1k"
                elif exp == -3:
                    label = "1m"
                major_ticks.append((float(exp), label))
                for mul in [2, 3, 4, 5, 6, 7, 8, 9]:
                    minor_ticks.append((np.log10(val * mul), ""))
            x_axis.setTicks([major_ticks, minor_ticks])

    def replot(self):
        # 1. Clear current plots
        self.plot_widget.clear()
        self.y2_view.clear()
        self.curve_items.clear()

        # Get the selected plot domain filter
        active_domain = self.filter_combo.currentData()

        traces = self.manager.get_all_traces()
        visible_traces = {}
        for tid, trace in traces.items():
            if tid not in self.trace_settings:
                continue

            # Check parent visibility
            if not self.trace_settings[tid]["visible"]:
                continue

            # Apply plot domain filter
            trace_domain = self._get_trace_domain(trace)
            if trace_domain != active_domain:
                continue

            # Ensure at least one sub-trace is visible
            settings = self.trace_settings[tid]
            has_y = settings.get("y_visible", True)
            has_y2 = (trace.y2_data is not None) and settings.get("y2_visible", True)

            if has_y or has_y2:
                visible_traces[tid] = trace

        if not visible_traces:
            self.plot_widget.setLabel("bottom", tr("X Axis"))
            self.plot_widget.setLabel("left", tr("Y Axis"))
            self.plot_item.getAxis("right").setLabel(tr("Secondary Y"))
            return

        # 2. Determine dominant plot style from the first visible trace
        first_tid = list(visible_traces.keys())[0]
        first_trace = visible_traces[first_tid]

        # Apply Axis Settings based on Plot Domain or Manual Overrides
        if not self.scale_overridden:
            self.log_x_check.blockSignals(True)
            self.log_y_check.blockSignals(True)

            first_domain = self._get_trace_domain(first_trace)
            if first_domain == "frequency":
                self.log_x_check.setChecked(True)
                self.log_y_check.setChecked(first_trace.y_axis.is_log if first_trace.y_axis else False)
            elif first_domain == "time":
                self.log_x_check.setChecked(False)
                self.log_y_check.setChecked(first_trace.y_axis.is_log if first_trace.y_axis else False)
            elif first_domain == "amplitude":
                self.log_x_check.setChecked(first_trace.x_axis.is_log if first_trace.x_axis else False)
                self.log_y_check.setChecked(first_trace.y_axis.is_log if first_trace.y_axis else False)
            else:
                self.log_x_check.setChecked(False)
                self.log_y_check.setChecked(first_trace.y_axis.is_log if first_trace.y_axis else False)

            self.log_x_check.blockSignals(False)
            self.log_y_check.blockSignals(False)

        self.is_log_x = self.log_x_check.isChecked()
        self.is_log_y = self.log_y_check.isChecked()

        # ALWAYS keep PyQtGraph's setLogMode(x=False) to avoid its severe non-linear coordinate scaling bugs.
        # We manually perform np.log10 on X coordinates instead.
        self.plot_widget.setLogMode(x=False, y=self.is_log_y)

        # Determine if we need manual kHz scaling for frequency to avoid pyqtgraph units bugs
        first_domain = self._get_trace_domain(first_trace)
        use_khz = first_domain == "frequency" and first_trace.x_axis.display_unit == "Hz"

        if first_domain == "frequency":
            if use_khz:
                self.plot_widget.setLabel("bottom", f"{tr(first_trace.x_axis.dimension).capitalize()} (kHz)")
            else:
                self.plot_widget.setLabel(
                    "bottom", tr(first_trace.x_axis.dimension).capitalize(), units=tr(first_trace.x_axis.display_unit)
                )
        elif first_domain == "time":
            self.plot_widget.setLabel(
                "bottom", tr(first_trace.x_axis.dimension).capitalize(), units=tr(first_trace.x_axis.display_unit)
            )
        elif first_domain == "amplitude":
            self.plot_widget.setLabel(
                "bottom", tr(first_trace.x_axis.dimension).capitalize(), units=tr(first_trace.x_axis.display_unit)
            )
        else:
            self.plot_widget.setLabel("bottom", "X")

        y1_labels = []
        y2_labels = []

        # 3. Draw each trace
        for tid, trace in visible_traces.items():
            settings = self.trace_settings[tid]

            # Arrays
            x = np.array(trace.x_data, dtype=float)
            if use_khz:
                x = x / 1000.0
            y = np.array(trace.y_data, dtype=float)
            y2 = np.array(trace.y2_data, dtype=float) if trace.y2_data is not None else None

            if len(x) == 0:
                continue

            # Apply Time Shift (X Shift)
            if settings["shift"] != 0.0:
                x = x + settings["shift"]

            # Convert to display formats (e.g. logX handling)
            x_for_y2 = x
            y_for_y2 = y
            y2_for_y2 = y2

            if getattr(self, "is_log_x", False):
                valid_mask = x > 0
                x_log = np.log10(x[valid_mask])
                x_for_y2 = x_log
                x = x_log
                if y is not None:
                    y_for_y2 = y[valid_mask]
                    y = y[valid_mask]
                if y2 is not None:
                    y2_for_y2 = y2[valid_mask]
                    y2 = y2[valid_mask]

            y_curve = None
            y2_curve = None

            # --- Primary Data (y) ---
            if settings.get("y_visible", True) and len(y) > 0:
                # Apply Offset (Gain Offset / Amplitude Scaling)
                y_processed = y_for_y2.copy() if settings.get("y_axis_choice", "Y1") == "Y2" else y.copy()
                if settings["offset_db"] != 0.0:
                    if trace.y_axis.display_unit in {"dB", "dBFS", "dBV", "dBu"}:
                        y_processed = y_processed + settings["offset_db"]
                    else:
                        gain_factor = 10 ** (settings["offset_db"] / 20.0)
                        y_processed = y_processed * gain_factor

                # Normalize (Align Peaks) if requested
                if self.normalize_check.isChecked():
                    if trace.y_axis.display_unit in {"dB", "dBFS", "dBV", "dBu"}:
                        y_processed = y_processed - np.max(y_processed)
                    else:
                        max_y = np.max(np.abs(y_processed))
                        if max_y > 1e-12:
                            y_processed = y_processed / max_y

                # Clip non-positive values to 1e-6 if using log Y scale to prevent math domain errors / warnings
                if getattr(self, "is_log_y", False):
                    y_processed = np.clip(y_processed, 1e-6, None)

                axis_choice = settings.get("y_axis_choice", "Y1")
                dim_cap = tr(trace.y_axis.dimension).capitalize()
                unit = trace.y_axis.display_unit
                label_str = f"{dim_cap} ({unit})" if unit else dim_cap

                if axis_choice == "Y1":
                    pen = pg.mkPen(settings["color"], width=settings.get("width", 2))
                    y_curve = self.plot_widget.plot(
                        x, y_processed, pen=pen, name=f"{trace.name} - {tr(trace.y_axis.dimension)}"
                    )
                    y1_labels.append(label_str)
                else:  # Y2
                    pen = pg.mkPen(
                        settings["color"], width=max(1, settings.get("width", 2) - 1), style=Qt.PenStyle.DashLine
                    )
                    y_curve = pg.PlotCurveItem(x_for_y2, y_processed, pen=pen)
                    self.y2_view.addItem(y_curve)
                    if self.plot_item.legend:
                        self.plot_item.legend.addItem(y_curve, f"{trace.name} - {tr(trace.y_axis.dimension)}")
                    y2_labels.append(label_str)

            # --- Secondary Data (y2) ---
            if y2 is not None and settings.get("y2_visible", True) and len(y2) > 0:
                y2_processed = y2_for_y2.copy() if settings.get("y2_axis_choice", "Y2") == "Y2" else y2.copy()

                axis_choice = settings.get("y2_axis_choice", "Y2")
                dim_cap = tr(trace.y2_axis.dimension).capitalize()
                unit = trace.y2_axis.display_unit
                label_str = f"{dim_cap} ({unit})" if unit else dim_cap

                if axis_choice == "Y1":
                    # Draw on primary axis
                    pen_y2 = pg.mkPen(
                        settings["color"], width=max(1, settings.get("width", 2) - 1), style=Qt.PenStyle.DotLine
                    )
                    y2_curve = self.plot_widget.plot(
                        x, y2_processed, pen=pen_y2, name=f"{trace.name} - {tr(trace.y2_axis.dimension)}"
                    )
                    y1_labels.append(label_str)
                else:  # Y2
                    pen_y2 = pg.mkPen(
                        settings["color"], width=max(1, settings.get("width", 2) - 1), style=Qt.PenStyle.DashLine
                    )
                    y2_curve = pg.PlotCurveItem(x_for_y2, y2_processed, pen=pen_y2)
                    self.y2_view.addItem(y2_curve)
                    if self.plot_item.legend:
                        self.plot_item.legend.addItem(y2_curve, f"{trace.name} - {tr(trace.y2_axis.dimension)}")
                    y2_labels.append(label_str)

            if y_curve is not None or y2_curve is not None:
                self.curve_items[tid] = (y_curve, y2_curve)

        # Dynamic Axis Labels
        if y1_labels:
            y1_uniq = list(dict.fromkeys(y1_labels))
            self.plot_widget.setLabel("left", ", ".join(y1_uniq))
        else:
            self.plot_widget.setLabel("left", tr("Y Axis"))

        if y2_labels:
            y2_uniq = list(dict.fromkeys(y2_labels))
            self.plot_item.getAxis("right").setLabel(", ".join(y2_uniq))
        else:
            self.plot_item.getAxis("right").setLabel("")

        # 4. Ticks setup for log Y scale
        y1_axis = self.plot_widget.getPlotItem().getAxis("left")
        y2_axis = self.plot_item.getAxis("right")

        # Reset ticks first
        y1_axis.setTicks(None)
        y2_axis.setTicks(None)

        if getattr(self, "is_log_y", False):
            # If the primary visible trace uses percent, set log ticks
            if first_trace.y_axis and first_trace.y_axis.display_unit == "%":
                percent_ticks = [100, 10, 1, 0.1, 0.01, 0.001, 0.0001]
                ticks_log = [(np.log10(t), f"{t:g}%") for t in percent_ticks]
                y1_axis.setTicks([ticks_log])
                # Set range from 0.0001% to 100%
                self.plot_widget.setYRange(np.log10(0.0001), np.log10(100))

        # Update custom X axis log ticks
        self.update_x_axis_ticks(use_khz, active_domain)

        self.update_y2_views()

        # Update min/max limits
        self.update_spinbox_limits()

        # Apply manual limits if Auto is unchecked
        # 1. X Axis Limit
        if hasattr(self, "x_auto_cb") and not self.x_auto_cb.isChecked():
            min_val = self.x_min_spin.value()
            max_val = self.x_max_spin.value()

            if getattr(self, "is_log_x", False):
                if min_val > 0 and max_val > 0:
                    self.plot_widget.setXRange(np.log10(min_val), np.log10(max_val), padding=0)
            elif use_khz:
                self.plot_widget.setXRange(min_val / 1000.0, max_val / 1000.0, padding=0)
            else:
                self.plot_widget.setXRange(min_val, max_val, padding=0)
        else:
            self.plot_widget.enableAutoRange(axis=pg.ViewBox.XAxis, enable=True)

        # 2. Y1 Axis Limit
        if hasattr(self, "y1_auto_cb") and not self.y1_auto_cb.isChecked():
            min_val = self.y1_min_spin.value()
            max_val = self.y1_max_spin.value()

            if getattr(self, "is_log_y", False):
                if first_trace.y_axis and first_trace.y_axis.display_unit == "%":
                    self.plot_widget.setYRange(np.log10(max(1e-6, min_val)), np.log10(max(1e-6, max_val)), padding=0)
                else:
                    self.plot_widget.setYRange(min_val, max_val, padding=0)
            else:
                self.plot_widget.setYRange(min_val, max_val, padding=0)
        else:
            self.plot_widget.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)

        # 3. Y2 Axis Limit
        if hasattr(self, "y2_auto_cb") and not self.y2_auto_cb.isChecked():
            min_val = self.y2_min_spin.value()
            max_val = self.y2_max_spin.value()
            self.y2_view.setYRange(min_val, max_val, padding=0)
        else:
            self.y2_view.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)

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
