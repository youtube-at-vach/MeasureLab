"""Module loading metadata and widget feature declarations.

This module intentionally avoids importing PyQt or widget implementations so it
can act as the lightweight source of truth for both runtime loading and tests.
"""

from dataclasses import dataclass
from enum import StrEnum

from src.core.module_constants import (
    MODULE_1PPS_MONITOR,
    MODULE_ADVANCED_DISTORTION_METER,
    MODULE_ARBITRARY_HARMONIC_GENERATOR,
    MODULE_BNIM_METER,
    MODULE_BOXCAR_AVERAGER,
    MODULE_DISTORTION_ANALYZER,
    MODULE_EVENT_DETECTOR,
    MODULE_FEEDFORWARD_COMPENSATOR,
    MODULE_FREQUENCY_COUNTER,
    MODULE_GONIOMETER,
    MODULE_HRTF_PLAYER,
    MODULE_IMPEDANCE_ANALYZER,
    MODULE_LINEARITY_ANALYZER,
    MODULE_LOCK_IN_AMPLIFIER,
    MODULE_LOCK_IN_FREQUENCY_COUNTER,
    MODULE_LOCK_IN_HARMONIC_ANALYZER,
    MODULE_LOCKIN_MODELER,
    MODULE_LOCKIN_SPECTRUM_FINDER,
    MODULE_LOOPBACK_FINDER,
    MODULE_LUFS_METER,
    MODULE_NETWORK_ANALYZER,
    MODULE_NOISE_PROFILER,
    MODULE_NONLINEAR_ANALYZER,
    MODULE_NONLINEAR_RESPONSE_ANALYZER,
    MODULE_OSCILLOSCOPE,
    MODULE_PLOT_COMPARER,
    MODULE_PROCESSOR_BENCHMARK,
    MODULE_RAW_TIME_SERIES,
    MODULE_RECORDER_PLAYER,
    MODULE_RESPONSE_VIEWER,
    MODULE_SIGNAL_GENERATOR,
    MODULE_SOUND_LEVEL_METER,
    MODULE_SOUND_QUALITY_ANALYZER,
    MODULE_SPATIAL_BINAURAL_MIXER,
    MODULE_SPECTROGRAM,
    MODULE_SPECTRUM_ANALYZER,
    MODULE_STEREO_ALIGNMENT_MONITOR,
    MODULE_TIMECODE_MONITOR,
    MODULE_TRANSIENT_ANALYZER,
    MODULE_TRANSMISSION_ANALYZER,
    MODULE_ULTRASOUND_MODULATOR,
    MODULE_WAVEFORM_LOOP_PLAYER,
)


class CapabilityStatus(StrEnum):
    """Whether a widget feature is part of the module's supported contract."""

    SUPPORTED = "supported"
    EXCLUDED = "excluded"


class CapabilityExclusionReason(StrEnum):
    """Reviewed reasons why a widget feature is intentionally unavailable."""

    NO_INDEPENDENT_DISPLAY = "no_independent_display"  # Matrix: 外A
    NON_TRACE_COMPARISON = "non_trace_comparison"  # Matrix: 外B
    COMPARISON_RECEIVER = "comparison_receiver"  # Matrix: 外C
    COMPARISON_DEFERRED = "comparison_deferred"  # Matrix: 外D
    COMPACT_DEFERRED = "compact_deferred"  # Matrix: 外E
    SPLIT_DEFERRED = "split_deferred"  # Matrix: 外F


@dataclass(frozen=True, slots=True)
class FeatureCapability:
    """One explicit supported/excluded decision for a widget feature."""

    status: CapabilityStatus
    exclusion_reason: CapabilityExclusionReason | None = None

    def __post_init__(self) -> None:
        if self.status is CapabilityStatus.SUPPORTED and self.exclusion_reason is not None:
            raise ValueError("Supported capabilities cannot have an exclusion reason")
        if self.status is CapabilityStatus.EXCLUDED and self.exclusion_reason is None:
            raise ValueError("Excluded capabilities must have an exclusion reason")

    @property
    def is_supported(self) -> bool:
        return self.status is CapabilityStatus.SUPPORTED


