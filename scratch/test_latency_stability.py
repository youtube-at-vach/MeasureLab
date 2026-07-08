import sys
import os
import time
import logging
import threading
import numpy as np
import sounddevice as sd
from scipy.signal import windows

# Add src to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.audio_engine import AudioEngine
from src.core.nonlinear_analyzer_core import find_subsample_peak
from src.core.fft_manager import fft_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# Sweep Signal Generators
# ---------------------------------------------------------

def generate_linear_sweep(fs, duration, f1, f2):
    num_samples = int(np.round(fs * duration))
    t = np.arange(num_samples) / fs
    phase = 2 * np.pi * (f1 * t + (f2 - f1) / (2 * duration) * t**2)
    sig = np.sin(phase)
    win = windows.tukey(num_samples, alpha=0.02)
    return sig * win

def generate_log_sweep(fs, duration, f1, f2):
    # Novak's SSS
    nyquist = fs / 2.0
    if f1 <= f2:
        start_margin = max(2.0, f1 / 1.3)
        end_margin = min(nyquist * 0.95, f2 * 1.15)
    else:
        start_margin = min(nyquist * 0.95, f1 * 1.15)
        end_margin = max(2.0, f2 / 1.3)
    
    fs1 = float(start_margin)
    fs2 = float(end_margin)
    
    ln_ratio = np.log(fs2 / fs1)
    k = int(np.round((fs1 / ln_ratio) * duration))
    if k == 0:
        k = -1 if ln_ratio < 0 else 1
    L = k / fs1
    T = L * ln_ratio
    
    num_samples = int(np.round(fs * T))
    t = np.arange(num_samples) / fs
    phase = 2 * np.pi * k * np.exp(t / L)
    sig = np.sin(phase)
    win = windows.tukey(num_samples, alpha=0.02)
    return sig * win, T

def generate_hyperbolic_sweep(fs, duration, f1, f2):
    # Hyperbolic sweep: f(t) = 1 / (A * t + B)
    # f(0) = f1, f(duration) = f2
    num_samples = int(np.round(fs * duration))
    t = np.arange(num_samples) / fs
    
    A = (f1 - f2) / (f1 * f2 * duration)
    B = 1.0 / f1
    
    phase = (2 * np.pi / A) * np.log(1 + (A / B) * t)
    sig = np.sin(phase)
    win = windows.tukey(num_samples, alpha=0.02)
    return sig * win

# ---------------------------------------------------------
# Deconvolution and PNR Analysis
# ---------------------------------------------------------

def deconvolve_signal(recorded_signal, sss_signal, regularization=1e-4):
    N_rec = len(recorded_signal)
    N_sss = len(sss_signal)
    N_fft = int(2 ** np.ceil(np.log2(N_rec + N_sss)))

    S = fft_manager.rfft(np.pad(sss_signal, (0, N_fft - N_sss)))
    Y = fft_manager.rfft(np.pad(recorded_signal, (0, N_fft - N_rec)))

    S_power = np.abs(S) ** 2
    epsilon = regularization * np.max(S_power) + 1e-12

    H = (Y * np.conj(S)) / (S_power + epsilon)
    g = fft_manager.irfft(H, n=N_fft)
    return g

def calculate_pnr(ir, peak_sample):
    """
    Calculate Peak-to-Noise Ratio (PNR) of the impulse response.
    """
    N = len(ir)
    peak_idx = int(np.round(peak_sample)) % N
    
    # Define noise region: exclude peak and immediate surroundings (e.g. ±50 samples)
    exclude_half = 50
    mask = np.ones(N, dtype=bool)
    
    # Handle wrap-around
    for i in range(-exclude_half, exclude_half + 1):
        mask[(peak_idx + i) % N] = False
        
    noise_part = ir[mask]
    if len(noise_part) == 0:
        return 0.0
        
    rms_noise = np.sqrt(np.mean(noise_part ** 2))
    peak_val = np.max(np.abs(ir))
    
    if rms_noise < 1e-12:
        return 100.0
        
    pnr = 20 * np.log10(peak_val / rms_noise)
    return pnr

# ---------------------------------------------------------
# Calibrator class
# ---------------------------------------------------------

