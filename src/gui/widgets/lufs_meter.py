import threading
import time

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from scipy import signal

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.gui.widgets.compactable_interface import CompactableWidgetInterface


class LufsMeter(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.sample_rate = 48000  # Default, updated on start

        # Use a deep floor so very low-noise devices don't collapse to -INF.
        # This affects only dBFS-related meters (RMS/Peak and C-weighted variants).
        self._db_floor = -200.0

        # Filter states (per-channel for strict BS.1770 energy summation)
        self.zi_shelf_l = None
        self.zi_shelf_r = None
        self.zi_hp_l = None
        self.zi_hp_r = None



        # Buffers / windows
        self.momentary_window = 0.4  # 400ms
        self.short_term_window = 3.0  # 3s
        self.buffer_size_m = 0
        self.buffer_size_s = 0

        # Ring-buffers of per-sample energy (Lk^2 + Rk^2)
        self._p_ring_m = None
        self._p_ring_s = None
        self._p_pos_m = 0
        self._p_pos_s = 0
        self._p_filled_m = 0
        self._p_filled_s = 0
        self._p_sum_m = 0.0
        self._p_sum_s = 0.0

        # Values
        self.momentary_lufs = -100.0
        self.short_term_lufs = -100.0
        self.integrated_lufs = -100.0
        self.target_lufs = -23.0
        self.integrated_threshold = -100.0
        self.lra = 0.0

        # Integrated loudness (BS.1770-style gating, streaming)
        self._i_started_at = None
        self._i_sample_count = 0
        self._i_block_step = 0
        self._i_since_last_block = 0
        self._i_block_ms = []  # per-block mean-square (Lk^2+Rk^2), 400 ms blocks, 75% overlap
        self._i_abs_gate_ms = float(10 ** ((-70.0 + 0.691) / 10.0))
        self._i_dirty = False
        self._i_lock = threading.Lock()

        self._lra_blocks = []
        self._lra_step_frames = 0

        # Stereo RMS & Peak
        self.rms_l = self._db_floor
        self.rms_r = self._db_floor
        self.peak_l = self._db_floor
        self.peak_r = self._db_floor
        self.peak_hold_l = self._db_floor
        self.peak_hold_r = self._db_floor
        self.crest_l = 0.0
        self.crest_r = 0.0



        self.callback_id = None

    @property
    def name(self) -> str:
        return "LUFS Meter"

    @property
    def description(self) -> str:
        return "Real-time Loudness (LUFS) and Stereo Level Meter"

    def get_widget(self):
        return LufsMeterWidget(self)

    def _init_filters(self):
        # K-weighting filter coefficients (ITU-R BS.1770-4)
        # Keep float32 to avoid per-block float64 upcasts in the audio callback.
        self.b0_shelf = np.array([1.53512485958697, -2.69169618940638, 1.19839281085285], dtype=np.float32)
        self.a0_shelf = np.array([1.0, -1.69065929318241, 0.73248077421585], dtype=np.float32)
        self.b1_hp = np.array([1.0, -2.0, 1.0], dtype=np.float32)
        self.a1_hp = np.array([1.0, -1.99004745483398, 0.99007225036621], dtype=np.float32)

        # Initial filter states (per-channel)
        zi_shelf = signal.lfilter_zi(self.b0_shelf, self.a0_shelf).astype(np.float32, copy=False)
        zi_hp = signal.lfilter_zi(self.b1_hp, self.a1_hp).astype(np.float32, copy=False)
        self.zi_shelf_l = zi_shelf.copy()
        self.zi_shelf_r = zi_shelf.copy()
        self.zi_hp_l = zi_hp.copy()
        self.zi_hp_r = zi_hp.copy()



    def reset_peaks(self):
        self.peak_hold_l = self._db_floor
        self.peak_hold_r = self._db_floor

    def reset_integration(self):
        self.integrated_lufs = -100.0
        self.integrated_threshold = -100.0
        self.lra = 0.0
        self._i_started_at = time.perf_counter()
        self._i_sample_count = 0
        self._i_since_last_block = 0
        # 400 ms block with 75% overlap -> 100 ms step
        self._i_block_step = int(round(0.1 * float(self.sample_rate)))
        self._lra_step_frames = 0
        with self._i_lock:
            self._i_block_ms = []
            self._lra_blocks = []
            self._i_dirty = False

    def update_integrated_lufs_if_dirty(self):
        """Recompute gated integrated loudness (BS.1770) when new blocks arrive.

        Intended to be called from the GUI thread to keep the audio callback lean.
        """
        with self._i_lock:
            if not self._i_dirty:
                return
            blocks = np.asarray(self._i_block_ms, dtype=np.float64)
            lra_blocks = np.asarray(self._lra_blocks, dtype=np.float64)
            self._i_dirty = False

        if blocks.size == 0:
            self.integrated_lufs = -100.0
            self.integrated_threshold = -100.0
        else:
            mean_ms_ungated = float(blocks.mean())
            l_ungated = self._to_lufs(mean_ms_ungated)
            rel_gate_l = l_ungated - 10.0
            rel_gate_ms = float(10 ** ((rel_gate_l + 0.691) / 10.0))
            gate_ms = max(self._i_abs_gate_ms, rel_gate_ms)

            gated = blocks[blocks > gate_ms]
            if gated.size == 0:
                self.integrated_lufs = -100.0
                self.integrated_threshold = -100.0
            else:
                self.integrated_lufs = self._to_lufs(float(gated.mean()))
                self.integrated_threshold = self._to_lufs(gate_ms)

        # Calculation of LRA
        if lra_blocks.size >= 2:
            lra_abs_gate = self._i_abs_gate_ms
            lra_abs_gated = lra_blocks[lra_blocks > lra_abs_gate]
            if lra_abs_gated.size > 0:
                lra_ungated_mean = float(lra_abs_gated.mean())
                lra_rel_gate = self._to_lufs(lra_ungated_mean) - 20.0
                lra_rel_gate_ms = float(10 ** ((lra_rel_gate + 0.691) / 10.0))

                lra_gated = lra_abs_gated[lra_abs_gated > lra_rel_gate_ms]
                if lra_gated.size >= 2:
                    lra_lufs = -0.691 + 10.0 * np.log10(np.maximum(lra_gated, 1e-10))
                    p10 = np.percentile(lra_lufs, 10)
                    p95 = np.percentile(lra_lufs, 95)
                    self.lra = p95 - p10
                else:
                    self.lra = 0.0
            else:
                self.lra = 0.0
        else:
            self.lra = 0.0

    def reset_all_stats(self):
        self.reset_peaks()
        self.reset_integration()

    def start_meter(self):
        if self.is_running:
            return

        self.is_running = True
        self.sample_rate = self.audio_engine.sample_rate
        self._init_filters()

        # Reset session accumulators
        self.reset_integration()

        # Initialize buffers (ring of per-sample power)
        self.buffer_size_m = int(round(self.momentary_window * float(self.sample_rate)))
        self.buffer_size_s = int(round(self.short_term_window * float(self.sample_rate)))
        self._p_ring_m = np.zeros(self.buffer_size_m, dtype=np.float32)
        self._p_ring_s = np.zeros(self.buffer_size_s, dtype=np.float32)
        self._p_pos_m = 0
        self._p_pos_s = 0
        self._p_filled_m = 0
        self._p_filled_s = 0
        self._p_sum_m = 0.0
        self._p_sum_s = 0.0

        abs_gate_ms = self._i_abs_gate_ms

        def ring_update_power(ring: np.ndarray, pos: int, filled: int, sum_p: float, p_chunk: np.ndarray):
            """Write p_chunk into ring (overwrite) and update running sum in O(len(p_chunk))."""
            n = int(ring.shape[0])
            m = int(p_chunk.shape[0])
            if m <= 0:
                return pos, filled, sum_p

            p_chunk_sum = float(np.sum(p_chunk, dtype=np.float64))

            end = pos + m
            if end <= n:
                sum_p -= float(np.sum(ring[pos:end], dtype=np.float64))
                ring[pos:end] = p_chunk
                sum_p += p_chunk_sum
            else:
                first = n - pos
                sum_p -= float(np.sum(ring[pos:], dtype=np.float64))
                sum_p -= float(np.sum(ring[: (end - n)], dtype=np.float64))

                ring[pos:] = p_chunk[:first]
                ring[: (end - n)] = p_chunk[first:]
                sum_p += p_chunk_sum

            pos = end % n
            filled = min(n, filled + m)
            return pos, filled, sum_p

        def callback(indata, outdata, frames, time, status):
            # --- Stereo RMS & Peak Calculation ---
            # indata is (frames, channels)
            num_channels = indata.shape[1]

            if num_channels >= 2:
                l_channel = indata[:, 0]
                r_channel = indata[:, 1]
            elif num_channels == 1:
                l_channel = indata[:, 0]
                r_channel = indata[:, 0]  # Duplicate mono
            else:
                # Should not happen if stream is active
                l_channel = np.zeros(frames)
                r_channel = np.zeros(frames)

            # RMS (Instantaneous for this block)
            # Use dot for low-allocation sumsq
            if frames > 0:
                rms_l_linear = float(np.sqrt(np.dot(l_channel, l_channel) / float(frames)))
                rms_r_linear = float(np.sqrt(np.dot(r_channel, r_channel) / float(frames)))
            else:
                rms_l_linear = 0.0
                rms_r_linear = 0.0
            self.rms_l = self._to_db(rms_l_linear)
            self.rms_r = self._to_db(rms_r_linear)



            # True Peak (Instantaneous)
            if frames > 0:
                l_up = signal.resample_poly(l_channel, 4, 1)
                r_up = signal.resample_poly(r_channel, 4, 1)
                peak_l_linear = float(np.max(np.abs(l_up)))
                peak_r_linear = float(np.max(np.abs(r_up)))
            else:
                peak_l_linear = 0.0
                peak_r_linear = 0.0

            self.peak_l = self._to_db(peak_l_linear)
            self.peak_r = self._to_db(peak_r_linear)

            # Peak Hold Update
            self.peak_hold_l = max(self.peak_hold_l, self.peak_l)
            self.peak_hold_r = max(self.peak_hold_r, self.peak_r)

            # Crest Factor (True Peak dB - RMS dB)
            # Ensure we don't subtract -100 from -100 resulting in 0 if both are silence, which is fine.
            # But if RMS is -100 and True Peak is -90, CF is 10.
            self.crest_l = self.peak_l - self.rms_l
            self.crest_r = self.peak_r - self.rms_r

            # --- LUFS Calculation (Strict stereo: per-channel K-weighting, sum energies) ---
            # For true mono input, avoid double-counting energy (would read +3 dB too hot).
            if num_channels == 1:
                l_lufs = l_channel
                r_lufs = np.zeros_like(l_channel)
            else:
                l_lufs = l_channel
                r_lufs = r_channel

            # Apply K-weighting per channel
            l_shelf, self.zi_shelf_l = signal.lfilter(self.b0_shelf, self.a0_shelf, l_lufs, zi=self.zi_shelf_l)
            r_shelf, self.zi_shelf_r = signal.lfilter(self.b0_shelf, self.a0_shelf, r_lufs, zi=self.zi_shelf_r)
            l_k, self.zi_hp_l = signal.lfilter(self.b1_hp, self.a1_hp, l_shelf, zi=self.zi_hp_l)
            r_k, self.zi_hp_r = signal.lfilter(self.b1_hp, self.a1_hp, r_shelf, zi=self.zi_hp_r)

            # Per-sample power (avoid rolling full windows)
            p_chunk = (l_k * l_k) + (r_k * r_k)
            self._p_pos_m, self._p_filled_m, self._p_sum_m = ring_update_power(
                self._p_ring_m, self._p_pos_m, self._p_filled_m, self._p_sum_m, p_chunk
            )
            self._p_pos_s, self._p_filled_s, self._p_sum_s = ring_update_power(
                self._p_ring_s, self._p_pos_s, self._p_filled_s, self._p_sum_s, p_chunk
            )

            # Track session time
            self._i_sample_count += int(frames)

            # Momentary (400 ms) and Short-term (3 s)
            n_m = float(max(1, self._p_filled_m))
            n_s = float(max(1, self._p_filled_s))
            ms_m = float(self._p_sum_m / n_m) if self._p_filled_m > 0 else 0.0
            ms_s = float(self._p_sum_s / n_s) if self._p_filled_s > 0 else 0.0
            self.momentary_lufs = self._to_lufs(ms_m)
            self.short_term_lufs = self._to_lufs(ms_s)

            # Integrated loudness with gating (400 ms blocks, 75% overlap)
            # Start once we have a full 400 ms window.
            if self._p_filled_m >= self.buffer_size_m and self._i_block_step > 0:
                self._i_since_last_block += int(frames)
                while self._i_since_last_block >= self._i_block_step:
                    self._i_since_last_block -= self._i_block_step
                    block_ms = float(self._p_sum_m / float(self.buffer_size_m))
                    if block_ms > abs_gate_ms:
                        with self._i_lock:
                            self._i_block_ms.append(block_ms)
                            self._i_dirty = True
            else:
                self._i_since_last_block += int(frames)

            # LRA collection (3s short-term blocks, 1s step)
            self._lra_step_frames += int(frames)
            while self._lra_step_frames >= self.sample_rate:
                self._lra_step_frames -= self.sample_rate
                if self._p_filled_s >= self.buffer_size_s:
                    block_s_ms = float(self._p_sum_s / float(self.buffer_size_s))
                    with self._i_lock:
                        self._lra_blocks.append(block_s_ms)
                        self._i_dirty = True

            # No output (meter is analysis-only). AudioEngine provides a fresh zeroed buffer.

        self.callback_id = self.audio_engine.register_callback(callback)

    def stop_meter(self):
        if self.is_running:
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None
            self.is_running = False

    def _to_db(self, value):
        if value <= 0 or not np.isfinite(value):
            return float(self._db_floor)
        if value <= 1e-20:
            return float(self._db_floor)
        return 20 * np.log10(value)

    def _to_lufs(self, mean_square):
        if mean_square <= 1e-10:
            return -100.0
        return -0.691 + 10 * np.log10(mean_square)

    def get_integrated_seconds(self) -> float:
        if self._i_sample_count <= 0 or self.sample_rate <= 0:
            return 0.0
        return self._i_sample_count / float(self.sample_rate)


class LufsMeterWidget(QWidget, CompactableWidgetInterface):
    def __init__(self, module: LufsMeter):
        QWidget.__init__(self)
        CompactableWidgetInterface.__init__(self)
        self.module = module



        # History for plotting
        self.history_size = 400  # 20s at 50ms interval
        self.m_history = np.full(self.history_size, -100.0)
        self.s_history = np.full(self.history_size, -100.0)

        # Performance optimizations state
        self._state_l = None
        self._state_r = None
        self._state_m = None
        self._state_s = None

        # Session stats (since last reset)
        self._reset_session_stats()

        self.init_ui()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_display)
        self.timer.setInterval(50)  # 20 FPS

    def init_ui(self):
        # Two-column layout (Sidebar on Left, Content on Right)
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)

        # --- Left Sidebar ---
        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(240)
        sidebar_layout = QVBoxLayout()
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(10)

        # Controls Group
        controls_group = QGroupBox(tr("Controls"))
        controls_layout = QVBoxLayout()
        controls_layout.setSpacing(8)

        self.toggle_btn = QPushButton(tr("Start Metering"))
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setMinimumHeight(36)
        self.toggle_btn.setStyleSheet("font-weight: bold; font-size: 13px;")
        self.toggle_btn.clicked.connect(self.on_toggle)
        controls_layout.addWidget(self.toggle_btn)

        self.reset_btn = QPushButton(tr("Reset Peaks"))
        self.reset_btn.setMinimumHeight(28)
        self.reset_btn.clicked.connect(self.module.reset_peaks)
        controls_layout.addWidget(self.reset_btn)

        self.reset_stats_btn = QPushButton(tr("Reset Stats"))
        self.reset_stats_btn.setMinimumHeight(28)
        self.reset_stats_btn.clicked.connect(self.on_reset_stats)
        controls_layout.addWidget(self.reset_stats_btn)

        controls_group.setLayout(controls_layout)
        sidebar_layout.addWidget(controls_group)

        # Settings Group
        settings_group = QGroupBox(tr("Settings"))
        settings_layout = QVBoxLayout()
        settings_layout.setSpacing(8)

        settings_layout.addWidget(QLabel(tr("Target LUFS:")))
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(-70.0, 0.0)
        self.target_spin.setDecimals(1)
        self.target_spin.setSingleStep(1.0)
        self.target_spin.setValue(-23.0)
        self.target_spin.setSuffix(" LUFS")
        self.target_spin.setMinimumHeight(28)
        self.target_spin.valueChanged.connect(self.on_target_changed)
        settings_layout.addWidget(self.target_spin)



        settings_group.setLayout(settings_layout)
        sidebar_layout.addWidget(settings_group)

        sidebar_layout.addStretch()
        self.sidebar.setLayout(sidebar_layout)



        # --- Right Main Content Area ---
        content_area = QWidget()
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(8)

        # 1. Top Panel (Horizontal combination of Digital Displays + Level Meters to optimize height!)
        top_panel = QWidget()
        top_panel_layout = QHBoxLayout(top_panel)
        top_panel_layout.setContentsMargins(0, 0, 0, 0)
        top_panel_layout.setSpacing(10)

        # 1a. Digital Readouts Frame
        display_frame = QWidget()
        display_frame.setStyleSheet("background-color: #000; border-radius: 8px;")
        display_layout = QHBoxLayout(display_frame)
        display_layout.setContentsMargins(6, 6, 6, 6)
        display_layout.setSpacing(6)

        self.disp_i = self._create_big_display(tr("Integrated"), "#ffaa00")
        display_layout.addWidget(self.disp_i["container"])

        self.disp_s = self._create_big_display(tr("Short-Term"), "#00ccff")
        display_layout.addWidget(self.disp_s["container"])

        top_panel_layout.addWidget(display_frame, 3)  # Stretch factor 3

        # 1b. Level Meters Panel
        meters_group = QGroupBox(tr("Levels"))
        meters_layout = QHBoxLayout()
        meters_layout.setContentsMargins(10, 6, 10, 6)
        meters_layout.setSpacing(15)  # spacing between stereo and loudness meter groups

        # Custom progress bar styling helper (Compact vertical height)
        def apply_meter_style(bar):
            bar.setRange(-120, 0)
            bar.setTextVisible(False)
            bar.setOrientation(Qt.Orientation.Vertical)
            bar.setFixedSize(18, 110)  # Compact meter size
            bar.setStyleSheet("""
                QProgressBar {
                    border: none;
                    background: #222;
                    border-radius: 2px;
                }
                QProgressBar::chunk {
                    border-radius: 2px;
                }
            """)

        # Stereo Group (L & R)
        stereo_widget = QWidget()
        stereo_layout = QHBoxLayout(stereo_widget)
        stereo_layout.setContentsMargins(0, 0, 0, 0)
        stereo_layout.setSpacing(8)

        # L channel
        l_container = QVBoxLayout()
        l_container.setSpacing(2)
        l_label = QLabel(tr("L"))
        l_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l_label.setStyleSheet("font-weight: bold; font-size: 10px; color: #eee;")
        self.l_bar = QProgressBar()
        apply_meter_style(self.l_bar)
        self.l_val_label = QLabel(tr("-INF"))
        self.l_val_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.l_val_label.setStyleSheet("font-size: 9px; font-weight: bold;")
        self.l_peak_label = QLabel(tr("TP: -INF"))
        self.l_peak_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.l_peak_label.setStyleSheet("color: #ff5555; font-size: 8px;")
        self.l_cf_label = QLabel(tr("CF: 0.0"))
        self.l_cf_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.l_cf_label.setStyleSheet("color: #00cccc; font-size: 8px;")

        l_container.addWidget(l_label)
        l_container.addWidget(self.l_bar, 0, Qt.AlignmentFlag.AlignHCenter)
        l_container.addWidget(self.l_val_label)
        l_container.addWidget(self.l_peak_label)
        l_container.addWidget(self.l_cf_label)
        stereo_layout.addLayout(l_container)

        # R channel
        r_container = QVBoxLayout()
        r_container.setSpacing(2)
        r_label = QLabel(tr("R"))
        r_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        r_label.setStyleSheet("font-weight: bold; font-size: 10px; color: #eee;")
        self.r_bar = QProgressBar()
        apply_meter_style(self.r_bar)
        self.r_val_label = QLabel(tr("-INF"))
        self.r_val_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.r_val_label.setStyleSheet("font-size: 9px; font-weight: bold;")
        self.r_peak_label = QLabel(tr("TP: -INF"))
        self.r_peak_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.r_peak_label.setStyleSheet("color: #ff5555; font-size: 8px;")
        self.r_cf_label = QLabel(tr("CF: 0.0"))
        self.r_cf_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.r_cf_label.setStyleSheet("color: #00cccc; font-size: 8px;")

        r_container.addWidget(r_label)
        r_container.addWidget(self.r_bar, 0, Qt.AlignmentFlag.AlignHCenter)
        r_container.addWidget(self.r_val_label)
        r_container.addWidget(self.r_peak_label)
        r_container.addWidget(self.r_cf_label)
        stereo_layout.addLayout(r_container)

        # Loudness Group (M & S)
        loudness_widget = QWidget()
        loudness_layout = QHBoxLayout(loudness_widget)
        loudness_layout.setContentsMargins(0, 0, 0, 0)
        loudness_layout.setSpacing(8)

        # M Meter
        m_container = QVBoxLayout()
        m_container.setSpacing(2)
        m_label = QLabel(tr("M"))
        m_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        m_label.setStyleSheet("font-weight: bold; font-size: 10px; color: #eee;")
        self.m_bar = QProgressBar()
        apply_meter_style(self.m_bar)
        self.m_val_label = QLabel(tr("-INF"))
        self.m_val_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.m_val_label.setStyleSheet("font-size: 9px; font-weight: bold;")
        m_text_lbl = QLabel(tr("LUFS(M)"))
        m_text_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        m_text_lbl.setStyleSheet("color: #aaa; font-size: 8px;")

        m_container.addWidget(m_label)
        m_container.addWidget(self.m_bar, 0, Qt.AlignmentFlag.AlignHCenter)
        m_container.addWidget(self.m_val_label)
        m_container.addWidget(m_text_lbl)
        loudness_layout.addLayout(m_container)

        # S Meter
        s_container = QVBoxLayout()
        s_container.setSpacing(2)
        s_label = QLabel(tr("S"))
        s_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s_label.setStyleSheet("font-weight: bold; font-size: 10px; color: #eee;")
        self.s_bar = QProgressBar()
        apply_meter_style(self.s_bar)
        self.s_val_label = QLabel(tr("-INF"))
        self.s_val_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.s_val_label.setStyleSheet("font-size: 9px; font-weight: bold;")
        s_text_lbl = QLabel(tr("LUFS(S)"))
        s_text_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s_text_lbl.setStyleSheet("color: #aaa; font-size: 8px;")

        s_container.addWidget(s_label)
        s_container.addWidget(self.s_bar, 0, Qt.AlignmentFlag.AlignHCenter)
        s_container.addWidget(self.s_val_label)
        s_container.addWidget(s_text_lbl)
        loudness_layout.addLayout(s_container)

        # Assemble Meters Area
        meters_layout.addWidget(stereo_widget)
        meters_layout.addStretch()
        meters_layout.addWidget(loudness_widget)
        meters_group.setLayout(meters_layout)

        top_panel_layout.addWidget(meters_group, 4)  # Stretch factor 4

        content_layout.addWidget(top_panel)

        # 2. Tabs (Statistics and Graph)
        self.tabs = QTabWidget()

        # --- Statistics Tab (Dashboard Grid Card Layout) ---
        stats_tab = QWidget()
        stats_grid = QGridLayout(stats_tab)
        stats_grid.setContentsMargins(8, 8, 8, 8)
        stats_grid.setSpacing(8)

        # Create dashboard cards
        self.card_lra = self._create_metric_card(tr("LRA"), tr("Loudness Range"), "#ffcc00")
        self.card_offset = self._create_metric_card(tr("Target Offset"), tr("Diff from target"), "#00ffcc")
        self.card_threshold = self._create_metric_card(tr("Gating Threshold"), tr("BS.1770 gating limit"), "#bb99ff")
        self.card_time = self._create_metric_card(tr("Duration"), tr("Total integration time"), "#ff99bb")

        stats_grid.addWidget(self.card_lra["container"], 0, 0)
        stats_grid.addWidget(self.card_offset["container"], 0, 1)
        stats_grid.addWidget(self.card_threshold["container"], 0, 2)
        stats_grid.addWidget(self.card_time["container"], 0, 3)

        # Create details panel (Momentary and Short-term side-by-side to save height!)
        details_panel = QWidget()
        details_layout = QHBoxLayout(details_panel)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(8)

        # M-LUFS Detail Stats Card
        m_group = QGroupBox(tr("Momentary LUFS Stats"))
        m_box = QHBoxLayout(m_group)
        m_box.setContentsMargins(4, 8, 4, 4)
        m_box.setSpacing(4)
        self.card_m_cur = self._create_stat_value_box(tr("Current"), "#00ff00")
        self.card_m_min = self._create_stat_value_box(tr("Min"), "#ff3333")
        self.card_m_max = self._create_stat_value_box(tr("Max"), "#3399ff")
        self.card_m_avg = self._create_stat_value_box(tr("Avg"), "#ffffff")
        m_box.addWidget(self.card_m_cur["container"])
        m_box.addWidget(self.card_m_min["container"])
        m_box.addWidget(self.card_m_max["container"])
        m_box.addWidget(self.card_m_avg["container"])
        details_layout.addWidget(m_group)

        # S-LUFS Detail Stats Card
        s_group = QGroupBox(tr("Short-Term LUFS Stats"))
        s_box = QHBoxLayout(s_group)
        s_box.setContentsMargins(4, 8, 4, 4)
        s_box.setSpacing(4)
        self.card_s_cur = self._create_stat_value_box(tr("Current"), "#00ff00")
        self.card_s_min = self._create_stat_value_box(tr("Min"), "#ff3333")
        self.card_s_max = self._create_stat_value_box(tr("Max"), "#3399ff")
        self.card_s_avg = self._create_stat_value_box(tr("Avg"), "#ffffff")
        s_box.addWidget(self.card_s_cur["container"])
        s_box.addWidget(self.card_s_min["container"])
        s_box.addWidget(self.card_s_max["container"])
        s_box.addWidget(self.card_s_avg["container"])
        details_layout.addWidget(s_group)

        stats_grid.addWidget(details_panel, 1, 0, 1, 4)

        self.tabs.addTab(stats_tab, tr("Statistics"))

        # --- Graph Tab ---
        graph_tab = QWidget()
        graph_layout = QVBoxLayout(graph_tab)
        graph_layout.setContentsMargins(4, 4, 4, 4)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel("left", tr("LUFS"), units="dB")
        self.plot_widget.setLabel("bottom", tr("Time"), units="s")
        self.plot_widget.setYRange(-60, 0)
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.setBackground("#111")
        self.plot_widget.setFixedHeight(140)  # Reduced from 180 to 140 for height limit

        # Curves
        self.m_curve = self.plot_widget.plot(pen=pg.mkPen("#00ccff", width=1), name=tr("Momentary"))  # Cyan
        self.s_curve = self.plot_widget.plot(pen=pg.mkPen("#ffcc00", width=2), name=tr("Short-Term"))  # Yellow

        # Target Line
        target = self.module.target_lufs
        self.target_line = pg.InfiniteLine(angle=0, pos=target, pen=pg.mkPen("#00ff00", style=Qt.PenStyle.DashLine))
        self.plot_widget.addItem(self.target_line)

        # Target band (-23 LUFS ±2) for quick visual alignment
        self.target_band = pg.LinearRegionItem(
            values=[target - 2, target + 2], orientation=pg.LinearRegionItem.Horizontal
        )
        self.target_band.setBrush(pg.mkBrush(0, 255, 0, 20))
        self.target_band.setMovable(False)
        self.target_band.setZValue(-10)
        self.plot_widget.addItem(self.target_band)

        graph_layout.addWidget(self.plot_widget)
        self.tabs.addTab(graph_tab, tr("Graph"))

        content_layout.addWidget(self.tabs)
        content_area.setLayout(content_layout)

        # --- Assemble Main Layout ---
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(content_area)
        self.setLayout(main_layout)

    def _create_big_display(self, title, color):
        container = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        lbl_title = QLabel(title)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setStyleSheet("color: #aaa; font-size: 10pt; font-weight: bold; margin-top: 2px;")

        lbl_val = QLabel("--.-")
        lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_val.setStyleSheet(f"color: {color}; font-size: 32px; font-weight: bold; font-family: monospace;")

        lbl_unit = QLabel("LUFS")
        lbl_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_unit.setStyleSheet(f"color: {color}; font-size: 10pt; margin-bottom: 2px;")

        layout.addWidget(lbl_title)
        layout.addWidget(lbl_val)
        layout.addWidget(lbl_unit)
        container.setLayout(layout)
        return {"container": container, "label": lbl_val, "unit": lbl_unit}

    def _create_metric_card(self, title, desc, color):
        container = QWidget()
        v_box = QVBoxLayout()
        v_box.setContentsMargins(4, 4, 4, 4)
        v_box.setSpacing(2)

        lbl_title = QLabel(title)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setStyleSheet("font-weight: bold; font-size: 10pt; color: #eee;")

        lbl_desc = QLabel(desc)
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_desc.setStyleSheet("font-size: 8pt; color: #888;")

        lbl_val = QLabel("--.-")
        lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_val.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {color}; font-family: monospace;")

        v_box.addWidget(lbl_title)
        v_box.addWidget(lbl_desc)
        v_box.addWidget(lbl_val)
        container.setLayout(v_box)
        container.setStyleSheet("background-color: #222; border-radius: 6px; border: 1px solid #333;")
        return {"container": container, "label": lbl_val}

    def _create_stat_value_box(self, label_text, color):
        container = QWidget()
        h_box = QHBoxLayout()
        h_box.setContentsMargins(6, 3, 6, 3)

        lbl_label = QLabel(label_text + ":")
        lbl_label.setStyleSheet("font-weight: bold; font-size: 9pt; color: #aaa;")

        lbl_val = QLabel("--.-")
        lbl_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_val.setStyleSheet(f"font-size: 11pt; font-weight: bold; color: {color}; font-family: monospace;")

        h_box.addWidget(lbl_label)
        h_box.addStretch()
        h_box.addWidget(lbl_val)
        container.setLayout(h_box)
        container.setStyleSheet("background-color: #1a1a1a; border-radius: 4px;")
        return {"container": container, "label": lbl_val}

    def _reset_session_stats(self):
        self._m_min = None
        self._m_max = None
        self._m_sum = 0.0
        self._m_n = 0

        self._s_min = None
        self._s_max = None
        self._s_sum = 0.0
        self._s_n = 0

    def on_reset_stats(self):
        self._reset_session_stats()
        self.m_history[:] = -100.0
        self.s_history[:] = -100.0
        # Reset color states so they force update on next tick
        self._state_l = None
        self._state_r = None
        self._state_m = None
        self._state_s = None
        self.module.reset_all_stats()

    def on_toggle(self, checked):
        if checked:
            self.module.start_meter()
            self.timer.start()
            self.toggle_btn.setText(tr("Stop Metering"))
            self.toggle_btn.setStyleSheet("background-color: #aa3333; font-weight: bold; font-size: 13px;")
        else:
            self.module.stop_meter()
            self.timer.stop()
            self.toggle_btn.setText(tr("Start Metering"))
            self.toggle_btn.setStyleSheet("font-weight: bold; font-size: 13px;")



    def on_target_changed(self, value):
        self.module.target_lufs = value
        self.target_line.setPos(value)
        self.target_band.setRegion([value - 2, value + 2])

    def update_display(self):
        if not self.module.is_running:
            return

        # Keep integrated LUFS computation off the audio callback.
        self.module.update_integrated_lufs_if_dirty()

        # Update RMS/Peak
        rms_l = self.module.rms_l
        rms_r = self.module.rms_r
        peak_hold_l = self.module.peak_hold_l
        peak_hold_r = self.module.peak_hold_r
        crest_l = self.module.crest_l
        crest_r = self.module.crest_r

        disp_rms_l = rms_l
        disp_rms_r = rms_r
        disp_peak_hold_l = peak_hold_l
        disp_peak_hold_r = peak_hold_r
        disp_unit = "dBFS"

        l_min = int(self.l_bar.minimum())
        l_max = int(self.l_bar.maximum())
        r_min = int(self.r_bar.minimum())
        r_max = int(self.r_bar.maximum())
        self.l_bar.setValue(int(max(l_min, min(l_max, rms_l))))
        self.r_bar.setValue(int(max(r_min, min(r_max, rms_r))))

        self.l_val_label.setText(tr("{0} {1}").format(self._format_db(disp_rms_l), disp_unit))
        self.r_val_label.setText(tr("{0} {1}").format(self._format_db(disp_rms_r), disp_unit))

        self.l_peak_label.setText(tr("TP: {0} {1}").format(self._format_db(disp_peak_hold_l), disp_unit))
        self.r_peak_label.setText(tr("TP: {0} {1}").format(self._format_db(disp_peak_hold_r), disp_unit))

        self.l_cf_label.setText(tr("CF: {0:.1f}").format(crest_l))
        self.r_cf_label.setText(tr("CF: {0:.1f}").format(crest_r))

        # Update LUFS
        m_lufs = self.module.momentary_lufs
        s_lufs = self.module.short_term_lufs
        i_lufs = self.module.integrated_lufs

        m_min = int(self.m_bar.minimum())
        m_max = int(self.m_bar.maximum())
        s_min = int(self.s_bar.minimum())
        s_max = int(self.s_bar.maximum())
        self.m_bar.setValue(int(max(m_min, min(m_max, m_lufs))))
        self.s_bar.setValue(int(max(s_min, min(s_max, s_lufs))))

        self.m_val_label.setText(tr("{0:.1f}").format(m_lufs))
        self.s_val_label.setText(tr("{0:.1f}").format(s_lufs))

        # Update Session digital displays
        self.disp_i["label"].setText(self._format_db(i_lufs))
        self.disp_s["label"].setText(self._format_db(s_lufs))
        self.disp_i["unit"].setText("LUFS")
        self.disp_s["unit"].setText("LUFS")

        # Update session stats
        self._update_session_stats(m_lufs, s_lufs)
        self._update_stats_labels(m_lufs, s_lufs)

        # Color coding with optimization
        self._set_bar_color(self.l_bar, rms_l, "l")
        self._set_bar_color(self.r_bar, rms_r, "r")
        self._set_lufs_bar_color(self.m_bar, m_lufs, self.module.target_lufs, "m")
        self._set_lufs_bar_color(self.s_bar, s_lufs, self.module.target_lufs, "s")

        # Update Plot
        self.m_history = np.roll(self.m_history, -1)
        self.m_history[-1] = m_lufs

        self.s_history = np.roll(self.s_history, -1)
        self.s_history[-1] = s_lufs

        # X axis (time)
        # 0 to -20s
        x = np.linspace(-self.history_size * 0.05, 0, self.history_size)

        self.m_curve.setData(x, self.m_history)
        self.s_curve.setData(x, self.s_history)

    def _format_db(self, value: float) -> str:
        if value <= -199.9:
            return tr("-INF")
        return tr("{0:.1f}").format(value)

    def _format_seconds(self, seconds: float) -> str:
        if seconds < 0:
            seconds = 0.0
        if seconds < 60:
            return tr("{0:.1f} s").format(seconds)
        minutes = int(seconds // 60)
        rem = seconds - (minutes * 60)
        return tr("{0:d} m {1:.0f} s").format(minutes, rem)

    def _update_session_stats(self, m_lufs: float, s_lufs: float):
        # Momentary
        if m_lufs > -99.9:
            self._m_min = m_lufs if self._m_min is None else min(self._m_min, m_lufs)
            self._m_max = m_lufs if self._m_max is None else max(self._m_max, m_lufs)
            self._m_sum += float(m_lufs)
            self._m_n += 1

        # Short-term
        if s_lufs > -99.9:
            self._s_min = s_lufs if self._s_min is None else min(self._s_min, s_lufs)
            self._s_max = s_lufs if self._s_max is None else max(self._s_max, s_lufs)
            self._s_sum += float(s_lufs)
            self._s_n += 1

    def _update_stats_labels(self, m_lufs: float, s_lufs: float):
        # Momentary details
        self.card_m_cur["label"].setText(self._format_db(m_lufs))
        self.card_m_min["label"].setText(self._format_db(self._m_min if self._m_min is not None else -100.0))
        self.card_m_max["label"].setText(self._format_db(self._m_max if self._m_max is not None else -100.0))
        m_avg = (self._m_sum / self._m_n) if self._m_n > 0 else -100.0
        self.card_m_avg["label"].setText(self._format_db(m_avg))

        # Short-term details
        self.card_s_cur["label"].setText(self._format_db(s_lufs))
        self.card_s_min["label"].setText(self._format_db(self._s_min if self._s_min is not None else -100.0))
        self.card_s_max["label"].setText(self._format_db(self._s_max if self._s_max is not None else -100.0))
        s_avg = (self._s_sum / self._s_n) if self._s_n > 0 else -100.0
        self.card_s_avg["label"].setText(self._format_db(s_avg))

        # Gated items
        self.card_lra["label"].setText(tr("{0:.1f} LU").format(self.module.lra))
        self.card_threshold["label"].setText(self._format_db(self.module.integrated_threshold))
        self.card_time["label"].setText(self._format_seconds(self.module.get_integrated_seconds()))

        # Target Offset
        if self.module.integrated_lufs > -99.9:
            offset = self.module.target_lufs - self.module.integrated_lufs
            sign = "+" if offset > 0 else ""
            self.card_offset["label"].setText(tr("{0}{1:.1f} LU").format(sign, offset))
        else:
            self.card_offset["label"].setText(tr("---"))

    def _set_bar_color(self, bar, val, ch_id):
        # Standard dBFS colors
        if val > -3:
            state = "red"
            color = "red"
        elif val > -12:
            state = "yellow"
            color = "#aaaa00"  # Yellow
        else:
            state = "green"
            color = "#00ff00"  # Green

        attr_name = f"_state_{ch_id}"
        prev_state = getattr(self, attr_name, None)
        if prev_state != state:
            setattr(self, attr_name, state)
            bar.setStyleSheet(f"""
                QProgressBar {{
                    border: none;
                    background: #222;
                    border-radius: 3px;
                }}
                QProgressBar::chunk {{
                    background-color: {color};
                    border-radius: 3px;
                }}
            """)

    def _set_lufs_bar_color(self, bar, lufs, target, ch_id):
        if lufs > target + 2:
            state = "red"
            color = "red"
        elif lufs > target - 2:
            state = "green"
            color = "#00ff00"  # Green (Target)
        else:
            state = "yellow"
            color = "#aaaa00"  # Yellow/Orange

        attr_name = f"_state_{ch_id}"
        prev_state = getattr(self, attr_name, None)
        if prev_state != state:
            setattr(self, attr_name, state)
            bar.setStyleSheet(f"""
                QProgressBar {{
                    border: none;
                    background: #222;
                    border-radius: 3px;
                }}
                QProgressBar::chunk {{
                    background-color: {color};
                    border-radius: 3px;
                }}
            """)

    def update_compact_layout(self):
        compact = self.is_compact_mode()
        if hasattr(self, "sidebar"):
            self.sidebar.setHidden(compact)
        if hasattr(self, "tabs"):
            self.tabs.setHidden(compact)

        # Trigger parent window size adjustment to prevent vertical stretching
        win = self.window()
        if win:
            from PyQt6 import sip
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(50, lambda: win.adjustSize() if not sip.isdeleted(win) else None)
