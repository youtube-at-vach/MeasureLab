import logging
import time

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.analysis import get_cached_window
from src.core.audio_engine import AudioEngine
from src.core.fft_manager import fft_manager
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule


logger = logging.getLogger(__name__)


class ProcessorBenchmark(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine

    @property
    def name(self) -> str:
        return "Processor Benchmark"

    @property
    def description(self) -> str:
        return "Test FFT and UI rendering performance for Real-Time measurement."

    def get_widget(self):
        return ProcessorBenchmarkWidget(self)


class ProcessorBenchmarkWidget(QWidget):
    def __init__(self, module: ProcessorBenchmark):
        super().__init__()
        self.module = module
        self.fft_sizes = [2**i for i in range(8, 21)]  # 256 to 1048576
        self.sample_rates = [44100, 48000, 96000, 192000]
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Controls
        controls_group = QGroupBox(tr("Benchmark Controls"))
        controls_layout = QHBoxLayout(controls_group)

        self.start_btn = QPushButton(tr("Start Benchmark"))
        self.start_btn.setMinimumHeight(40)
        self.start_btn.setStyleSheet(
            "QPushButton { font-weight: bold; font-size: 14px; background-color: #ffcccc; color: black; }"
        )
        self.start_btn.clicked.connect(self.start_benchmark)
        controls_layout.addWidget(self.start_btn)

        controls_layout.addWidget(QLabel(tr("Safety Factor:")))
        self.safety_spin = QDoubleSpinBox()
        self.safety_spin.setRange(0.1, 1.0)
        self.safety_spin.setSingleStep(0.05)
        self.safety_spin.setValue(0.8)
        self.safety_spin.setToolTip(tr("Fraction of total buffer time allowed for processing."))
        self.safety_spin.valueChanged.connect(self.update_results_display)
        controls_layout.addWidget(self.safety_spin)

        controls_layout.addStretch()

        self.status_label = QLabel(tr("Status: Ready"))
        self.status_label.setStyleSheet("font-weight: bold; color: yellow;")
        controls_layout.addWidget(self.status_label)

        layout.addWidget(controls_group)

        # Main Content Layout (Table on left, Plot on right)
        content_layout = QHBoxLayout()

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([tr("FFT Size"), "44.1kHz", "48kHz", "96kHz", "192kHz", tr("Max FPS")])
        # Make the columns stretch evenly
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setRowCount(len(self.fft_sizes))

        # Populate table with default empty values
        for i, size in enumerate(self.fft_sizes):
            # Size
            idx_item = QTableWidgetItem(str(size))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 0, idx_item)
            # Empty cols
            for col in range(1, 6):
                item = QTableWidgetItem("--")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(i, col, item)

        content_layout.addWidget(self.table, stretch=2)

        # Plot setup (used for Render Benchmark)
        plot_group = QGroupBox(tr("Render Test View"))
        plot_layout = QVBoxLayout(plot_group)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel("left", tr("Magnitude"), units="dB")
        self.plot_widget.setLabel("bottom", tr("Frequency"), units="Hz")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.curve = self.plot_widget.plot(pen="c")
        plot_layout.addWidget(self.plot_widget)

        content_layout.addWidget(plot_group, stretch=1)
        layout.addLayout(content_layout, stretch=1)

        # Summary / Recommendations
        summary_group = QGroupBox(tr("Recommendations"))
        self.summary_layout = QVBoxLayout(summary_group)
        layout.addWidget(summary_group)

        self._benchmark_data = {}  # { size: {'dsp': t, 'render': t, 'total': t} }

    def set_output_destination(self, mode: str):
        pass  # Not used for this module

    def start_benchmark(self):
        self.start_btn.setEnabled(False)
        self.status_label.setText(tr("Status: Running..."))
        self.safety_spin.setEnabled(False)

        # Attempt to stop audio stream safely to prevent dropouts during heavy benchmark
        try:
            self.module.audio_engine.stop_stream()
        except Exception:
            pass

        self._benchmark_data.clear()

        # We process sizes sequentially via QTimer to avoid freezing the GUI completely
        self._current_benchmark_idx = 0
        QTimer.singleShot(100, self._benchmark_next)

    def _benchmark_next(self):
        if self._current_benchmark_idx >= len(self.fft_sizes):
            self.finalize_benchmark()
            return

        size = self.fft_sizes[self._current_benchmark_idx]
        self.status_label.setText(tr("Status: Testing N={0}...").format(size))
        QApplication.processEvents()

        # 1. Warm-up / Generate Data
        num_iters = 5 if size < 262144 else 2

        # 48kHz freq axis matching the N
        freqs = fft_manager.rfftfreq(size, 1.0 / 48000.0)

        dsp_times = []
        render_times = []

        window = get_cached_window("hann", size, fftbins=False)
        window = window[:, np.newaxis]  # Dual channel usually

        for _ in range(num_iters + 1):
            # Test DSP
            data = np.random.normal(size=(size, 2)).astype(np.float32)

            t0 = time.perf_counter()
            windowed = data * window
            # Compute for 2 channels
            fft_0 = np.abs(fft_manager.rfft(windowed[:, 0]))
            fft_1 = np.abs(fft_manager.rfft(windowed[:, 1]))
            # Simulated db calc over averaged magnitude
            fft_db = 20 * np.log10((fft_0 + fft_1) / 2 + 1e-12)
            t2 = time.perf_counter()

            # Test Render
            t3 = time.perf_counter()
            self.curve.setData(freqs, fft_db)
            QApplication.processEvents()
            t4 = time.perf_counter()

            # skip the first warmup run
            if _ > 0:
                dsp_times.append(t2 - t0)
                render_times.append(t4 - t3)

        t_dsp = np.mean(dsp_times)
        t_render = np.mean(render_times)
        t_total = t_dsp + t_render

        self._benchmark_data[size] = {"dsp": t_dsp, "render": t_render, "total": t_total}

        self._current_benchmark_idx += 1
        self.update_results_display()

        # Schedule next
        QTimer.singleShot(10, self._benchmark_next)

    def finalize_benchmark(self):
        self.status_label.setText(tr("Status: Completed"))
        self.start_btn.setEnabled(True)
        self.safety_spin.setEnabled(True)

        # Restart the stream so that other widgets can be used immediately
        try:
            self.module.audio_engine._restart_stream()
        except Exception:
            pass

    def update_results_display(self):
        safety = self.safety_spin.value()

        # Clear existing summary
        while self.summary_layout.count():
            item = self.summary_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        recommended_n = {sr: None for sr in self.sample_rates}

        for i, size in enumerate(self.fft_sizes):
            if size not in self._benchmark_data:
                continue

            scores = self._benchmark_data[size]
            t_total = scores["total"]

            fps = 1.0 / t_total if t_total > 0 else 0

            # FPS Column
            item = QTableWidgetItem(f"{fps:.1f}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 5, item)

            # We evaluate against an expected audio buffer cycle of 16384 samples
            # This makes 192kHz @ 262144 barely working (takes ~54ms, limit ~68ms)
            reference_block_samples = 16384
            for col, fs in enumerate(self.sample_rates, start=1):
                t_buf = reference_block_samples / fs
                limit = t_buf * safety
                limit_warn = t_buf * safety * 0.8  # 80% of limit

                if t_total <= limit_warn:
                    text = "OK"
                    # also recommend if it passing
                    recommended_n[fs] = size
                elif t_total <= limit:
                    text = "⚠"
                    # also recommend if it technically passes
                    recommended_n[fs] = size
                else:
                    text = "NG"

                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if text == "OK":
                    item.setForeground(Qt.GlobalColor.green)
                elif text == "⚠":
                    item.setForeground(Qt.GlobalColor.yellow)
                elif text == "NG":
                    item.setForeground(Qt.GlobalColor.red)

                self.table.setItem(i, col, item)

        # Update recommendations
        summary_text = ""
        for fs in self.sample_rates:
            n = recommended_n[fs]
            if n is not None:
                res = fs / n
                summary_text += tr("{0}kHz → Recommended: {1} (Max Realtime Resolution: ~{2:.2f}Hz)\n").format(
                    fs / 1000.0, n, res
                )
            else:
                summary_text += tr("{0}kHz → Recommended: None (Cannot process in real-time)\n").format(fs / 1000.0)

        lbl = QLabel(summary_text.strip())
        lbl.setStyleSheet("font-size: 14px;")
        self.summary_layout.addWidget(lbl)