class TestLatencyCalibrator:
    def __init__(self, audio_engine, sss_sig, in_ch=0, out_ch=0):
        self.audio_engine = audio_engine
        self.sample_rate = audio_engine.sample_rate
        self.sss = sss_sig
        self.in_ch = in_ch
        self.out_ch = out_ch
        
        self.margin_samples = int(0.3 * self.sample_rate)
        self.total_samples = len(self.sss) + self.margin_samples
        self.recorded_data = np.zeros(self.total_samples)
        
        self.write_pos = 0
        self.read_pos = 0
        self.finished = threading.Event()
        self.callback_id = None
        self.error = None
        
    def callback(self, indata, outdata, frames, time, status):
        try:
            outdata.fill(0.0)
            if self.finished.is_set():
                return
                
            # 1. Playback
            out_samples = min(frames, len(self.sss) - self.write_pos)
            if out_samples > 0:
                sig = self.sss[self.write_pos : self.write_pos + out_samples]
                if outdata.shape[1] > self.out_ch:
                    outdata[:out_samples, self.out_ch] = sig
                else:
                    outdata[:out_samples, 0] = sig
                self.write_pos += out_samples
                
            # 2. Record
            in_samples = min(frames, self.total_samples - self.read_pos)
            if in_samples > 0:
                if indata.shape[1] > self.in_ch:
                    self.recorded_data[self.read_pos : self.read_pos + in_samples] = indata[:in_samples, self.in_ch]
                else:
                    self.recorded_data[self.read_pos : self.read_pos + in_samples] = indata[:in_samples, 0]
                self.read_pos += in_samples
                if self.read_pos >= self.total_samples:
                    self.finished.set()
            else:
                self.finished.set()
        except Exception as e:
            self.error = e
            self.finished.set()

# ---------------------------------------------------------
# Test runner
# ---------------------------------------------------------

def measure_latency_test(audio_engine, sweep_type, duration, f1, f2, in_ch=0, out_ch=0, add_noise=0.0):
    fs = audio_engine.sample_rate
    
    # Pre-generate log sweep to find its synchronized actual duration
    log_sig, actual_duration = generate_log_sweep(fs, duration, f1, f2)
    
    if sweep_type == "log":
        sss = log_sig
        use_duration = actual_duration
    elif sweep_type == "linear":
        sss = generate_linear_sweep(fs, actual_duration, f1, f2)
        use_duration = actual_duration
    elif sweep_type == "hyperbolic":
        sss = generate_hyperbolic_sweep(fs, actual_duration, f1, f2)
        use_duration = actual_duration
    else:
        raise ValueError(f"Unknown sweep type {sweep_type}")
        
    logger.debug(f"Sweep type: {sweep_type}, samples: {len(sss)}, duration: {use_duration:.4f}s")
    calibrator = TestLatencyCalibrator(audio_engine, sss, in_ch, out_ch)
    
    # Register callback (starts stream if not running)
    calibrator.callback_id = audio_engine.register_callback(calibrator.callback)
    
    # Wait for execution
    success = calibrator.finished.wait(timeout=use_duration + 1.5)
    
    # Unregister
    audio_engine.unregister_callback(calibrator.callback_id)
    
    if calibrator.error:
        raise calibrator.error
    if not success:
        raise TimeoutError("Latency measurement timed out.")
        
    recorded = calibrator.recorded_data.copy()
    
    # Optionally inject white noise to test robustness
    if add_noise > 0.0:
        noise = np.random.normal(0, add_noise, len(recorded))
        recorded += noise
        
    # Deconvolve and peak find
    ir = deconvolve_signal(recorded, sss)
    peak_sample = find_subsample_peak(ir)
    pnr = calculate_pnr(ir, peak_sample)
    
    return peak_sample, pnr

