"""Lazy-loaded module registrations and their widget capability declarations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.core import module_constants as module_keys


class CapabilityStatus(Enum):
    """Implementation status used by the widget capability matrix."""

    SUPPORTED = "supported"
    EXCLUDED_A = "outside_a"
    EXCLUDED_B = "outside_b"
    EXCLUDED_C = "outside_c"
    EXCLUDED_D = "outside_d"
    EXCLUDED_E = "outside_e"
    EXCLUDED_F = "outside_f"

    @property
    def is_supported(self) -> bool:
        return self is CapabilityStatus.SUPPORTED

    @property
    def matrix_label(self) -> str:
        if self.is_supported:
            return "個✓"
        return {
            CapabilityStatus.EXCLUDED_A: "外A",
            CapabilityStatus.EXCLUDED_B: "外B",
            CapabilityStatus.EXCLUDED_C: "外C",
            CapabilityStatus.EXCLUDED_D: "外D",
            CapabilityStatus.EXCLUDED_E: "外E",
            CapabilityStatus.EXCLUDED_F: "外F",
        }[self]


@dataclass(frozen=True)
class WidgetCapabilities:
    """Expected optional UI capabilities for one registered widget."""

    split: CapabilityStatus
    compact: CapabilityStatus
    compare: CapabilityStatus


@dataclass(frozen=True)
class ModuleSpec:
    """A lazily imported measurement module and the widget it creates."""

    module_path: str
    module_class_name: str
    widget_class_name: str
    capabilities: WidgetCapabilities
    note: str = ""


S = CapabilityStatus.SUPPORTED
A = CapabilityStatus.EXCLUDED_A
B = CapabilityStatus.EXCLUDED_B
C = CapabilityStatus.EXCLUDED_C
D = CapabilityStatus.EXCLUDED_D
E = CapabilityStatus.EXCLUDED_E
F = CapabilityStatus.EXCLUDED_F


def _spec(
    module_path: str,
    module_class_name: str,
    widget_class_name: str,
    split: CapabilityStatus,
    compact: CapabilityStatus,
    compare: CapabilityStatus,
    note: str = "",
) -> ModuleSpec:
    return ModuleSpec(
        module_path=module_path,
        module_class_name=module_class_name,
        widget_class_name=widget_class_name,
        capabilities=WidgetCapabilities(split=split, compact=compact, compare=compare),
        note=note,
    )


# Keep this mapping in the same order as ALL_MODULE_KEYS. Besides driving lazy
# imports, this is the source of truth for optional wrapper capabilities and the
# generated implementation matrix.
MODULE_REGISTRY: dict[str, ModuleSpec] = {
    module_keys.MODULE_SIGNAL_GENERATOR: _spec(
        "src.gui.widgets.signal_generator", "SignalGenerator", "SignalGeneratorWidget", A, A, A,
        "独立表示部のない信号生成・出力操作画面",
    ),
    module_keys.MODULE_SPECTRUM_ANALYZER: _spec(
        "src.gui.widgets.spectrum_analyzer", "SpectrumAnalyzer", "SpectrumAnalyzerWidget", S, S, S,
        "個別機能 3 種すべてに対応",
    ),
    module_keys.MODULE_SOUND_LEVEL_METER: _spec(
        "src.gui.widgets.sound_level_meter", "SoundLevelMeter", "SoundLevelMeterWidget", S, S, D
    ),
    module_keys.MODULE_LUFS_METER: _spec(
        "src.gui.widgets.lufs_meter", "LufsMeter", "LufsMeterWidget", S, S, D
    ),
    module_keys.MODULE_LOOPBACK_FINDER: _spec(
        "src.gui.widgets.loopback_finder", "LoopbackFinder", "LoopbackFinderWidget", F, E, B,
        "比較対象は接続マトリクス表。結果表の表示専用化はレビューによりひとまず対象外",
    ),
    module_keys.MODULE_DISTORTION_ANALYZER: _spec(
        "src.gui.widgets.distortion_analyzer", "DistortionAnalyzer", "DistortionAnalyzerWidget", F, E, S
    ),
    module_keys.MODULE_ADVANCED_DISTORTION_METER: _spec(
        "src.gui.widgets.advanced_distortion_meter",
        "AdvancedDistortionMeter",
        "AdvancedDistortionMeterWidget",
        F,
        E,
        D,
    ),
    module_keys.MODULE_NETWORK_ANALYZER: _spec(
        "src.gui.widgets.network_analyzer", "NetworkAnalyzer", "NetworkAnalyzerWidget", F, E, S
    ),
    module_keys.MODULE_OSCILLOSCOPE: _spec(
        "src.gui.widgets.oscilloscope", "Oscilloscope", "OscilloscopeWidget", S, S, S,
        "個別機能 3 種すべてに対応",
    ),
    module_keys.MODULE_RAW_TIME_SERIES: _spec(
        "src.gui.widgets.raw_time_series", "RawTimeSeries", "RawTimeSeriesWidget", S, S, D
    ),
    module_keys.MODULE_EVENT_DETECTOR: _spec(
        "src.gui.widgets.event_detector", "EventDetector", "EventDetectorWidget", S, S, D
    ),
    module_keys.MODULE_LOCK_IN_AMPLIFIER: _spec(
        "src.gui.widgets.lock_in_amplifier", "LockInAmplifier", "LockInAmplifierWidget", F, E, S
    ),
    module_keys.MODULE_LOCK_IN_HARMONIC_ANALYZER: _spec(
        "src.gui.widgets.lockin_harmonic_analyzer",
        "LockInHarmonicAnalyzer",
        "LockInHarmonicWidget",
        F,
        E,
        D,
    ),
    module_keys.MODULE_ARBITRARY_HARMONIC_GENERATOR: _spec(
        "src.gui.widgets.arbitrary_harmonic_generator",
        "ArbitraryHarmonicGenerator",
        "ArbitraryHarmonicWidget",
        F,
        E,
        D,
        "生成プレビューの比較価値はレビューによりひとまず対象外",
    ),
    module_keys.MODULE_LOCKIN_SPECTRUM_FINDER: _spec(
        "src.gui.widgets.lockin_spectrum_finder", "LockInSpectrumFinder", "LockInSpectrumFinderWidget", S, E, D
    ),
    module_keys.MODULE_FREQUENCY_COUNTER: _spec(
        "src.gui.widgets.frequency_counter", "FrequencyCounter", "FrequencyCounterWidget", F, S, D
    ),
    module_keys.MODULE_LOCK_IN_FREQUENCY_COUNTER: _spec(
        "src.gui.widgets.lock_in_frequency_counter",
        "LockInFrequencyCounter",
        "LockInFrequencyCounterWidget",
        F,
        E,
        D,
    ),
    module_keys.MODULE_SPECTROGRAM: _spec(
        "src.gui.widgets.spectrogram", "Spectrogram", "SpectrogramWidget", S, S, B,
        "比較対象は時間×周波数の 2D 画像",
    ),
    module_keys.MODULE_BOXCAR_AVERAGER: _spec(
        "src.gui.widgets.boxcar_averager", "BoxcarAverager", "BoxcarAveragerWidget", F, E, D
    ),
    module_keys.MODULE_GONIOMETER: _spec(
        "src.gui.widgets.goniometer", "Goniometer", "GoniometerWidget", S, S, D
    ),
    module_keys.MODULE_IMPEDANCE_ANALYZER: _spec(
        "src.gui.widgets.impedance_analyzer", "ImpedanceAnalyzer", "ImpedanceAnalyzerWidget", F, E, D
    ),
    module_keys.MODULE_NOISE_PROFILER: _spec(
        "src.gui.widgets.noise_profiler", "NoiseProfiler", "NoiseProfilerWidget", S, S, D
    ),
    module_keys.MODULE_RECORDER_PLAYER: _spec(
        "src.gui.widgets.recorder_player", "RecorderPlayer", "RecorderPlayerWidget", A, A, A,
        "独立表示部のない録音・再生操作画面",
    ),
    module_keys.MODULE_WAVEFORM_LOOP_PLAYER: _spec(
        "src.gui.widgets.waveform_loop_player", "WaveformLoopPlayer", "WaveformLoopPlayerWidget", F, E, D,
        "波形は選択・再生操作にも使うため、分離はレビューによりひとまず対象外",
    ),
    module_keys.MODULE_TRANSIENT_ANALYZER: _spec(
        "src.gui.widgets.transient_analyzer", "TransientAnalyzer", "TransientAnalyzerWidget", F, E, D
    ),
    module_keys.MODULE_SOUND_QUALITY_ANALYZER: _spec(
        "src.gui.widgets.sound_quality_analyzer", "SoundQualityAnalyzer", "SoundQualityAnalyzerWidget", F, E, D
    ),
    module_keys.MODULE_TIMECODE_MONITOR: _spec(
        "src.gui.widgets.timecode_monitor", "TimecodeMonitor", "TimecodeMonitorWidget", F, S, B,
        "比較対象は時刻・同期状態の数値表示",
    ),
    module_keys.MODULE_BNIM_METER: _spec(
        "src.gui.widgets.bnim_meter", "BNIMMeter", "BNIMMeterWidget", S, S, D
    ),
    module_keys.MODULE_HRTF_PLAYER: _spec(
        "src.gui.widgets.hrtf_player", "HRTFPlayer", "HRTFPlayerWidget", F, E, B,
        "比較対象は方向×指標の 2D ヒートマップ",
    ),
    module_keys.MODULE_ULTRASOUND_MODULATOR: _spec(
        "src.gui.widgets.ultrasound_modulator", "UltrasoundModulator", "UltrasoundModulatorWidget", A, A, A,
        "独立表示部のない変調・出力操作画面",
    ),
    module_keys.MODULE_LINEARITY_ANALYZER: _spec(
        "src.gui.widgets.linearity_analyzer", "LinearityAnalyzer", "LinearityAnalyzerWidget", F, E, D
    ),
    module_keys.MODULE_1PPS_MONITOR: _spec(
        "src.gui.widgets.one_pps_monitor", "OnePPSMonitor", "OnePPSMonitorWidget", F, E, D
    ),
    module_keys.MODULE_STEREO_ALIGNMENT_MONITOR: _spec(
        "src.gui.widgets.stereo_alignment_monitor",
        "StereoAlignmentMonitor",
        "StereoAlignmentMonitorWidget",
        F,
        S,
        D,
    ),
    module_keys.MODULE_SPATIAL_BINAURAL_MIXER: _spec(
        "src.gui.widgets.spatial_binaural_mixer",
        "SpatialBinauralMixer",
        "SpatialBinauralMixerWidget",
        A,
        A,
        A,
        "独立表示部のないオフライン・レンダリング操作画面",
    ),
    module_keys.MODULE_PROCESSOR_BENCHMARK: _spec(
        "src.gui.widgets.processor_benchmark", "ProcessorBenchmark", "ProcessorBenchmarkWidget", F, E, D
    ),
    module_keys.MODULE_PLOT_COMPARER: _spec(
        "src.gui.widgets.plot_comparer", "PlotComparer", "PlotComparerWidget", F, E, C,
        "比較データの受信・表示側",
    ),
    module_keys.MODULE_TRANSMISSION_ANALYZER: _spec(
        "src.gui.widgets.transmission_analyzer",
        "TransmissionAnalyzer",
        "TransmissionAnalyzerWidget",
        F,
        S,
        D,
    ),
    module_keys.MODULE_NONLINEAR_ANALYZER: _spec(
        "src.gui.widgets.nonlinear_analyzer", "NonlinearAnalyzer", "NonlinearAnalyzerWidget", F, E, D
    ),
    module_keys.MODULE_LOCKIN_MODELER: _spec(
        "src.gui.widgets.lock_in_modeler", "LockInModeler", "LockInModelerWidget", F, E, D
    ),
    module_keys.MODULE_RESPONSE_VIEWER: _spec(
        "src.gui.widgets.response_viewer", "ResponseViewer", "ResponseViewerWidget", F, E, D
    ),
    module_keys.MODULE_FEEDFORWARD_COMPENSATOR: _spec(
        "src.gui.widgets.feedforward_compensator",
        "FeedforwardCompensator",
        "FeedforwardCompensatorWidget",
        F,
        E,
        D,
    ),
    module_keys.MODULE_NONLINEAR_RESPONSE_ANALYZER: _spec(
        "src.gui.widgets.nonlinear_response_analyzer",
        "NonlinearResponseAnalyzer",
        "NonlinearResponseAnalyzerWidget",
        F,
        E,
        D,
        "実験的モジュール",
    ),
}


def get_module_spec(module_key: str) -> ModuleSpec:
    try:
        return MODULE_REGISTRY[module_key]
    except KeyError as exc:
        raise KeyError(f"Unknown module key: {module_key}") from exc
