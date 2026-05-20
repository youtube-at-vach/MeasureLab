"""
Explicit imports so PyInstaller can discover dynamically loaded modules.

This file is never imported at runtime, but PyInstaller's static analysis
will detect these imports and include the modules in the bundle.
"""

if False:
    from src.gui.widgets.advanced_distortion_meter import AdvancedDistortionMeter

    from src.gui.widgets.bnim_meter import BNIMMeter
    from src.gui.widgets.boxcar_averager import BoxcarAverager
    from src.gui.widgets.distortion_analyzer import DistortionAnalyzer
    from src.gui.widgets.frequency_counter import FrequencyCounter
    from src.gui.widgets.goniometer import Goniometer
    from src.gui.widgets.hrtf_player import HRTFPlayer
    from src.gui.widgets.impedance_analyzer import ImpedanceAnalyzer
    from src.gui.widgets.inverse_filter import InverseFilter
    from src.gui.widgets.linearity_analyzer import LinearityAnalyzer
    from src.gui.widgets.lock_in_amplifier import LockInAmplifier
    from src.gui.widgets.lock_in_frequency_counter import LockInFrequencyCounter
    from src.gui.widgets.lockin_harmonic_analyzer import LockInHarmonicAnalyzer
    from src.gui.widgets.lockin_spectrum_finder import LockInSpectrumFinder
    from src.gui.widgets.loopback_finder import LoopbackFinder
    from src.gui.widgets.lufs_meter import LufsMeter
    from src.gui.widgets.network_analyzer import NetworkAnalyzer
    from src.gui.widgets.noise_profiler import NoiseProfiler
    from src.gui.widgets.one_pps_monitor import OnePPSMonitor
    from src.gui.widgets.oscilloscope import Oscilloscope
    from src.gui.widgets.processor_benchmark import ProcessorBenchmark
    from src.gui.widgets.raw_time_series import RawTimeSeries
    from src.gui.widgets.recorder_player import RecorderPlayer
    from src.gui.widgets.signal_generator import SignalGenerator
    from src.gui.widgets.sound_level_meter import SoundLevelMeter
    from src.gui.widgets.sound_quality_analyzer import SoundQualityAnalyzer
    from src.gui.widgets.spectrogram import Spectrogram
    from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer
    from src.gui.widgets.stereo_alignment_monitor import StereoAlignmentMonitor
    from src.gui.widgets.timecode_monitor import TimecodeMonitor
    from src.gui.widgets.transient_analyzer import TransientAnalyzer
    from src.gui.widgets.ultrasound_modulator import UltrasoundModulator
    from src.gui.widgets.waveform_loop_player import WaveformLoopPlayer
    from src.gui.widgets.settings import SettingsWidget
    from src.gui.widgets.welcome import WelcomeWidget

    # Use the imports to satisfy linters while keeping them available for PyInstaller
    _imports_for_pyinstaller = [
        AdvancedDistortionMeter,
        BNIMMeter,
        BoxcarAverager,
        DistortionAnalyzer,
        FrequencyCounter,
        Goniometer,
        HRTFPlayer,
        ImpedanceAnalyzer,
        InverseFilter,
        LinearityAnalyzer,
        LockInAmplifier,
        LockInFrequencyCounter,
        LockInHarmonicAnalyzer,
        LockInSpectrumFinder,
        LoopbackFinder,
        LufsMeter,
        NetworkAnalyzer,
        NoiseProfiler,
        OnePPSMonitor,
        Oscilloscope,
        ProcessorBenchmark,
        RawTimeSeries,
        RecorderPlayer,
        SignalGenerator,
        SoundLevelMeter,
        SoundQualityAnalyzer,
        Spectrogram,
        SpectrumAnalyzer,
        StereoAlignmentMonitor,
        TimecodeMonitor,
        TransientAnalyzer,
        UltrasoundModulator,
        WaveformLoopPlayer,
        SettingsWidget,
        WelcomeWidget,
    ]
