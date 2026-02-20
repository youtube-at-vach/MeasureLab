import numpy as np
import scipy.signal

fs = 48000
duration = 1.0
t = np.linspace(0, duration, int(fs * duration), endpoint=False)
chirp = scipy.signal.chirp(t, 20, duration, 20000, method='logarithmic')

# add some noise
noise = np.random.normal(0, 0.1, len(chirp))
meas = chirp + noise

f, coh = scipy.signal.coherence(meas, chirp, fs=fs, nperseg=8192)
print("Mean coherence:", np.mean(coh))
print("Coherence at indices 100, 200, 500:", coh[100], coh[200], coh[500])
