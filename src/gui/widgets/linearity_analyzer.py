import argparse
import time
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.core.analysis import AudioCalc
from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule


class LinearitySweepWorker(QThread):
    progress = pyqtSignal(int)
    result_ready = pyqtSignal(dict)
    finished_sweep = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, module):
        super().__init__()
        self.module = module
        self.is_running = True

    def run(self):
        try:
            # 1. Generate Levels (High to Low usually, or Low to High)
            # AES17 usually implies stepping down from 0 dBFS.
            start_db = self.module.start_level
            end_db = self.module.end_level
            steps = self.module.steps

            # Linear space for dB means... linspace in dB domain
            levels_db = np.linspace(start_db, end_db, steps)

            freq = self.module.test_frequency
            sample_rate = self.module.audio_engine.sample_rate

            # Calibration state
            ref_gain_db = None 

            # Pre-calculate wait times
            # 100ms settling time is usually enough for electronics, plus buffer latency
            min_wait = 0.2 

            for i, level_db in enumerate(levels_db):
                if not self.is_running: break

                # Set Amplitude
                # Convert dBFS to Linear
                amp_linear = 10**(level_db/20)
                self.module.gen_amplitude = amp_linear

                # Wait for system to settle
                time.sleep(min_wait)

                # Capture
                # We need fresh data.
                # The module's input_data is a ring buffer updated by callback.
                # We need to ensure we capture *new* data generated at this amplitude.
                # Simplest way: Wait for buffer_duration * 2
                buffer_duration = self.module.buffer_size / sample_rate
                time.sleep(buffer_duration * 1.5)

                # Snapshot average of recent buffers? 
                # For now, just take the current buffer. 
                # Lock-in is robust.
                data = self.module.input_data.copy()

                # Process
                if self.module.input_channel == 0: # Left
                    sig = data[:, 0]
                else: # Right
                    if data.shape[1] > 1:
                        sig = data[:, 1]
                    else:
                        sig = data[:, 0]

                # Lock-in measurement
                mag, phase = AudioCalc.calculate_lockin_measurement(
                    sig, freq, sample_rate, phase_ref=0, window_name='blackmanharris'
                )

                meas_db = 20 * np.log10(mag + 1e-15)

                # Calculate Gain & Linearity Error
                # Gain = Measured - Input
                # Linearity Error = (Measured - Input) - Ref_Gain

                current_gain = meas_db - level_db

                if ref_gain_db is None:
                    # First point is reference (usually the highest level)
                    ref_gain_db = current_gain

                lin_error = current_gain - ref_gain_db

                result = {
                    'input_level': level_db,
                    'measured_level': meas_db,
                    'gain': current_gain,
                    'linearity_error': lin_error,
                    'phase': phase
                }

                self.result_ready.emit(result)
                self.progress.emit(int((i+1)/steps * 100))

            self.finished_sweep.emit()

        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        self.is_running = False


class LinearityAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.buffer_size = 65536 # Increased buffer size for safety
        self.input_data = np.zeros((self.buffer_size, 2))
        self.is_running = False

        # Generator
        self.test_frequency = 1000.0
        self.gen_amplitude = 0.0
        self.output_channel = 0 # 0=L, 1=R
        self.input_channel = 0

        # Sweep Params
        self.start_level = -5.0
        self.end_level = -120.0
        self.steps = 30

        self.callback_id = None
        self.worker = None

    @property
    def name(self) -> str:
        return "Linearity Analyzer"

    @property
    def description(self) -> str:
        return "Measure Linearity Error (Gain Accuracy vs Level)."

    def run(self, args: argparse.Namespace):
        print("CLI not implemented")

    def get_widget(self):
        return LinearityAnalyzerWidget(self)

    def start_analysis(self):
        if self.is_running:
            print(f"LinearityAnalyzer: Already running (callback_id={self.callback_id})")
            return
            
        # Safety: Ensure we don't leak a callback if state is inconsistent
        if self.callback_id is not None:
            print(f"LinearityAnalyzer: Found lingering callback {self.callback_id} during start. Unregistering.")
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None
            
        self.is_running = True

        # Reset generator phase
        self._phase = 0.0
        sample_rate = self.audio_engine.sample_rate

        def callback(indata, outdata, frames, time, status):
            # Input
            if indata.shape[1] >= 2:
                # Handle ring buffer safely
                new_data = indata[:, :2]
                new_frames = len(new_data)
                
                if new_frames >= self.buffer_size:
                    # If incoming data handles the entire buffer or more, just take the last part
                    self.input_data[:] = new_data[-self.buffer_size:]
                else:
                    # Otherwise roll and append
                    self.input_data[:] = np.roll(self.input_data, -new_frames, axis=0)
                    self.input_data[-new_frames:] = new_data
            else:
                # Mono input -> duplicate? 
                pass # TODO handle mono gracefully

            # Output
            t = (np.arange(frames) + self._phase) / sample_rate
            self._phase += frames

            sig = self.gen_amplitude * np.sin(2 * np.pi * self.test_frequency * t)

            outdata.fill(0)
            if self.output_channel == 0:
                outdata[:, 0] = sig
            elif self.output_channel == 1:
                if outdata.shape[1] > 1:
                    outdata[:, 1] = sig
            elif self.output_channel == 2: # Stereo
                outdata[:, 0] = sig
                if outdata.shape[1] > 1:
                    outdata[:, 1] = sig

        cid = self.audio_engine.register_callback(callback)
        self.callback_id = cid
        # print(f"LinearityAnalyzer: Started analysis. Registered callback {cid}")

    def stop_analysis(self):
        if self.callback_id:
            # print(f"LinearityAnalyzer: Stopping analysis. Unregistering callback {self.callback_id}")
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None
        else:
            # print("LinearityAnalyzer: Stop requested but no callback ID.")
            pass
            
        self.is_running = False

    def start_sweep(self):
        if self.worker and self.worker.isRunning(): return

        # Ensure audio is running
        self.start_analysis()

        self.worker = LinearitySweepWorker(self)
        return self.worker

    def stop_sweep(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        self.stop_analysis()


class LinearityAnalyzerWidget(QWidget):
    def __init__(self, module: LinearityAnalyzer):
        super().__init__()
        self.module = module
        self.init_ui()

        self.results_x = []
        self.results_error = []
        self.results_gain = []

    def init_ui(self):
        layout = QHBoxLayout()

        # --- Settings Panel ---
        settings_panel = QWidget()
        settings_panel.setFixedWidth(300)
        settings_layout = QVBoxLayout(settings_panel)

        # Controls
        group = QGroupBox(tr("Sweep Settings"))
        form = QFormLayout()

        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(20, 20000); self.freq_spin.setValue(1000); self.freq_spin.setSuffix(" Hz")
        self.freq_spin.valueChanged.connect(lambda v: setattr(self.module, 'test_frequency', v))
        form.addRow(tr("Frequency:"), self.freq_spin)

        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(-140, 0); self.start_spin.setValue(-5); self.start_spin.setSuffix(" dBFS")
        self.start_spin.valueChanged.connect(lambda v: setattr(self.module, 'start_level', v))
        form.addRow(tr("Start Level:"), self.start_spin)

        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(-140, 0); self.end_spin.setValue(-120); self.end_spin.setSuffix(" dBFS")
        self.end_spin.valueChanged.connect(lambda v: setattr(self.module, 'end_level', v))
        form.addRow(tr("End Level:"), self.end_spin)

        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(2, 200); self.steps_spin.setValue(30)
        self.steps_spin.valueChanged.connect(lambda v: setattr(self.module, 'steps', v))
        form.addRow(tr("Steps:"), self.steps_spin)

        group.setLayout(form)
        settings_layout.addWidget(group)

        # IO
        io_group = QGroupBox(tr("I/O Routing"))
        io_form = QFormLayout()

        self.out_combo = QComboBox()
        self.out_combo.addItems(["Left", "Right", "Stereo"])
        self.out_combo.currentIndexChanged.connect(lambda v: setattr(self.module, 'output_channel', v))
        io_form.addRow(tr("Output:"), self.out_combo)

        self.in_combo = QComboBox()
        self.in_combo.addItems(["Left", "Right"])
        self.in_combo.currentIndexChanged.connect(lambda v: setattr(self.module, 'input_channel', v))
        io_form.addRow(tr("Input:"), self.in_combo)

        io_group.setLayout(io_form)
        settings_layout.addWidget(io_group)

        # Statistics
        stats_group = QGroupBox(tr("Statistics"))
        stats_layout = QFormLayout()

        self.stat_ref_gain = QLabel("-- dB")
        self.stat_max_error = QLabel("-- dB")
        self.stat_linear_range = QLabel("-- dB")
        self.stat_slope = QLabel("--")

        stats_layout.addRow(tr("Ref Gain:"), self.stat_ref_gain)
        stats_layout.addRow(tr("Max Deviation:"), self.stat_max_error)
        stats_layout.addRow(tr("Linear Range (<0.5dB):"), self.stat_linear_range) # Using 0.5dB as standard
        stats_layout.addRow(tr("Slope:"), self.stat_slope)

        stats_group.setLayout(stats_layout)
        settings_layout.addWidget(stats_group)

        # Run
        self.start_btn = QPushButton(tr("Start Sweep"))
        self.start_btn.setCheckable(True)
        self.start_btn.clicked.connect(self.on_start_stop)
        self.start_btn.setFixedHeight(50)
        settings_layout.addWidget(self.start_btn)

        self.progress = QProgressBar()
        settings_layout.addWidget(self.progress)

        settings_layout.addStretch()
        layout.addWidget(settings_panel)

        # --- Plots ---
        plot_layout = QVBoxLayout()

        # Plot 1: Linearity Error
        self.error_plot = pg.PlotWidget(title=tr("Linearity Error (Deviation)"))
        self.error_plot.setLabel('left', tr('Error'), units='dB')
        self.error_plot.setLabel('bottom', tr('Input Level'), units='dBFS')
        self.error_plot.showGrid(x=True, y=True)
        self.error_plot.setYRange(-5, 5) # Typical range focus
        self.error_curve = self.error_plot.plot(pen=pg.mkPen('r', width=3), symbol='o')

        # Add tolerance lines? +/- 1dB maybe?

        plot_layout.addWidget(self.error_plot)

        # Plot 2: Absolute Gain
        self.gain_plot = pg.PlotWidget(title=tr("Absolute Gain"))
        self.gain_plot.setLabel('left', tr('Gain'), units='dB')
        self.gain_plot.setLabel('bottom', tr('Input Level'), units='dBFS')
        self.gain_plot.showGrid(x=True, y=True)
        self.gain_curve = self.gain_plot.plot(pen='y', symbol='+')

        plot_layout.addWidget(self.gain_plot)

        layout.addLayout(plot_layout)

        self.setLayout(layout)

    def on_start_stop(self):
        if self.start_btn.isChecked():
            self.results_x = []
            self.results_error = []
            self.results_gain = []
            self.error_curve.setData([], [])
            self.gain_curve.setData([], [])
            
            # Reset Stats
            self.stat_ref_gain.setText("-- dB")
            self.stat_max_error.setText("-- dB")
            self.stat_linear_range.setText("-- dB")
            self.stat_slope.setText("--")

            worker = self.module.start_sweep()
            worker.progress.connect(self.progress.setValue)
            worker.result_ready.connect(self.on_result)
            worker.finished_sweep.connect(self.on_finished)
            worker.error.connect(self.on_error)
            worker.start()

            self.start_btn.setText(tr("Stop"))
        else:
            self.module.stop_sweep()
            self.start_btn.setText(tr("Start Sweep"))

    def on_result(self, res):
        self.results_x.append(res['input_level'])
        self.results_error.append(res['linearity_error'])
        self.results_gain.append(res['gain'])

        # Sort data just in case? Usually sweep is monotonic, so appending is fine.
        # Plot
        self.error_curve.setData(self.results_x, self.results_error)
        self.gain_curve.setData(self.results_x, self.results_gain)

        self.update_stats()

    def update_stats(self):
        if not self.results_gain:
            return

        # 1. Ref Gain (Gain at highest input level)
        # Assuming sorted high-to-low or low-to-high, find max input
        max_input_idx = np.argmax(self.results_x)
        ref_gain = self.results_gain[max_input_idx]
        self.stat_ref_gain.setText(f"{ref_gain:.3f} dB")

        # 2. Max Deviation (Max absolute linearity error)
        errors = np.array(self.results_error)
        max_dev = np.max(np.abs(errors))
        self.stat_max_error.setText(f"{max_dev:.3f} dB")

        # 3. Slope (Linear Regression of Output vs Input)
        # Measured = Input + Gain
        # We want to check how close Measured is to Input + const.
        # Here we just calculate slope of Gain vs Input? No, Gain should be flat (slope 0).
        # OR Measured Level vs Input Level (slope 1).
        # Let's do Gain Slope (should be 0).
        if len(self.results_x) > 1:
            inputs = np.array(self.results_x)
            gains = np.array(self.results_gain)
            # Filter for valid range? E.g. exclude noise floor bottom
            # For now use all points
            slope, _ = np.polyfit(inputs, gains, 1)
            self.stat_slope.setText(f"{slope:.5f} dB/dB")
        
        # 4. Linear Range (Lowest level where error < 0.5 dB)
        # This assumes monotonic definition from Ref downwards.
        limit = 0.5
        # Find indices where error exceeds limit
        bad_indices = np.where(np.abs(errors) > limit)[0]
        
        if len(bad_indices) == 0:
            # All good, use min input
            min_input = np.min(self.results_x)
            self.stat_linear_range.setText(f"> {min_input:.1f} dBFS")
        else:
            # Find the highest input level that fails? 
            # Or usually we define it as "Dynamic Range" 
            # We want the point where it falls off.
            # Assuming sweeping downwards, we look for the first point (highest level) that fails?
            # No, usually low levels fail.
            # We want the lowest level that PASSES.
            
            # Sort by level descending
            sorted_indices = np.argsort(self.results_x)[::-1]
            inputs_sorted = np.array(self.results_x)[sorted_indices]
            errors_sorted = errors[sorted_indices]
            
            # Find first failure from top
            # Usually top is good.
            fail_idx = -1
            for i, err in enumerate(errors_sorted):
                if abs(err) > limit:
                    fail_idx = i
                    break
            
            if fail_idx == -1:
                 # Should have been caught by bad_indices check, but just in case
                 self.stat_linear_range.setText(f"> {np.min(inputs_sorted):.1f} dBFS")
            else:
                 # The last good point was i-1
                 if fail_idx > 0:
                     last_good = inputs_sorted[fail_idx-1]
                     self.stat_linear_range.setText(f"> {last_good:.1f} dBFS")
                 else:
                     self.stat_linear_range.setText("Poor Linearity")

    def on_finished(self):
        self.start_btn.setChecked(False)
        self.start_btn.setText(tr("Start Sweep"))
        self.module.stop_analysis()
        self.progress.setValue(100)

    def on_error(self, msg):
        self.on_finished()
        # TODO show message box
        print(f"Error: {msg}")
