"""
Explicit imports so PyInstaller can discover dynamically loaded modules.

This file is never imported at runtime, but PyInstaller's static analysis
will detect these imports and include the modules in the bundle.
"""

if False:
    from src.gui.widgets.advanced_distortion_meter import AdvancedDistortionMeter  # noqa: F401
    from src.gui.widgets.bnim_meter import BNIMMeter  # noqa: F401
    from src.gui.widgets.boxcar_averager import BoxcarAverager  # noqa: F401
    from src.gui.widgets.distortion_analyzer import DistortionAnalyzer  # noqa: F401
    from src.gui.widgets.frequency_counter import FrequencyCounter  # noqa: F401
    from src.gui.widgets.goniometer import Goniometer  # noqa: F401
    from src.gui.widgets.hrtf_player import HRTFPlayer  # noqa: F401
    from src.gui.widgets.impedance_analyzer import ImpedanceAnalyzer  # noqa: F401
    from src.gui.widgets.inverse_filter import InverseFilter  # noqa: F401
    from src.gui.widgets.linearity_analyzer import LinearityAnalyzer  # noqa: F401
    from src.gui.widgets.lock_in_amplifier import LockInAmplifier  # noqa: F401
    from src.gui.widgets.lock_in_frequency_counter import LockInFrequencyCounter  # noqa: F401
    from src.gui.widgets.lockin_harmonic_analyzer import LockInHarmonicAnalyzer  # noqa: F401
    from src.gui.widgets.lockin_spectrum_finder import LockInSpectrumFinder  # noqa: F401
    from src.gui.widgets.lockin_thd_analyzer import LockInTHDAnalyzer  # noqa: F401
    from src.gui.widgets.loopback_finder import LoopbackFinder  # noqa: F401
    from src.gui.widgets.lufs_meter import LufsMeter  # noqa: F401
    from src.gui.widgets.network_analyzer import NetworkAnalyzer  # noqa: F401
    from src.gui.widgets.noise_profiler import NoiseProfiler  # noqa: F401
    from src.gui.widgets.one_pps_monitor import OnePPSMonitor  # noqa: F401
    from src.gui.widgets.oscilloscope import Oscilloscope  # noqa: F401
    from src.gui.widgets.processor_benchmark import ProcessorBenchmark  # noqa: F401
    from src.gui.widgets.raw_time_series import RawTimeSeries  # noqa: F401
    from src.gui.widgets.recorder_player import RecorderPlayer  # noqa: F401
    from src.gui.widgets.settings import SettingsWidget  # noqa: F401
    from src.gui.widgets.signal_generator import SignalGenerator  # noqa: F401
    from src.gui.widgets.sound_level_meter import SoundLevelMeter  # noqa: F401
    from src.gui.widgets.sound_quality_analyzer import SoundQualityAnalyzer  # noqa: F401
    from src.gui.widgets.spectrogram import Spectrogram  # noqa: F401
    from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer  # noqa: F401
    from src.gui.widgets.stereo_alignment_monitor import StereoAlignmentMonitor  # noqa: F401
    from src.gui.widgets.timecode_monitor import TimecodeMonitor  # noqa: F401
    from src.gui.widgets.transient_analyzer import TransientAnalyzer  # noqa: F401
    from src.gui.widgets.ultrasound_modulator import UltrasoundModulator  # noqa: F401
    from src.gui.widgets.waveform_loop_player import WaveformLoopPlayer  # noqa: F401
    from src.gui.widgets.welcome import WelcomeWidget  # noqa: F401