SUPPORTED = FeatureCapability(CapabilityStatus.SUPPORTED)
NO_INDEPENDENT_DISPLAY = FeatureCapability(
    CapabilityStatus.EXCLUDED,
    CapabilityExclusionReason.NO_INDEPENDENT_DISPLAY,
)
NON_TRACE_COMPARISON = FeatureCapability(
    CapabilityStatus.EXCLUDED,
    CapabilityExclusionReason.NON_TRACE_COMPARISON,
)
COMPARISON_RECEIVER = FeatureCapability(
    CapabilityStatus.EXCLUDED,
    CapabilityExclusionReason.COMPARISON_RECEIVER,
)
COMPARISON_DEFERRED = FeatureCapability(
    CapabilityStatus.EXCLUDED,
    CapabilityExclusionReason.COMPARISON_DEFERRED,
)
COMPACT_DEFERRED = FeatureCapability(
    CapabilityStatus.EXCLUDED,
    CapabilityExclusionReason.COMPACT_DEFERRED,
)
SPLIT_DEFERRED = FeatureCapability(
    CapabilityStatus.EXCLUDED,
    CapabilityExclusionReason.SPLIT_DEFERRED,
)


@dataclass(frozen=True, slots=True)
class WidgetCapabilities:
    """Authoritative feature contract for one registered module widget."""

    split_window: FeatureCapability
    compact_mode: FeatureCapability
    comparison: FeatureCapability

    def __post_init__(self) -> None:
        allowed_reasons = {
            "split_window": {
                CapabilityExclusionReason.NO_INDEPENDENT_DISPLAY,
                CapabilityExclusionReason.SPLIT_DEFERRED,
            },
            "compact_mode": {
                CapabilityExclusionReason.NO_INDEPENDENT_DISPLAY,
                CapabilityExclusionReason.COMPACT_DEFERRED,
            },
            "comparison": {
                CapabilityExclusionReason.NO_INDEPENDENT_DISPLAY,
                CapabilityExclusionReason.NON_TRACE_COMPARISON,
                CapabilityExclusionReason.COMPARISON_RECEIVER,
                CapabilityExclusionReason.COMPARISON_DEFERRED,
            },
        }
        for feature_name, allowed in allowed_reasons.items():
            capability = getattr(self, feature_name)
            reason = capability.exclusion_reason
            if reason is not None and reason not in allowed:
                raise ValueError(f"{reason.value!r} is not a valid exclusion reason for {feature_name}")


@dataclass(frozen=True, slots=True)
class ModuleRegistration:
    """Lazy-loading metadata plus the widget contract for one module."""

    module_path: str
    class_name: str
    capabilities: WidgetCapabilities


def _caps(
    *,
    split: FeatureCapability,
    compact: FeatureCapability,
    comparison: FeatureCapability,
) -> WidgetCapabilities:
    return WidgetCapabilities(split_window=split, compact_mode=compact, comparison=comparison)


def _registration(
    module_path: str,
    class_name: str,
    *,
    split: FeatureCapability,
    compact: FeatureCapability,
    comparison: FeatureCapability,
) -> ModuleRegistration:
    return ModuleRegistration(module_path, class_name, _caps(split=split, compact=compact, comparison=comparison))


