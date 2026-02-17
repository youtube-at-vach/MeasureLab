
import sys
import os
import numpy as np
from unittest.mock import MagicMock

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from src.gui.widgets.signal_generator import SignalGenerator

param_copy = None

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.callback = None

    def register_callback(self, cb):
        self.callback = cb
        return 1

    def unregister_callback(self, cid):
        self.callback = None

    @property
    def calibration(self):
        cal = MagicMock()
        cal.output_gain = 1.0
        return cal

def test_lpf_filtering():
    engine = MockAudioEngine()
    sg = SignalGenerator(engine)

    # Configure LPF
    sg.params_L.lpf_enabled = True
    sg.params_L.lpf_freq = 1000.0
    sg.params_L.lpf_order = 4
    sg.params_L.waveform = "noise" # Use noise to see filtering effect easily in spectrum? 
    # Or use Sine at 500Hz (pass) and 2000Hz (fail)

    # 1. Pass band (500 Hz)
    sg.params_L.waveform = "sine"
    sg.params_L.frequency = 500.0
    sg.params_L.amplitude = 1.0

    sg.start_generation()

    # Generate 1 sec
    frames = 48000
    outdata = np.zeros((frames, 2))
    sg.audio_engine.callback(None, outdata, frames, 0.0, None)

    signal_pass = outdata[:, 0]
    rms_pass = np.sqrt(np.mean(signal_pass**2))
    print(f"Pass band RMS: {rms_pass}")

    # 2. Stop band (5000 Hz)
    sg.stop_generation()
    sg.params_L.frequency = 5000.0
    sg.start_generation()

    outdata.fill(0)
    sg.audio_engine.callback(None, outdata, frames, 0.0, None)

    signal_stop = outdata[:, 0]
    rms_stop = np.sqrt(np.mean(signal_stop**2))
    print(f"Stop band RMS: {rms_stop}")

    # Expect attenuation
    # 4th order LPF at 1kHz. 5kHz is > 2 octaves. -24dB/oct * 2 = -48dB attenuation roughly?
    # Actually butterworth 4th order is -24dB/octave? No, 6dB/pole/octave -> 24dB/octave.
    # 5000/1000 = 5 ratio. log2(5) = 2.32 octaves.
    # Attenuation approx 2.32 * 24 = 55dB.
    # 10^(-55/20) = 0.0017

    assert rms_pass > 0.5 # Sine RMS is 0.707
    assert rms_stop < rms_pass * 0.1 # Should be significantly attenuated

    print("Test LPF Passed")

def test_hpf_filtering():
    engine = MockAudioEngine()
    sg = SignalGenerator(engine)

    # Configure HPF at 1000 Hz
    sg.params_L.hpf_enabled = True
    sg.params_L.hpf_freq = 1000.0
    sg.params_L.hpf_order = 4

    # 1. Pass band (2000 Hz)
    sg.params_L.waveform = "sine"
    sg.params_L.frequency = 2000.0
    sg.params_L.amplitude = 1.0

    sg.start_generation()

    frames = 48000
    outdata = np.zeros((frames, 2))
    sg.audio_engine.callback(None, outdata, frames, 0.0, None)

    signal_pass = outdata[:, 0]
    rms_pass = np.sqrt(np.mean(signal_pass**2))
    print(f"HPF Pass band RMS: {rms_pass}")

    # 2. Stop band (200 Hz)
    sg.stop_generation()
    sg.params_L.frequency = 200.0
    sg.start_generation()

    outdata.fill(0)
    sg.audio_engine.callback(None, outdata, frames, 0.0, None)

    signal_stop = outdata[:, 0]
    rms_stop = np.sqrt(np.mean(signal_stop**2))
    print(f"HPF Stop band RMS: {rms_stop}")

    assert rms_pass > 0.5
    assert rms_stop < rms_pass * 0.1

    print("Test HPF Passed")

if __name__ == "__main__":
    test_lpf_filtering()
    test_hpf_filtering()
