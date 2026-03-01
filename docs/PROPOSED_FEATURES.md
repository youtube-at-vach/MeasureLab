# Feature Proposals for MeasureLab

**Project Direction Update (2025):**
The primary focus of this project is **Signal Measurement** (analyzing audio signals directly, e.g., DAC/Amp performance, signal integrity) rather than Acoustic Measurement (speakers/rooms).

---

## 🔮 Future / Visionary Ideas (Experimental)

* **AI-Based Audio Anomaly Detection:**
    * **Concept:** Real-time monitoring of audio streams using a lightweight ML model to detect clicks, pops, dropouts, and digital artifacts.
    * **Why:** Automates long-term reliability testing without human supervision.

* **Digital Interface Analyzer (Jitter/Eye Metrics):**
    * **Concept:** Dedicated analysis of digital signals (SPDIF/I2S via very high sample-rate analog capture or specialized hardware) to extract metrics: Eye Height/Width, Total Jitter (TIE), Rise/Fall stats.
    * **Why:** Complements the visual "Eye Pattern" in Oscilloscope with quantitative data for signal integrity verification. Requires hardware beyond standard audio interfaces.

* **Headless / Web Remote Interface:**
    * **Concept:** Decouple the GUI from the core engine to allow running the backend on embedded devices (e.g., Raspberry Pi) and viewing results via a web browser or mobile app.
    * **Why:** Enables remote monitoring of equipment in difficult-to-access locations.

* **Plugin / Scripting System:**
    * **Concept:** Allow users to write custom Python scripts (DSP hooks) to process audio buffers without recompiling the application.
    * **Why:** Empowers advanced users to implement custom filters or specialized measurements.

* **3D Spectral Waterfall:**
    * **Concept:** Extension to the Spectrogram widget to visualize frequency response over time in 3D (Z-axis depth).
    * **Why:** Superior visualization for analyzing resonance decay and transient behavior.

---

## 🚀 Active / High Priority (Signal Focus)

### 🆕 New Proposals

* **Realtime Null Comparator:**
    * **Concept:** A widget to perform real-time difference listening (Null Test) by inverting one channel and applying precise delay/gain matching.
    * **Why:** Immediate auditory verification of signal chain transparency without offline file processing.

* **Offline Null Comparator:**
    * **Concept:** A file-based tool to compare two audio recordings (Reference vs. DUT).
    * **Features:** Automatic sub-sample time alignment, gain matching, and inversion to produce a "Difference" (Null) file.
    * **Why:** The gold standard for verifying "transparency" of codecs, cables, or analog chains.

* **Multimeter (AC Voltmeter):**
    * **Concept:** A dedicated widget acting as a Digital Multimeter (DMM) for audio.
    * **Features:** Large, high-visibility readout of Vrms, Vpeak, Crest Factor, Frequency, and **Phase (L vs R)**.
    * **Why:** Existing widgets (Scope/SpecAn) are too complex for simple level checks. A simple "Meter" mode is essential for gain staging and quick diagnostics.

* **Step Response Analyzer:**
    * **Concept:** Dedicated widget for analyzing transient response using band-limited step or square wave signals.
    * **Features:** Automated measurement of Rise/Fall Time (10-90%), Overshoot/Undershoot (%), Settling Time, and Pre/Post-ringing Ratio.
    * **Why:** Essential for characterizing DAC reconstruction filters (distinguishing Linear Phase vs Minimum Phase) and amplifier stability.

### 🛠️ Extensions to Existing Widgets

* **Impedance Analyzer: Cable Tester Mode:**
    * **Extension:** Add a "Cable Test" preset to measure Capacitance (pF/m), Inductance (µH/m), and Resistance (mΩ/m).
    * **Why:** Simplifies cable characterization for audiophiles and engineers using existing hardware.

* **Network Analyzer: Impulse Response View:**
    * **Extension:** Add a time-domain "Impulse Response" plot tab to the Network Analyzer.
    * **Why:** Visualizing the IR allows diagnosis of time-domain issues (polarity, pre-ringing, reflections).

* **Network Analyzer: Coherence Function:**
    * **Extension:** Add a Coherence plot (0.0 - 1.0) to the Transfer Function mode.
    * **Why:** To evaluate measurement confidence and linearity/SNR.

* **Spectrum Analyzer: Cepstrum Analysis:**
    * **Extension:** Add "Cepstrum" (Power Cepstrum) mode (Quefrency domain).
    * **Why:** Useful for analyzing harmonic structures and pitch detection.

---

## ✅ Already Implemented

* **Quantization / Bit Depth Analyzer:** Integrated into Settings (Audio Devices tab).
* **Crosstalk Analyzer:** Integrated into `NetworkAnalyzer`.
* **Multitone Analyzer:** Implemented in `AdvancedDistortionMeter`.
* **Oscilloscope Persistence / Eye Pattern:** Implemented in `Oscilloscope`.
* **Linearity Analyzer:** Implemented as `LinearityAnalyzer`.

---

## 💤 Deferred / Reference (Acoustic & Correction)

*Features related to physical acoustics are preserved here for reference but are **not currently planned**.*

* **DC Stability & Drift Logger:** Impossible (AC Coupled hardware).
* **Wow & Flutter Meter:** Deferred (Analog focus).
* **Room Acoustics (RT60):** Deferred (Acoustic focus).
* **Loudspeaker Parameters (T/S):** Deferred (Electromechanical focus).
* **EQ Designer:** Auto-calculate PEQ. Deferred.
* **Polarity Tester:** Pulse-based detection. Deferred.


<!-- trigger ci -->
