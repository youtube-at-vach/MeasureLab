import numpy as np
from PyQt6.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.localization import tr
from src.core.utils import format_si


class ImpedanceResultsWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.is_detailed = False
        self.circuit_mode = tr("Series")  # "Series" or "Parallel"
        self.init_ui()

        # Display precision defaults
        # Previously we used ".4g" for impedance-related readouts; increase by one digit.
        self._default_z_sig_figs = 5
        self._default_phase_places = 2

    def _sig_figs_from_std(
        self, val_std: float | None, val_abs: float | None, default: int, max_figs: int = 7, min_figs: int = 3
    ) -> int:
        """Choose significant figures based on measurement dispersion.

        Strategy: show stable digits + ~1 noise digit.
        For a value with decade p=floor(log10(|x|)) and std decade s=floor(log10(std)),
        sig_figs ≈ p - s + 1.
        """
        try:
            if val_std is None or val_abs is None:
                return int(default)
            std = float(val_std)
            x = float(val_abs)
            if not np.isfinite(std) or std <= 0.0:
                return int(default)
            if not np.isfinite(x) or x == 0.0:
                return int(default)

            p = int(np.floor(np.log10(abs(x))))
            s = int(np.floor(np.log10(std)))
            sig = p - s + 1
            sig = max(int(min_figs), min(int(max_figs), int(sig)))
            return sig
        except Exception:
            return int(default)

    def _phase_places_from_std(self, phase_std_deg: float | None, default: int, max_places: int = 4) -> int:
        """Choose decimal places for degrees based on phase std-dev (degrees)."""
        try:
            if phase_std_deg is None:
                return int(default)
            std = float(phase_std_deg)
            if not np.isfinite(std) or std <= 0.0:
                return int(default)
            if std <= 1e-9:
                return int(max_places)
            places = -int(np.floor(np.log10(std)))
            places = max(0, min(int(max_places), int(places)))
            return places
        except Exception:
            return int(default)

    def _fmt_dimless(self, value: float, sig_figs: int = 5) -> str:
        try:
            x = float(value)
            if not np.isfinite(x):
                return "-"
            return f"{x:.{int(sig_figs)}g}"
        except Exception:
            return "-"

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Header / Toggle ---
        header_layout = QHBoxLayout()
        self.mode_label = QLabel(f"{tr('Mode:')} {tr('Series')}")
        self.mode_label.setStyleSheet("font-weight: bold; color: #aaa;")
        header_layout.addWidget(self.mode_label)

        header_layout.addStretch()

        self.detail_btn = QPushButton(tr("Show Details"))
        self.detail_btn.setCheckable(True)
        self.detail_btn.clicked.connect(self.toggle_details)
        self.detail_btn.setStyleSheet("font-size: 10px; padding: 2px;")
        header_layout.addWidget(self.detail_btn)
        layout.addLayout(header_layout)

        # --- Simple View ---
        self.simple_widget = QWidget()
        simple_layout = QGridLayout(self.simple_widget)

        # Primary Z
        self.lbl_z_mag = QLabel("0.00 Ω")
        self.lbl_z_mag.setStyleSheet("font-size: 28px; font-weight: bold; color: #4caf50;")  # Green
        self.lbl_z_phase = QLabel("0.00°")
        self.lbl_z_phase.setStyleSheet("font-size: 20px; font-weight: bold; color: #2196f3;")  # Blue

        simple_layout.addWidget(QLabel(tr("|Z|:")), 0, 0)
        simple_layout.addWidget(self.lbl_z_mag, 0, 1)
        simple_layout.addWidget(QLabel(tr("θ:")), 0, 2)
        simple_layout.addWidget(self.lbl_z_phase, 0, 3)

        # Secondary (R/X or G/B based on mode)
        self.lbl_p1_name = QLabel(tr("Rs:"))
        self.lbl_p1_val = QLabel("0.00 Ω")
        self.lbl_p1_val.setStyleSheet("font-size: 18px; color: #ffeb3b;")  # Yellow

        self.lbl_p2_name = QLabel(tr("Xs:"))
        self.lbl_p2_val = QLabel("0.00 Ω")
        self.lbl_p2_val.setStyleSheet("font-size: 18px; color: #e91e63;")  # Pink

        simple_layout.addWidget(self.lbl_p1_name, 1, 0)
        simple_layout.addWidget(self.lbl_p1_val, 1, 1)
        simple_layout.addWidget(self.lbl_p2_name, 1, 2)
        simple_layout.addWidget(self.lbl_p2_val, 1, 3)

        # L/C/Q
        self.lbl_lc_name = QLabel(tr("L:"))
        self.lbl_lc_val = QLabel("0.00 H")
        self.lbl_q_val = QLabel(f"{tr('Q:')} 0.00")

        simple_layout.addWidget(self.lbl_lc_name, 2, 0)
        simple_layout.addWidget(self.lbl_lc_val, 2, 1)
        simple_layout.addWidget(self.lbl_q_val, 2, 2, 1, 2)

        layout.addWidget(self.simple_widget)

        # --- Detailed View ---
        self.detail_widget = QWidget()
        self.detail_widget.setVisible(False)
        detail_layout = QGridLayout(self.detail_widget)

        # Group 1: Series
        box_s = QGroupBox(tr("Series Equivalent"))
        lay_s = QFormLayout()
        self.val_rs = QLabel("-")
        lay_s.addRow(tr("Rs:"), self.val_rs)
        self.val_xs = QLabel("-")
        lay_s.addRow(tr("Xs:"), self.val_xs)
        self.val_ls = QLabel("-")
        lay_s.addRow(tr("Ls:"), self.val_ls)
        self.val_cs = QLabel("-")
        lay_s.addRow(tr("Cs:"), self.val_cs)
        box_s.setLayout(lay_s)
        detail_layout.addWidget(box_s, 0, 0)

        # Group 2: Parallel
        box_p = QGroupBox(tr("Parallel Equivalent"))
        lay_p = QFormLayout()
        self.val_rp = QLabel("-")
        lay_p.addRow(tr("Rp:"), self.val_rp)
        self.val_xp = QLabel("-")
        lay_p.addRow(tr("Xp:"), self.val_xp)
        self.val_lp = QLabel("-")
        lay_p.addRow(tr("Lp:"), self.val_lp)
        self.val_cp = QLabel("-")
        lay_p.addRow(tr("Cp:"), self.val_cp)
        box_p.setLayout(lay_p)
        detail_layout.addWidget(box_p, 0, 1)

        # Group 3: Admittance
        box_y = QGroupBox(tr("Admittance (Y)"))
        lay_y = QFormLayout()
        self.val_y_mag = QLabel("-")
        lay_y.addRow(tr("|Y|:"), self.val_y_mag)
        self.val_g = QLabel("-")
        lay_y.addRow(tr("G (Cond):"), self.val_g)
        self.val_b = QLabel("-")
        lay_y.addRow(tr("B (Susc):"), self.val_b)
        box_y.setLayout(lay_y)
        detail_layout.addWidget(box_y, 1, 0)

        # Group 4: Quality / Loss
        box_q = QGroupBox(tr("Quality / Loss"))
        lay_q = QFormLayout()
        self.val_q = QLabel("-")
        lay_q.addRow(tr("Q Factor:"), self.val_q)
        self.val_d = QLabel("-")
        lay_q.addRow(tr("D (Loss):"), self.val_d)
        self.val_esr = QLabel("-")
        lay_q.addRow(tr("ESR:"), self.val_esr)  # Same as Rs usually
        box_q.setLayout(lay_q)
        detail_layout.addWidget(box_q, 1, 1)

        # Group 5: Raw Signals (V / I)
        box_raw = QGroupBox(tr("Raw Signals (V / I)"))
        lay_raw = QFormLayout()
        self.val_v = QLabel("-")
        lay_raw.addRow(tr("Voltage:"), self.val_v)
        self.val_i = QLabel("-")
        lay_raw.addRow(tr("Current:"), self.val_i)
        self.val_v_phase = QLabel("-")
        lay_raw.addRow(tr("V Phase:"), self.val_v_phase)
        self.val_i_phase = QLabel("-")
        lay_raw.addRow(tr("I Phase:"), self.val_i_phase)
        box_raw.setLayout(lay_raw)
        detail_layout.addWidget(box_raw, 2, 0)

        # Group 6: Buffer (shown as a separate framed column to the right of V/I)
        box_buf = QGroupBox(tr("Buffer"))
        lay_buf = QFormLayout()
        self.val_buffer = QLabel("-")
        lay_buf.addRow(tr("Size:"), self.val_buffer)
        box_buf.setLayout(lay_buf)
        detail_layout.addWidget(box_buf, 2, 1)

        layout.addWidget(self.detail_widget)
        layout.addStretch()

    def toggle_details(self, checked):
        self.is_detailed = checked
        self.detail_widget.setVisible(checked)
        self.detail_btn.setText(tr("Hide Details") if checked else tr("Show Details"))

    def update_data(
        self,
        z: complex,
        v: complex,
        i: complex,
        freq: float,
        buffer_size: int | None = None,
        sample_rate: float | None = None,
        z_mag_std: float | None = None,
        z_phase_std_deg: float | None = None,
    ):
        if freq <= 0:
            return
        w = 2 * np.pi * freq
        # Buffer display (shown in the Details panel)
        try:
            if buffer_size is not None and sample_rate is not None and sample_rate > 0:
                bs = int(buffer_size)
                dt_ms = (bs / float(sample_rate)) * 1000.0
                self.val_buffer.setText(f"{bs} samples ({dt_ms:.1f} ms)")
            elif buffer_size is not None:
                self.val_buffer.setText(f"{int(buffer_size)} samples")
        except Exception:
            pass

        # Basic Z
        z_mag = float(abs(z))
        z_phase = float(np.degrees(np.angle(z)))

        # Precision
        z_sig_figs = self._sig_figs_from_std(
            z_mag_std,
            z_mag,
            default=int(getattr(self, "_default_z_sig_figs", 5) or 5),
            max_figs=7,
            min_figs=3,
        )
        phase_places = self._phase_places_from_std(
            z_phase_std_deg,
            default=int(getattr(self, "_default_phase_places", 2) or 2),
            max_places=4,
        )

        self.lbl_z_mag.setText(format_si(z_mag, "Ω", sig_figs=z_sig_figs))
        self.lbl_z_phase.setText(f"{z_phase:.{phase_places}f}°")

        # Series
        rs = z.real
        xs = z.imag
        ls = xs / w if w > 0 else 0
        cs = -1 / (w * xs) if (w > 0 and abs(xs) > 1e-12) else float("inf")

        # Parallel
        # Y = 1/Z = G + jB
        if z_mag > 1e-12:
            y = 1.0 / z
            g = y.real
            b = y.imag

            rp = 1.0 / g if abs(g) > 1e-12 else float("inf")
            xp = -1.0 / b if abs(b) > 1e-12 else float("inf")

            lp = -1.0 / (w * b) if (w > 0 and abs(b) > 1e-12) else float("inf")
            cp = b / w if w > 0 else 0
        else:
            y = 0j
            g = 0
            b = 0
            rp = 0
            xp = 0
            lp = 0
            cp = 0

        # Q / D
        q = abs(xs) / abs(rs) if abs(rs) > 1e-12 else float("inf")
        d = 1.0 / q if q > 1e-12 else float("inf")

        # --- Update Detailed View ---
        self.val_rs.setText(format_si(rs, "Ω", sig_figs=z_sig_figs))
        self.val_xs.setText(format_si(xs, "Ω", sig_figs=z_sig_figs))
        self.val_ls.setText(format_si(ls, "H", sig_figs=z_sig_figs))
        self.val_cs.setText(format_si(cs, "F", sig_figs=z_sig_figs))

        self.val_rp.setText(format_si(rp, "Ω", sig_figs=z_sig_figs))
        self.val_xp.setText(format_si(xp, "Ω", sig_figs=z_sig_figs))
        self.val_lp.setText(format_si(lp, "H", sig_figs=z_sig_figs))
        self.val_cp.setText(format_si(cp, "F", sig_figs=z_sig_figs))

        # Admittance display: use SI prefixes (nS/µS/mS/...) with significant figures.
        # Keep slightly lower default sig-figs than impedance to avoid noisy UI.
        self.val_y_mag.setText(format_si(abs(y), "S", sig_figs=max(4, z_sig_figs - 1)))
        self.val_g.setText(format_si(g, "S", sig_figs=max(4, z_sig_figs - 1)))
        self.val_b.setText(format_si(b, "S", sig_figs=max(4, z_sig_figs - 1)))

        self.val_q.setText(self._fmt_dimless(q, sig_figs=max(4, z_sig_figs - 1)))
        self.val_d.setText(self._fmt_dimless(d, sig_figs=max(4, z_sig_figs - 1)))
        self.val_esr.setText(format_si(rs, "Ω", sig_figs=z_sig_figs))

        # Raw signals are shown primarily for debugging; keep their previous style.
        self.val_v.setText(f"{abs(v):.4g} V")
        self.val_i.setText(f"{abs(i) * 1000:.4g} mA")
        self.val_v_phase.setText(f"{np.degrees(np.angle(v)):.2f}°")
        self.val_i_phase.setText(f"{np.degrees(np.angle(i)):.2f}°")

        # --- Update Simple View ---
        self.mode_label.setText(f"{tr('Mode:')} {self.circuit_mode}")

        if self.circuit_mode == tr("Series"):
            self.lbl_p1_name.setText(tr("Rs:"))
            self.lbl_p1_val.setText(format_si(rs, "Ω", sig_figs=z_sig_figs))
            self.lbl_p2_name.setText(tr("Xs:"))
            self.lbl_p2_val.setText(format_si(xs, "Ω", sig_figs=z_sig_figs))

            if xs > 0:  # Inductive
                self.lbl_lc_name.setText(tr("Ls:"))
                self.lbl_lc_val.setText(format_si(ls, "H", sig_figs=z_sig_figs))
            else:  # Capacitive
                self.lbl_lc_name.setText(tr("Cs:"))
                self.lbl_lc_val.setText(format_si(cs, "F", sig_figs=z_sig_figs))

        else:  # Parallel
            self.lbl_p1_name.setText(tr("Rp:"))
            self.lbl_p1_val.setText(format_si(rp, "Ω", sig_figs=z_sig_figs))
            self.lbl_p2_name.setText(tr("Xp:"))
            self.lbl_p2_val.setText(format_si(xp, "Ω", sig_figs=z_sig_figs))

            if b < 0:  # Inductive (B is negative for Inductor in Admittance? Y = 1/jwL = -j/wL -> B < 0)
                self.lbl_lc_name.setText(tr("Lp:"))
                self.lbl_lc_val.setText(format_si(lp, "H", sig_figs=z_sig_figs))
            else:  # Capacitive (Y = jwC -> B > 0)
                self.lbl_lc_name.setText(tr("Cp:"))
                self.lbl_lc_val.setText(format_si(cp, "F", sig_figs=z_sig_figs))

        self.lbl_q_val.setText(f"{tr('Q:')} {self._fmt_dimless(q, sig_figs=max(4, z_sig_figs - 1))}")
