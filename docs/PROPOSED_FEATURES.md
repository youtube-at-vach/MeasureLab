# Feature Proposals for MeasureLab

**Project Direction Update (2025):**
The primary focus of this project is **Signal Measurement** (analyzing audio signals directly, e.g., DAC/Amp performance, signal integrity) rather than Acoustic Measurement (speakers/rooms).

---

## 🚀 Active / High Priority (Signal Focus)

---

## ✅ Already Implemented

* **Crosstalk Analyzer:** Integrated into `NetworkAnalyzer` as a dedicated mode (L->R and R->L). Includes automated routing and "Crosstalk (dB)" plotting.
* **Multitone Analyzer:** Implemented in `AdvancedDistortionMeter` (supports MIM/Multitone TD+N).
* **Oscilloscope Persistence / Eye Pattern:** Implemented "Infinite Persistence" / "Eye Pattern" mode in `Oscilloscope`.
* **Linearity Analyzer:** Implemented as a dedicated widget (`LinearityAnalyzer`). Measures linearity error (AES17), gain accuracy, and noise floor by sweeping input amplitude.

---

## 💤 Deferred / Reference (Acoustic & Correction)

*Features related to physical acoustics are preserved here for reference but are **not currently planned**.*

* **DC Stability & Drift Logger:** Long-term logging of DC Offset to verify amplifier thermal stability.
    * **Status:** Impossible (AC Coupled)
    * **Reason:** Sound devices are AC coupled, making DC measurement impossible without external circuitry. This is not currently planned.
* **Wow & Flutter Meter:** Measure frequency fluctuation of analog playback devices (IEC 60386). Deferred as current focus is digital/signal.
* **Room Acoustics (RT60):** Schroeder integration for decay times. (`TransientAnalyzer` uses Wavelets).
* **Loudspeaker Parameters (T/S):** Derive Thiele/Small parameters from impedance sweeps. (`ImpedanceAnalyzer` measures Z only).
* **EQ Designer:** Auto-calculate PEQ to match target curves.
* **Polarity Tester:** Pulse-based polarity detection.
