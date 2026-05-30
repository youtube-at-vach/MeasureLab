import logging
import threading
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.core.bit_perfect_logic import (
    PRBSGenerator,
    find_sequence_delay,
    diagnose_bit_perfection,
)
from src.gui.styles import MONOSPACE_FONT_FAMILY

logger = logging.getLogger(__name__)


class BitPerfectVerifier(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self._lock = threading.Lock()

        # DSP/Ring Buffer settings
        self.max_buffer_len = 131072
        self.rx_buffer = np.zeros(self.max_buffer_len, dtype=np.float32)
        self.write_ptr = 0
        self.new_samples_count = 0

        # Generator settings
        self.pattern_mode = "PRBS-15"
        self.bit_depth = 24
        self.input_channel_idx = 0  # 0 for Left, 1 for Right

        # State variables
        self.generator = PRBSGenerator(self.pattern_mode)
        self.ref_cycle_len = 32767
        self.ref_cycle = self.generator.generate_reference_sequence(self.ref_cycle_len, self.bit_depth)
        self.tx_ptr = 0

        # Lock and Sync state
        self.is_locked = False
        self.lock_offset = 0
        self.samples_processed = 0

        # Accumulated stats
        self.total_test_samples = 0
        self.total_bit_errors = 0
        self.bit_hist = np.zeros(24, dtype=np.int64)

        # UI Diagnostic results
        self.results = {
            "locked": False,
            "bit_perfect": False,
            "reason": tr("Waiting for signal..."),
            "gain_db": 0.0,
            "bit_depth": 0,
            "bit_errors": 0,
            "error_rate": 0.0,
            "total_samples": 0,
            "active_bits": 0,
        }

        self.callback_id = None

    @property
    def name(self) -> str:
        return "Bit-Perfect Verifier"

    @property
    def description(self) -> str:
        return tr("Verifies digital audio path transparency by checking bits under loopback.")

    def get_widget(self):
        return BitPerfectVerifierWidget(self)

    def start_analysis(self):
        with self._lock:
            if self.is_running:
                return
            self.is_running = True

            # Reset buffers and state
            self.rx_buffer.fill(0)
            self.write_ptr = 0
            self.new_samples_count = 0

            self.generator = PRBSGenerator(self.pattern_mode)
            self.ref_cycle_len = 32767 if self.pattern_mode == "PRBS-15" else 511
            self.ref_cycle = self.generator.generate_reference_sequence(self.ref_cycle_len, self.bit_depth)
            self.tx_ptr = 0

            self.is_locked = False
            self.lock_offset = 0
            self.samples_processed = 0
            self.total_test_samples = 0
            self.total_bit_errors = 0
            self.bit_hist.fill(0)

            # Reset results
            self.results = {
                "locked": False,
                "bit_perfect": False,
                "reason": tr("Synchronizing..."),
                "gain_db": 0.0,
                "bit_depth": 0,
                "bit_errors": 0,
                "error_rate": 0.0,
                "total_samples": 0,
                "active_bits": 0,
            }

        self.callback_id = self.audio_engine.register_callback(self._audio_callback)

    def stop_analysis(self):
        with self._lock:
            if not self.is_running:
                return
            self.is_running = False

            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None

    def _audio_callback(self, indata, outdata, frames, time, status):
        # 1. Play reference sequence
        # Note: PRBS is filled on output channel 1 (Left) and 2 (Right)
        out_ch = outdata.shape[1]
        for i in range(frames):
            val = self.ref_cycle[self.tx_ptr]
            outdata[i, 0] = val
            if out_ch > 1:
                outdata[i, 1] = val
            self.tx_ptr = (self.tx_ptr + 1) % self.ref_cycle_len

        # 2. Record input signal
        with self._lock:
            if not self.is_running:
                outdata.fill(0)
                return

            n = len(indata)
            ptr = self.write_ptr
            space = self.max_buffer_len - ptr

            # Select input channel
            ch = self.input_channel_idx
            if ch >= indata.shape[1]:
                ch = 0
            ch_data = indata[:, ch]

            if n <= space:
                self.rx_buffer[ptr : ptr + n] = ch_data
                self.write_ptr = (ptr + n) % self.max_buffer_len
            else:
                self.rx_buffer[ptr:] = ch_data[:space]
                self.rx_buffer[: n - space] = ch_data[space:]
                self.write_ptr = n - space

            self.new_samples_count = min(self.max_buffer_len, self.new_samples_count + n)

    def process_data(self):
        """Processes ring buffer samples to verify bit-perfection."""
        with self._lock:
            if not self.is_running or self.new_samples_count < 1024:
                return None

            # Extract new samples from the ring buffer
            n = self.new_samples_count
            w_ptr = self.write_ptr
            r_ptr = (w_ptr - n) % self.max_buffer_len

            if r_ptr + n <= self.max_buffer_len:
                new_data = self.rx_buffer[r_ptr : r_ptr + n].copy()
            else:
                part1 = self.max_buffer_len - r_ptr
                new_data = np.concatenate((self.rx_buffer[r_ptr:], self.rx_buffer[: n - part1]))

            self.new_samples_count = 0

        # Synchronization and lock checks
        if not self.is_locked:
            # Need at least a full cycle of reference to do a reliable search
            # We slide a 1024-sample window of the recorded data over the reference cycle
            search_len = min(len(new_data), 1024)
            segment = new_data[:search_len]

            offset, corr = find_sequence_delay(segment, self.ref_cycle)

            if corr > 0.95:
                self.is_locked = True
                self.lock_offset = offset
                self.samples_processed = 0
                logger.info(f"Bit-Perfect Verifier Locked: Offset={offset}, Correlation={corr:.4f}")
            else:
                # No lock
                self.results["reason"] = tr("Waiting for sync... (Correlation: {0:.2f})").format(corr)
                self.results["locked"] = False
                return None

        # Lock is active: perform continuous verification
        N = len(new_data)

        # Build reference segment matching the aligned playback pointer
        ref_indices = (np.arange(N) + self.lock_offset + self.samples_processed) % self.ref_cycle_len
        ref_segment = self.ref_cycle[ref_indices]

        # Run diagnosis
        diag = diagnose_bit_perfection(new_data, ref_segment)

        # Keep track of offset
        self.samples_processed += N
        self.total_test_samples += N

        # Update bit error histogram
        K = 10 ** (diag["gain_db"] / 20.0)
        rx_scaled = new_data / (K + 1e-12)

        # Difference mask check (for histogram)
        err_mask = np.abs(rx_scaled - ref_segment) > 1e-7
        err_count = np.sum(err_mask)
        self.total_bit_errors += err_count

        if err_count > 0:
            # Analyze exact bits
            rx_int = np.round(rx_scaled[err_mask] * 8388608.0).astype(np.int32)
            ref_int = np.round(ref_segment[err_mask] * 8388608.0).astype(np.int32)

            diff_mask = (rx_int ^ ref_int) & 0xFFFFFF

            for b in range(24):
                bits_flipped = np.sum((diff_mask >> b) & 1)
                self.bit_hist[b] += bits_flipped

        # If error rate is extremely high (e.g. path disconnected or slip), unlock
        if err_count / N > 0.95 and N > 128:
            logger.warning("Bit-Perfect Verifier lost sync.")
            self.is_locked = False
            self.results["locked"] = False
            self.results["reason"] = tr("Sync lost (Heavy errors).")
            return None

        # Write results
        self.results = {
            "locked": True,
            "bit_perfect": diag["bit_perfect"],
            "reason": diag["reason"],
            "gain_db": diag["gain_db"],
            "bit_depth": diag["bit_depth"],
            "bit_errors": self.total_bit_errors,
            "error_rate": (self.total_bit_errors / self.total_test_samples) * 100.0,
            "total_samples": self.total_test_samples,
            "active_bits": diag["active_bits"],
        }

        return self.results


class BitPerfectVerifierWidget(QWidget, CompactableWidgetInterface):
    def __init__(self, module: BitPerfectVerifier):
        QWidget.__init__(self)
        CompactableWidgetInterface.__init__(self)
        self.module = module

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_display)
        self.timer.setInterval(100)  # 10Hz UI refresh

        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # ================= Left Panel: Controls =================
        self.left_panel = QWidget()
        self.left_panel.setFixedWidth(260)
        controls_layout = QVBoxLayout(self.left_panel)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10)

        # Test control card
        ctrl_group = QGroupBox(tr("Test Controls"))
        ctrl_layout = QVBoxLayout()

        self.btn_toggle = QPushButton(tr("Start Test"))
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setStyleSheet(
            "QPushButton { background-color: #2ecc71; color: black; font-weight: bold; height: 36px; border-radius: 4px; }"
            "QPushButton:checked { background-color: #e74c3c; color: white; }"
        )
        self.btn_toggle.clicked.connect(self.on_toggle_test)
        ctrl_layout.addWidget(self.btn_toggle)

        self.btn_clear = QPushButton(tr("Reset Statistics"))
        self.btn_clear.clicked.connect(self.on_reset_stats)
        ctrl_layout.addWidget(self.btn_clear)

        ctrl_group.setLayout(ctrl_layout)
        controls_layout.addWidget(ctrl_group)

        # Settings card
        settings_group = QGroupBox(tr("Settings"))
        form_layout = QFormLayout()

        self.combo_channel = QComboBox()
        self.combo_channel.addItem(tr("Left Channel (CH1)"), 0)
        self.combo_channel.addItem(tr("Right Channel (CH2)"), 1)
        self.combo_channel.currentIndexChanged.connect(self.on_channel_changed)
        form_layout.addRow(tr("Input Channel:"), self.combo_channel)

        self.combo_pattern = QComboBox()
        self.combo_pattern.addItem("PRBS-15 (Standard)", "PRBS-15")
        self.combo_pattern.addItem("PRBS-9 (Low Latency)", "PRBS-9")
        self.combo_pattern.currentIndexChanged.connect(self.on_settings_changed)
        form_layout.addRow(tr("Pattern:"), self.combo_pattern)

        self.combo_depth = QComboBox()
        self.combo_depth.addItem(tr("24-bit (High Precision)"), 24)
        self.combo_depth.addItem(tr("16-bit (CD Quality)"), 16)
        self.combo_depth.currentIndexChanged.connect(self.on_settings_changed)
        form_layout.addRow(tr("Bit Depth:"), self.combo_depth)

        settings_group.setLayout(form_layout)
        controls_layout.addWidget(settings_group)

        controls_layout.addStretch()
        main_layout.addWidget(self.left_panel)

        # ================= Right/Center Panel: Visuals & Report =================
        right_panel = QVBoxLayout()
        right_panel.setSpacing(12)

        # Status badge row
        self.card_status = QWidget()
        self.card_status.setStyleSheet("background-color: #2c3e50; border-radius: 8px;")
        self.card_status.setFixedHeight(120)
        status_layout = QVBoxLayout(self.card_status)
        status_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_status = QLabel(tr("WAITING FOR SIGNAL..."))
        self.lbl_status.setFont(QFont("Arial", 28, QFont.Weight.Bold))
        self.lbl_status.setStyleSheet("color: #bdc3c7;")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(self.lbl_status)

        self.lbl_reason = QLabel(tr("Start testing to check transmission channel bit-perfection."))
        self.lbl_reason.setStyleSheet("color: #ecf0f1; font-size: 13px;")
        self.lbl_reason.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(self.lbl_reason)

        right_panel.addWidget(self.card_status)

        # Report & Histogram split row
        mid_layout = QHBoxLayout()
        mid_layout.setSpacing(12)

        # Diagnostic Report Box
        report_group = QGroupBox(tr("Diagnostic Report"))
        report_layout = QVBoxLayout()
        self.lbl_report = QLabel(tr("Diagnostic report will appear here once lock is established."))
        self.lbl_report.setStyleSheet(f"font-family: {MONOSPACE_FONT_FAMILY}; font-size: 13px; color: #34495e;")
        self.lbl_report.setWordWrap(True)
        self.lbl_report.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        report_layout.addWidget(self.lbl_report)
        report_group.setLayout(report_layout)
        report_group.setMinimumWidth(280)
        mid_layout.addWidget(report_group, stretch=1)

        # Histogram Box
        hist_group = QGroupBox(tr("Active Bit-Error Distribution"))
        hist_layout = QVBoxLayout()

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel("bottom", tr("Bit Position (LSB 0 to MSB 23)"))
        self.plot_widget.setLabel("left", tr("Error Count"))
        self.plot_widget.showGrid(x=False, y=True, alpha=0.3)
        self.plot_widget.setXRange(-0.5, 23.5)

        self.bar_item = pg.BarGraphItem(x=np.arange(24), height=np.zeros(24), width=0.6, brush="y")
        self.plot_widget.addItem(self.bar_item)

        hist_layout.addWidget(self.plot_widget)
        hist_group.setLayout(hist_layout)
        mid_layout.addWidget(hist_group, stretch=2)

        right_panel.addLayout(mid_layout)
        main_layout.addLayout(right_panel, stretch=1)

        self.setLayout(main_layout)

    def on_toggle_test(self, checked):
        if checked:
            self.module.start_analysis()
            self.timer.start()
            self.btn_toggle.setText(tr("Stop Test"))
            self.lbl_status.setText(tr("WAITING FOR SYNC..."))
            self.lbl_status.setStyleSheet("color: #f39c12;")
            self.lbl_reason.setText(tr("Synchronizing with digital playback sequence..."))
        else:
            self.module.stop_analysis()
            self.timer.stop()
            self.btn_toggle.setText(tr("Start Test"))
            self.lbl_status.setText(tr("IDLE"))
            self.lbl_status.setStyleSheet("color: #bdc3c7;")
            self.lbl_reason.setText(tr("Start testing to check transmission channel bit-perfection."))

    def on_reset_stats(self):
        with self.module._lock:
            self.module.total_test_samples = 0
            self.module.total_bit_errors = 0
            self.module.bit_hist.fill(0)
            self.bar_item.setOpts(height=np.zeros(24))

    def on_channel_changed(self, idx):
        self.module.input_channel_idx = idx

    def on_settings_changed(self):
        # Restart test with new settings if currently running
        is_running = self.btn_toggle.isChecked()
        if is_running:
            self.module.stop_analysis()

        self.module.pattern_mode = self.combo_pattern.currentData()
        self.module.bit_depth = self.combo_depth.currentData()

        if is_running:
            self.module.start_analysis()

    def update_display(self):
        res = self.module.process_data()
        if res is None:
            # Check lock state
            if not self.module.is_locked:
                self.lbl_status.setText(tr("WAITING FOR SYNC..."))
                self.lbl_status.setStyleSheet("color: #f39c12;")
                self.lbl_reason.setText(self.module.results["reason"])
            return

        # Locked and verifying!
        is_perfect = res["bit_perfect"]

        # Color updates
        if is_perfect:
            self.lbl_status.setText(tr("✔ BIT-PERFECT"))
            self.lbl_status.setStyleSheet("color: #2ecc71; font-weight: bold;")
            self.card_status.setStyleSheet("background-color: #1b4d3e; border-radius: 8px;")
        else:
            self.lbl_status.setText(tr("❌ ALTERED"))
            self.lbl_status.setStyleSheet("color: #e74c3c; font-weight: bold;")
            self.card_status.setStyleSheet("background-color: #5c1d1d; border-radius: 8px;")

        self.lbl_reason.setText(res["reason"])

        # Update text report
        report_text = (
            f"<b>{tr('Transmission Path:')}</b> {'Bit-Perfect!' if is_perfect else tr('Modified')}<br/>"
            f"<b>{tr('Detected Bit Depth:')}</b> {res['bit_depth'] if res['bit_depth'] > 0 else 'N/A'}-bit<br/>"
            f"<b>{tr('Volume Alteration:')}</b> {res['gain_db']:+.3f} dB<br/>"
            f"<b>{tr('Total Processed:')}</b> {res['total_samples']:,} samples<br/>"
            f"<b>{tr('Bit Errors:')}</b> {res['bit_errors']:,}<br/>"
            f"<b>{tr('Bit Error Rate (BER):')}</b> {res['error_rate']:.6f} %"
        )
        self.lbl_report.setText(report_text)

        # Update Error Histogram
        hist = self.module.bit_hist.copy()
        self.bar_item.setOpts(height=hist)

        # Rescale plot y-axis automatically if errors grow
        max_err = np.max(hist)
        if max_err > 0:
            self.plot_widget.setYRange(0, max_err * 1.1)
        else:
            self.plot_widget.setYRange(0, 10)

    def update_compact_layout(self):
        compact = self.is_compact_mode()
        self.left_panel.setHidden(compact)

        # Adjust size for parent window
        win = self.window()
        if win:
            from PyQt6 import sip
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(50, lambda: win.adjustSize() if not sip.isdeleted(win) else None)
