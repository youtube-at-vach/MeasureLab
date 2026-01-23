
import numpy as np
from collections import deque
import time

class MockFrequencyCounter:
    def __init__(self):
        self.history_len = 2000
        self.freq_history = deque(maxlen=self.history_len)
        self.update_interval_ms = 100
        self.allan_taus = []
        self.allan_devs = []

    def calculate_allan_plot_data(self):
        """
        Calculates Allan Deviation for multiple Tau values.
        Tau is in units of update_interval.
        """
        if len(self.freq_history) < 10:
            return [], []

        data = np.array(self.freq_history)
        n = len(data)

        taus = []
        devs = []

        # Calculate for Tau = 1, 2, 4, 8, ... up to N/2
        max_m = n // 2
        m = 1
        while m <= max_m:
            num_samples = (n // m) * m
            if num_samples < 2 * m:
                break

            y = data[:num_samples].reshape(-1, m).mean(axis=1)

            if len(y) < 2:
                break

            diffs = np.diff(y)
            sigma = np.sqrt(0.5 * np.mean(diffs**2))

            tau_seconds = m * (self.update_interval_ms / 1000.0)
            taus.append(tau_seconds)
            devs.append(sigma)

            m *= 2

        self.allan_taus = taus
        self.allan_devs = devs
        return taus, devs

def test_adev():
    counter = MockFrequencyCounter()
    
    # constant freq - should be 0 ADEV
    for _ in range(100):
        counter.freq_history.append(1000.0)
    
    taus, devs = counter.calculate_allan_plot_data()
    print("Constant Freq Test:")
    print(f"Taus: {taus}")
    print(f"Devs: {devs}")
    assert all(d == 0.0 for d in devs)

    # white noise
    counter.freq_history.clear()
    np.random.seed(42)
    noise = np.random.normal(1000.0, 1.0, 1000)
    for v in noise:
        counter.freq_history.append(v)
        
    taus, devs = counter.calculate_allan_plot_data()
    print("\nWhite Noise Test:")
    for t, d in zip(taus, devs):
        print(f"Tau: {t:.2f}s, ADEV: {d:.4f}")

    # Theoretical slope for white FM is -1/2 (log-log)
    # sigma(tau) ~ tau^-0.5
    # Let's check slopes
    log_taus = np.log10(taus)
    log_devs = np.log10(devs)
    slopes = np.diff(log_devs) / np.diff(log_taus)
    print(f"Slopes (should be around -0.5): {slopes}")

if __name__ == "__main__":
    test_adev()
