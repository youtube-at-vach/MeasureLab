"""Module loader with registry for dynamic dispatch."""

import importlib
from typing import Type

from src.core.module_constants import (
    MODULE_1PPS_MONITOR,
    MODULE_ADVANCED_DISTORTION_METER,
    MODULE_BNIM_METER,
    MODULE_BOXCAR_AVERAGER,
    MODULE_DISTORTION_ANALYZER,
    MODULE_FREQUENCY_COUNTER,
    MODULE_GONIOMETER,
    MODULE_HRTF_PLAYER,
    MODULE_IMPEDANCE_ANALYZER,
    MODULE_INVERSE_FILTER,
    MODULE_LINEARITY_ANALYZER,
    MODULE_LOCK_IN_AMPLIFIER,
    MODULE_LOCK_IN_FREQUENCY_COUNTER,
    MODULE_LOCK_IN_THD_ANALYZER,
    MODULE_LOOPBACK_FINDER,
    MODULE_LUFS_METER,
    MODULE_NETWORK_ANALYZER,
    MODULE_NOISE_PROFILER,
    MODULE_OSCILLOSCOPE,
    MODULE_RAW_TIME_SERIES,
    MODULE_RECORDER_PLAYER,
    MODULE_SIGNAL_GENERATOR,
    MODULE_SOUND_LEVEL_METER,
    MODULE_SOUND_QUALITY_ANALYZER,
    MODULE_SPECTROGRAM,
    MODULE_SPECTRUM_ANALYZER,
    MODULE_TIMECODE_MONITOR,
    MODULE_TRANSIENT_ANALYZER,
    MODULE_ULTRASOUND_MODULATOR,
)

MODULE_REGISTRY = {
    MODULE_SIGNAL_GENERATOR: ("src.gui.widgets.signal_generator", "SignalGenerator"),
    MODULE_SPECTRUM_ANALYZER: ("src.gui.widgets.spectrum_analyzer", "SpectrumAnalyzer"),
    MODULE_SOUND_LEVEL_METER: ("src.gui.widgets.sound_level_meter", "SoundLevelMeter"),
    MODULE_LUFS_METER: ("src.gui.widgets.lufs_meter", "LufsMeter"),
    MODULE_LOOPBACK_FINDER: ("src.gui.widgets.loopback_finder", "LoopbackFinder"),
    MODULE_DISTORTION_ANALYZER: ("src.gui.widgets.distortion_analyzer", "DistortionAnalyzer"),
    MODULE_ADVANCED_DISTORTION_METER: ("src.gui.widgets.advanced_distortion_meter", "AdvancedDistortionMeter"),
    MODULE_NETWORK_ANALYZER: ("src.gui.widgets.network_analyzer", "NetworkAnalyzer"),
    MODULE_OSCILLOSCOPE: ("src.gui.widgets.oscilloscope", "Oscilloscope"),
    MODULE_RAW_TIME_SERIES: ("src.gui.widgets.raw_time_series", "RawTimeSeries"),
    MODULE_LOCK_IN_AMPLIFIER: ("src.gui.widgets.lock_in_amplifier", "LockInAmplifier"),
    MODULE_LOCK_IN_THD_ANALYZER: ("src.gui.widgets.lockin_thd_analyzer", "LockInTHDAnalyzer"),
    MODULE_FREQUENCY_COUNTER: ("src.gui.widgets.frequency_counter", "FrequencyCounter"),
    MODULE_LOCK_IN_FREQUENCY_COUNTER: ("src.gui.widgets.lock_in_frequency_counter", "LockInFrequencyCounter"),
    MODULE_SPECTROGRAM: ("src.gui.widgets.spectrogram", "Spectrogram"),
    MODULE_BOXCAR_AVERAGER: ("src.gui.widgets.boxcar_averager", "BoxcarAverager"),
    MODULE_GONIOMETER: ("src.gui.widgets.goniometer", "Goniometer"),
    MODULE_IMPEDANCE_ANALYZER: ("src.gui.widgets.impedance_analyzer", "ImpedanceAnalyzer"),
    MODULE_NOISE_PROFILER: ("src.gui.widgets.noise_profiler", "NoiseProfiler"),
    MODULE_RECORDER_PLAYER: ("src.gui.widgets.recorder_player", "RecorderPlayer"),
    MODULE_INVERSE_FILTER: ("src.gui.widgets.inverse_filter", "InverseFilter"),
    MODULE_TRANSIENT_ANALYZER: ("src.gui.widgets.transient_analyzer", "TransientAnalyzer"),
    MODULE_SOUND_QUALITY_ANALYZER: ("src.gui.widgets.sound_quality_analyzer", "SoundQualityAnalyzer"),
    MODULE_TIMECODE_MONITOR: ("src.gui.widgets.timecode_monitor", "TimecodeMonitor"),
    MODULE_BNIM_METER: ("src.gui.widgets.bnim_meter", "BNIMMeter"),
    MODULE_HRTF_PLAYER: ("src.gui.widgets.hrtf_player", "HRTFPlayer"),
    MODULE_ULTRASOUND_MODULATOR: ("src.gui.widgets.ultrasound_modulator", "UltrasoundModulator"),
    MODULE_LINEARITY_ANALYZER: ("src.gui.widgets.linearity_analyzer", "LinearityAnalyzer"),
    MODULE_1PPS_MONITOR: ("src.gui.widgets.one_pps_monitor", "OnePPSMonitor"),
}


