# Feature Proposals for MeasureLab

**Project Direction Update (2025):**
The primary focus of this project is **Signal Measurement** (analyzing audio signals directly, e.g., DAC/Amp performance, signal integrity) rather than Acoustic Measurement (speakers/rooms).

---

## 🚀 Active / High Priority (Signal Focus)

### 1. Linearity Analyzer (Gain vs Level)

**Status:** Planned (Extend `DistortionAnalyzer`)
**Description:** Measure output level accuracy and linearity error (AES17) by sweeping input amplitude from -120 dBFS to 0 dBFS.
**Gap:** The current Amplitude Sweep plots THD+N vs Amplitude. It needs to calculate and plot **Deviation from Linearity (dB)** vs Amplitude to verify DAC low-level performance.

### 2. Crosstalk Analyzer

**Status:** Planned (Extend `NetworkAnalyzer`)
**Description:** Automated measurement of channel separation vs Frequency (e.g., Drive L -> Measure R).
**Gap:** `NetworkAnalyzer` supports generic XFER (Meas/Ref) but requires manual patching/setup. A dedicated mode should handle the routing and plot "Crosstalk (dB)" directly.

### 3. DC Stability & Drift Logger

**Status:** Planned (New Widget or Extend `Voltmeter`)
**Description:** Long-term logging of DC Offset (and Temperature if supported) to verify amplifier thermal stability over minutes/hours.
**Gap:** No existing widget focuses on slow, long-term trend logging of DC parameters.

---

## ✅ Already Implemented

* **Multitone Analyzer:** Implemented in `AdvancedDistortionMeter` (supports MIM/Multitone TD+N).
* **Oscilloscope Persistence / Eye Pattern:** Implemented "Infinite Persistence" / "Eye Pattern" mode in `Oscilloscope`.

---

## 💤 Deferred / Reference (Acoustic & Correction)

*Features related to physical acoustics are preserved here for reference but are **not currently planned**.*

* **Wow & Flutter Meter:** Measure frequency fluctuation of analog playback devices (IEC 60386). Deferred as current focus is digital/signal.
* **Room Acoustics (RT60):** Schroeder integration for decay times. (`TransientAnalyzer` uses Wavelets).
* **Loudspeaker Parameters (T/S):** Derive Thiele/Small parameters from impedance sweeps. (`ImpedanceAnalyzer` measures Z only).
* **EQ Designer:** Auto-calculate PEQ to match target curves.
* **Polarity Tester:** Pulse-based polarity detection.
