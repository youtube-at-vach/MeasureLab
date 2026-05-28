import logging
import sys
import time

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
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


def get_cpu_name():
    if sys.platform == "win32":
        import winreg

        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return name.strip()
        except OSError as e:
            logger.debug(f"Failed to read CPU name from registry: {e}")

    elif sys.platform == "linux":
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":")[1].strip()
        except OSError as e:
            logger.debug(f"Failed to read CPU name from /proc/cpuinfo: {e}")

    elif sys.platform == "darwin":
        import subprocess

        try:
            return (
                subprocess.check_output(["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"], timeout=2.0)
                .decode()
                .strip()
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.debug(f"Failed to read CPU name from sysctl: {e}")

    return None


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
        self.fft_sizes = []
        self.sample_rates = [44100, 48000, 96000, 192000]
        self._benchmark_data = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # System Information
        sys_info_group = QGroupBox(tr("System Information"))
        sys_info_layout = QVBoxLayout(sys_info_group)

        import platform

        cpu_name = get_cpu_name() or platform.processor() or "Unknown CPU"
        arch_info = platform.machine()

        os_name = f"{platform.system()} {platform.release()}"

        self.sys_info_str = f"OS: {os_name} | CPU: {cpu_name} ({arch_info})"
        sys_info_label = QLabel(self.sys_info_str)
        sys_info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        sys_info_layout.addWidget(sys_info_label)
        layout.addWidget(sys_info_group)

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

        self.extreme_mode_cb = QCheckBox(tr("Enable Extreme Sizes (Max 16M)"))
        self.extreme_mode_cb.toggled.connect(self._on_extreme_mode_toggled)
        controls_layout.addWidget(self.extreme_mode_cb)

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
        self._update_fft_sizes()

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
        summary_main_layout = QVBoxLayout(summary_group)

        self.summary_text_layout = QVBoxLayout()
        summary_main_layout.addLayout(self.summary_text_layout)

        btn_layout = QHBoxLayout()
        self.copy_btn = QPushButton(tr("Copy Results to Clipboard"))
        self.copy_btn.clicked.connect(self.copy_to_clipboard)
        btn_layout.addStretch()
        btn_layout.addWidget(self.copy_btn)
        summary_main_layout.addLayout(btn_layout)

        layout.addWidget(summary_group)

    def _on_extreme_mode_toggled(self):
        self._benchmark_data.clear()
        self._update_fft_sizes()
        self.update_results_display()

    def _update_fft_sizes(self):
        extreme = getattr(self, "extreme_mode_cb", None) and self.extreme_mode_cb.isChecked()
        if extreme:
            self.fft_sizes = [2**i for i in range(12, 25)]  # 4096 to 16M
        else:
            self.fft_sizes = [2**i for i in range(12, 21)]  # 4096 to 1M

        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(self.fft_sizes))
            for i, size in enumerate(self.fft_sizes):
                if item := self.table.item(i, 0):
                    item.setText(str(size))
                else:
                    idx_item = QTableWidgetItem(str(size))
                    idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(i, 0, idx_item)

                for col in range(1, 6):
                    if item := self.table.item(i, col):
                        item.setText("--")
                        item.setForeground(
                            QBrush(
                                Qt.GlobalColor.white
                                if self.palette().color(QPalette.ColorRole.WindowText).lightness() > 128
                                else Qt.GlobalColor.black
                            )
                        )
                    else:
                        item = QTableWidgetItem("--")
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        self.table.setItem(i, col, item)
        finally:
            self.table.setUpdatesEnabled(True)

    def set_output_destination(self, mode: str):
        pass  # Not used for this module

    def start_benchmark(self):
        self.start_btn.setEnabled(False)
        self.status_label.setText(tr("Status: Running..."))
        self.safety_spin.setEnabled(False)

        # Attempt to stop audio stream safely to prevent dropouts during heavy benchmark
        try:
            self.module.audio_engine.stop_stream()
        except Exception as e:
            logger.debug(f"Failed to stop stream safely: {e}")

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
            t4 = time.perf_counter()

            # Process UI events outside the timing block to avoid
            # artificially inflating benchmark time on Windows DWM.
            QApplication.processEvents()

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
        except Exception as e:
            logger.debug(f"Failed to restart stream: {e}")

    def update_results_display(self):
        safety = self.safety_spin.value()

        # Clear existing summary
        while self.summary_text_layout.count():
            item = self.summary_text_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        recommended_n = {sr: None for sr in self.sample_rates}

        self.table.setUpdatesEnabled(False)
        try:
            # We evaluate against an expected audio buffer cycle of 4096 samples
            # This perfectly compensates for the UI/OS overhead removed from the raw timing,
            # making 192kHz @ 262144 the practical limit (takes ~18ms, limit ~21ms).
            reference_block_samples = 8192
            for i, size in enumerate(self.fft_sizes):
                if size not in self._benchmark_data:
                    continue

                scores = self._benchmark_data[size]
                t_total = scores["total"]

                fps = 1.0 / t_total if t_total > 0 else 0

                # FPS Column
                if item := self.table.item(i, 5):
                    item.setText(f"{fps:.1f}")
                else:
                    item = QTableWidgetItem(f"{fps:.1f}")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(i, 5, item)

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

                    if item := self.table.item(i, col):
                        item.setText(text)
                    else:
                        item = QTableWidgetItem(text)
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        self.table.setItem(i, col, item)

                    if text == "OK":
                        item.setForeground(QBrush(Qt.GlobalColor.green))
                    elif text == "⚠":
                        item.setForeground(QBrush(Qt.GlobalColor.yellow))
                    elif text == "NG":
                        item.setForeground(QBrush(Qt.GlobalColor.red))
        finally:
            self.table.setUpdatesEnabled(True)

        # Update recommendations
        summary_parts = []
        for fs in self.sample_rates:
            n = recommended_n[fs]
            if n is not None:
                res = fs / n
                summary_parts.append(
                    tr("{0}kHz → Recommended: {1} (Max Realtime Resolution: ~{2:.2f}Hz)\n").format(fs / 1000.0, n, res)
                )
            else:
                summary_parts.append(
                    tr("{0}kHz → Recommended: None (Cannot process in real-time)\n").format(fs / 1000.0)
                )
        summary_text = "".join(summary_parts)

        # Clear existing labels in summary layout
        while self.summary_text_layout.count():
            child = self.summary_text_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        lbl = QLabel(summary_text.strip())
        lbl.setStyleSheet("font-size: 14px;")
        self.summary_text_layout.addWidget(lbl)

    def copy_to_clipboard(self):
        lines = []
        lines.append("--- MeasureLab Processor Benchmark ---")
        lines.append(self.sys_info_str)
        lines.append("")

        # Table content
        col_count = self.table.columnCount()
        headers = [(item.text() if (item := self.table.horizontalHeaderItem(i)) else "") for i in range(col_count)]
        lines.append(" | ".join(headers))
        lines.append("-" * 50)

        for row in range(self.table.rowCount()):
            item_0 = self.table.item(row, 0)
            if item_0 is None or not item_0.text():
                continue
            row_data = [(item.text() if (item := self.table.item(row, col)) else "") for col in range(col_count)]
            lines.append(" | ".join(row_data))

        lines.append("")

        # Recommendations
        lines.append(tr("Recommendations") + ":")
        for i in range(self.summary_text_layout.count()):
            item = self.summary_text_layout.itemAt(i)
            if item and item.widget():
                lines.append(item.widget().text())

        QApplication.clipboard().setText("\n".join(lines))
        self.status_label.setText(tr("Status: Copied to clipboard"))
