import logging
import time
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
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QMessageBox,
    QSlider,
    QGridLayout,
    QCheckBox,
    QFileDialog,
)

from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.gui.widgets.comparable_interface import ComparableWidgetInterface
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


class HammersteinAnalyzer(MeasurementModule):
    def __init__(self, audio_engine):
        self.audio_engine = audio_engine

    @property
    def name(self) -> str:
        return "Hammerstein Analyzer"

    @property
    def description(self) -> str:
        return "Visualizes Parallel Hammerstein kernels, generates 2D THD/harmonic maps, and simulates tone response."

    def get_widget(self):
        return HammersteinAnalyzerWidget(self)


class HammersteinAnalyzerWidget(QWidget, ComparableWidgetInterface):
    def __init__(self, module: HammersteinAnalyzer):
        QWidget.__init__(self)
        ComparableWidgetInterface.__init__(self)
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

        self.init_ui()

        # Check for initial live model
        self.update_cache_button_state()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # --- Left Panel: Sidebar (Fixed Width, Wrapped in Scroll Area) ---
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setFixedWidth(290)
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
        self.import_btn.setStyleSheet(
            "background-color: #4ba3e3; color: white; font-weight: bold; padding: 5px;"
        )
        self.import_btn.clicked.connect(self.import_model_file)
        source_form.addWidget(self.import_btn)

        self.load_cache_btn = QPushButton(tr("Load Live Cache"))
        self.load_cache_btn.setStyleSheet(
            "background-color: #2b8c56; color: white; font-weight: bold; padding: 5px;"
        )
        self.load_cache_btn.clicked.connect(self.load_live_cache)
        source_form.addWidget(self.load_cache_btn)

        # Info Labels
        self.lbl_status = QLabel(tr("No Model Loaded"))
        self.lbl_status.setStyleSheet("font-weight: bold; color: #d9534f;")
        self.lbl_sr = QLabel("SR: -- Hz")
        self.lbl_order = QLabel("Order (P): --")

        info_layout = QFormLayout()
        info_layout.setSpacing(4)
        info_layout.addRow(tr("Status:"), self.lbl_status)
        info_layout.addRow(tr("Rate:"), self.lbl_sr)
        info_layout.addRow(tr("Order:"), self.lbl_order)
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
        self.harm_unit_combo.addItem("dBFS (Absolute)", "dbfs")
        self.harm_unit_combo.addItem("dBc (Relative)", "dbc")
        self.harm_unit_combo.currentIndexChanged.connect(self.update_2d_map)
        map_form.addRow(tr("Harmonic Unit:"), self.harm_unit_combo)

        self.map_resolution_spin = QSpinBox()
        self.map_resolution_spin.setRange(50, 500)
        self.map_resolution_spin.setSingleStep(50)
        self.map_resolution_spin.setValue(200)
        self.map_resolution_spin.valueChanged.connect(self.update_2d_map)
        map_form.addRow(tr("Resolution:"), self.map_resolution_spin)

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
        self.color_map_combo.setCurrentIndex(self.color_map_combo.findData("turbo"))
        self.color_map_combo.blockSignals(False)
        map_form.addRow(tr("Color Map:"), self.color_map_combo)

        self.show_contours_chk = QCheckBox(tr("Show Contours"))
        self.show_contours_chk.setChecked(True)
        self.show_contours_chk.toggled.connect(self.update_2d_map)
        map_form.addRow(self.show_contours_chk)

        self.map_group.setEnabled(False)
        sidebar_layout.addWidget(self.map_group)



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
        self.tabs.addTab(self.tab_kernels, tr("Hammerstein Kernels"))

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

        # Floating coordinate overlay label
        self.hover_label_item = pg.TextItem(text="", color=(255, 255, 255), fill=(0, 0, 0, 180), anchor=(0, 0))
        self.hover_label_item.hide()
        self.map_plot_item.addItem(self.hover_label_item, ignoreBounds=True)

        # Connect mouse move
        self.map_plot_item.scene().sigMouseMoved.connect(self.on_mouse_moved)

        self.colorbar = pg.ColorBarItem(colorMap=_get_safe_colormap('turbo'))
        self.colorbar.setImageItem(self.image_item)
        self.map_graphics_widget.addItem(self.colorbar)

        map_layout.addWidget(self.map_graphics_widget)
        self.tabs.addTab(self.tab_map, tr("2D Distortion Map"))

        # Tab 4: Simulator
        self.tab_sim = QWidget()
        sim_layout = QHBoxLayout(self.tab_sim)
        sim_layout.setContentsMargins(2, 2, 2, 2)
        sim_layout.setSpacing(5)

        # Left Column for Simulator Settings & Results
        sim_left_panel = QWidget()
        sim_left_panel.setFixedWidth(280)
        sim_left_layout = QVBoxLayout(sim_left_panel)
        sim_left_layout.setContentsMargins(0, 0, 0, 0)
        sim_left_layout.setSpacing(8)

        # Tone Simulator Configuration Group (moved from sidebar)
        self.sim_group = QGroupBox(tr("Tone Simulator"))
        sim_form = QVBoxLayout(self.sim_group)
        sim_form.setSpacing(6)

        # Freq
        sim_form.addWidget(QLabel(tr("Input Frequency")))
        self.sim_f0_spin = QDoubleSpinBox()
        self.sim_f0_spin.setRange(20.0, 20000.0)
        self.sim_f0_spin.setSuffix(" Hz")
        self.sim_f0_spin.setValue(1000.0)
        self.sim_f0_spin.setSingleStep(100.0)
        self.sim_f0_spin.valueChanged.connect(self._on_sim_freq_spin_changed)
        sim_form.addWidget(self.sim_f0_spin)

        self.sim_f0_slider = QSlider(Qt.Orientation.Horizontal)
        self.sim_f0_slider.setRange(0, 1000)
        self.sim_f0_slider.setValue(500)
        self.sim_f0_slider.valueChanged.connect(self._on_sim_freq_slider_changed)
        sim_form.addWidget(self.sim_f0_slider)

        # Amplitude
        sim_form.addWidget(QLabel(tr("Input Amplitude")))
        self.sim_amp_spin = QDoubleSpinBox()
        self.sim_amp_spin.setRange(-100.0, 10.0)
        self.sim_amp_spin.setSuffix(" dBFS")
        self.sim_amp_spin.setValue(-6.0)
        self.sim_amp_spin.setSingleStep(1.0)
        self.sim_amp_spin.valueChanged.connect(self._on_sim_amp_spin_changed)
        sim_form.addWidget(self.sim_amp_spin)

        self.sim_amp_slider = QSlider(Qt.Orientation.Horizontal)
        self.sim_amp_slider.setRange(-1000, 100)
        self.sim_amp_slider.setValue(-60)
        self.sim_amp_slider.valueChanged.connect(self._on_sim_amp_slider_changed)
        sim_form.addWidget(self.sim_amp_slider)

        # Phase options
        self.sim_loopback_phase_chk = QCheckBox(tr("Include Audio Interface Phase"))
        self.sim_loopback_phase_chk.setChecked(True)
        self.sim_loopback_phase_chk.toggled.connect(self.update_simulation)
        sim_form.addWidget(self.sim_loopback_phase_chk)

        self.sim_group.setEnabled(False)
        sim_left_layout.addWidget(self.sim_group)

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

        self.tabs.addTab(self.tab_sim, tr("Harmonic Simulator"))

        main_layout.addWidget(self.tabs, stretch=1)

    def update_cache_button_state(self):
        available = has_active_model()
        self.load_cache_btn.setEnabled(available)
        if available:
            self.load_cache_btn.setToolTip(tr("Load model from the latest measurement."))
        else:
            self.load_cache_btn.setToolTip(tr("No active measurement found. Run sweep first."))

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
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            tr("Import Hammerstein Model"),
            "",
            "JSON Files (*.json)"
        )
        if not filepath:
            return

        try:
            data = load_hammerstein_model(filepath)
            self.set_model_data(data)
            import os
            filename = os.path.basename(filepath)
            self.lbl_status.setText(filename)
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

        # Enable Groups
        self.map_group.setEnabled(True)
        self.sim_group.setEnabled(True)

        # Redraw Bode, Kernels, Maps and Simulation
        self.update_bode_plots()
        self.update_kernel_plots()
        self.update_2d_map()
        self.update_simulation()

    def update_bode_plots(self):
        if self.cached_freqs is None:
            return

        self.mag_plot.clear()
        self.phase_plot.clear()

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
                mag_smoothed = self.cached_mags[key]
                phase_smoothed = self.cached_phases[key]

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
        N_f = self.map_resolution_spin.value()
        min_level = self.min_level_spin.value()
        max_level = self.max_level_spin.value()

        # Update GUI combobox enabling states based on type
        self.harm_unit_combo.setEnabled(map_type != "THD")


        # 1. Grids Setup
        start_f = self.model_metadata.get("start_freq", 20.0)
        end_f = self.model_metadata.get("end_freq", 20000.0)
        freqs_grid = np.logspace(np.log10(start_f), np.log10(end_f), num=N_f)

        N_A = 80 # fixed amplitude steps for nice vertical gradient resolution
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
        for n in range(1, 6):
            f_n = n * freqs_grid
            out_of_bounds = f_n > nyquist
            for p in range(1, 6):
                if p in H_dict:
                    real_val = np.interp(f_n, self.cached_freqs, np.real(H_dict[p]))
                    imag_val = np.interp(f_n, self.cached_freqs, np.imag(H_dict[p]))
                    val = real_val + 1j * imag_val
                    val[out_of_bounds] = 0.0j
                    H_interp[n][p] = val
                else:
                    H_interp[n][p] = np.zeros(N_f, dtype=np.complex128)

        # 4. Synthesize outputs
        A = amps_linear[:, np.newaxis] # (N_A, 1)

        Y = {}
        Y[1] = (1.0) * (A * H_interp[1][1] + (0.75 * (A**3)) * H_interp[1][3] + (0.625 * (A**5)) * H_interp[1][5])
        Y[2] = (-1j) * ((0.5 * (A**2)) * H_interp[2][2] + (0.5 * (A**4)) * H_interp[2][4])
        Y[3] = (-1.0) * ((0.25 * (A**3)) * H_interp[3][3] + (0.3125 * (A**5)) * H_interp[3][5])
        Y[4] = (+1j) * ((0.125 * (A**4)) * H_interp[4][4])
        Y[5] = (1.0) * ((0.0625 * (A**5)) * H_interp[5][5])

        # 5. Extract Map value
        mag_Y1 = np.abs(Y[1])
        mag_Y1_safe = np.where(mag_Y1 < 1e-12, 1e-12, mag_Y1)

        Z = None
        title = ""

        if map_type == "THD":
            mag_harmonics_sq = np.zeros_like(mag_Y1)
            for n in range(2, 6):
                mag_harmonics_sq += np.abs(Y[n])**2
            thd_linear = np.sqrt(mag_harmonics_sq) / mag_Y1_safe

            Z = 20 * np.log10(thd_linear + 1e-12)
            title = tr("Total Harmonic Distortion (THD)") + " [dB]"
        else:
            # High-order harmonic H2-H5
            order = int(map_type[1])
            mag_Yn = np.abs(Y[order])

            if harm_unit == "dbfs":
                Z = 20 * np.log10(mag_Yn + 1e-12)
                title = f"{order}rd Harmonic Amplitude [dBFS]" if order == 3 else f"{order}th Harmonic Amplitude [dBFS]"
                if order == 2:
                    title = "2nd Harmonic Amplitude [dBFS]"
            else: # dbc (relative to fundamental)
                Z = 20 * np.log10(mag_Yn / mag_Y1_safe + 1e-12)
                title = f"{order}rd Harmonic Level [dBc]" if order == 3 else f"{order}th Harmonic Level [dBc]"
                if order == 2:
                    title = "2nd Harmonic Level [dBc]"

        # Draw Image
        # autoLevels=False to preserve user interaction with the color bar handles
        self.image_item.setImage(Z.T, autoLevels=False)
        self.map_plot_item.setTitle(title)
        self.cached_Z = Z  # Cache for mouse hover query

        # Set mapping coordinates
        log_f_min = np.log10(start_f)
        log_f_max = np.log10(end_f)
        self.image_item.setRect(QRectF(
            log_f_min,
            min_level,
            log_f_max - log_f_min,
            max_level - min_level
        ))

        if getattr(self, "first_map_draw", True):
            self.image_item.setLevels((-120.0, -40.0))
            self.colorbar.setLevels((-120.0, -40.0))
            self.first_map_draw = False

        # Clear existing contours & labels
        for iso in self.iso_curves:
            self.map_plot_item.removeItem(iso)
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

                # Right-edge labels: Z has shape (N_A, N_f), Z[:, -1] has shape (N_A) corresponding to amps_db
                Z_right = Z[:, -1]
                if np.min(Z_right) <= lvl <= np.max(Z_right):
                    sort_idx = np.argsort(Z_right)
                    y_pos = np.interp(lvl, Z_right[sort_idx], amps_db[sort_idx])

                    lbl = pg.TextItem(f"{lvl:g} dB", color=(255, 255, 255, 200), anchor=(1.0, 0.5))
                    lbl.setPos(log_f_max - 0.02, y_pos)
                    self.map_plot_item.addItem(lbl, ignoreBounds=True)
                    self.iso_labels.append(lbl)

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
                f = 10 ** log_f

                # Show crosshairs
                self.v_line.setPos(log_f)
                self.h_line.setPos(amp_db)
                self.v_line.show()
                self.h_line.show()

                N_f = self.map_resolution_spin.value()
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

                    unit_str = "dB"
                    if map_type == "THD":
                        name_str = "THD"
                    else:
                        order = int(map_type[1])
                        name_str = f"H{order}"
                        if harm_unit == "dbfs":
                            unit_str = "dBFS"
                        else:
                            unit_str = "dBc"

                    f_str = f"{f/1000.0:.2f} kHz" if f >= 1000.0 else f"{f:.1f} Hz"
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

    # --- Simulator Methods ---
    def on_tab_changed(self, index):
        # Update cache button status on tab switches
        self.update_cache_button_state()

    def _on_sim_freq_spin_changed(self, val):
        self._update_slider_from_freq(val)
        self.update_simulation()

    def _on_sim_freq_slider_changed(self, val):
        freq = 20.0 * (1000.0 ** (val / 1000.0))
        self.sim_f0_spin.blockSignals(True)
        self.sim_f0_spin.setValue(freq)
        self.sim_f0_spin.blockSignals(False)
        self.update_simulation()

    def _update_slider_from_freq(self, freq):
        val = int(1000.0 * np.log(freq / 20.0) / np.log(1000.0))
        val = max(0, min(1000, val))
        self.sim_f0_slider.blockSignals(True)
        self.sim_f0_slider.setValue(val)
        self.sim_f0_slider.blockSignals(False)

    def _on_sim_amp_spin_changed(self, val):
        self.sim_amp_slider.blockSignals(True)
        self.sim_amp_slider.setValue(int(val * 10))
        self.sim_amp_slider.blockSignals(False)
        self.update_simulation()

    def _on_sim_amp_slider_changed(self, val):
        amp = val / 10.0
        self.sim_amp_spin.blockSignals(True)
        self.sim_amp_spin.setValue(amp)
        self.sim_amp_spin.blockSignals(False)
        self.update_simulation()

    def update_simulation(self):
        if self.cached_freqs is None or len(self.cached_freqs) == 0:
            return

        f0 = self.sim_f0_spin.value()
        amp_db = self.sim_amp_spin.value()

        H_dict = {}
        for p in range(1, 6):
            h_key = f"h{p}"
            if h_key not in self.cached_mags or h_key not in self.cached_phases:
                continue
            mag_linear = 10 ** (self.cached_mags[h_key] / 20.0)
            phase_rad = np.radians(self.cached_phases[h_key])
            H_dict[p] = mag_linear * np.exp(1j * phase_rad)

        H_interp = {}
        sample_rate = self.model_metadata.get("sample_rate", 48000)
        nyquist = sample_rate / 2.0

        for n in range(1, 6):
            f_n = n * f0
            H_interp[n] = {}
            if f_n > nyquist:
                for p in range(1, 6):
                    H_interp[n][p] = 0.0 + 0.0j
                continue

            for p in range(1, 6):
                if p not in H_dict:
                    H_interp[n][p] = 0.0 + 0.0j
                    continue
                real_val = np.interp(f_n, self.cached_freqs, np.real(H_dict[p]))
                imag_val = np.interp(f_n, self.cached_freqs, np.imag(H_dict[p]))
                H_interp[n][p] = real_val + 1j * imag_val

        A_in = 10 ** (amp_db / 20.0)

        # Synthesize harmonic outputs
        Y = {}
        Y[1] = (1.0) * (
            A_in * H_interp[1][1] + (0.75 * (A_in**3)) * H_interp[1][3] + (0.625 * (A_in**5)) * H_interp[1][5]
        )
        Y[2] = (-1j) * ((0.5 * (A_in**2)) * H_interp[2][2] + (0.5 * (A_in**4)) * H_interp[2][4])
        Y[3] = (-1.0) * ((0.25 * (A_in**3)) * H_interp[3][3] + (0.3125 * (A_in**5)) * H_interp[3][5])
        Y[4] = (+1j) * ((0.125 * (A_in**4)) * H_interp[4][4])
        Y[5] = (1.0) * ((0.0625 * (A_in**5)) * H_interp[5][5])

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
        if self.sim_loopback_phase_chk.isChecked() and "ref_phase" in self.cached_phases:
            ref_phase_f0 = np.interp(f0, self.cached_freqs, self.cached_phases["ref_phase"])

        for n in range(1, 6):
            h_key = f"h{n}"
            f_n = n * f0
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

            if self.sim_loopback_phase_chk.isChecked() and "ref_phase" in self.cached_phases:
                ref_phase_fn = np.interp(f_n, self.cached_freqs, self.cached_phases["ref_phase"])
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

    # --- ComparableWidgetInterface ---
    def get_comparison_data(self):
        if self.cached_freqs is None or "h1" not in self.cached_mags:
            return None

        return {
            "x": self.cached_freqs,
            "y": self.cached_mags["h1"],
            "title": f"PHM Fundamental (h1) Sweep - {time.strftime('%H:%M:%S')}",
            "x_label": "Frequency",
            "x_units": "Hz",
            "y_label": "Gain",
            "y_units": "dB",
        }
