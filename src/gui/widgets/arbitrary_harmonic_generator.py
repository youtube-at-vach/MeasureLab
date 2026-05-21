import logging
import threading
import os
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QMessageBox,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule

logger = logging.getLogger(__name__)

MAX_HARMONICS = 50
OFF_DB = -120.0


class ArbitraryHarmonicGenerator(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.lock = threading.Lock()

        # Core Parameters
        self.gen_frequency = 1000.0
        self.gen_amplitude = 0.5  # Linear amplitude for fundamental (e.g. -6dBFS = 0.5)
        self.gen_phase = 0.0  # Degrees for fundamental
        self.output_channel = 2  # Stereo default
        self.output_enabled = True

        # Harmonics
        self.max_harmonic = 20
        self.harmonics_amps = np.zeros(MAX_HARMONICS)  # Linear amplitude (0.0 means OFF)
        self.harmonics_phases_deg = np.zeros(MAX_HARMONICS)

        # Compensation
        self.compensation_enabled = False
        self.compensation_coeffs = np.zeros(MAX_HARMONICS, dtype=complex)
        self.compensation_amps_db = np.full(MAX_HARMONICS, OFF_DB)  # Manual/Absolute amplitude (dB)
        self.compensation_phases_deg = np.zeros(MAX_HARMONICS)  # Manual/Absolute phase (degrees)
        self.adjusted_compensation_coeffs = np.zeros(MAX_HARMONICS, dtype=complex)
        self.compensation_file_path = ""
        self.compensation_freq = 0.0

        # DSP State
        self._phase_gen = 0.0
        self.callback_id = None

    @property
    def name(self) -> str:
        return "Arbitrary Harmonic Generator"

    @property
    def description(self) -> str:
        return "Generates pure sine waves or complex multi-tones with arbitrary harmonic amplitude and phase, incorporating system distortion compensation."

    def get_widget(self):
        return ArbitraryHarmonicWidget(self)

    def start_generation(self):
        if self.is_running:
            return
        self.is_running = True
        self._phase_gen = 0.0
        sample_rate = self.audio_engine.sample_rate

        def callback(indata, outdata, frames, time, status):
            if not self.is_running:
                outdata.fill(0)
                return

            outdata.fill(0)
            if self.output_enabled:
                with self.lock:
                    f0 = self.gen_frequency
                    a1 = self.gen_amplitude
                    p1_rad = np.radians(self.gen_phase)
                    max_h = self.max_harmonic

                    # Copy to avoid race conditions during array operations
                    h_amps = self.harmonics_amps.copy()
                    h_phases = self.harmonics_phases_deg.copy()
                    comp_enabled = self.compensation_enabled
                    comp_coeffs = self.adjusted_compensation_coeffs.copy()

                phase_step = 2.0 * np.pi * f0 / sample_rate
                wt = self._phase_gen + np.arange(frames) * phase_step
                self._phase_gen = float((self._phase_gen + frames * phase_step) % (2.0 * np.pi))

                # Fundamental wave
                sig = a1 * np.sin(wt + p1_rad)

                # Add User Harmonics
                for n in range(2, max_h + 1):
                    amp = h_amps[n - 1]
                    if amp > 0:
                        phase_rad = np.radians(h_phases[n - 1])
                        sig += amp * np.sin(n * wt + phase_rad)

                # Add Compensation Harmonics
                if comp_enabled:
                    for n in range(2, min(max_h + 1, len(comp_coeffs) + 1)):
                        c = comp_coeffs[n - 1]
                        if c.real != 0 or c.imag != 0:
                            sig += c.real * np.cos(n * wt) + c.imag * np.sin(n * wt)

                # Output routing
                if self.output_channel == 2:  # Stereo
                    if outdata.shape[1] >= 2:
                        outdata[:, 0] = sig
                        outdata[:, 1] = sig
                elif outdata.shape[1] > self.output_channel:
                    outdata[:, self.output_channel] = sig

        self.callback_id = self.audio_engine.register_callback(callback)

    def stop_generation(self):
        if self.is_running:
            self.is_running = False
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None

    def update_adjusted_compensation_coeffs(self):
        with self.lock:
            self.adjusted_compensation_coeffs.fill(0.0)
            for n in range(1, MAX_HARMONICS):  # 0 is fundamental, 1 is 2nd harmonic (index 1), etc.
                amp_db = self.compensation_amps_db[n]
                phase_deg = self.compensation_phases_deg[n]

                if amp_db <= OFF_DB:
                    continue

                amp = 10 ** (amp_db / 20.0)
                # Keep phase in [-180, 180]
                phase_deg = (phase_deg + 180) % 360 - 180
                phase_rad = np.radians(phase_deg)

                # Convert back to complex
                adj_real = amp * np.sin(phase_rad)
                adj_imag = amp * np.cos(phase_rad)

                self.adjusted_compensation_coeffs[n] = complex(adj_real, adj_imag)


class ArbitraryHarmonicWidget(QWidget):
    def __init__(self, module: ArbitraryHarmonicGenerator):
        super().__init__()
        self.module = module
        self._block_updates = False
        self.init_ui()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_plots)
        self.timer.setInterval(100)  # 10 Hz update for visual stability
        self.timer.start()

    def init_ui(self):
        layout = QHBoxLayout()

        # LEFT PANEL: Controls
        left_panel = QVBoxLayout()
        left_panel.setContentsMargins(0, 0, 0, 0)

        # Toggle play
        self.btn_toggle = QPushButton(tr("Start Generating"))
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.clicked.connect(self.on_toggle_generating)
        self.btn_toggle.setStyleSheet("QPushButton:checked { background-color: #ccffcc; }")
        left_panel.addWidget(self.btn_toggle)

        # QTabWidget to organize controls
        self.control_tabs = QTabWidget()

        # ----------------- Tab 1: Manual Mix -----------------
        manual_tab = QWidget()
        manual_layout = QVBoxLayout()
        manual_layout.setContentsMargins(0, 5, 0, 0)

        # Fundamental settings
        fund_group = QGroupBox(tr("Fundamental Tone"))
        fund_form = QFormLayout()

        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(20, 20000)
        self.freq_spin.setValue(self.module.gen_frequency)
        self.freq_spin.setSuffix(" Hz")
        self.freq_spin.valueChanged.connect(self.on_fundamental_changed)
        fund_form.addRow(tr("Frequency:"), self.freq_spin)

        self.amp_spin = QDoubleSpinBox()
        self.amp_spin.setRange(-120.0, 0.0)
        self.amp_spin.setValue(20 * np.log10(self.module.gen_amplitude + 1e-15))
        self.amp_spin.setSuffix(" dBFS")
        self.amp_spin.valueChanged.connect(self.on_fundamental_changed)
        fund_form.addRow(tr("Amplitude:"), self.amp_spin)

        self.phase_spin = QDoubleSpinBox()
        self.phase_spin.setRange(-180.0, 180.0)
        self.phase_spin.setValue(self.module.gen_phase)
        self.phase_spin.setSuffix(" deg")
        self.phase_spin.valueChanged.connect(self.on_fundamental_changed)
        fund_form.addRow(tr("Phase Offset:"), self.phase_spin)

        fund_group.setLayout(fund_form)
        manual_layout.addWidget(fund_group)

        # Harmonic Limits and table controls
        harm_group = QGroupBox(tr("Harmonic Tone Mix"))
        harm_layout = QVBoxLayout()

        limit_layout = QHBoxLayout()
        limit_layout.addWidget(QLabel(tr("Max Harmonics:")))
        self.spin_max_harm = QSpinBox()
        self.spin_max_harm.setRange(2, MAX_HARMONICS)
        self.spin_max_harm.setValue(self.module.max_harmonic)
        self.spin_max_harm.valueChanged.connect(self.on_max_harmonic_changed)
        limit_layout.addWidget(self.spin_max_harm)
        harm_layout.addLayout(limit_layout)

        # Harmonics editing Table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels([tr("Harmonic"), tr("Amp (dBFS)"), tr("Phase (deg)")])
        self.table.setColumnWidth(0, 80)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 100)
        self._rebuild_harmonics_table()
        harm_layout.addWidget(self.table)

        harm_group.setLayout(harm_layout)
        manual_layout.addWidget(harm_group)
        manual_tab.setLayout(manual_layout)
        self.control_tabs.addTab(manual_tab, tr("Manual Mix"))

        # ----------------- Tab 2: Compensation -----------------
        comp_tab = QWidget()
        comp_layout = QVBoxLayout()
        comp_layout.setContentsMargins(0, 5, 0, 0)

        # Compensation settings
        comp_group = QGroupBox(tr("System Distortion Compensation"))
        comp_settings_layout = QVBoxLayout()

        self.btn_load_comp = QPushButton(tr("Import Compensation Data..."))
        self.btn_load_comp.clicked.connect(self.on_load_compensation)
        comp_settings_layout.addWidget(self.btn_load_comp)

        self.chk_comp_enable = QCheckBox(tr("Apply Compensation"))
        self.chk_comp_enable.setChecked(self.module.compensation_enabled)
        self.chk_comp_enable.setEnabled(False)  # Disabled until data is loaded
        self.chk_comp_enable.toggled.connect(self.on_comp_toggled)
        comp_settings_layout.addWidget(self.chk_comp_enable)

        self.lbl_comp_status = QLabel(tr("No compensation data loaded"))
        self.lbl_comp_status.setWordWrap(True)
        self.lbl_comp_status.setStyleSheet("color: gray;")
        comp_settings_layout.addWidget(self.lbl_comp_status)

        comp_group.setLayout(comp_settings_layout)
        comp_layout.addWidget(comp_group)

        # Compensation Fine Tuning
        self.comp_adj_group = QGroupBox(tr("Compensation Fine Tuning"))
        comp_adj_layout = QVBoxLayout()

        self.comp_adj_table = QTableWidget()
        self.comp_adj_table.setColumnCount(3)
        self.comp_adj_table.setHorizontalHeaderLabels([tr("Harmonic"), tr("Amp (dBFS)"), tr("Phase (deg)")])
        self.comp_adj_table.setColumnWidth(0, 80)
        self.comp_adj_table.setColumnWidth(1, 100)
        self.comp_adj_table.setColumnWidth(2, 100)
        self.comp_adj_table.setEnabled(False)
        self._rebuild_comp_adj_table()
        comp_adj_layout.addWidget(self.comp_adj_table)

        self.comp_adj_group.setLayout(comp_adj_layout)
        comp_layout.addWidget(self.comp_adj_group)

        comp_tab.setLayout(comp_layout)
        self.control_tabs.addTab(comp_tab, tr("Compensation"))

        left_panel.addWidget(self.control_tabs)

        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        left_widget.setFixedWidth(340)
        layout.addWidget(left_widget)

        # RIGHT PANEL: Visualizer (WOW Design!)
        right_panel = QVBoxLayout()

        tabs = QTabWidget()

        # 1. Preview Waveform Plot
        self.plot_wave = pg.PlotWidget(title=tr("Synthesized Waveform Preview"))
        self.plot_wave.setLabel("bottom", tr("Time"), units="s")
        self.plot_wave.setLabel("left", tr("Amplitude"))
        self.plot_wave.showGrid(x=True, y=True)
        self.plot_wave.setYRange(-1.5, 1.5)
        self.curve_wave = self.plot_wave.plot(pen="y")
        tabs.addTab(self.plot_wave, tr("Waveform Preview"))

        # 2. Spectrum Plot
        self.plot_spec = pg.PlotWidget(title=tr("Synthesized Spectrum Preview"))
        self.plot_spec.setLabel("bottom", tr("Harmonic Order"))
        self.plot_spec.setLabel("left", tr("Amplitude"), units="dBFS")
        self.plot_spec.showGrid(y=True)
        self.plot_spec.setYRange(-120, 10)
        self.bar_spec = pg.BarGraphItem(
            x=np.arange(1, self.module.max_harmonic + 1),
            y0=-120,
            height=np.zeros(self.module.max_harmonic),
            width=0.6,
            brush="g",
        )
        self.plot_spec.addItem(self.bar_spec)
        tabs.addTab(self.plot_spec, tr("Spectrum Preview"))

        right_panel.addWidget(tabs)
        layout.addLayout(right_panel, 2)

        self.setLayout(layout)
        self.update_plots()

    def on_toggle_generating(self, checked):
        if checked:
            self.module.start_generation()
            self.btn_toggle.setText(tr("Stop Generating"))
        else:
            self.module.stop_generation()
            self.btn_toggle.setText(tr("Start Generating"))

    def on_fundamental_changed(self):
        with self.module.lock:
            self.module.gen_frequency = self.freq_spin.value()
            self.module.gen_amplitude = 10 ** (self.amp_spin.value() / 20.0)
            self.module.gen_phase = self.phase_spin.value()
        self.update_plots()

    def on_max_harmonic_changed(self, val):
        with self.module.lock:
            self.module.max_harmonic = val
        self._rebuild_harmonics_table()
        self._rebuild_comp_adj_table()

        # Update spec plot x-axis range
        self.plot_spec.removeItem(self.bar_spec)
        self.bar_spec = pg.BarGraphItem(x=np.arange(1, val + 1), y0=-120, height=np.zeros(val), width=0.6, brush="g")
        self.plot_spec.addItem(self.bar_spec)
        self.update_plots()

    def _rebuild_harmonics_table(self):
        self._block_updates = True
        n_rows = self.module.max_harmonic - 1
        self.table.setRowCount(n_rows)

        for i in range(n_rows):
            harmonic_idx = i + 1  # harmonic_idx = 1 maps to 2nd harmonic, etc.

            # Label
            item_lbl = QTableWidgetItem(tr("{}th").format(harmonic_idx + 1))
            item_lbl.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(i, 0, item_lbl)

            # Amp editor
            amp_spin = QDoubleSpinBox()
            amp_spin.setRange(-120.0, -10.0)
            amp_spin.setValue(OFF_DB)
            amp_spin.setSpecialValueText(tr("OFF"))
            amp_spin.setSuffix(" dBFS")

            # Map current value
            with self.module.lock:
                linear_amp = self.module.harmonics_amps[harmonic_idx]
            if linear_amp > 0:
                amp_spin.setValue(20 * np.log10(linear_amp))
            else:
                amp_spin.setValue(OFF_DB)

            amp_spin.valueChanged.connect(self._on_table_changed)
            self.table.setCellWidget(i, 1, amp_spin)

            # Phase editor
            phase_spin = QDoubleSpinBox()
            phase_spin.setRange(-180.0, 180.0)
            with self.module.lock:
                phase_spin.setValue(self.module.harmonics_phases_deg[harmonic_idx])
            phase_spin.setSuffix(" deg")
            phase_spin.valueChanged.connect(self._on_table_changed)
            self.table.setCellWidget(i, 2, phase_spin)

        self._block_updates = False

    def _rebuild_comp_adj_table(self):
        self._block_updates = True
        n_rows = self.module.max_harmonic - 1
        self.comp_adj_table.setRowCount(n_rows)

        for i in range(n_rows):
            harmonic_idx = i + 1  # 2nd harmonic is index 1 in coeffs

            # Label
            item_lbl = QTableWidgetItem(tr("{}th").format(harmonic_idx + 1))
            item_lbl.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.comp_adj_table.setItem(i, 0, item_lbl)

            # Amp Adjust editor
            amp_spin = QDoubleSpinBox()
            amp_spin.setRange(-120.0, 0.0)
            amp_spin.setSingleStep(0.1)
            with self.module.lock:
                amp_spin.setValue(self.module.compensation_amps_db[harmonic_idx])
            amp_spin.setSuffix(" dBFS")
            amp_spin.valueChanged.connect(self._on_comp_adj_changed)
            self.comp_adj_table.setCellWidget(i, 1, amp_spin)

            # Phase Adjust editor
            phase_spin = QDoubleSpinBox()
            phase_spin.setRange(-180.0, 180.0)
            phase_spin.setSingleStep(1.0)
            with self.module.lock:
                phase_spin.setValue(self.module.compensation_phases_deg[harmonic_idx])
            phase_spin.setSuffix(" deg")
            phase_spin.valueChanged.connect(self._on_comp_adj_changed)
            self.comp_adj_table.setCellWidget(i, 2, phase_spin)

        self._block_updates = False

    def _on_table_changed(self):
        if self._block_updates:
            return

        with self.module.lock:
            n_rows = self.table.rowCount()
            for i in range(n_rows):
                harmonic_idx = i + 1

                amp_spin = self.table.cellWidget(i, 1)
                phase_spin = self.table.cellWidget(i, 2)

                if amp_spin and phase_spin:
                    amp_db = amp_spin.value()
                    if amp_db <= OFF_DB:
                        self.module.harmonics_amps[harmonic_idx] = 0.0
                    else:
                        self.module.harmonics_amps[harmonic_idx] = 10 ** (amp_db / 20.0)
                    self.module.harmonics_phases_deg[harmonic_idx] = phase_spin.value()

        self.update_plots()

    def _on_comp_adj_changed(self):
        if self._block_updates:
            return

        with self.module.lock:
            n_rows = self.comp_adj_table.rowCount()
            for i in range(n_rows):
                harmonic_idx = i + 1

                amp_spin = self.comp_adj_table.cellWidget(i, 1)
                phase_spin = self.comp_adj_table.cellWidget(i, 2)

                if amp_spin and phase_spin:
                    self.module.compensation_amps_db[harmonic_idx] = amp_spin.value()
                    self.module.compensation_phases_deg[harmonic_idx] = phase_spin.value()

        self.module.update_adjusted_compensation_coeffs()
        self.update_plots()

    def on_load_compensation(self):
        filename, _ = QFileDialog.getOpenFileName(self, tr("Import Compensation Data"), "", "JSON Files (*.json)")
        if not filename:
            return

        import json

        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)

            if data.get("format") != "MeasureLab_Harmonic_Compensation":
                raise ValueError("Invalid file format")

            f_cal = data.get("fundamental_frequency", 1000.0)
            f_curr = self.freq_spin.value()

            # Warning if frequency mismatch by more than 1%
            if abs(f_cal - f_curr) / f_cal > 0.01:
                reply = QMessageBox.warning(
                    self,
                    tr("Frequency Mismatch"),
                    tr(
                        "The compensation data frequency ({0:.1f} Hz) does not match the current generator frequency ({1:.1f} Hz).\nApply anyway?"
                    ).format(f_cal, f_curr),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.No:
                    return

            coeffs_data = data.get("compensation_coeffs", [])
            coeffs = np.zeros(MAX_HARMONICS, dtype=complex)
            for item in coeffs_data:
                h = item.get("harmonic")
                if 2 <= h <= MAX_HARMONICS:
                    coeffs[h - 1] = complex(item.get("real", 0.0), item.get("imag", 0.0))

            with self.module.lock:
                self.module.compensation_coeffs = coeffs
                self.module.compensation_freq = f_cal
                self.module.compensation_file_path = filename
                self.module.compensation_enabled = True

                self.module.compensation_amps_db.fill(OFF_DB)
                self.module.compensation_phases_deg.fill(0.0)
                for n in range(1, MAX_HARMONICS):
                    c = coeffs[n]
                    if c.real != 0.0 or c.imag != 0.0:
                        amp = np.sqrt(c.real**2 + c.imag**2)
                        amp_db = 20 * np.log10(amp) if amp > 1e-15 else OFF_DB
                        phase_rad = np.arctan2(c.real, c.imag)
                        phase_deg = np.degrees(phase_rad)
                        self.module.compensation_amps_db[n] = amp_db
                        self.module.compensation_phases_deg[n] = phase_deg

            self.module.update_adjusted_compensation_coeffs()

            self.chk_comp_enable.setEnabled(True)
            self.chk_comp_enable.setChecked(True)
            self.comp_adj_table.setEnabled(True)
            self._rebuild_comp_adj_table()

            basename = os.path.basename(filename)
            self.lbl_comp_status.setText(tr("Loaded: {0} ({1:.1f} Hz)").format(basename, f_cal))
            self.lbl_comp_status.setStyleSheet("color: #55ff55; font-weight: bold;")
            logger.info(f"Loaded compensation data from {filename}")

        except Exception as e:
            logger.error(f"Failed to load compensation data: {e}")
            QMessageBox.critical(self, tr("Error"), tr("Failed to load compensation data: {0}").format(str(e)))
        self.update_plots()

    def on_comp_toggled(self, checked):
        with self.module.lock:
            self.module.compensation_enabled = checked
        if checked:
            self.lbl_comp_status.setStyleSheet("color: #55ff55; font-weight: bold;")
            self.comp_adj_table.setEnabled(True)
        else:
            self.lbl_comp_status.setStyleSheet("color: gray;")
            self.comp_adj_table.setEnabled(False)
        self.update_plots()

    def update_plots(self):
        # Retrieve all values safely
        with self.module.lock:
            f0 = self.module.gen_frequency
            a1 = self.module.gen_amplitude
            p1_rad = np.radians(self.module.gen_phase)
            max_h = self.module.max_harmonic

            h_amps = self.module.harmonics_amps.copy()
            h_phases = self.module.harmonics_phases_deg.copy()
            comp_enabled = self.module.compensation_enabled
            comp_coeffs = self.module.adjusted_compensation_coeffs.copy()

        # 1. Preview Waveform (3 cycles of fundamental)
        t_preview = np.linspace(0, 3.0 / f0 if f0 > 0 else 0.003, 1000)
        wt = 2 * np.pi * f0 * t_preview

        # Generate preview signal
        sig = a1 * np.sin(wt + p1_rad)

        # User harmonics
        for n in range(2, max_h + 1):
            amp = h_amps[n - 1]
            if amp > 0:
                phase_rad = np.radians(h_phases[n - 1])
                sig += amp * np.sin(n * wt + phase_rad)

        # Compensation harmonics
        if comp_enabled:
            for n in range(2, min(max_h + 1, len(comp_coeffs) + 1)):
                c = comp_coeffs[n - 1]
                if c.real != 0 or c.imag != 0:
                    sig += c.real * np.cos(n * wt) + c.imag * np.sin(n * wt)

        self.curve_wave.setData(t_preview, sig)

        # 2. Spectrum Preview
        heights = np.full(max_h, -120.0)

        # Fundamental
        heights[0] = 20 * np.log10(a1 + 1e-15)

        # User harmonics + Compensation
        for n in range(2, max_h + 1):
            real_comp = 0.0
            imag_comp = 0.0
            if comp_enabled and n <= len(comp_coeffs):
                c = comp_coeffs[n - 1]
                real_comp = c.real
                imag_comp = c.imag

            # User setting signal is A_n * sin(n*wt + phi_n)
            # = A_n * cos(phi_n) * sin(n*wt) + A_n * sin(phi_n) * cos(n*wt)
            # Add to compensation real / imag component:
            # Note:
            # c.real * cos(n*wt) + c.imag * sin(n*wt)
            # Therefore:
            # Total sin coefficient = A_n * cos(phase_user_rad) + imag_comp
            # Total cos coefficient = A_n * sin(phase_user_rad) + real_comp
            # The RMS / Amplitude of total is sqrt(sin_coeff^2 + cos_coeff^2)
            amp_user = h_amps[n - 1]
            phase_user_rad = np.radians(h_phases[n - 1])

            coeff_sin = amp_user * np.cos(phase_user_rad) + imag_comp
            coeff_cos = amp_user * np.sin(phase_user_rad) + real_comp

            total_amp = np.sqrt(coeff_sin**2 + coeff_cos**2)
            if total_amp > 1e-15:
                heights[n - 1] = 20 * np.log10(total_amp)

        self.bar_spec.setOpts(
            x=np.arange(1, max_h + 1), height=heights + 120.0
        )  # Scale offset for pyqtgraph height representation relative to y0=-120
