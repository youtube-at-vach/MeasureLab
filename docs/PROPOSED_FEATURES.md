# Feature Proposals for MeasureLab

**Project Direction Update (2026):**
The primary focus of this project is **Signal Measurement** (analyzing audio signals directly, e.g., DAC/Amp performance, signal integrity) rather than Acoustic Measurement (speakers/rooms).

---

## 🔮 Future / Visionary Ideas (Experimental)

* **Generative AI Non-Linearity Cloner:**
    * **Concept:** Analyzes a DUT (e.g., vintage tube amp) using specialized excitation signals and trains a lightweight ML model to replicate its exact dynamic, level-dependent non-linearities and phase characteristics.
    * **Why:** Advances beyond static impulse responses (IR) to digitally "clone" the dynamic behavior of analog gear.

* **Holographic Audio Topography:**
    * **Concept:** Evolves the Goniometer into a full 3D interactive visualization of phase, amplitude, and frequency, mapping spatial energy over a spherical coordinate system.
    * **Why:** Radically intuitive visualization of complex phase relationships and soundstage width in multi-channel or stereo signals.

* **AI-Based Audio Anomaly Detection:**
    * **Concept:** Real-time ML monitoring of audio streams to detect clicks, pops, dropouts, and digital artifacts.
    * **Why:** Automates long-term reliability testing without human supervision.

* **Digital Interface Analyzer (Jitter/Eye Metrics):**
    * **Concept:** Dedicated analysis of digital signals (SPDIF/I2S) to extract Eye Height/Width and Total Jitter (TIE).
    * **Why:** Quantitative data for signal integrity verification (requires specialized hardware).

* **Headless / Web Remote Interface:**
    * **Concept:** Decouple GUI from the core engine to run on embedded devices (e.g., Raspberry Pi) with web/mobile viewing.
    * **Why:** Remote monitoring of equipment.

* **Plugin / Scripting System:**
    * **Concept:** Python scripting hooks for custom DSP processing of audio buffers.
    * **Why:** Empowers advanced users to implement custom filters.

* **3D Spectral Waterfall:**
    * **Concept:** Extension to the Spectrogram to visualize frequency response over time in 3D (Z-axis depth).
    * **Why:** Superior visualization for analyzing resonance decay.

---

## 🚀 Active / High Priority (Signal Focus)

### 🆕 New Proposals

* **Bit-Perfect Verifier:**
    * **Concept:** Outputs a pseudo-random bit sequence (PRBS) or digital watermark and captures the loopback to verify 100% bit-accurate transmission.
    * **Why:** Essential to prove zero OS-level resampling or attenuation for high-fidelity audio setups.

* **Realtime Null Comparator:**
    * **Concept:** Real-time difference listening (Null Test) by inverting one channel with precise delay/gain matching.
    * **Why:** Immediate auditory verification of signal chain transparency.

* **Offline Null Comparator:**
    * **Concept:** File-based tool to compare Reference vs. DUT recordings with automatic sub-sample alignment and gain matching.
    * **Why:** Gold standard for verifying "transparency" of codecs or analog chains.

* **Multimeter (AC Voltmeter):**
    * **Concept:** Dedicated widget acting as a Digital Multimeter (DMM) for audio, showing Vrms, Vpeak, Crest Factor, Frequency, and Phase.
    * **Why:** Simplifies level checks and gain staging without complex Scope/SpecAn visuals.

* **Step Response Analyzer:**
    * **Concept:** Transient response analysis using band-limited step/square waves to measure Rise/Fall Time and Overshoot.
    * **Why:** Characterizes DAC reconstruction filters and amplifier stability.

### 🛠️ Extensions to Existing Widgets

* **Frequency Counter: Phase Noise Plot:**
    * **Extension:** Add an FFT-based plot of phase deviations (Phase Noise in dBc/Hz) alongside the existing jitter histogram.
    * **Why:** Industry standard for evaluating clock quality and oscillator performance in DACs.

* **Signal Generator: Psychoacoustic Masking Tones:**
    * **Extension:** Add generation modes for complex masking scenarios (e.g., pure tone + narrow-band noise at specific ratios).
    * **Why:** Facilitates testing of perceptual masking thresholds for codecs and psychoacoustic research.

* **Impedance Analyzer: Cable Tester Mode:**
    * **Extension:** Add "Cable Test" preset to measure Capacitance, Inductance, and Resistance per meter.
    * **Why:** Simplifies cable characterization.

* **Network Analyzer: Impulse Response & Coherence:**
    * **Extension:** Add time-domain "Impulse Response" and Coherence (0.0 - 1.0) plots.
    * **Why:** Diagnoses time-domain issues and evaluates measurement confidence.

* **Spectrum Analyzer: Cepstrum Analysis:**
    * **Extension:** Add "Cepstrum" mode (Quefrency domain).
    * **Why:** Analyzes harmonic structures and pitch detection.

---

## ✅ Already Implemented

* **Quantization / Bit Depth Analyzer:** In Settings (Audio Devices tab).
* **Crosstalk & Multitone Analyzer:** In `NetworkAnalyzer` & `AdvancedDistortionMeter`.
* **Oscilloscope Persistence / Eye Pattern:** In `Oscilloscope`.
* **Linearity Analyzer:** As `LinearityAnalyzer`.

---

## 💤 Deferred / Reference (Acoustic & Correction)

*Features related to physical acoustics are preserved here for reference but are **not currently planned**.*

* **DC Stability & Drift Logger:** Impossible (AC Coupled hardware).
* **Wow & Flutter Meter:** Deferred (Analog focus).
* **Room Acoustics (RT60) & T/S Parameters:** Deferred (Acoustic/Electromechanical focus).
* **EQ Designer & Polarity Tester:** Deferred.
