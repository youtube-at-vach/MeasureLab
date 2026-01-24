# Feature Proposals for MeasureLab

**Project Direction Update (2025):**
The primary focus of this project is **Signal Measurement** (analyzing audio signals directly, e.g., DAC/Amp performance, signal integrity) rather than Acoustic Measurement (speakers/rooms).

---

## 🚀 Active / High Priority (Signal Focus)

### 1. Multitone Analyzer

**Status:** Planned (Extend `DistortionAnalyzer`)
**Description:** Use log-spaced multitone signals (already supported by `SignalGenerator`) to measure TD+N (Total Distortion + Noise) across the full bandwidth in a single shot (< 2 seconds).
**Gap:** `DistortionAnalyzer` currently only supports Single-Tone THD or Dual-Tone IMD.

### 2. Linearity Analyzer (Gain vs Level)

**Status:** Planned (Extend `DistortionAnalyzer`)
**Description:** Measure output level accuracy and linearity error (AES17) by sweeping input amplitude from -120 dBFS to 0 dBFS.
**Gap:** The current Amplitude Sweep plots THD+N vs Amplitude. It needs to calculate and plot **Deviation from Linearity (dB)** vs Amplitude to verify DAC low-level performance.

### 3. Crosstalk Analyzer

**Status:** Planned (Extend `NetworkAnalyzer`)
**Description:** Automated measurement of channel separation vs Frequency (e.g., Drive L -> Measure R).
**Gap:** `NetworkAnalyzer` supports generic XFER (Meas/Ref) but requires manual patching/setup. A dedicated mode should handle the routing and plot "Crosstalk (dB)" directly.

### 4. Oscilloscope Persistence / Eye Pattern

**Status:** Planned (Extend `Oscilloscope`)
**Description:** Add an "Infinite Persistence" or "Phosphor" mode to visualize signal integrity, jitter, and ISI (Eye Pattern).
**Gap:** `Oscilloscope` currently clears the trace on every frame (`goniometer.py` has this, but `oscilloscope.py` does not).

### 5. Wow & Flutter Meter

**Status:** Planned (Extend `FrequencyCounter`)
**Description:** Measure frequency fluctuation of analog playback devices using standard weighting filters (IEC 60386 / DIN 45507).
**Gap:** `FrequencyCounter` measures raw Jitter (Std Dev) but lacks the specific demodulation (0.5Hz–200Hz) and weighting ballistics required for standard W&F measurements.

### 6. DC Stability & Drift Logger

**Status:** Planned (New Widget or Extend `Voltmeter`)
**Description:** Long-term logging of DC Offset (and Temperature if supported) to verify amplifier thermal stability over minutes/hours.
**Gap:** No existing widget focuses on slow, long-term trend logging of DC parameters.

---

## 💤 Deferred / Reference (Acoustic & Correction)

*Features related to physical acoustics are preserved here for reference but are **not currently planned**.*

* **Room Acoustics (RT60):** Schroeder integration for decay times. (`TransientAnalyzer` uses Wavelets).
* **Loudspeaker Parameters (T/S):** Derive Thiele/Small parameters from impedance sweeps. (`ImpedanceAnalyzer` measures Z only).
* **EQ Designer:** Auto-calculate PEQ to match target curves.
* **Polarity Tester:** Pulse-based polarity detection.
