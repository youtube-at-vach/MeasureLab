import sys
import time
from unittest.mock import MagicMock

# Mock dependencies of main_window
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtWidgets"] = MagicMock()
sys.modules["src.core.audio_engine"] = MagicMock()
sys.modules["src.core.config_manager"] = MagicMock()
sys.modules["src.core.localization"] = MagicMock()
sys.modules["src.gui.widgets.detachable_wrapper"] = MagicMock()

# Mock the modules that _load_module_class imports.
# I need to mock the module and ensure the class attribute exists on it.
module_map = {
    "src.gui.widgets.signal_generator": "SignalGenerator",
    "src.gui.widgets.spectrum_analyzer": "SpectrumAnalyzer",
    "src.gui.widgets.sound_level_meter": "SoundLevelMeter",
    "src.gui.widgets.lufs_meter": "LufsMeter",
    "src.gui.widgets.loopback_finder": "LoopbackFinder",
    "src.gui.widgets.distortion_analyzer": "DistortionAnalyzer",
    "src.gui.widgets.advanced_distortion_meter": "AdvancedDistortionMeter",
    "src.gui.widgets.network_analyzer": "NetworkAnalyzer",
    "src.gui.widgets.oscilloscope": "Oscilloscope",
    "src.gui.widgets.raw_time_series": "RawTimeSeries",
    "src.gui.widgets.lock_in_amplifier": "LockInAmplifier",
    "src.gui.widgets.lockin_thd_analyzer": "LockInTHDAnalyzer",
    "src.gui.widgets.frequency_counter": "FrequencyCounter",
    "src.gui.widgets.lock_in_frequency_counter": "LockInFrequencyCounter",
    "src.gui.widgets.spectrogram": "Spectrogram",
    "src.gui.widgets.boxcar_averager": "BoxcarAverager",
    "src.gui.widgets.goniometer": "Goniometer",
    "src.gui.widgets.impedance_analyzer": "ImpedanceAnalyzer",
    "src.gui.widgets.noise_profiler": "NoiseProfiler",
    "src.gui.widgets.recorder_player": "RecorderPlayer",
    "src.gui.widgets.inverse_filter": "InverseFilter",
    "src.gui.widgets.transient_analyzer": "TransientAnalyzer",
    "src.gui.widgets.sound_quality_analyzer": "SoundQualityAnalyzer",
    "src.gui.widgets.timecode_monitor": "TimecodeMonitor",
    "src.gui.widgets.bnim_meter": "BNIMMeter",
    "src.gui.widgets.hrtf_player": "HRTFPlayer",
    "src.gui.widgets.ultrasound_modulator": "UltrasoundModulator",
    "src.gui.widgets.linearity_analyzer": "LinearityAnalyzer",
}

for mod_name, cls_name in module_map.items():
    mock_mod = MagicMock()
    setattr(mock_mod, cls_name, MagicMock())
    sys.modules[mod_name] = mock_mod

# Now import the function to test
try:
    from src.gui.main_window import _load_module_class
except ImportError as e:
    print(f"Failed to import _load_module_class: {e}")
    sys.exit(1)

keys = [
    "Signal Generator",
    "Spectrum Analyzer",
    "Sound Level Meter",
    "LUFS Meter",
    "Loopback Finder",
    "Distortion Analyzer",
    "Advanced Distortion Meter",
    "Network Analyzer",
    "Oscilloscope",
    "Raw Time Series",
    "Lock-in Amplifier",
    "Lock-in THD Analyzer",
    "Frequency Counter",
    "Lock-in Frequency Counter",
    "Spectrogram",
    "Boxcar Averager",
    "Goniometer",
    "Impedance Analyzer",
    "Noise Profiler",
    "Recorder / Player",
    "Inverse Filter",
    "Transient Analyzer",
    "Sound Quality Analyzer",
    "Timecode Monitor & Generator",
    "BNIM Meter",
    "HRTF Player",
    "Ultrasound AM Modulator",
    "Linearity Analyzer",
]

def run_benchmark():
    # Warm up
    for key in keys:
        _load_module_class(key)

    start_time = time.perf_counter()
    iterations = 10000
    for _ in range(iterations):
        for key in keys:
            _load_module_class(key)
    end_time = time.perf_counter()

    total_calls = iterations * len(keys)
    duration = end_time - start_time
    print(f"Total time for {total_calls} calls: {duration:.4f} seconds")
    print(f"Average time per call: {duration/total_calls*1e6:.4f} microseconds")

if __name__ == "__main__":
    run_benchmark()