def load_module_class(module_key: str) -> Type:
    """Return MeasurementModule class by key.

    Uses dynamic import to avoid importing all heavy GUI modules
    at application startup.
    """
    if module_key not in MODULE_REGISTRY:
        raise KeyError(f"Unknown module key: {module_key}")

    module_path, class_name = MODULE_REGISTRY[module_key]
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _pyinstaller_hooks():
    """Explicit imports for PyInstaller discovery.

    This function is never called but helps static analysis tools find dependencies.
    """
    import src.gui.widgets.signal_generator  # noqa: F401
    import src.gui.widgets.spectrum_analyzer  # noqa: F401
    import src.gui.widgets.sound_level_meter  # noqa: F401
    import src.gui.widgets.lufs_meter  # noqa: F401
    import src.gui.widgets.loopback_finder  # noqa: F401
    import src.gui.widgets.distortion_analyzer  # noqa: F401
    import src.gui.widgets.advanced_distortion_meter  # noqa: F401
    import src.gui.widgets.network_analyzer  # noqa: F401
    import src.gui.widgets.oscilloscope  # noqa: F401
    import src.gui.widgets.raw_time_series  # noqa: F401
    import src.gui.widgets.lock_in_amplifier  # noqa: F401
    import src.gui.widgets.lockin_thd_analyzer  # noqa: F401
    import src.gui.widgets.frequency_counter  # noqa: F401
    import src.gui.widgets.lock_in_frequency_counter  # noqa: F401
    import src.gui.widgets.spectrogram  # noqa: F401
    import src.gui.widgets.boxcar_averager  # noqa: F401
    import src.gui.widgets.goniometer  # noqa: F401
    import src.gui.widgets.impedance_analyzer  # noqa: F401
    import src.gui.widgets.noise_profiler  # noqa: F401
    import src.gui.widgets.recorder_player  # noqa: F401
    import src.gui.widgets.inverse_filter  # noqa: F401
    import src.gui.widgets.transient_analyzer  # noqa: F401
    import src.gui.widgets.sound_quality_analyzer  # noqa: F401
    import src.gui.widgets.timecode_monitor  # noqa: F401
    import src.gui.widgets.bnim_meter  # noqa: F401
    import src.gui.widgets.hrtf_player  # noqa: F401
    import src.gui.widgets.ultrasound_modulator  # noqa: F401
    import src.gui.widgets.linearity_analyzer  # noqa: F401
    import src.gui.widgets.one_pps_monitor  # noqa: F401
