# Feature Proposals for MeasureLab

**Project Direction Update (2025):**
The primary focus of this project is **Signal Measurement** (analyzing audio signals directly, e.g., DAC/Amp performance, signal integrity) rather than Acoustic Measurement (speakers/rooms).

---

## 🚀 Active / High Priority (Signal Focus)

### 🆕 New Proposals

* **Multimeter (AC Voltmeter):**
    * **Concept:** A dedicated widget acting as a Digital Multimeter (DMM) for audio.
    * **Features:** Large, high-visibility readout of Vrms, Vpeak, Crest Factor, and Frequency.
    * **Why:** Existing widgets (Scope/SpecAn) are too complex for simple level checks. A simple "Meter" mode is essential for gain staging and quick diagnostics.

* **Network Analyzer Extensions:**
    * **Coherence Function:** Add a Coherence plot (0.0 - 1.0) to the Transfer Function mode.
    * **Why:** To evaluate measurement confidence and linearity/SNR, especially in noisy environments or when measuring non-linear devices.

* **Spectrum Analyzer Extensions:**
    * **Cepstrum Analysis:** Add "Cepstrum" (Power Cepstrum) mode (Quefrency domain).
    * **Why:** Useful for analyzing harmonic structures, pitch detection, and separating source/filter characteristics (echo/reflection analysis).

---

## ✅ Already Implemented

* **Crosstalk Analyzer:** Integrated into `NetworkAnalyzer` (supports L->R / R->L).
* **Multitone Analyzer:** Implemented in `AdvancedDistortionMeter`.
* **Oscilloscope Persistence / Eye Pattern:** Implemented in `Oscilloscope`.
* **Linearity Analyzer:** Implemented as a dedicated widget (`LinearityAnalyzer`).

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
