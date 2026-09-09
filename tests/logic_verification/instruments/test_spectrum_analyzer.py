import numpy as np
import pytest
from unittest.mock import MagicMock

from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer, SpectrumAnalyzerWidget
# AudioEngine not imported as class, only mocked


class TestSpectrumAnalyzer:
    """Consolidated tests for SpectrumAnalyzer logic and widget integration."""

    @pytest.fixture
    def mock_engine(self):
        # We don't use spec=AudioEngine because it misses instance attributes like calibration
        # initialized in __init__. Instead we just use MagicMock and configure it.
        engine = MagicMock()
        engine.sample_rate = 48000

        # Setup calibration mock
        engine.calibration = MagicMock()
        engine.calibration.input_sensitivity = 1.0
        engine.calibration.output_gain = 1.0
        engine.calibration.get_input_offset_db.return_value = 0.0
        engine.calibration.get_spl_offset_db.return_value = None

        # Mock register_callback to return a dummy ID
        engine.register_callback.return_value = 1
        return engine

    @pytest.fixture
    def sa_module(self, mock_engine):
        sa = SpectrumAnalyzer(mock_engine)
        sa.set_buffer_size(4096)
        return sa

    @pytest.fixture
    def sa_widget(self, sa_module, qtbot):
        widget = SpectrumAnalyzerWidget(sa_module)
        qtbot.addWidget(widget)
        return widget

    def test_transfer_buffer_data_flow(self, sa_module):
        """Verify that data flows from callback -> transfer buffer -> input data."""

        # Start analysis to register callback
        sa_module.start_analysis()

        # Verify callback was registered
        sa_module.audio_engine.register_callback.assert_called_once()
        callback = sa_module.audio_engine.register_callback.call_args[0][0]

        assert sa_module.transfer_buffer.available() == 0
        assert sa_module.transfer_buffer.dtype == sa_module.input_data.dtype

        # Simulate audio callback
        frames = 100
        indata = np.ones((frames, 2), dtype=np.float32) * 0.5
        outdata = np.zeros_like(indata)

        callback(indata, outdata, frames, 0.0, None)

        assert sa_module.transfer_buffer.available() == frames

        # Process queue
        sa_module.process_queue()

        assert sa_module.transfer_buffer.available() == 0
        # write_head should be advanced by frames
        assert sa_module.write_head == frames
        # Check data content
        assert np.allclose(sa_module.input_data[:frames], 0.5)

    def test_transfer_buffer_is_bounded_and_keeps_latest_samples(self, sa_module):
        """A stalled display must not allow pending audio memory to grow indefinitely."""
        sa_module.transfer_buffer = sa_module.transfer_buffer.__class__(10, 2, dtype=np.float32)
        samples = np.arange(30, dtype=np.float32).reshape(15, 2)

        sa_module.transfer_buffer.write(samples)
        sa_module.process_queue()

        assert sa_module.display_dropped_samples == 5
        assert sa_module.write_head == 10
        assert np.array_equal(sa_module.input_data[:10], samples[-10:])
        assert sa_module.transfer_buffer.available() == 0

        sa_module.process_queue()
        assert sa_module.display_dropped_samples == 0

    def test_snapshot_restarts_after_transfer_gap(self, sa_module):
        """A slow FFT snapshot must never combine samples from across a transfer gap."""
        sa_module.set_buffer_size(sa_module.LARGE_BUFFER_THRESHOLD)
        sa_module.transfer_buffer = sa_module.transfer_buffer.__class__(10, 2, dtype=np.float32)
        sa_module.input_data[:4] = -1.0
        sa_module.write_head = 4
        samples = np.arange(30, dtype=np.float32).reshape(15, 2)

        sa_module.transfer_buffer.write(samples)
        sa_module.process_queue()

        assert sa_module.display_dropped_samples == 5
        assert sa_module.write_head == 10
        assert np.array_equal(sa_module.input_data[:10], samples[-10:])

    def test_widget_reports_transfer_gap(self, sa_module, sa_widget):
        """Display loss is visible even while a slow snapshot is still incomplete."""
        sa_module.is_running = True
        sa_module.display_dropped_samples = 23
        sa_module.process_queue = MagicMock()
        sa_module.compute_spectrum = MagicMock(return_value=None)

        sa_widget.update_plot()

        assert not sa_widget.display_gap_badge.isHidden()
        assert "23" in sa_widget.display_gap_badge.text()

        sa_module.display_dropped_samples = 0
        sa_widget.update_plot()
        assert sa_widget.display_gap_badge.isHidden()

    def test_weighting_application(self, sa_module, sa_widget):
        """Verify A/C/Z weighting application affects the overall RMS reading correctly."""

        # Generate Sine Wave 100Hz, Amplitude 1.0 (Peak 0dBFS)
        fs = 48000
        N = 4096
        t = np.arange(N) / fs
        sig = 1.0 * np.sin(2 * np.pi * 100 * t)

        # Fill buffer directly for testing update_plot
        sa_module.input_data[:, 0] = sig
        sa_module.input_data[:, 1] = sig
        sa_module.write_head = 0  # Rolling mode uses full buffer if head is 0

        sa_module.is_running = True  # Needed for update_plot to run
        sa_module.analysis_mode = "Spectrum"
        sa_module.multitaper_enabled = False
        sa_module.display_unit = "dBFS"

        # Helper to extract text from label
        def get_overall_db():
            text = sa_widget.overall_label.text()
            # "Overall: -3.0 dBFS(Z)"
            try:
                val_str = text.split(" ")[1]  # "-3.0"
                return float(val_str)
            except (IndexError, ValueError):
                return None

        # 1. Test Z-weighting (Flat)
        # 1.0 Amplitude Sine -> -3.01 dBFS RMS
        sa_module.weighting = "Z"
        sa_widget.update_plot()

        val_z = get_overall_db()
        assert val_z == pytest.approx(-3.01, abs=0.2)
        assert "dBFS(Z)" in sa_widget.overall_label.text()

        # 2. Test A-weighting
        # A-weighting at 100Hz is approx -19.14 dB
        # So expected: -3.01 - 19.14 = -22.15
        sa_module.weighting = "A"
        sa_widget.update_plot()

        val_a = get_overall_db()
        assert val_a == pytest.approx(-3.01 - 19.14, abs=0.5)
        assert "dBFS(A)" in sa_widget.overall_label.text()

        # 3. Test C-weighting
        # C-weighting at 100Hz is approx -0.3 dB
        # Expected: -3.01 - 0.3 = -3.31
        sa_module.weighting = "C"
        sa_widget.update_plot()

        val_c = get_overall_db()
        assert val_c == pytest.approx(-3.01 - 0.3, abs=0.2)
        assert "dBFS(C)" in sa_widget.overall_label.text()

    def test_spl_offset_application(self, sa_module, sa_widget, mock_engine):
        """Verify SPL offset is applied correctly in dB SPL mode."""

        # Set SPL offset to +94 dB
        mock_engine.calibration.get_spl_offset_db.return_value = 94.0

        # Generate Sine Wave 1kHz, Amplitude 1.0
        # 1kHz is standard reference freq where A/C weighting is 0dB
        fs = 48000
        N = 4096
        t = np.arange(N) / fs
        sig = 1.0 * np.sin(2 * np.pi * 1000 * t)

        sa_module.input_data[:, 0] = sig
        sa_module.input_data[:, 1] = sig
        sa_module.write_head = 0
        sa_module.is_running = True

        # 1. Check dBFS first
        sa_module.display_unit = "dBFS"
        sa_module.weighting = "Z"
        sa_widget.update_plot()

        val_dbfs = float(sa_widget.overall_label.text().split(" ")[1])
        assert val_dbfs == pytest.approx(-3.01, abs=0.2)

        # 2. Switch to dB SPL
        sa_module.display_unit = "dB SPL"
        sa_widget.update_plot()

        val_spl = float(sa_widget.overall_label.text().split(" ")[1])
        # Expected: -3.01 + 94.0 = 90.99
        assert val_spl == pytest.approx(-3.01 + 94.0, abs=0.2)
        assert "dB SPL(Z)" in sa_widget.overall_label.text()

        # 3. Check A-weighting at 1kHz (Should be 0dB diff)
        sa_module.weighting = "A"
        sa_widget.update_plot()
        val_spl_a = float(sa_widget.overall_label.text().split(" ")[1])
        assert val_spl_a == pytest.approx(val_spl, abs=0.2)
        assert "dB SPL(A)" in sa_widget.overall_label.text()

    def test_uncalibrated_spl_falls_back_to_dbfs(self, sa_module, sa_widget, mock_engine):
        """An unavailable SPL offset must never leave dBFS values labelled as dB SPL."""
        mock_engine.calibration.get_spl_offset_db.return_value = None
        sa_module.display_unit = "dB SPL"
        sa_module.is_running = True

        sa_widget.update_plot()

        assert sa_module.display_unit == "dBFS"
        assert sa_widget.unit_combo.findText("dB SPL") == -1
        assert "dBFS" in sa_widget.overall_label.text()
        assert "dB SPL" not in sa_widget.overall_label.text()

    def test_spl_option_appears_after_calibration(self, sa_module, sa_widget, mock_engine):
        """The SPL unit becomes available without recreating the analyzer widget."""
        assert sa_widget.unit_combo.findText("dB SPL") == -1

        mock_engine.calibration.get_spl_offset_db.return_value = 94.0
        sa_widget.update_plot()

        assert sa_widget.unit_combo.findText("dB SPL") >= 0

    def test_apply_min_max_envelope(self, sa_widget):
        """Verify that apply_min_max_envelope correctly downsamples single/dual channel magnitudes."""
        # 1. Single Channel test
        freqs = np.linspace(20, 20000, 1000)
        magnitude_1d = -20 * np.ones_like(freqs)
        x_range_log = [np.log10(20.0), np.log10(20000.0)]
        width_px = 100

        plot_freqs, plot_mags = sa_widget.apply_min_max_envelope(freqs, magnitude_1d, x_range_log, width_px)

        assert len(plot_freqs) > 0
        assert len(plot_freqs) == len(plot_mags)
        assert len(plot_freqs) % 2 == 0  # Even number of points (interleaved min and max)
        assert np.allclose(plot_mags, -20.0)

        # 2. Dual Channel test
        magnitude_2d = -30 * np.ones((len(freqs), 2))
        plot_freqs_2d, plot_mags_2d = sa_widget.apply_min_max_envelope(freqs, magnitude_2d, x_range_log, width_px)

        assert len(plot_freqs_2d) > 0
        assert len(plot_freqs_2d) == len(plot_mags_2d)
        assert plot_mags_2d.ndim == 2
        assert plot_mags_2d.shape[1] == 2
        assert np.allclose(plot_mags_2d, -30.0)
