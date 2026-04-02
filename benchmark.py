import time
import numpy as np
from src.gui.widgets.lockin_spectrum_finder import LockInSpectrumFinder, CalculationParams
from src.core.audio_engine import AudioEngine
from src.core.config_manager import ConfigManager
import sys

# Mock AudioEngine to avoid sounddevice initialization
class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.callbacks = {}
        self.next_id = 0
        self.calibration = type('MockCal', (), {'get_input_offset_db': lambda self: 0.0, 'get_spl_offset_db': lambda self: 0.0})()

    def register_callback(self, cb):
        return 0

finder = LockInSpectrumFinder(MockAudioEngine())
finder.is_running = True

fs = 48000
sig = np.random.randn(262144)

params_scan = CalculationParams(
    start_f=20.0,
    stop_f=20000.0,
    points=2048,
    spacing="Log",
    display_unit="dBFS",
    offset_dbv=0.0,
    offset_spl=0.0,
    mode="Scan",
    zoom_center=1000.0,
    zoom_span=10.0,
    window_type="hann",
    include_targets=False,
    octave_ref=1000.0,
    targets={}
)

params_zoom = CalculationParams(
    start_f=20.0,
    stop_f=20000.0,
    points=2048,
    spacing="Log",
    display_unit="dBFS",
    offset_dbv=0.0,
    offset_spl=0.0,
    mode="Zoom",
    zoom_center=1000.0,
    zoom_span=10.0,
    window_type="hann",
    include_targets=False,
    octave_ref=1000.0,
    targets={}
)

# Warmup
finder._do_calculation(sig, fs, params_scan)
finder._do_calculation(sig, fs, params_zoom)

# Benchmark Scan
t0 = time.time()
for _ in range(5):
    finder._do_calculation(sig, fs, params_scan)
t_scan = time.time() - t0

# Benchmark Zoom
t0 = time.time()
for _ in range(5):
    finder._do_calculation(sig, fs, params_zoom)
t_zoom = time.time() - t0

print(f"Scan Time: {t_scan:.4f}s")
print(f"Zoom Time: {t_zoom:.4f}s")
