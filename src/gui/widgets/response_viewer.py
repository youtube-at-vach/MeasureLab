import logging
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QMessageBox,
    QSlider,
    QGridLayout,
    QCheckBox,
    QFileDialog,
)

from scipy.signal import savgol_filter

from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.hammerstein_model import load_hammerstein_model, get_active_model, has_active_model

logger = logging.getLogger(__name__)


def _get_safe_colormap(name: str) -> pg.ColorMap:
    try:
        return pg.colormap.get(name)
    except Exception:
        from pyqtgraph.graphicsItems.GradientEditorItem import Gradients

        if name in Gradients:
            preset = Gradients[name]
            ticks = sorted(preset["ticks"], key=lambda t: t[0])
            pos = [t[0] for t in ticks]
            color = [t[1] for t in ticks]
            return pg.ColorMap(pos, color)
        raise


class ResponseViewer(MeasurementModule):
    def __init__(self, audio_engine):
        self.audio_engine = audio_engine

    @property
    def name(self) -> str:
        return "Response Viewer"

    @property
    def description(self) -> str:
        return "Visualizes Parallel Hammerstein kernels, generates 2D THD/harmonic maps, and simulates tone response."

    def get_widget(self):
        return ResponseViewerWidget(self)


class ResponseViewerWidget(QWidget):
    def __init__(self, module: ResponseViewer):
        QWidget.__init__(self)
        self.module = module

        # Model Data Cache
        self.cached_freqs = None
        self.cached_mags = {}
        self.cached_phases = {}
        self.cached_kernels = None
        self.cached_time_ms = None
        self.model_metadata = {}
        self.first_map_draw = True
        self.cached_Z = None

        self.iso_curves = []
        self.iso_labels = []

        # Global Reference Tone Parameters
        self.ref_f0 = 1000.0
        self.ref_amp = -6.0

        self.init_ui()

        # Check for initial live model
        self.update_cache_button_state()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # --- Left Panel: Sidebar (Fixed Width, Wrapped in Scroll Area) ---
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setFixedWidth(330)
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sidebar_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        sidebar_content = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_content)
        sidebar_layout.setContentsMargins(0, 0, 4, 0)
        sidebar_layout.setSpacing(8)

        # 1. Model Source Group
        source_group = QGroupBox(tr("Model Source"))
        source_form = QVBoxLayout(source_group)
        source_form.setSpacing(6)

        self.import_btn = QPushButton(tr("Import Model JSON..."))
        self.import_btn.setStyleSheet("background-color: #4ba3e3; color: white; font-weight: bold; padding: 5px;")
        self.import_btn.clicked.connect(self.import_model_file)
        source_form.addWidget(self.import_btn)

        self.load_cache_btn = QPushButton(tr("Load Live Cache"))
        self.load_cache_btn.setStyleSheet("background-color: #2b8c56; color: white; font-weight: bold; padding: 5px;")
        self.load_cache_btn.clicked.connect(self.load_live_cache)
        source_form.addWidget(self.load_cache_btn)

        # Info Labels
        self.lbl_status = QLabel(tr("No Model Loaded"))
        self.lbl_status.setStyleSheet("font-weight: bold; color: #d9534f;")
        self.lbl_status.setMaximumWidth(180)
        self.lbl_sr = QLabel("SR: -- Hz")
        self.lbl_order = QLabel("Order (P): --")

        self.smooth_combo = QComboBox()
        self.smooth_combo.addItem(tr("None"), "None")
        self.smooth_combo.addItem(tr("Low Smoothing"), "Light")
        self.smooth_combo.addItem(tr("Medium Smoothing"), "Medium")
        self.smooth_combo.addItem(tr("High Smoothing"), "Heavy")
        self.smooth_combo.setCurrentIndex(1)  # Default: Light
        self.smooth_combo.currentIndexChanged.connect(self.refresh_plots_with_smoothing)

        info_layout = QFormLayout()
        info_layout.setSpacing(4)
        info_layout.addRow(tr("Status:"), self.lbl_status)
        info_layout.addRow(tr("Rate:"), self.lbl_sr)
        info_layout.addRow(tr("Order:"), self.lbl_order)
        info_layout.addRow(tr("Graph Smoothing:"), self.smooth_combo)
        source_form.addLayout(info_layout)
        sidebar_layout.addWidget(source_group)

        # 2. 2D Map Configuration Group
        self.map_group = QGroupBox(tr("2D Map Settings"))
        map_form = QFormLayout(self.map_group)
        map_form.setSpacing(6)

        self.map_type_combo = QComboBox()
        self.map_type_combo.addItem(tr("THD Map"), "THD")
        self.map_type_combo.addItem("H2 Map", "h2")
        self.map_type_combo.addItem("H3 Map", "h3")
        self.map_type_combo.addItem("H4 Map", "h4")
        self.map_type_combo.addItem("H5 Map", "h5")
        self.map_type_combo.currentIndexChanged.connect(self.update_2d_map)
        map_form.addRow(tr("Map Type:"), self.map_type_combo)

        self.harm_unit_combo = QComboBox()
        self.harm_unit_combo.addItem(tr("dBr (Relative)"), "dbr")
        self.harm_unit_combo.addItem(tr("dBFS (Absolute)"), "dbfs")
        self.harm_unit_combo.currentIndexChanged.connect(self.update_2d_map)
        map_form.addRow(tr("Harmonic Unit:"), self.harm_unit_combo)

        self.map_resolution_combo = QComboBox()
        self.map_resolution_combo.addItem(tr("Overview"), 100)
        self.map_resolution_combo.addItem(tr("Standard"), 300)
        self.map_resolution_combo.addItem(tr("Detail"), 600)
        self.map_resolution_combo.setCurrentIndex(1)  # Default to Standard (300)
        self.map_resolution_combo.currentIndexChanged.connect(self.update_2d_map)
        map_form.addRow(tr("Resolution:"), self.map_resolution_combo)

        self.min_level_spin = QDoubleSpinBox()
        self.min_level_spin.setRange(-120.0, -10.0)
        self.min_level_spin.setValue(-60.0)
        self.min_level_spin.setSuffix(" dBFS")
        self.min_level_spin.valueChanged.connect(self.update_2d_map)
        map_form.addRow(tr("Min Level:"), self.min_level_spin)

        self.max_level_spin = QDoubleSpinBox()
        self.max_level_spin.setRange(-20.0, 10.0)
        self.max_level_spin.setValue(0.0)
        self.max_level_spin.setSuffix(" dBFS")
        self.max_level_spin.valueChanged.connect(self.update_2d_map)
        map_form.addRow(tr("Max Level:"), self.max_level_spin)

        # Color Map
        self.color_map_combo = QComboBox()
        self.color_map_combo.addItem("Inferno", "inferno")
        self.color_map_combo.addItem("Viridis", "viridis")
        self.color_map_combo.addItem("Plasma", "plasma")
        self.color_map_combo.addItem("Magma", "magma")
        self.color_map_combo.addItem("Turbo", "turbo")
        self.color_map_combo.addItem("Thermal", "thermal")
        self.color_map_combo.addItem("Flame", "flame")
        self.color_map_combo.addItem("Yellowy", "yellowy")
        self.color_map_combo.addItem("Bipolar", "bipolar")
        self.color_map_combo.addItem("Spectrum", "spectrum")
        self.color_map_combo.addItem("Cyclic", "cyclic")
        self.color_map_combo.addItem("Greyscale", "grey")
        self.color_map_combo.currentIndexChanged.connect(self.update_color_map)
        self.color_map_combo.blockSignals(True)
        self.color_map_combo.setCurrentIndex(self.color_map_combo.findData("thermal"))
        self.color_map_combo.blockSignals(False)
        map_form.addRow(tr("Color Map:"), self.color_map_combo)

        self.show_contours_chk = QCheckBox(tr("Show Contours"))
        self.show_contours_chk.setChecked(True)
        self.show_contours_chk.toggled.connect(self.update_2d_map)
        map_form.addRow(self.show_contours_chk)

        self.enable_noise_chk = QCheckBox(tr("Enable Noise Floor"))
        self.enable_noise_chk.setChecked(False)
        self.enable_noise_chk.toggled.connect(self.on_noise_floor_toggled)
        map_form.addRow(self.enable_noise_chk)

        self.noise_source_combo = QComboBox()
        self.noise_source_combo.addItem(tr("Measured Value"), "Measured")
        self.noise_source_combo.addItem(tr("Manual Setting"), "Manual")
        self.noise_source_combo.setCurrentIndex(1)  # Default to Manual setting
        self.noise_source_combo.setEnabled(False)
        self.noise_source_combo.currentIndexChanged.connect(self.on_noise_source_changed)
        map_form.addRow(tr("Noise Floor Source:"), self.noise_source_combo)

        self.measured_noise_label = QLabel(tr("N/A"))
        self.measured_noise_label.setStyleSheet("font-weight: bold; color: #2b8c56;")
        map_form.addRow(tr("Measured:"), self.measured_noise_label)

        self.noise_floor_spin = QDoubleSpinBox()
        self.noise_floor_spin.setRange(-160.0, -40.0)
        self.noise_floor_spin.setValue(-100.0)
        self.noise_floor_spin.setSuffix(" dBFS")
        self.noise_floor_spin.setSingleStep(5.0)
        self.noise_floor_spin.setEnabled(False)
        self.noise_floor_spin.valueChanged.connect(self.update_2d_map)
        map_form.addRow(tr("Manual Noise Floor:"), self.noise_floor_spin)

        self.map_group.setEnabled(False)
        sidebar_layout.addWidget(self.map_group)

        # 3. Reference Tone Settings Group
        self.ref_group = QGroupBox(tr("Reference Tone Settings"))
        ref_form = QVBoxLayout(self.ref_group)
        ref_form.setSpacing(6)

        # Freq
        ref_form.addWidget(QLabel(tr("Input Frequency")))
        self.ref_f0_spin = QDoubleSpinBox()
        self.ref_f0_spin.setRange(20.0, 20000.0)
        self.ref_f0_spin.setSuffix(" Hz")
        self.ref_f0_spin.setValue(self.ref_f0)
        self.ref_f0_spin.setSingleStep(100.0)
        self.ref_f0_spin.valueChanged.connect(self._on_ref_freq_spin_changed)
        ref_form.addWidget(self.ref_f0_spin)

        self.ref_f0_slider = QSlider(Qt.Orientation.Horizontal)
        self.ref_f0_slider.setRange(0, 1000)
        self.ref_f0_slider.setValue(500)
        self.ref_f0_slider.valueChanged.connect(self._on_ref_freq_slider_changed)
        ref_form.addWidget(self.ref_f0_slider)

        # Amplitude
        ref_form.addWidget(QLabel(tr("Input Amplitude")))
        self.ref_amp_spin = QDoubleSpinBox()
        self.ref_amp_spin.setRange(-100.0, 10.0)
        self.ref_amp_spin.setSuffix(" dBFS")
        self.ref_amp_spin.setValue(self.ref_amp)
        self.ref_amp_spin.setSingleStep(1.0)
        self.ref_amp_spin.valueChanged.connect(self._on_ref_amp_spin_changed)
        ref_form.addWidget(self.ref_amp_spin)

        self.ref_amp_slider = QSlider(Qt.Orientation.Horizontal)
        self.ref_amp_slider.setRange(-1000, 100)
        self.ref_amp_slider.setValue(int(self.ref_amp * 10))
        self.ref_amp_slider.valueChanged.connect(self._on_ref_amp_slider_changed)
        ref_form.addWidget(self.ref_amp_slider)

        # Phase options
        self.ref_loopback_phase_chk = QCheckBox(tr("Include Audio Interface Phase"))
        self.ref_loopback_phase_chk.setChecked(True)
        self.ref_loopback_phase_chk.toggled.connect(self.update_simulation)
        ref_form.addWidget(self.ref_loopback_phase_chk)

        self.ref_group.setEnabled(False)
        sidebar_layout.addWidget(self.ref_group)

        # 4. Wiener Settings Group
        self.wiener_group = QGroupBox(tr("Wiener Settings"))
        wiener_form = QVBoxLayout(self.wiener_group)
        wiener_form.setSpacing(6)

        wiener_form.addWidget(QLabel(tr("Equivalent Gaussian RMS Level (σ)")))
        self.wiener_sigma_spin = QDoubleSpinBox()
        self.wiener_sigma_spin.setRange(-100.0, 10.0)
        self.wiener_sigma_spin.setSuffix(" dBFS")
        self.wiener_sigma_spin.setValue(-6.0)
        self.wiener_sigma_spin.setSingleStep(1.0)
        self.wiener_sigma_spin.valueChanged.connect(self._on_wiener_sigma_spin_changed)
        wiener_form.addWidget(self.wiener_sigma_spin)

        self.wiener_sigma_slider = QSlider(Qt.Orientation.Horizontal)
        self.wiener_sigma_slider.setRange(-1000, 100)
        self.wiener_sigma_slider.setValue(-60)
        self.wiener_sigma_slider.valueChanged.connect(self._on_wiener_sigma_slider_changed)
        wiener_form.addWidget(self.wiener_sigma_slider)

        self.wiener_group.setEnabled(False)
        sidebar_layout.addWidget(self.wiener_group)

        sidebar_layout.addStretch()
        sidebar_content.setLayout(sidebar_layout)
        sidebar_scroll.setWidget(sidebar_content)
        main_layout.addWidget(sidebar_scroll)

        # --- Right Panel: Tab Content Area ---
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self.on_tab_changed)

        # Tab 1: Bode plots
        self.tab_bode = QWidget()
        bode_layout = QVBoxLayout(self.tab_bode)
        bode_layout.setContentsMargins(2, 2, 2, 2)

        self.mag_plot = pg.PlotWidget(title=tr("Bode Magnitude Response (PHM Separation)"))
        self.mag_plot.setLabel("left", tr("Gain"), units="dB")
        self.mag_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.mag_plot.setLogMode(True, False)
        self.mag_plot.showGrid(True, True, alpha=0.3)
        self.mag_plot.addLegend(offset=(10, 10))
        bode_layout.addWidget(self.mag_plot)

        self.phase_plot = pg.PlotWidget(title=tr("Bode Phase Response (PHM Separation)"))
        self.phase_plot.setLabel("left", tr("Phase"), units="deg")
        self.phase_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.phase_plot.setLogMode(True, False)
        self.phase_plot.showGrid(True, True, alpha=0.3)
        self.phase_plot.addLegend(offset=(10, 10))
        bode_layout.addWidget(self.phase_plot)
        self.tabs.addTab(self.tab_bode, tr("Bode Plots"))

        # Tab 2: Kernels
        self.tab_kernels = QWidget()
        kernels_layout = QVBoxLayout(self.tab_kernels)
        kernels_layout.setContentsMargins(2, 2, 2, 2)

        self.kernel_plot = pg.PlotWidget(title=tr("Separated Parallel Hammerstein Kernels"))
        self.kernel_plot.setLabel("left", tr("Normalized Amplitude"))
        self.kernel_plot.setLabel("bottom", tr("Time"), units="ms")
        self.kernel_plot.showGrid(True, True, alpha=0.3)
        self.kernel_plot.addLegend(offset=(10, 10))
        kernels_layout.addWidget(self.kernel_plot)
        self.tabs.addTab(self.tab_kernels, tr("Kernels"))

        # Tab 3: 2D Distortion Map
        self.tab_map = QWidget()
        map_layout = QVBoxLayout(self.tab_map)
        map_layout.setContentsMargins(2, 2, 2, 2)

        self.map_graphics_widget = pg.GraphicsLayoutWidget()
        self.map_plot_item = self.map_graphics_widget.addPlot(title=tr("Nonlinear Distortion Map"))
        self.map_plot_item.setLabel("left", tr("Input Amplitude"), units="dBFS")
        self.map_plot_item.setLabel("bottom", tr("Frequency"), units="Hz")
        self.map_plot_item.setLogMode(True, False)
        self.map_plot_item.showGrid(True, True, alpha=0.3)

        self.image_item = pg.ImageItem()
        self.map_plot_item.addItem(self.image_item)

        # Crosshair lines
        self.v_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen((255, 255, 0, 150), width=1.0))
        self.h_line = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen((255, 255, 0, 150), width=1.0))
        self.v_line.hide()
        self.h_line.hide()
        self.map_plot_item.addItem(self.v_line, ignoreBounds=True)
        self.map_plot_item.addItem(self.h_line, ignoreBounds=True)

        # Reference indicator lines (permanent, showing self.ref_f0, self.ref_amp)
        self.ref_v_line = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen((255, 80, 0, 200), width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.ref_h_line = pg.InfiniteLine(
            angle=0, movable=False, pen=pg.mkPen((255, 80, 0, 200), width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.map_plot_item.addItem(self.ref_v_line, ignoreBounds=True)
        self.map_plot_item.addItem(self.ref_h_line, ignoreBounds=True)

        # Floating coordinate overlay label
        self.hover_label_item = pg.TextItem(text="", color=(255, 255, 255), fill=(0, 0, 0, 180), anchor=(0, 0))
        self.hover_label_item.hide()
        self.map_plot_item.addItem(self.hover_label_item, ignoreBounds=True)

        # Connect mouse move & click
        self.map_plot_item.scene().sigMouseMoved.connect(self.on_mouse_moved)
        self.map_plot_item.scene().sigMouseClicked.connect(self.on_map_clicked)

        self.colorbar = pg.ColorBarItem(colorMap=_get_safe_colormap("thermal"))
        self.colorbar.setImageItem(self.image_item)
        self.map_graphics_widget.addItem(self.colorbar)

        map_layout.addWidget(self.map_graphics_widget)
        self.tabs.addTab(self.tab_map, tr("2D Map"))

        # Tab 4: Distortion Curves
        self.tab_curves = QWidget()
        curves_layout = QHBoxLayout(self.tab_curves)
        curves_layout.setContentsMargins(2, 2, 2, 2)
        curves_layout.setSpacing(5)

        # Left plot: Distortion vs Frequency (at fixed amplitude ref_amp)
        self.curve_freq_plot = pg.PlotWidget(title=tr("Distortion vs Frequency (at Reference Amplitude)"))
        self.curve_freq_plot.setLabel("left", tr("Level"), units="dB")
        self.curve_freq_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.curve_freq_plot.setLogMode(True, False)
        self.curve_freq_plot.showGrid(True, True, alpha=0.3)
        self.curve_freq_plot.addLegend(offset=(10, 10))
        curves_layout.addWidget(self.curve_freq_plot, stretch=1)

        # Red vertical indicator line for ref_f0
        self.curve_freq_ref_line = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen((255, 80, 0, 150), width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.curve_freq_plot.addItem(self.curve_freq_ref_line)

        # Right plot: Distortion vs Amplitude (at fixed frequency ref_f0)
        self.curve_amp_plot = pg.PlotWidget(title=tr("Distortion vs Amplitude (at Reference Frequency)"))
        self.curve_amp_plot.setLabel("left", tr("Level"), units="dB")
        self.curve_amp_plot.setLabel("bottom", tr("Input Amplitude"), units="dBFS")
        self.curve_amp_plot.setLogMode(False, False)
        self.curve_amp_plot.showGrid(True, True, alpha=0.3)
        self.curve_amp_plot.addLegend(offset=(10, 10))
        curves_layout.addWidget(self.curve_amp_plot, stretch=1)

        # Red vertical indicator line for ref_amp
        self.curve_amp_ref_line = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen((255, 80, 0, 150), width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.curve_amp_plot.addItem(self.curve_amp_ref_line)

        # Set default Y range to match distortion_analyzer sweep plot (-140 to 0 dB)
        self.curve_amp_plot.setYRange(-140, 0)

        # Synchronize Y-axes ranges of left and right plots, defaulting to the right plot's scale
        self.curve_freq_plot.setYLink(self.curve_amp_plot)

        self.tabs.addTab(self.tab_curves, tr("Dist. Curves"))

        # Tab 5: Simulator
        self.tab_sim = QWidget()
        sim_layout = QHBoxLayout(self.tab_sim)
        sim_layout.setContentsMargins(2, 2, 2, 2)
        sim_layout.setSpacing(5)

        # Left Column for Simulator Results
        sim_left_panel = QWidget()
        sim_left_panel.setFixedWidth(280)
        sim_left_layout = QVBoxLayout(sim_left_panel)
        sim_left_layout.setContentsMargins(0, 0, 0, 0)
        sim_left_layout.setSpacing(8)

        # Simulator info grid
        grid_widget = QWidget()
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setContentsMargins(5, 5, 5, 5)
        grid_layout.setSpacing(6)

        grid_layout.addWidget(QLabel(f"<b>{tr('Harmonic')}</b>"), 0, 0)
        grid_layout.addWidget(QLabel(f"<b>{tr('Frequency')}</b>"), 0, 1)
        grid_layout.addWidget(QLabel(f"<b>{tr('Amplitude')}</b>"), 0, 2)
        grid_layout.addWidget(QLabel(f"<b>{tr('Phase')}</b>"), 0, 3)

        self.sim_result_labels = {}
        harmonics_labels = [
            ("h1", tr("Fundamental")),
            ("h2", "2nd Harm"),
            ("h3", "3rd Harm"),
            ("h4", "4th Harm"),
            ("h5", "5th Harm"),
        ]

        colors_hex = {
            "h1": "#4ba3e3",
            "h2": "#2b8c56",
            "h3": "#e68c14",
            "h4": "#c832a0",
            "h5": "#d9534f",
        }

        for idx, (key, label) in enumerate(harmonics_labels, 1):
            lbl_name = QLabel(label)
            lbl_name.setStyleSheet(f"color: {colors_hex[key]}; font-weight: bold;")
            lbl_freq = QLabel("-- Hz")
            lbl_amp = QLabel("-- dBFS")
            lbl_phase = QLabel("--°")

            grid_layout.addWidget(lbl_name, idx, 0)
            grid_layout.addWidget(lbl_freq, idx, 1)
            grid_layout.addWidget(lbl_amp, idx, 2)
            grid_layout.addWidget(lbl_phase, idx, 3)

            self.sim_result_labels[key] = {"freq": lbl_freq, "amp": lbl_amp, "phase": lbl_phase}

        sim_left_layout.addWidget(grid_widget)
        sim_left_layout.addStretch()

        sim_layout.addWidget(sim_left_panel)

        # Simulator plot (right side of simulator tab)
        self.sim_plot = pg.PlotWidget(title=tr("Output Prediction Spectrum"))
        self.sim_plot.setLabel("left", tr("Amplitude"), units="dBFS")
        self.sim_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.sim_plot.setLogMode(True, False)
        self.sim_plot.setXRange(np.log10(20.0), np.log10(100000.0))
        self.sim_plot.setYRange(-120.0, 10.0)
        self.sim_plot.showGrid(True, True, alpha=0.3)
        sim_layout.addWidget(self.sim_plot, stretch=1)

        self.tabs.addTab(self.tab_sim, tr("Simulator"))

        # Tab 6: I/O & Gain Compression
        self.tab_io_comp = QWidget()
        io_comp_layout = QHBoxLayout(self.tab_io_comp)
        io_comp_layout.setContentsMargins(2, 2, 2, 2)
        io_comp_layout.setSpacing(5)

        self.io_plot = pg.PlotWidget(title=tr("Input-Output Transfer Curve"))
        self.io_plot.setLabel("left", tr("Output Amplitude"), units="dBFS")
        self.io_plot.setLabel("bottom", tr("Input Amplitude"), units="dBFS")
        self.io_plot.showGrid(True, True, alpha=0.3)
        self.io_plot.addLegend(offset=(10, 10))
        io_comp_layout.addWidget(self.io_plot, stretch=1)

        # Reference indicator lines for io_plot
        self.io_ref_v_line = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen((255, 80, 0, 150), width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.io_ref_h_line = pg.InfiniteLine(
            angle=0, movable=False, pen=pg.mkPen((255, 80, 0, 150), width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.io_plot.addItem(self.io_ref_v_line)
        self.io_plot.addItem(self.io_ref_h_line)

        # 1dB Compression Point guide lines and marker for io_plot
        self.io_p1db_v_line = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen((0, 200, 255, 180), width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.io_p1db_h_line = pg.InfiniteLine(
            angle=0, movable=False, pen=pg.mkPen((0, 200, 255, 180), width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.io_plot.addItem(self.io_p1db_v_line)
        self.io_plot.addItem(self.io_p1db_h_line)
        self.io_p1db_marker = pg.PlotDataItem(
            symbol="o",
            symbolBrush=pg.mkBrush((0, 200, 255)),
            symbolPen=pg.mkPen((255, 255, 255)),
            symbolSize=10,
        )
        self.io_plot.addItem(self.io_p1db_marker)

        self.comp_plot = pg.PlotWidget(title=tr("Gain Compression (Compression Error)"))
        self.comp_plot.setLabel("left", tr("Compression Error"), units="dB")
        self.comp_plot.setLabel("bottom", tr("Input Amplitude"), units="dBFS")
        self.comp_plot.showGrid(True, True, alpha=0.3)
        self.comp_plot.addLegend(offset=(10, 10))
        io_comp_layout.addWidget(self.comp_plot, stretch=1)

        # Permanent line at 0 dB representing the ideal linear gain
        self.comp_linear_ref_line = pg.InfiniteLine(
            angle=0, movable=False, pen=pg.mkPen((120, 120, 120, 150), width=1.2, style=Qt.PenStyle.DashLine)
        )
        self.comp_plot.addItem(self.comp_linear_ref_line)

        # Reference indicator lines for comp_plot
        self.comp_ref_v_line = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen((255, 80, 0, 150), width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.comp_ref_h_line = pg.InfiniteLine(
            angle=0, movable=False, pen=pg.mkPen((255, 80, 0, 150), width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.comp_plot.addItem(self.comp_ref_v_line)
        self.comp_plot.addItem(self.comp_ref_h_line)

        # 1dB Compression Point limit line (-1 dB)
        self.comp_1db_limit_line = pg.InfiniteLine(
            angle=0, movable=False, pen=pg.mkPen((200, 0, 0, 150), width=1.2, style=Qt.PenStyle.DashLine)
        )
        self.comp_1db_limit_line.setPos(-1.0)
        self.comp_plot.addItem(self.comp_1db_limit_line)

        # 1dB Compression Point guide lines and marker for comp_plot
        self.comp_p1db_v_line = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen((0, 200, 255, 180), width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.comp_p1db_h_line = pg.InfiniteLine(
            angle=0, movable=False, pen=pg.mkPen((0, 200, 255, 180), width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.comp_plot.addItem(self.comp_p1db_v_line)
        self.comp_plot.addItem(self.comp_p1db_h_line)
        self.comp_p1db_marker = pg.PlotDataItem(
            symbol="o",
            symbolBrush=pg.mkBrush((0, 200, 255)),
            symbolPen=pg.mkPen((255, 255, 255)),
            symbolSize=10,
        )
        self.comp_plot.addItem(self.comp_p1db_marker)

        # Initially hide the 1dB compression lines & markers
        self.io_p1db_v_line.hide()
        self.io_p1db_h_line.hide()
        self.io_p1db_marker.setData([], [])
        self.comp_p1db_v_line.hide()
        self.comp_p1db_h_line.hide()
        self.comp_p1db_marker.setData([], [])

        self.tabs.addTab(self.tab_io_comp, tr("I/O & Comp"))

        # Tab 7: Wiener Representation
        self.tab_wiener = QWidget()
        wiener_layout = QHBoxLayout(self.tab_wiener)
        wiener_layout.setContentsMargins(2, 2, 2, 2)
        wiener_layout.setSpacing(5)

        # Left Column for Bode plots (Magnitude & Phase)
        bode_col = QWidget()
        bode_col_layout = QVBoxLayout(bode_col)
        bode_col_layout.setContentsMargins(0, 0, 0, 0)
        bode_col_layout.setSpacing(5)

        self.wie_mag_plot = pg.PlotWidget(title=tr("Wiener Kernel Magnitude Response"))
        self.wie_mag_plot.setLabel("left", tr("Gain"), units="dB")
        self.wie_mag_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.wie_mag_plot.setLogMode(True, False)
        self.wie_mag_plot.showGrid(True, True, alpha=0.3)
        self.wie_mag_plot.addLegend(offset=(10, 10))
        bode_col_layout.addWidget(self.wie_mag_plot)

        self.wie_phase_plot = pg.PlotWidget(title=tr("Wiener Kernel Phase Response"))
        self.wie_phase_plot.setLabel("left", tr("Phase"), units="deg")
        self.wie_phase_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.wie_phase_plot.setLogMode(True, False)
        self.wie_phase_plot.showGrid(True, True, alpha=0.3)
        self.wie_phase_plot.addLegend(offset=(10, 10))
        bode_col_layout.addWidget(self.wie_phase_plot)

        # Sync X-axis of Wiener mag and phase plots
        self.wie_phase_plot.setXLink(self.wie_mag_plot)

        wiener_layout.addWidget(bode_col, stretch=1)

        # Right Column for Energy Fraction plot
        energy_col = QWidget()
        energy_col_layout = QVBoxLayout(energy_col)
        energy_col_layout.setContentsMargins(0, 0, 0, 0)
        energy_col_layout.setSpacing(5)

        self.wie_energy_plot = pg.PlotWidget(title=tr("Wiener Kernel Energy Fraction"))
        self.wie_energy_plot.setLabel("left", tr("Energy Fraction"), units="%")
        self.wie_energy_plot.setLabel("bottom", tr("Kernel Order"))
        self.wie_energy_plot.setYRange(0, 100)
        self.wie_energy_plot.showGrid(x=False, y=True, alpha=0.3)

        # Set discrete ticks for orders
        x_ticks = [(1, "w1"), (2, "w2"), (3, "w3"), (4, "w4"), (5, "w5")]
        self.wie_energy_plot.getAxis("bottom").setTicks([x_ticks])
        energy_col_layout.addWidget(self.wie_energy_plot)

        wiener_layout.addWidget(energy_col, stretch=1)

        self.tabs.addTab(self.tab_wiener, tr("Wiener Representation"))

        main_layout.addWidget(self.tabs, stretch=1)

    def on_noise_floor_toggled(self, checked):
        self.noise_source_combo.setEnabled(checked)
        self.update_noise_floor_ui_states()
        thd_idx = self.map_type_combo.findData("THD")
        if thd_idx >= 0:
            label = tr("THD+N Map") if checked else tr("THD Map")
            self.map_type_combo.setItemText(thd_idx, label)
        self.update_2d_map()

    def on_noise_source_changed(self, index):
        self.update_noise_floor_ui_states()
        self.update_2d_map()

    def update_noise_floor_ui_states(self):
        checked = self.enable_noise_chk.isChecked()
        source = self.noise_source_combo.currentData()
        self.noise_floor_spin.setEnabled(checked and source == "Manual")

    def get_current_noise_floor(self):
        """Returns (use_noise, noise_dbfs) based on UI states and loaded model metadata."""
        if not self.enable_noise_chk.isChecked():
            return False, -160.0

        source = self.noise_source_combo.currentData()
        measured_val = self.model_metadata.get("noise_floor_dbfs", None)

        if source == "Measured":
            if measured_val is not None:
                return True, float(measured_val)
            else:
                # Fallback to manual if measured value is missing
                return True, self.noise_floor_spin.value()
        else:
            return True, self.noise_floor_spin.value()

    def update_cache_button_state(self):
        available = has_active_model()
        self.load_cache_btn.setEnabled(available)
        if available:
            self.load_cache_btn.setToolTip(tr("Load model from the latest measurement."))
        else:
            self.load_cache_btn.setToolTip(tr("No active measurement found. Run sweep first."))

    def showEvent(self, event):
        super().showEvent(event)
        self.update_cache_button_state()

    def load_live_cache(self):
        data = get_active_model()
        if data is not None:
            try:
                self.set_model_data(data)
                self.lbl_status.setText(tr("Live Cache Loaded"))
                self.lbl_status.setStyleSheet("font-weight: bold; color: #2b8c56;")
            except Exception as e:
                logger.error("Failed to load model from cache: %s", e)
                QMessageBox.critical(self, tr("Load Error"), f"Failed to load cache model: {e}")
        else:
            QMessageBox.warning(self, tr("Cache Empty"), tr("No active model cached. Please perform SSS measurement."))

    def import_model_file(self):
        filepath, _ = QFileDialog.getOpenFileName(self, tr("Import Hammerstein Model"), "", "JSON Files (*.json)")
        if not filepath:
            return

        try:
            data = load_hammerstein_model(filepath)
            self.set_model_data(data)
            import os

            filename = os.path.basename(filepath)
            display_name = filename
            if len(filename) > 24:
                display_name = filename[:21] + "..."
            self.lbl_status.setText(display_name)
            self.lbl_status.setToolTip(filename)
            self.lbl_status.setStyleSheet("font-weight: bold; color: #4ba3e3;")
        except Exception as e:
            logger.error("Failed to import model from %s: %s", filepath, e)
            QMessageBox.critical(self, tr("Import Error"), f"Failed to parse model file: {e}")

    def set_model_data(self, data):
        self.first_map_draw = True
        self.model_metadata = data.get("metadata", {})
        self.cached_freqs = data["frequency_domain"]["freqs"]
        self.cached_mags = data["frequency_domain"]["magnitudes_db"]
        self.cached_phases = data["frequency_domain"]["phases_deg"]

        self.cached_time_ms = data["time_domain"]["time_ms"]
        # Convert dictionary to list for kernels if needed
        kernels_dict = data["time_domain"]["kernels"]
        self.cached_kernels = [kernels_dict[f"h{p}"] for p in range(1, len(kernels_dict) + 1)]

        # Update Sidebar stats
        self.lbl_sr.setText(f"{self.model_metadata.get('sample_rate', 48000):g} Hz")
        self.lbl_order.setText(str(self.model_metadata.get("P", 5)))

        # Update measured noise floor label and source choices
        measured_val = self.model_metadata.get("noise_floor_dbfs", None)
        if measured_val is not None:
            self.measured_noise_label.setText(f"{measured_val:.1f} dBFS")
            self.noise_source_combo.model().item(0).setEnabled(True)
            # Switch to Measured if available
            self.noise_source_combo.blockSignals(True)
            self.noise_source_combo.setCurrentIndex(0)  # Measured
            self.noise_source_combo.blockSignals(False)
        else:
            self.measured_noise_label.setText(tr("N/A"))
            self.noise_source_combo.model().item(0).setEnabled(False)
            if self.noise_source_combo.currentData() == "Measured":
                self.noise_source_combo.blockSignals(True)
                self.noise_source_combo.setCurrentIndex(1)  # Manual
                self.noise_source_combo.blockSignals(False)

        self.update_noise_floor_ui_states()

        # Enable Groups
        self.map_group.setEnabled(True)
        self.ref_group.setEnabled(True)
        self.wiener_group.setEnabled(True)

        # Sync Wiener level default with ref_amp
        self.wiener_sigma_spin.blockSignals(True)
        self.wiener_sigma_slider.blockSignals(True)
        self.wiener_sigma_spin.setValue(self.ref_amp)
        self.wiener_sigma_slider.setValue(int(self.ref_amp * 10))
        self.wiener_sigma_spin.blockSignals(False)
        self.wiener_sigma_slider.blockSignals(False)

        # Redraw Bode, Kernels, Maps
        self.update_bode_plots()
        self.update_kernel_plots()
        self.update_2d_map()
        self.update_wiener_plots()

        # Update reference parameters and dependent plots/simulation
        self.update_reference_params(self.ref_f0, self.ref_amp)

    def refresh_plots_with_smoothing(self):
        if self.cached_freqs is not None:
            self.update_bode_plots()

    def apply_smoothing(self, y_data, level):
        if level == "None" or len(y_data) < 15:
            return y_data

        window_size = 15
        if level == "Medium":
            window_size = 35
        elif level == "Heavy":
            window_size = 75

        window_size = min(window_size, len(y_data) - 1)
        if window_size % 2 == 0:
            window_size -= 1

        if window_size < 5:
            return y_data

        try:
            return savgol_filter(y_data, window_size, polyorder=2)
        except Exception as e:
            logger.warning("Smoothing failed: %s", e)
            return y_data

    def update_bode_plots(self):
        if self.cached_freqs is None:
            return

        self.mag_plot.clear()
        self.phase_plot.clear()

        smooth_level = self.smooth_combo.currentData()

        colors = {
            "h1": (75, 163, 227),  # fundamental
            "h2": (43, 140, 86),
            "h3": (230, 140, 20),
            "h4": (200, 50, 160),
            "h5": (217, 83, 79),
        }

        labels = {
            "h1": tr("Fundamental (Linear Kernel h1)"),
            "h2": tr("2nd Order (Kernel h2)"),
            "h3": tr("3rd Order (Kernel h3)"),
            "h4": tr("4th Order (Kernel h4)"),
            "h5": tr("5th Order (Kernel h5)"),
        }

        for key in ["h1", "h2", "h3", "h4", "h5"]:
            if key in self.cached_mags:
                mag_smoothed = self.apply_smoothing(self.cached_mags[key], smooth_level)
                phase_smoothed = self.apply_smoothing(self.cached_phases[key], smooth_level)

                # Magnitude
                pen_mag = pg.mkPen(color=colors[key], width=2)
                self.mag_plot.plot(self.cached_freqs, mag_smoothed, pen=pen_mag, name=labels[key])

                # Phase
                pen_phase = pg.mkPen(color=colors[key], width=1.5)
                self.phase_plot.plot(self.cached_freqs, phase_smoothed, pen=pen_phase, name=labels[key])

    def update_kernel_plots(self):
        if self.cached_kernels is None:
            return

        self.kernel_plot.clear()
        self.kernel_plot.setXRange(-5.0, 35.0)

        ref_max = np.max(np.abs(self.cached_kernels[0])) if len(self.cached_kernels) > 0 else 1.0
        if ref_max < 1e-12:
            ref_max = 1.0

        colors = [
            (75, 163, 227),
            (43, 140, 86),
            (230, 140, 20),
            (200, 50, 160),
            (217, 83, 79),
        ]

        labels = [
            tr("Kernel h1"),
            tr("Kernel h2"),
            tr("Kernel h3"),
            tr("Kernel h4"),
            tr("Kernel h5"),
        ]

        for p in range(len(self.cached_kernels)):
            pen = pg.mkPen(color=colors[p], width=1.8)
            norm_kernel = self.cached_kernels[p] / ref_max
            self.kernel_plot.plot(self.cached_time_ms, norm_kernel, pen=pen, name=labels[p])

    def update_2d_map(self):
        if self.cached_freqs is None:
            return

        map_type = self.map_type_combo.currentData()
        harm_unit = self.harm_unit_combo.currentData()
        N_f = self.map_resolution_combo.currentData() or 300
        min_level = self.min_level_spin.value()
        max_level = self.max_level_spin.value()

        # Update GUI combobox enabling states based on type
        # Keep harm_unit_combo enabled always to allow switching dBFS/dBr for THD/Fundamental as well
        self.harm_unit_combo.setEnabled(True)

        use_noise, noise_db = self.get_current_noise_floor()
        noise_linear = 10 ** (noise_db / 20.0) if use_noise else 0.0
        noise_sq = noise_linear**2

        # 1. Grids Setup
        start_f = self.model_metadata.get("start_freq", 20.0)
        end_f = self.model_metadata.get("end_freq", 20000.0)
        freqs_grid = np.logspace(np.log10(start_f), np.log10(end_f), num=N_f)

        N_A = 80  # fixed amplitude steps for nice vertical gradient resolution
        amps_db = np.linspace(min_level, max_level, num=N_A)
        amps_linear = 10 ** (amps_db / 20.0)

        sample_rate = self.model_metadata.get("sample_rate", 48000)
        nyquist = sample_rate / 2.0

        # 2. Reconstruct complex frequency responses H_p
        H_dict = {}
        for p in range(1, 6):
            h_key = f"h{p}"
            if h_key not in self.cached_mags:
                continue
            mag_linear = 10 ** (self.cached_mags[h_key] / 20.0)
            phase_rad = np.radians(self.cached_phases[h_key])
            H_dict[p] = mag_linear * np.exp(1j * phase_rad)

        # 3. Vectorized Interpolation for each harmonic frequency
        H_interp = {n: {} for n in range(1, 6)}
        f_n_list = [n * freqs_grid for n in range(1, 6)]
        f_all = np.concatenate(f_n_list)
        out_of_bounds_all = f_all > nyquist
        zero_arr = np.zeros(N_f, dtype=np.complex128)
        for p in range(1, 6):
            if p in H_dict:
                Hp = H_dict[p]
                mags = np.abs(Hp)
                phases = np.unwrap(np.angle(Hp))
                nan_mask = np.isnan(mags) | np.isnan(phases)
                if np.all(nan_mask):
                    mag_val_all = np.zeros_like(f_all)
                    phase_val_all = np.zeros_like(f_all)
                elif np.any(nan_mask):
                    valid_freqs = self.cached_freqs[~nan_mask]
                    mag_val_all = np.interp(f_all, valid_freqs, mags[~nan_mask])
                    phase_val_all = np.interp(f_all, valid_freqs, phases[~nan_mask])
                else:
                    mag_val_all = np.interp(f_all, self.cached_freqs, mags)
                    phase_val_all = np.interp(f_all, self.cached_freqs, phases)
                val_all = mag_val_all * np.exp(1j * phase_val_all)
                val_all[out_of_bounds_all] = 0.0j
                val_all_reshaped = val_all.reshape(5, N_f)
                H_interp[1][p] = val_all_reshaped[0]
                H_interp[2][p] = val_all_reshaped[1]
                H_interp[3][p] = val_all_reshaped[2]
                H_interp[4][p] = val_all_reshaped[3]
                H_interp[5][p] = val_all_reshaped[4]
            else:
                for n in range(1, 6):
                    H_interp[n][p] = zero_arr

        # 4. Synthesize outputs
        A = amps_linear[:, np.newaxis]  # (N_A, 1)

        A2 = A * A
        A3 = A2 * A
        A4 = A2 * A2
        A5 = A4 * A

        Y = {}
        Y[1] = (1.0) * (A * H_interp[1][1] + (0.75 * A3) * H_interp[1][3] + (0.625 * A5) * H_interp[1][5])
        Y[2] = (-1j) * ((0.5 * A2) * H_interp[2][2] + (0.5 * A4) * H_interp[2][4])
        Y[3] = (-1.0) * ((0.25 * A3) * H_interp[3][3] + (0.3125 * A5) * H_interp[3][5])
        Y[4] = (+1j) * ((0.125 * A4) * H_interp[4][4])
        Y[5] = (1.0) * ((0.0625 * A5) * H_interp[5][5])

        # 5. Extract Map value
        mag_Y1 = np.abs(Y[1])
        mag_Y1_safe = np.where(mag_Y1 < 1e-12, 1e-12, mag_Y1)

        Z = None
        title = ""

        if map_type == "THD":
            mag_harmonics_sq = sum(np.abs(Y[n]) ** 2 for n in range(2, 6))

            if use_noise:
                numerator_sq = mag_harmonics_sq + noise_sq
                if harm_unit == "dbfs":
                    Z = 20 * np.log10(np.sqrt(numerator_sq) + 1e-12)
                    title = tr("Total Harmonic Distortion + Noise (THD+N)") + " [dBFS]"
                else:  # dbr
                    denom_sq = sum(np.abs(Y[n]) ** 2 for n in range(1, 6))
                    denom_sq += noise_sq
                    Z = 20 * np.log10(np.sqrt(numerator_sq) / np.sqrt(denom_sq) + 1e-12)
                    title = tr("Total Harmonic Distortion + Noise (THD+N)") + " [dBr]"
            else:
                if harm_unit == "dbfs":
                    Z = 20 * np.log10(np.sqrt(mag_harmonics_sq) + 1e-12)
                    title = tr("Total Harmonic Distortion (THD)") + " [dBFS]"
                else:  # dbr
                    thd_linear = np.sqrt(mag_harmonics_sq) / mag_Y1_safe
                    Z = 20 * np.log10(thd_linear + 1e-12)
                    title = tr("Total Harmonic Distortion (THD)") + " [dBr]"
        else:
            # High-order harmonic H2-H5
            order = int(map_type[1])
            mag_Yn = np.abs(Y[order])

            if use_noise:
                val_sq = mag_Yn**2 + noise_sq
                if harm_unit == "dbfs":
                    Z = 20 * np.log10(np.sqrt(val_sq) + 1e-12)
                    title = tr("{order}th Harmonic + Noise [dBFS]").format(order=order)
                else:  # dbr
                    denom_sq = sum(np.abs(Y[n]) ** 2 for n in range(1, 6))
                    denom_sq += noise_sq
                    Z = 20 * np.log10(np.sqrt(val_sq) / np.sqrt(denom_sq) + 1e-12)
                    title = tr("{order}th Harmonic + Noise [dBr]").format(order=order)
            else:
                if harm_unit == "dbfs":
                    Z = 20 * np.log10(mag_Yn + 1e-12)
                    if order == 2:
                        title = tr("2nd Harmonic Amplitude [dBFS]")
                    elif order == 3:
                        title = tr("3rd Harmonic Amplitude [dBFS]")
                    elif order == 4:
                        title = tr("4th Harmonic Amplitude [dBFS]")
                    elif order == 5:
                        title = tr("5th Harmonic Amplitude [dBFS]")
                    else:
                        title = tr("{order}th Harmonic Amplitude [dBFS]").format(order=order)
                else:  # dbr (relative to fundamental)
                    Z = 20 * np.log10(mag_Yn / mag_Y1_safe + 1e-12)
                    if order == 2:
                        title = tr("2nd Harmonic Level [dBr]")
                    elif order == 3:
                        title = tr("3rd Harmonic Level [dBr]")
                    elif order == 4:
                        title = tr("4th Harmonic Level [dBr]")
                    elif order == 5:
                        title = tr("5th Harmonic Level [dBr]")
                    else:
                        title = tr("{order}th Harmonic Level [dBr]").format(order=order)

        # Draw Image
        # autoLevels=False to preserve user interaction with the color bar handles
        self.image_item.setImage(Z.T, autoLevels=False)
        self.map_plot_item.setTitle(title)
        self.cached_Z = Z  # Cache for mouse hover query

        # Set mapping coordinates
        log_f_min = np.log10(start_f)
        log_f_max = np.log10(end_f)
        self.image_item.setRect(QRectF(log_f_min, min_level, log_f_max - log_f_min, max_level - min_level))

        if getattr(self, "first_map_draw", True):
            self.image_item.setLevels((-120.0, -40.0))
            self.colorbar.setLevels((-120.0, -40.0))
            self.curve_amp_plot.setYRange(-140, 0)
            self.first_map_draw = False

        # Clear existing contours & labels
        for iso in self.iso_curves:
            scene = iso.scene()
            if scene is not None:
                scene.removeItem(iso)
            iso.setParentItem(None)
        self.iso_curves.clear()
        for lbl in self.iso_labels:
            self.map_plot_item.removeItem(lbl)
        self.iso_labels.clear()

        # Draw contours if enabled
        if self.show_contours_chk.isChecked():
            levels_range = self.colorbar.levels()
            if levels_range is not None and len(levels_range) == 2 and levels_range[0] is not None:
                c_min, c_max = levels_range
            else:
                c_min, c_max = -120.0, -40.0
            levels = np.arange(np.ceil(c_min / 10) * 10, np.floor(c_max / 10) * 10 + 1, 10)

            for lvl in levels:
                iso = pg.IsocurveItem(data=Z.T, level=lvl)
                iso.setParentItem(self.image_item)
                iso.setPen(pg.mkPen(color=(255, 255, 255, 140), width=1.0))
                self.iso_curves.append(iso)

                # Right-edge labels: find all crossings of lvl in Z_right
                Z_right = Z[:, -1]
                crossings = []
                for i in range(len(Z_right) - 1):
                    z_low, z_high = Z_right[i], Z_right[i + 1]
                    y_low, y_high = amps_db[i], amps_db[i + 1]
                    if (z_low <= lvl < z_high) or (z_high <= lvl < z_low) or (i == len(Z_right) - 2 and z_high == lvl):
                        if z_high == z_low:
                            y_pos = y_low
                        else:
                            y_pos = y_low + (lvl - z_low) * (y_high - y_low) / (z_high - z_low)
                        crossings.append(y_pos)

                for y_pos in crossings:
                    lbl = pg.TextItem(f"{lvl:g} dB", color=(255, 255, 255, 200), anchor=(1.0, 0.5))
                    lbl.setPos(log_f_max - 0.02, y_pos)
                    self.map_plot_item.addItem(lbl, ignoreBounds=True)
                    self.iso_labels.append(lbl)

        # Update reference indicator lines on 2D Map
        self.ref_v_line.setPos(np.log10(self.ref_f0))
        self.ref_h_line.setPos(self.ref_amp)

        # Update 1D distortion curves to match the current map type and unit selection
        self.update_1d_distortion_curves()
        self.update_io_compression_plots()

    def update_color_map(self):
        cmap_name = self.color_map_combo.currentData()
        try:
            cmap = _get_safe_colormap(cmap_name)
            self.colorbar.setColorMap(cmap)
        except Exception as e:
            logger.error("Failed to set colormap %s: %s", cmap_name, e)

    def on_mouse_moved(self, pos):
        if self.cached_freqs is None:
            return

        if self.tabs.currentWidget() != self.tab_map:
            return

        vb = self.map_plot_item.vb
        if vb.sceneBoundingRect().contains(pos):
            mouse_point = vb.mapSceneToView(pos)
            log_f = mouse_point.x()
            amp_db = mouse_point.y()

            start_f = self.model_metadata.get("start_freq", 20.0)
            end_f = self.model_metadata.get("end_freq", 20000.0)
            log_f_min = np.log10(start_f)
            log_f_max = np.log10(end_f)
            min_level = self.min_level_spin.value()
            max_level = self.max_level_spin.value()

            if log_f_min <= log_f <= log_f_max and min_level <= amp_db <= max_level:
                f = 10**log_f

                # Show crosshairs
                self.v_line.setPos(log_f)
                self.h_line.setPos(amp_db)
                self.v_line.show()
                self.h_line.show()

                N_f = self.map_resolution_combo.currentData() or 300
                freqs_grid = np.logspace(np.log10(start_f), np.log10(end_f), num=N_f)
                N_A = 80
                amps_db = np.linspace(min_level, max_level, num=N_A)

                if getattr(self, "cached_Z", None) is not None:
                    f_idx = np.argmin(np.abs(freqs_grid - f))
                    a_idx = np.argmin(np.abs(amps_db - amp_db))
                    f_idx = max(0, min(N_f - 1, f_idx))
                    a_idx = max(0, min(N_A - 1, a_idx))
                    val = self.cached_Z[a_idx, f_idx]

                    map_type = self.map_type_combo.currentData()
                    harm_unit = self.harm_unit_combo.currentData()
                    use_noise = self.enable_noise_chk.isChecked()

                    unit_str = "dB"
                    if map_type == "THD":
                        name_str = "THD+N" if use_noise else "THD"
                    else:
                        order = int(map_type[1])
                        name_str = f"H{order}+N" if use_noise else f"H{order}"

                    if harm_unit == "dbfs":
                        unit_str = "dBFS"
                    else:
                        unit_str = "dBr"

                    f_str = f"{f / 1000.0:.2f} kHz" if f >= 1000.0 else f"{f:.1f} Hz"
                    text = f" {f_str}, {amp_db:.1f} dBFS  →  {name_str}: {val:.1f} {unit_str}"

                    self.hover_label_item.setText(text)

                    # Place label at the top-left corner of the viewbox
                    label_x = log_f_min + (log_f_max - log_f_min) * 0.01
                    label_y = max_level - (max_level - min_level) * 0.05
                    self.hover_label_item.setPos(label_x, label_y)
                    self.hover_label_item.show()
                return

        self.v_line.hide()
        self.h_line.hide()
        self.hover_label_item.hide()

    def on_map_clicked(self, event):
        if self.cached_freqs is None:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        vb = self.map_plot_item.vb
        scene_pos = event.scenePos()
        if vb.sceneBoundingRect().contains(scene_pos):
            mouse_point = vb.mapSceneToView(scene_pos)
            log_f = mouse_point.x()
            amp_db = mouse_point.y()

            start_f = self.model_metadata.get("start_freq", 20.0)
            end_f = self.model_metadata.get("end_freq", 20000.0)
            log_f_min = np.log10(start_f)
            log_f_max = np.log10(end_f)
            min_level = self.min_level_spin.value()
            max_level = self.max_level_spin.value()

            if log_f_min <= log_f <= log_f_max and min_level <= amp_db <= max_level:
                f = 10**log_f
                self.update_reference_params(f, amp_db)

    # --- Parameter Synchronization ---
    def update_reference_params(self, f0, amp_db):
        f0 = max(20.0, min(20000.0, f0))
        amp_db = max(-100.0, min(10.0, amp_db))

        self.ref_f0 = f0
        self.ref_amp = amp_db

        # Block signals to prevent feedback loop
        self.ref_f0_spin.blockSignals(True)
        self.ref_f0_slider.blockSignals(True)
        self.ref_amp_spin.blockSignals(True)
        self.ref_amp_slider.blockSignals(True)

        self.ref_f0_spin.setValue(f0)
        slider_f_val = int(1000.0 * np.log(f0 / 20.0) / np.log(1000.0))
        slider_f_val = max(0, min(1000, slider_f_val))
        self.ref_f0_slider.setValue(slider_f_val)

        self.ref_amp_spin.setValue(amp_db)
        self.ref_amp_slider.setValue(int(amp_db * 10))

        self.ref_f0_spin.blockSignals(False)
        self.ref_f0_slider.blockSignals(False)
        self.ref_amp_spin.blockSignals(False)
        self.ref_amp_slider.blockSignals(False)

        # Update 2D Map ref lines
        self.ref_v_line.setPos(np.log10(f0))
        self.ref_h_line.setPos(amp_db)

        # Update 1D plot indicator lines
        self.curve_freq_ref_line.setPos(np.log10(f0))
        self.curve_amp_ref_line.setPos(amp_db)

        # Redraw plots and simulator
        self.update_1d_distortion_curves()
        self.update_simulation()
        self.update_io_compression_plots()

    def _on_ref_freq_spin_changed(self, val):
        self.update_reference_params(val, self.ref_amp)

    def _on_ref_freq_slider_changed(self, val):
        freq = 20.0 * (1000.0 ** (val / 1000.0))
        self.update_reference_params(freq, self.ref_amp)

    def _on_ref_amp_spin_changed(self, val):
        self.update_reference_params(self.ref_f0, val)

    def _on_ref_amp_slider_changed(self, val):
        amp = val / 10.0
        self.update_reference_params(self.ref_f0, amp)

    def update_1d_distortion_curves(self):
        if self.cached_freqs is None or len(self.cached_freqs) == 0:
            return

        harm_unit = self.harm_unit_combo.currentData()

        # --- 1. Distortion vs Frequency (at self.ref_amp) ---
        self.curve_freq_plot.clear()
        self.curve_freq_plot.addItem(self.curve_freq_ref_line)

        # Reconstruct complex frequency responses H_p
        H_dict = {}
        for p in range(1, 6):
            h_key = f"h{p}"
            if h_key not in self.cached_mags:
                continue
            mag_linear = 10 ** (self.cached_mags[h_key] / 20.0)
            phase_rad = np.radians(self.cached_phases[h_key])
            H_dict[p] = mag_linear * np.exp(1j * phase_rad)

        sample_rate = self.model_metadata.get("sample_rate", 48000)
        nyquist = sample_rate / 2.0

        freqs_grid = self.cached_freqs
        N_f = len(freqs_grid)

        H_interp = {n: {} for n in range(1, 6)}
        f_n_list = [n * freqs_grid for n in range(1, 6)]
        f_all = np.concatenate(f_n_list)
        out_of_bounds_all = f_all > nyquist
        zero_arr = np.zeros(N_f, dtype=np.complex128)
        for p in range(1, 6):
            if p in H_dict:
                Hp = H_dict[p]
                mags = np.abs(Hp)
                phases = np.unwrap(np.angle(Hp))
                nan_mask = np.isnan(mags) | np.isnan(phases)
                if np.all(nan_mask):
                    mag_val_all = np.zeros_like(f_all)
                    phase_val_all = np.zeros_like(f_all)
                elif np.any(nan_mask):
                    valid_freqs = self.cached_freqs[~nan_mask]
                    mag_val_all = np.interp(f_all, valid_freqs, mags[~nan_mask])
                    phase_val_all = np.interp(f_all, valid_freqs, phases[~nan_mask])
                else:
                    mag_val_all = np.interp(f_all, self.cached_freqs, mags)
                    phase_val_all = np.interp(f_all, self.cached_freqs, phases)
                val_all = mag_val_all * np.exp(1j * phase_val_all)
                val_all[out_of_bounds_all] = 0.0j
                val_all_reshaped = val_all.reshape(5, N_f)
                H_interp[1][p] = val_all_reshaped[0]
                H_interp[2][p] = val_all_reshaped[1]
                H_interp[3][p] = val_all_reshaped[2]
                H_interp[4][p] = val_all_reshaped[3]
                H_interp[5][p] = val_all_reshaped[4]
            else:
                for n in range(1, 6):
                    H_interp[n][p] = zero_arr

        A_in = 10 ** (self.ref_amp / 20.0)

        A_in2 = A_in * A_in
        A_in3 = A_in2 * A_in
        A_in4 = A_in2 * A_in2
        A_in5 = A_in4 * A_in

        Y = {}
        Y[1] = (1.0) * (A_in * H_interp[1][1] + (0.75 * A_in3) * H_interp[1][3] + (0.625 * A_in5) * H_interp[1][5])
        Y[2] = (-1j) * ((0.5 * A_in2) * H_interp[2][2] + (0.5 * A_in4) * H_interp[2][4])
        Y[3] = (-1.0) * ((0.25 * A_in3) * H_interp[3][3] + (0.3125 * A_in5) * H_interp[3][5])
        Y[4] = (+1j) * ((0.125 * A_in4) * H_interp[4][4])
        Y[5] = (1.0) * ((0.0625 * A_in5) * H_interp[5][5])

        mag_Y1 = np.abs(Y[1])
        mag_Y1_safe = np.where(mag_Y1 < 1e-12, 1e-12, mag_Y1)

        colors = {
            "THD": (255, 255, 255),
            "h1": (75, 163, 227),
            "h2": (43, 140, 86),
            "h3": (230, 140, 20),
            "h4": (200, 50, 160),
            "h5": (217, 83, 79),
        }

        curves_data = {}

        use_noise, noise_db = self.get_current_noise_floor()
        noise_linear = 10 ** (noise_db / 20.0) if use_noise else 0.0
        noise_sq = noise_linear**2

        # THD
        mag_harmonics_sq = sum(np.abs(Y[n]) ** 2 for n in range(2, 6))

        if use_noise:
            numerator_sq = mag_harmonics_sq + noise_sq
            if harm_unit == "dbfs":
                curves_data["THD"] = 20 * np.log10(np.sqrt(numerator_sq) + 1e-12)
            else:  # dbr
                denom_sq = sum(np.abs(Y[n]) ** 2 for n in range(1, 6))
                denom_sq += noise_sq
                curves_data["THD"] = 20 * np.log10(np.sqrt(numerator_sq) / np.sqrt(denom_sq) + 1e-12)
        else:
            if harm_unit == "dbfs":
                curves_data["THD"] = 20 * np.log10(np.sqrt(mag_harmonics_sq) + 1e-12)
            else:  # dbr
                thd_linear = np.sqrt(mag_harmonics_sq) / mag_Y1_safe
                curves_data["THD"] = 20 * np.log10(thd_linear + 1e-12)

        # Harmonics
        for n in range(1, 6):
            h_key = f"h{n}"
            mag_Yn = np.abs(Y[n])
            if use_noise:
                val_sq = mag_Yn**2 + noise_sq
                if harm_unit == "dbfs":
                    curves_data[h_key] = 20 * np.log10(np.sqrt(val_sq) + 1e-12)
                else:  # dbr
                    denom_sq = sum(np.abs(Y[k]) ** 2 for k in range(1, 6))
                    denom_sq += noise_sq
                    curves_data[h_key] = 20 * np.log10(np.sqrt(val_sq) / np.sqrt(denom_sq) + 1e-12)
            else:
                if n == 1:
                    if harm_unit == "dbfs":
                        curves_data[h_key] = 20 * np.log10(mag_Yn + 1e-12)
                    else:  # dbr
                        curves_data[h_key] = 20 * np.log10(mag_Yn / mag_Y1_safe + 1e-12)
                else:
                    if harm_unit == "dbfs":
                        curves_data[h_key] = 20 * np.log10(mag_Yn + 1e-12)
                    else:
                        curves_data[h_key] = 20 * np.log10(mag_Yn / mag_Y1_safe + 1e-12)

        # Plot vs Frequency
        fundamental_name = tr("Fundamental (dBFS)") if harm_unit == "dbfs" else tr("Fundamental (dBr)")
        self.curve_freq_plot.plot(
            freqs_grid,
            curves_data["h1"],
            pen=pg.mkPen(color=colors["h1"], width=1.5, style=Qt.PenStyle.DashLine),
            name=fundamental_name,
        )
        unit_label = "dBFS" if harm_unit == "dbfs" else "dBr"

        thd_name = (
            tr("THD+N ({unit})").format(unit=unit_label) if use_noise else tr("THD ({unit})").format(unit=unit_label)
        )
        self.curve_freq_plot.plot(
            freqs_grid, curves_data["THD"], pen=pg.mkPen(color=colors["THD"], width=2.5), name=thd_name
        )
        for n in range(2, 6):
            h_key = f"h{n}"
            h_name = f"H{n} + Noise ({unit_label})" if use_noise else f"H{n} ({unit_label})"
            self.curve_freq_plot.plot(
                freqs_grid, curves_data[h_key], pen=pg.mkPen(color=colors[h_key], width=1.8), name=h_name
            )

        title_freq = (
            tr("THD+N & Distortion vs Frequency") if use_noise else tr("THD & Distortion vs Frequency")
        ) + f" (Amp = {self.ref_amp:.1f} dBFS)"
        self.curve_freq_plot.setTitle(title_freq)
        self.curve_freq_plot.setLabel("left", tr("Level") + f" [{unit_label}]")

        # --- 2. Distortion vs Amplitude (at self.ref_f0) ---
        self.curve_amp_plot.clear()
        self.curve_amp_plot.addItem(self.curve_amp_ref_line)

        min_level = self.min_level_spin.value()
        max_level = self.max_level_spin.value()
        amps_db = np.linspace(min_level, max_level, num=100)
        amps_linear = 10 ** (amps_db / 20.0)

        H_at_f0 = {n: {} for n in range(1, 6)}
        f_array = np.arange(1, 6) * self.ref_f0

        for p in range(1, 6):
            if p in H_dict:
                Hp = H_dict[p]
                mags = np.abs(Hp)
                phases = np.unwrap(np.angle(Hp))
                nan_mask = np.isnan(mags) | np.isnan(phases)
                if np.all(nan_mask):
                    mag_vals = np.zeros_like(f_array)
                    phase_vals = np.zeros_like(f_array)
                elif np.any(nan_mask):
                    valid_freqs = self.cached_freqs[~nan_mask]
                    mag_vals = np.interp(f_array, valid_freqs, mags[~nan_mask])
                    phase_vals = np.interp(f_array, valid_freqs, phases[~nan_mask])
                else:
                    mag_vals = np.interp(f_array, self.cached_freqs, mags)
                    phase_vals = np.interp(f_array, self.cached_freqs, phases)
                for n in range(1, 6):
                    if f_array[n - 1] > nyquist:
                        H_at_f0[n][p] = 0.0 + 0.0j
                    else:
                        H_at_f0[n][p] = mag_vals[n - 1] * np.exp(1j * phase_vals[n - 1])
            else:
                for n in range(1, 6):
                    H_at_f0[n][p] = 0.0 + 0.0j

        A = amps_linear[:, np.newaxis]

        A2 = A * A
        A3 = A2 * A
        A4 = A2 * A2
        A5 = A4 * A

        Y_amp = {}
        Y_amp[1] = (1.0) * (A * H_at_f0[1][1] + (0.75 * A3) * H_at_f0[1][3] + (0.625 * A5) * H_at_f0[1][5])
        Y_amp[2] = (-1j) * ((0.5 * A2) * H_at_f0[2][2] + (0.5 * A4) * H_at_f0[2][4])
        Y_amp[3] = (-1.0) * ((0.25 * A3) * H_at_f0[3][3] + (0.3125 * A5) * H_at_f0[3][5])
        Y_amp[4] = (+1j) * ((0.125 * A4) * H_at_f0[4][4])
        Y_amp[5] = (1.0) * ((0.0625 * A5) * H_at_f0[5][5])

        for k in Y_amp:
            Y_amp[k] = Y_amp[k].flatten()

        mag_Y1_amp = np.abs(Y_amp[1])
        mag_Y1_amp_safe = np.where(mag_Y1_amp < 1e-12, 1e-12, mag_Y1_amp)

        curves_data_amp = {}

        # THD
        mag_harmonics_sq_amp = sum(np.abs(Y_amp[n]) ** 2 for n in range(2, 6))

        if use_noise:
            numerator_sq = mag_harmonics_sq_amp + noise_sq
            if harm_unit == "dbfs":
                curves_data_amp["THD"] = 20 * np.log10(np.sqrt(numerator_sq) + 1e-12)
            else:  # dbr
                denom_sq = sum(np.abs(Y_amp[n]) ** 2 for n in range(1, 6))
                denom_sq += noise_sq
                curves_data_amp["THD"] = 20 * np.log10(np.sqrt(numerator_sq) / np.sqrt(denom_sq) + 1e-12)
        else:
            if harm_unit == "dbfs":
                curves_data_amp["THD"] = 20 * np.log10(np.sqrt(mag_harmonics_sq_amp) + 1e-12)
            else:  # dbr
                thd_linear_amp = np.sqrt(mag_harmonics_sq_amp) / mag_Y1_amp_safe
                curves_data_amp["THD"] = 20 * np.log10(thd_linear_amp + 1e-12)

        # Harmonics
        for n in range(1, 6):
            h_key = f"h{n}"
            mag_Yn = np.abs(Y_amp[n])
            if use_noise:
                val_sq = mag_Yn**2 + noise_sq
                if harm_unit == "dbfs":
                    curves_data_amp[h_key] = 20 * np.log10(np.sqrt(val_sq) + 1e-12)
                else:  # dbr
                    denom_sq = sum(np.abs(Y_amp[k]) ** 2 for k in range(1, 6))
                    denom_sq += noise_sq
                    curves_data_amp[h_key] = 20 * np.log10(np.sqrt(val_sq) / np.sqrt(denom_sq) + 1e-12)
            else:
                if n == 1:
                    if harm_unit == "dbfs":
                        curves_data_amp[h_key] = 20 * np.log10(mag_Yn + 1e-12)
                    else:  # dbr
                        curves_data_amp[h_key] = 20 * np.log10(mag_Yn / mag_Y1_amp_safe + 1e-12)
                else:
                    if harm_unit == "dbfs":
                        curves_data_amp[h_key] = 20 * np.log10(mag_Yn + 1e-12)
                    else:
                        curves_data_amp[h_key] = 20 * np.log10(mag_Yn / mag_Y1_amp_safe + 1e-12)

        # Plot vs Amplitude
        self.curve_amp_plot.plot(
            amps_db,
            curves_data_amp["h1"],
            pen=pg.mkPen(color=colors["h1"], width=1.5, style=Qt.PenStyle.DashLine),
            name=fundamental_name,
        )
        thd_name = (
            tr("THD+N ({unit})").format(unit=unit_label) if use_noise else tr("THD ({unit})").format(unit=unit_label)
        )
        self.curve_amp_plot.plot(
            amps_db, curves_data_amp["THD"], pen=pg.mkPen(color=colors["THD"], width=2.5), name=thd_name
        )
        for n in range(2, 6):
            h_key = f"h{n}"
            h_name = f"H{n} + Noise ({unit_label})" if use_noise else f"H{n} ({unit_label})"
            self.curve_amp_plot.plot(
                amps_db, curves_data_amp[h_key], pen=pg.mkPen(color=colors[h_key], width=1.8), name=h_name
            )

        f0_str = f"{self.ref_f0 / 1000.0:.2f} kHz" if self.ref_f0 >= 1000.0 else f"{self.ref_f0:.1f} Hz"
        title_amp = (
            tr("THD+N & Distortion vs Amplitude") if use_noise else tr("THD & Distortion vs Amplitude")
        ) + f" (Freq = {f0_str})"
        self.curve_amp_plot.setTitle(title_amp)
        self.curve_amp_plot.setLabel("left", tr("Level") + f" [{unit_label}]")

    def on_tab_changed(self, index):
        self.update_cache_button_state()

    def update_simulation(self):
        if self.cached_freqs is None or len(self.cached_freqs) == 0:
            return

        f0 = self.ref_f0
        amp_db = self.ref_amp

        H_dict = {}
        for p in range(1, 6):
            h_key = f"h{p}"
            if h_key not in self.cached_mags or h_key not in self.cached_phases:
                continue
            mag_linear = 10 ** (self.cached_mags[h_key] / 20.0)
            phase_rad = np.radians(self.cached_phases[h_key])
            H_dict[p] = mag_linear * np.exp(1j * phase_rad)

        H_interp = {n: {} for n in range(1, 6)}
        sample_rate = self.model_metadata.get("sample_rate", 48000)
        nyquist = sample_rate / 2.0
        f_array = np.arange(1, 6) * f0

        for p in range(1, 6):
            if p in H_dict:
                Hp = H_dict[p]
                mags = np.abs(Hp)
                phases = np.unwrap(np.angle(Hp))
                nan_mask = np.isnan(mags) | np.isnan(phases)
                if np.all(nan_mask):
                    mag_vals = np.zeros_like(f_array)
                    phase_vals = np.zeros_like(f_array)
                elif np.any(nan_mask):
                    valid_freqs = self.cached_freqs[~nan_mask]
                    mag_vals = np.interp(f_array, valid_freqs, mags[~nan_mask])
                    phase_vals = np.interp(f_array, valid_freqs, phases[~nan_mask])
                else:
                    mag_vals = np.interp(f_array, self.cached_freqs, mags)
                    phase_vals = np.interp(f_array, self.cached_freqs, phases)
                for n in range(1, 6):
                    if f_array[n - 1] > nyquist:
                        H_interp[n][p] = 0.0 + 0.0j
                    else:
                        H_interp[n][p] = mag_vals[n - 1] * np.exp(1j * phase_vals[n - 1])
            else:
                for n in range(1, 6):
                    H_interp[n][p] = 0.0 + 0.0j

        A_in = 10 ** (amp_db / 20.0)

        # Synthesize harmonic outputs
        A_in2 = A_in * A_in
        A_in3 = A_in2 * A_in
        A_in4 = A_in2 * A_in2
        A_in5 = A_in4 * A_in

        Y = {}
        Y[1] = (1.0) * (A_in * H_interp[1][1] + (0.75 * A_in3) * H_interp[1][3] + (0.625 * A_in5) * H_interp[1][5])
        Y[2] = (-1j) * ((0.5 * A_in2) * H_interp[2][2] + (0.5 * A_in4) * H_interp[2][4])
        Y[3] = (-1.0) * ((0.25 * A_in3) * H_interp[3][3] + (0.3125 * A_in5) * H_interp[3][5])
        Y[4] = (+1j) * ((0.125 * A_in4) * H_interp[4][4])
        Y[5] = (1.0) * ((0.0625 * A_in5) * H_interp[5][5])

        fundamental_phase_rad = np.angle(Y[1])

        self.sim_plot.clear()

        colors = {
            "h1": (75, 163, 227),
            "h2": (43, 140, 86),
            "h3": (230, 140, 20),
            "h4": (200, 50, 160),
            "h5": (217, 83, 79),
        }

        ref_phase_f0 = 0.0
        f_array = np.arange(1, 6) * f0
        if self.ref_loopback_phase_chk.isChecked() and "ref_phase" in self.cached_phases:
            # Unwrap ref_phase before interpolation to avoid linear interpolation errors at wrap boundaries
            ref_phase_data = self.cached_phases["ref_phase"]
            nan_mask = np.isnan(ref_phase_data)
            if np.all(nan_mask):
                ref_phase_f0 = 0.0
                ref_phase_fn_all = np.zeros_like(f_array)
            elif np.any(nan_mask):
                ref_phase_unwrapped = np.degrees(np.unwrap(np.radians(ref_phase_data[~nan_mask])))
                valid_freqs = self.cached_freqs[~nan_mask]
                ref_phase_f0 = np.interp(f0, valid_freqs, ref_phase_unwrapped)
                ref_phase_fn_all = np.interp(f_array, valid_freqs, ref_phase_unwrapped)
            else:
                ref_phase_unwrapped = np.degrees(np.unwrap(np.radians(ref_phase_data)))
                ref_phase_f0 = np.interp(f0, self.cached_freqs, ref_phase_unwrapped)
                ref_phase_fn_all = np.interp(f_array, self.cached_freqs, ref_phase_unwrapped)

        for n in range(1, 6):
            h_key = f"h{n}"
            f_n = f_array[n - 1]
            labels = self.sim_result_labels[h_key]

            if f_n > nyquist:
                labels["freq"].setText(f"{f_n / 1000.0:.2f} kHz (N/A)")
                labels["amp"].setText("N/A")
                labels["phase"].setText("N/A")
                continue

            y_val = Y[n]
            mag_val_db = 20 * np.log10(np.abs(y_val) + 1e-12)

            relative_phase_rad = np.angle(y_val) - n * fundamental_phase_rad
            phase_val_deg = np.degrees(relative_phase_rad)

            if self.ref_loopback_phase_chk.isChecked() and "ref_phase" in self.cached_phases:
                # Use the unwrapped reference phase array to prevent phase wrap interpolation issues
                ref_phase_fn = ref_phase_fn_all[n - 1]
                loopback_corr_deg = ref_phase_fn - n * ref_phase_f0
                phase_val_deg += loopback_corr_deg

            phase_val_deg = (phase_val_deg + 180) % 360 - 180

            labels["freq"].setText(f"{f_n:.1f} Hz")
            labels["amp"].setText(f"{mag_val_db:.1f} dB")
            labels["phase"].setText(f"{phase_val_deg:+.1f}°")

            # Draw vertical bar for spectrum
            pen_color = colors[h_key]
            curve = pg.PlotDataItem(
                x=[f_n, f_n],
                y=[-120.0, mag_val_db],
                pen=pg.mkPen(color=pen_color, width=2.5),
                symbol="o",
                symbolBrush=pg.mkBrush(color=pen_color),
                symbolSize=8,
            )
            self.sim_plot.addItem(curve)

        use_noise, noise_db = self.get_current_noise_floor()
        if use_noise:
            noise_line = pg.InfiniteLine(
                angle=0,
                movable=False,
                pen=pg.mkPen(color=(150, 150, 150, 150), width=1.2, style=Qt.PenStyle.DashLine),
                label=tr("Noise Floor"),
                labelOpts={"position": 0.9, "color": (150, 150, 150)},
            )
            noise_line.setPos(noise_db)
            self.sim_plot.addItem(noise_line)

    def update_io_compression_plots(self):
        if self.cached_freqs is None or len(self.cached_freqs) == 0:
            return

        f0 = self.ref_f0
        amp_db = self.ref_amp

        # Get interpolation data for kernels 1, 3, 5
        H_dict = {}
        for p in range(1, 6):
            h_key = f"h{p}"
            if h_key not in self.cached_mags or h_key not in self.cached_phases:
                continue
            mag_linear = 10 ** (self.cached_mags[h_key] / 20.0)
            phase_rad = np.radians(self.cached_phases[h_key])
            H_dict[p] = mag_linear * np.exp(1j * phase_rad)

        sample_rate = self.model_metadata.get("sample_rate", 48000)
        nyquist = sample_rate / 2.0

        H_at_f0 = {}
        for p in [1, 3, 5]:
            if f0 > nyquist or p not in H_dict:
                H_at_f0[p] = 0.0 + 0.0j
                continue
            Hp = H_dict[p]
            mags = np.abs(Hp)
            phases = np.unwrap(np.angle(Hp))
            nan_mask = np.isnan(mags) | np.isnan(phases)
            if np.all(nan_mask):
                mag_val = 0.0
                phase_val = 0.0
            elif np.any(nan_mask):
                valid_freqs = self.cached_freqs[~nan_mask]
                mag_val = np.interp(f0, valid_freqs, mags[~nan_mask])
                phase_val = np.interp(f0, valid_freqs, phases[~nan_mask])
            else:
                mag_val = np.interp(f0, self.cached_freqs, mags)
                phase_val = np.interp(f0, self.cached_freqs, phases)
            H_at_f0[p] = mag_val * np.exp(1j * phase_val)

        # Setup amplitudes grid
        min_level = self.min_level_spin.value()
        max_level = self.max_level_spin.value()
        amps_db = np.linspace(min_level, max_level, num=500)
        amps_linear = 10 ** (amps_db / 20.0)

        # Synthesize output component Y1 at f0
        # Y1 = A * H1 + 0.75 * A^3 * H3 + 0.625 * A^5 * H5
        Y1 = amps_linear * H_at_f0[1] + 0.75 * (amps_linear**3) * H_at_f0[3] + 0.625 * (amps_linear**5) * H_at_f0[5]

        out_db = 20 * np.log10(np.abs(Y1) + 1e-12)
        lin_gain_mag = np.abs(H_at_f0[1])
        if lin_gain_mag < 1e-12:
            lin_gain_mag = 1e-12
        ideal_out_db = amps_db + 20 * np.log10(lin_gain_mag)
        comp_error = out_db - ideal_out_db

        # Clear and replot
        self.io_plot.clear()
        self.io_plot.addItem(self.io_ref_v_line)
        self.io_plot.addItem(self.io_ref_h_line)
        self.io_plot.addItem(self.io_p1db_v_line)
        self.io_plot.addItem(self.io_p1db_h_line)
        self.io_plot.addItem(self.io_p1db_marker)

        self.comp_plot.clear()
        self.comp_plot.addItem(self.comp_linear_ref_line)
        self.comp_plot.addItem(self.comp_ref_v_line)
        self.comp_plot.addItem(self.comp_ref_h_line)
        self.comp_plot.addItem(self.comp_1db_limit_line)
        self.comp_plot.addItem(self.comp_p1db_v_line)
        self.comp_plot.addItem(self.comp_p1db_h_line)
        self.comp_plot.addItem(self.comp_p1db_marker)

        # Find reference output and error to position reference lines
        ref_amp_linear = 10 ** (amp_db / 20.0)
        ref_Y1 = (
            ref_amp_linear * H_at_f0[1]
            + 0.75 * (ref_amp_linear**3) * H_at_f0[3]
            + 0.625 * (ref_amp_linear**5) * H_at_f0[5]
        )
        ref_out = 20 * np.log10(np.abs(ref_Y1) + 1e-12)
        ref_ideal = amp_db + 20 * np.log10(lin_gain_mag)
        ref_error = ref_out - ref_ideal

        self.io_ref_v_line.setPos(amp_db)
        self.io_ref_h_line.setPos(ref_out)
        self.comp_ref_v_line.setPos(amp_db)
        self.comp_ref_h_line.setPos(ref_error)

        # Search for 1dB compression point (where comp_error <= -1.0)
        p1db_in = None
        p1db_out = None

        crossing_idx = np.where(comp_error <= -1.0)[0]
        if len(crossing_idx) > 0:
            idx = crossing_idx[0]
            if idx > 0:
                y0, y1 = comp_error[idx - 1], comp_error[idx]
                x0, x1 = amps_db[idx - 1], amps_db[idx]
                p1db_in = x0 + (-1.0 - y0) * (x1 - x0) / (y1 - y0)

                out0, out1 = out_db[idx - 1], out_db[idx]
                p1db_out = out0 + (p1db_in - x0) * (out1 - out0) / (x1 - x0)
            else:
                p1db_in = amps_db[0]
                p1db_out = out_db[0]

        # Draw 1dB Compression lines & markers if found
        if p1db_in is not None:
            self.io_p1db_v_line.setPos(p1db_in)
            self.io_p1db_h_line.setPos(p1db_out)
            self.io_p1db_v_line.show()
            self.io_p1db_h_line.show()
            self.io_p1db_marker.setData([p1db_in], [p1db_out])

            self.comp_p1db_v_line.setPos(p1db_in)
            self.comp_p1db_h_line.setPos(-1.0)
            self.comp_p1db_v_line.show()
            self.comp_p1db_h_line.show()
            self.comp_p1db_marker.setData([p1db_in], [-1.0])

            p1db_str = f"{p1db_in:.1f} dBFS"
        else:
            self.io_p1db_v_line.hide()
            self.io_p1db_h_line.hide()
            self.io_p1db_marker.setData([], [])

            self.comp_p1db_v_line.hide()
            self.comp_p1db_h_line.hide()
            self.comp_p1db_marker.setData([], [])

            p1db_str = tr("N/A")

        # Plot transfer curves
        pen_ideal = pg.mkPen(color=(120, 120, 120), width=1.5, style=Qt.PenStyle.DashLine)
        pen_actual = pg.mkPen(color=(43, 140, 86), width=2)
        pen_error = pg.mkPen(color=(217, 83, 79), width=2)

        self.io_plot.plot(amps_db, ideal_out_db, pen=pen_ideal, name=tr("Ideal Linear Output"))
        self.io_plot.plot(amps_db, out_db, pen=pen_actual, name=tr("Actual Output"))

        self.comp_plot.plot(amps_db, comp_error, pen=pen_error, name=tr("Compression Error"))

        # Setup titles with Freq and P1dB
        f_str = f"{f0 / 1000.0:.2f} kHz" if f0 >= 1000.0 else f"{f0:.1f} Hz"
        self.io_plot.setTitle(tr("Input-Output Curve (Freq = {freq})").format(freq=f_str) + f" [P1dB = {p1db_str}]")
        self.comp_plot.setTitle(tr("Gain Compression (Freq = {freq})").format(freq=f_str) + f" [P1dB = {p1db_str}]")

    def _on_wiener_sigma_slider_changed(self, val):
        self.wiener_sigma_spin.blockSignals(True)
        self.wiener_sigma_spin.setValue(val / 10.0)
        self.wiener_sigma_spin.blockSignals(False)
        self.update_wiener_plots()

    def _on_wiener_sigma_spin_changed(self, val):
        self.wiener_sigma_slider.blockSignals(True)
        self.wiener_sigma_slider.setValue(int(val * 10))
        self.wiener_sigma_slider.blockSignals(False)
        self.update_wiener_plots()

    def update_wiener_plots(self):
        if self.cached_freqs is None:
            return

        sigma_dbfs = self.wiener_sigma_spin.value()
        sigma_linear = 10 ** (sigma_dbfs / 20.0)
        sigma_sq = sigma_linear ** 2

        self.wie_mag_plot.clear()
        self.wie_phase_plot.clear()
        self.wie_energy_plot.clear()

        colors = [
            (75, 163, 227),  # w1
            (43, 140, 86),   # w2
            (230, 140, 20),  # w3
            (200, 50, 160),  # w4
            (217, 83, 79),   # w5
        ]

        labels_wie = {
            1: tr("Wiener Kernel w1"),
            2: tr("Wiener Kernel w2"),
            3: tr("Wiener Kernel w3"),
            4: tr("Wiener Kernel w4"),
            5: tr("Wiener Kernel w5"),
        }

        smooth_level = self.smooth_combo.currentData()

        # Reconstruct complex responses (H_complex)
        H_complex = {}
        for p in range(1, 6):
            h_key = f"h{p}"
            if h_key in self.cached_mags and h_key in self.cached_phases:
                mag_linear = 10 ** (self.cached_mags[h_key] / 20.0)
                phase_rad = np.radians(self.cached_phases[h_key])
                H_complex[p] = mag_linear * np.exp(1j * phase_rad)
            else:
                H_complex[p] = np.zeros_like(self.cached_freqs, dtype=np.complex128)

        # Wiener conversion (Hermite orthogonalization in frequency domain)
        W_complex = {}
        W_complex[1] = sigma_linear * (H_complex[1] + 3 * sigma_sq * H_complex[3] + 15 * (sigma_sq**2) * H_complex[5])
        W_complex[2] = (sigma_linear**2) * (H_complex[2] + 6 * sigma_sq * H_complex[4])
        W_complex[3] = (sigma_linear**3) * (H_complex[3] + 10 * sigma_sq * H_complex[5])
        W_complex[4] = (sigma_linear**4) * H_complex[4]
        W_complex[5] = (sigma_linear**5) * H_complex[5]

        # Draw Bode plots
        for p in range(1, 6):
            # Magnitude
            w_mag_db = 20 * np.log10(np.abs(W_complex[p]) + 1e-12)
            w_mag_smoothed = self.apply_smoothing(w_mag_db, smooth_level)
            pen_wie_mag = pg.mkPen(color=colors[p-1], width=1.8)
            self.wie_mag_plot.plot(self.cached_freqs, w_mag_smoothed, pen=pen_wie_mag, name=labels_wie[p])

            # Phase
            w_phase_deg = np.degrees(np.angle(W_complex[p]))
            w_phase_smoothed = self.apply_smoothing(w_phase_deg, smooth_level)
            pen_wie_phase = pg.mkPen(color=colors[p-1], width=1.5)
            self.wie_phase_plot.plot(self.cached_freqs, w_phase_smoothed, pen=pen_wie_phase, name=labels_wie[p])

        # Wiener conversion in time domain (for energy calculation)
        h_time = {}
        for p in range(1, 6):
            idx = p - 1
            if self.cached_kernels is not None and idx < len(self.cached_kernels):
                h_time[p] = self.cached_kernels[idx]
            else:
                h_time[p] = np.zeros_like(self.cached_kernels[0]) if self.cached_kernels is not None else np.array([])

        w_time = {}
        if len(h_time[1]) > 0:
            w_time[1] = sigma_linear * (h_time[1] + 3 * sigma_sq * h_time[3] + 15 * (sigma_sq**2) * h_time[5])
            w_time[2] = (sigma_linear**2) * (h_time[2] + 6 * sigma_sq * h_time[4])
            w_time[3] = (sigma_linear**3) * (h_time[3] + 10 * sigma_sq * h_time[5])
            w_time[4] = (sigma_linear**4) * h_time[4]
            w_time[5] = (sigma_linear**5) * h_time[5]
        else:
            for p in range(1, 6):
                w_time[p] = np.array([])

        # Calculate energy and fractions
        energies = []
        for p in range(1, 6):
            if len(w_time[p]) > 0:
                e = np.sum(w_time[p] ** 2)
            else:
                e = 0.0
            energies.append(e)
        energies = np.array(energies)
        total_energy = np.sum(energies)
        if total_energy > 1e-15:
            fractions_percent = (energies / total_energy) * 100.0
        else:
            fractions_percent = np.zeros(5)

        # Plot energy fractions as a bar chart
        x_ticks = [(1, "w1"), (2, "w2"), (3, "w3"), (4, "w4"), (5, "w5")]
        self.wie_energy_plot.getAxis("bottom").setTicks([x_ticks])

        x = np.arange(1, 6)
        for i in range(5):
            bar = pg.BarGraphItem(x=[x[i]], height=[fractions_percent[i]], width=0.6, brush=pg.mkBrush(colors[i]))
            self.wie_energy_plot.addItem(bar)