def run_evaluation(audio_engine, in_ch, out_ch, num_trials=10, noise_levels=[0.0, 0.01, 0.05]):
    f1 = 20.0
    f2 = 20000.0
    duration = 0.25
    
    results = {}
    
    sweep_types = ["linear", "log", "hyperbolic"]
    
    for noise in noise_levels:
        results[noise] = {}
        for stype in sweep_types:
            logger.info(f"Running: sweep_type={stype}, noise_level={noise}...")
            latencies = []
            pnrs = []
            
            for trial in range(num_trials):
                try:
                    lat, pnr = measure_latency_test(audio_engine, stype, duration, f1, f2, in_ch, out_ch, add_noise=noise)
                    latencies.append(lat)
                    pnrs.append(pnr)
                    time.sleep(0.05)
                except Exception as e:
                    logger.error(f"Error on trial {trial}: {e}")
                    
            if latencies:
                mean_lat = np.mean(latencies)
                std_lat = np.std(latencies)
                mean_pnr = np.mean(pnrs)
                results[noise][stype] = {
                    "mean_latency": mean_lat,
                    "std_latency": std_lat,
                    "mean_pnr": mean_pnr,
                    "raw_latencies": latencies
                }
                logger.info(f"  Result: Mean Latency = {mean_lat:.4f} samples, Std = {std_lat:.4f} samples, Mean PNR = {mean_pnr:.2f} dB")
            else:
                results[noise][stype] = None
                logger.error(f"  Result: No trials succeeded for {stype}")
                
    return results

def main():
    # Setup AudioEngine
    engine = AudioEngine()
    engine.set_sample_rate(48000)
    engine.set_block_size(256) # small block size for low latency / responsiveness
    
    # Try ZOOM UAC-232 first
    devices = sd.query_devices()
    device_names = [d['name'] for d in devices]
    
    uac_idx = [i for i, name in enumerate(device_names) if "ZOOM UAC-232" in name or "UAC-232" in name]
    blackhole_idx = [i for i, name in enumerate(device_names) if "BlackHole" in name]
    
    # Let's try UAC-232 first. We need to check if there is actual input loopback.
    # We will do a quick check measurement.
    use_device_id = None
    if uac_idx:
        logger.info(f"Probing ZOOM UAC-232 at index {uac_idx[0]}...")
        engine.set_devices(uac_idx[0], uac_idx[0])
        try:
            # Quick measurement to see if signal is loopbacked
            lat, pnr = measure_latency_test(engine, "log", 0.25, 20.0, 20000.0, in_ch=0, out_ch=0)
            logger.info(f"ZOOM UAC-232 probe success: latency={lat:.2f}, pnr={pnr:.1f} dB")
            if pnr > 15.0: # If PNR is decent, we assume it's looped back
                use_device_id = uac_idx[0]
                logger.info("Using ZOOM UAC-232 (physical/hardware loopback verified)")
        except Exception as e:
            logger.warning(f"ZOOM UAC-232 probe failed: {e}")
            
    if use_device_id is None and blackhole_idx:
        logger.info(f"Probing BlackHole 2ch at index {blackhole_idx[0]}...")
        engine.set_devices(blackhole_idx[0], blackhole_idx[0])
        try:
            lat, pnr = measure_latency_test(engine, "log", 0.25, 20.0, 20000.0, in_ch=0, out_ch=0)
            logger.info(f"BlackHole 2ch probe success: latency={lat:.2f}, pnr={pnr:.1f} dB")
            use_device_id = blackhole_idx[0]
            logger.info("Using BlackHole 2ch (virtual loopback)")
        except Exception as e:
            logger.warning(f"BlackHole 2ch probe failed: {e}")
            
    if use_device_id is None:
        logger.error("No working loopback device found. Please ensure BlackHole is installed or ZOOM UAC-232 is loopbacked.")
        sys.exit(1)
        
    logger.info("Starting evaluation...")
    eval_results = run_evaluation(engine, in_ch=0, out_ch=0, num_trials=20)
    
    # Print summary table
    print("\n" + "="*80)
    print(" LATENCY CALIBRATION STABILITY TEST RESULTS")
    print("="*80)
    
    for noise, sweep_data in eval_results.items():
        print(f"\nNoise Level (RMS): {noise}")
        print(f"{'Sweep Type':<15} | {'Mean Latency (samples)':<22} | {'Std Dev (samples)':<18} | {'Mean PNR (dB)':<15}")
        print("-"*80)
        for stype, data in sweep_data.items():
            if data:
                print(f"{stype:<15} | {data['mean_latency']:<22.4f} | {data['std_latency']:<18.6f} | {data['mean_pnr']:<15.2f}")
            else:
                print(f"{stype:<15} | {'N/A':<22} | {'N/A':<18} | {'N/A':<15}")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
