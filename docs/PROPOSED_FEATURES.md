# Feature Proposals for MeasureLab

**Project Direction Update (2025):**
The primary focus of this project is **Signal Measurement** (analyzing audio signals directly, e.g., DAC/Amp performance, signal integrity) rather than Acoustic Measurement (speakers/rooms).

---

## 🚀 Active / High Priority (Signal Focus)

### 🆕 New Proposals

* **Quantization / Bit Depth Analyzer:**
    * **Concept:** Analyzes the float stream to estimate the effective bit depth and quantization noise floor.
    * **Features:** Histogram of sample values, LSB activity meter, "Stuck Bit" detection, and ENOB (Effective Number of Bits) calculation.
    * **Why:** To verify digital signal path integrity (e.g., checking if a 24-bit interface is being truncated to 16-bit by the OS mixer).

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
    * **Why:** Essential for characterizing DAC reconstruction filters (distinguishing Linear Phase vs Minimum Phase) and amplifier stability, distinct from the frequency-domain focus of the Network Analyzer.

### 🛠️ Extensions to Existing Widgets

* **Network Analyzer: Impulse Response View:**
    * **Extension:** Add a time-domain "Impulse Response" plot tab to the Network Analyzer.
    * **Why:** The analyzer already calculates IR internally for the frequency response. Visualizing the IR allows diagnosis of time-domain issues (polarity, pre-ringing, reflections) without needing a separate tool.

* **Network Analyzer: Coherence Function:**
    * **Extension:** Add a Coherence plot (0.0 - 1.0) to the Transfer Function mode.
    * **Why:** To evaluate measurement confidence and linearity/SNR, especially in noisy environments or when measuring non-linear devices.

* **Spectrum Analyzer: Cepstrum Analysis:**
    * **Extension:** Add "Cepstrum" (Power Cepstrum) mode (Quefrency domain).
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

* **DC Stability & Drift Logger:** Impossible (AC Coupled hardware).
* **Wow & Flutter Meter:** Deferred (Analog focus).
* **Room Acoustics (RT60):** Deferred (Acoustic focus).
* **Loudspeaker Parameters (T/S):** Deferred (Electromechanical focus).
* **EQ Designer:** Auto-calculate PEQ. Deferred.
* **Polarity Tester:** Pulse-based detection. Deferred.