MODULE_REGISTRY: dict[str, ModuleRegistration] = {
    MODULE_SIGNAL_GENERATOR: _registration(
        "src.gui.widgets.signal_generator",
        "SignalGenerator",
        split=NO_INDEPENDENT_DISPLAY,
        compact=NO_INDEPENDENT_DISPLAY,
        comparison=NO_INDEPENDENT_DISPLAY,
    ),
    MODULE_SPECTRUM_ANALYZER: _registration(
        "src.gui.widgets.spectrum_analyzer",
        "SpectrumAnalyzer",
        split=SUPPORTED,
        compact=SUPPORTED,
        comparison=SUPPORTED,
    ),
    MODULE_SOUND_LEVEL_METER: _registration(
        "src.gui.widgets.sound_level_meter",
        "SoundLevelMeter",
        split=SUPPORTED,
        compact=SUPPORTED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_LUFS_METER: _registration(
        "src.gui.widgets.lufs_meter",
        "LufsMeter",
        split=SUPPORTED,
        compact=SUPPORTED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_LOOPBACK_FINDER: _registration(
        "src.gui.widgets.loopback_finder",
        "LoopbackFinder",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=NON_TRACE_COMPARISON,
    ),
    MODULE_DISTORTION_ANALYZER: _registration(
        "src.gui.widgets.distortion_analyzer",
        "DistortionAnalyzer",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=SUPPORTED,
    ),
    MODULE_ADVANCED_DISTORTION_METER: _registration(
        "src.gui.widgets.advanced_distortion_meter",
        "AdvancedDistortionMeter",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_NETWORK_ANALYZER: _registration(
        "src.gui.widgets.network_analyzer",
        "NetworkAnalyzer",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=SUPPORTED,
    ),
    MODULE_OSCILLOSCOPE: _registration(
        "src.gui.widgets.oscilloscope",
        "Oscilloscope",
        split=SUPPORTED,
        compact=SUPPORTED,
        comparison=SUPPORTED,
    ),
    MODULE_RAW_TIME_SERIES: _registration(
        "src.gui.widgets.raw_time_series",
        "RawTimeSeries",
        split=SUPPORTED,
        compact=SUPPORTED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_EVENT_DETECTOR: _registration(
        "src.gui.widgets.event_detector",
        "EventDetector",
        split=SUPPORTED,
        compact=SUPPORTED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_LOCK_IN_AMPLIFIER: _registration(
        "src.gui.widgets.lock_in_amplifier",
        "LockInAmplifier",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=SUPPORTED,
    ),
    MODULE_LOCK_IN_HARMONIC_ANALYZER: _registration(
        "src.gui.widgets.lockin_harmonic_analyzer",
        "LockInHarmonicAnalyzer",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_ARBITRARY_HARMONIC_GENERATOR: _registration(
        "src.gui.widgets.arbitrary_harmonic_generator",
        "ArbitraryHarmonicGenerator",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_LOCKIN_SPECTRUM_FINDER: _registration(
        "src.gui.widgets.lockin_spectrum_finder",
        "LockInSpectrumFinder",
        split=SUPPORTED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_FREQUENCY_COUNTER: _registration(
        "src.gui.widgets.frequency_counter",
        "FrequencyCounter",
        split=SPLIT_DEFERRED,
        compact=SUPPORTED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_LOCK_IN_FREQUENCY_COUNTER: _registration(
        "src.gui.widgets.lock_in_frequency_counter",
        "LockInFrequencyCounter",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_SPECTROGRAM: _registration(
        "src.gui.widgets.spectrogram",
        "Spectrogram",
        split=SUPPORTED,
        compact=SUPPORTED,
        comparison=NON_TRACE_COMPARISON,
    ),
    MODULE_BOXCAR_AVERAGER: _registration(
        "src.gui.widgets.boxcar_averager",
        "BoxcarAverager",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_GONIOMETER: _registration(
        "src.gui.widgets.goniometer",
        "Goniometer",
        split=SUPPORTED,
        compact=SUPPORTED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_IMPEDANCE_ANALYZER: _registration(
        "src.gui.widgets.impedance_analyzer",
        "ImpedanceAnalyzer",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_NOISE_PROFILER: _registration(
        "src.gui.widgets.noise_profiler",
        "NoiseProfiler",
        split=SUPPORTED,
        compact=SUPPORTED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_RECORDER_PLAYER: _registration(
        "src.gui.widgets.recorder_player",
        "RecorderPlayer",
        split=NO_INDEPENDENT_DISPLAY,
        compact=NO_INDEPENDENT_DISPLAY,
        comparison=NO_INDEPENDENT_DISPLAY,
    ),
    MODULE_WAVEFORM_LOOP_PLAYER: _registration(
        "src.gui.widgets.waveform_loop_player",
        "WaveformLoopPlayer",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_TRANSIENT_ANALYZER: _registration(
        "src.gui.widgets.transient_analyzer",
        "TransientAnalyzer",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_SOUND_QUALITY_ANALYZER: _registration(
        "src.gui.widgets.sound_quality_analyzer",
        "SoundQualityAnalyzer",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_TIMECODE_MONITOR: _registration(
        "src.gui.widgets.timecode_monitor",
        "TimecodeMonitor",
        split=SPLIT_DEFERRED,
        compact=SUPPORTED,
        comparison=NON_TRACE_COMPARISON,
    ),
    MODULE_BNIM_METER: _registration(
        "src.gui.widgets.bnim_meter",
        "BNIMMeter",
        split=SUPPORTED,
        compact=SUPPORTED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_HRTF_PLAYER: _registration(
        "src.gui.widgets.hrtf_player",
        "HRTFPlayer",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=NON_TRACE_COMPARISON,
    ),
    MODULE_ULTRASOUND_MODULATOR: _registration(
        "src.gui.widgets.ultrasound_modulator",
        "UltrasoundModulator",
        split=NO_INDEPENDENT_DISPLAY,
        compact=NO_INDEPENDENT_DISPLAY,
        comparison=NO_INDEPENDENT_DISPLAY,
    ),
    MODULE_LINEARITY_ANALYZER: _registration(
        "src.gui.widgets.linearity_analyzer",
        "LinearityAnalyzer",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_1PPS_MONITOR: _registration(
        "src.gui.widgets.one_pps_monitor",
        "OnePPSMonitor",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_STEREO_ALIGNMENT_MONITOR: _registration(
        "src.gui.widgets.stereo_alignment_monitor",
        "StereoAlignmentMonitor",
        split=SPLIT_DEFERRED,
        compact=SUPPORTED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_SPATIAL_BINAURAL_MIXER: _registration(
        "src.gui.widgets.spatial_binaural_mixer",
        "SpatialBinauralMixer",
        split=NO_INDEPENDENT_DISPLAY,
        compact=NO_INDEPENDENT_DISPLAY,
        comparison=NO_INDEPENDENT_DISPLAY,
    ),
    MODULE_PROCESSOR_BENCHMARK: _registration(
        "src.gui.widgets.processor_benchmark",
        "ProcessorBenchmark",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_PLOT_COMPARER: _registration(
        "src.gui.widgets.plot_comparer",
        "PlotComparer",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_RECEIVER,
    ),
    MODULE_TRANSMISSION_ANALYZER: _registration(
        "src.gui.widgets.transmission_analyzer",
        "TransmissionAnalyzer",
        split=SPLIT_DEFERRED,
        compact=SUPPORTED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_NONLINEAR_ANALYZER: _registration(
        "src.gui.widgets.nonlinear_analyzer",
        "NonlinearAnalyzer",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_LOCKIN_MODELER: _registration(
        "src.gui.widgets.lock_in_modeler",
        "LockInModeler",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_RESPONSE_VIEWER: _registration(
        "src.gui.widgets.response_viewer",
        "ResponseViewer",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_FEEDFORWARD_COMPENSATOR: _registration(
        "src.gui.widgets.feedforward_compensator",
        "FeedforwardCompensator",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
    MODULE_NONLINEAR_RESPONSE_ANALYZER: _registration(
        "src.gui.widgets.nonlinear_response_analyzer",
        "NonlinearResponseAnalyzer",
        split=SPLIT_DEFERRED,
        compact=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    ),
}
