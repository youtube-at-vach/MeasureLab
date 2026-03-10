# Feature Proposals for MeasureLab

**Project Direction Update (2026):**
Focus is strictly **Signal Measurement** (analyzing audio signals, DAC/Amp performance, etc.) rather than Acoustic Measurement (speakers/rooms).

---

## 🔮 Future / Visionary Ideas (Experimental)

* **Generative AI Non-Linearity Cloner:** AI model trained via specialized excitation signals to replicate exact dynamic non-linearities/phase of analog gear.
* **Brainwave (EEG) Perceptual Correlator:** Syncing auditory test signals with real-time EEG metrics to measure perceived distortion versus mathematical distortion.
* **Headless / Web Remote Interface:** Decouple GUI for embedded (Raspberry Pi) web/mobile remote monitoring.

---

## 🚀 Active / High Priority (Signal Focus)

### 🆕 New Proposals

* **Dynamics Processor Profiler:**
    * **Concept:** Measures static I/O transfer curves and time-domain dynamic attack/release times of compressors and limiters.
    * **Why:** The existing Linearity Analyzer only checks static levels; it cannot measure time-constants (Attack/Release).
* **Bit-Perfect Verifier:**
    * **Concept:** PRBS or watermark generator/analyzer to verify 100% bit-accurate loopback transmission.
    * **Why:** Proves zero OS-level resampling/attenuation.
* **Realtime Null Comparator:**
    * **Concept:** Real-time channel inversion with sub-sample delay/gain matching for difference listening.
    * **Why:** Auditory verification of chain transparency.
* **Offline Null Comparator:**
    * **Concept:** File-based reference vs. DUT comparison.

### 🛠️ Extensions to Existing Widgets

* **Network Analyzer: Amplifier Stability Margins:**
    * **Extension:** Calculate and display Gain Margin (dB) and Phase Margin (degrees) from Bode plots.
    * **Why:** Critical for evaluating custom amplifier stability under complex loads.
* **Frequency Counter: Phase Noise Plot:**
    * **Extension:** FFT-based phase deviation plot (dBc/Hz).
* **Signal Generator: Psychoacoustic Masking Tones:**
    * **Extension:** Pure tone + narrow-band noise generation modes.
* **Impedance Analyzer: Cable Tester Mode:**
    * **Extension:** Measure Capacitance, Inductance, and Resistance per meter.
* **Network Analyzer: Impulse Response & Coherence:**
    * **Extension:** Time-domain IR and 0.0-1.0 Coherence plot.

---

## ✅ Already Implemented

* **Quantization / Bit Depth Analyzer** (Settings)
* **Crosstalk & Multitone Analyzer** (`NetworkAnalyzer` / `AdvancedDistortionMeter`)
* **Oscilloscope Persistence / Eye Pattern** (`Oscilloscope`)
* **Linearity Analyzer**

---

## ⏸️ Under Review / On Hold

* **Holographic Audio Topography:** 3D spherical evolution of Goniometer visualizing phase, amplitude, and frequency mapping.
    * **Status:** On Hold
    * **Reason:** While interesting, current standard PC specifications cannot smoothly drive 3D rendering yet.
* **3D Spectral Waterfall:** Spectrogram extension adding Z-axis depth for resonance decay.
    * **Status:** On Hold
    * **Reason:** For room reverberation measurements, other advanced external software (like REW) already exist.
* **Plugin / Scripting System:** Python hooks for custom DSP audio buffer processing.
    * **Status:** On Hold
    * **Reason:** The core architecture needs to be finalized first. The future direction of the software is currently unclear.
* **AI Circuit Topology Reverse Engineer:** Analyzes extreme complex test signal responses (e.g., dynamic IMD) to predict internal topology.
    * **Status:** Under Investigation
    * **Reason:** Implementation feasibility is currently being researched as there are no concrete technical prospects yet.
* **Multimeter (AC Voltmeter):** Dedicated digital multimeter widget (Vrms, Vpeak, Crest Factor, Freq, Phase).
    * **Status:** Under Consideration
    * **Reason:** Very useful, but too limited if used solely as an AC meter. We are exploring alternative approaches.
* **Spectrum Analyzer: Cepstrum Analysis:** "Cepstrum" mode for pitch and harmonic structure analysis.
    * **Status:** Under Consideration
    * **Reason:** Highly promising, but since the horizontal axis is not frequency, we are considering adding it to a separate, dedicated vibration analysis widget instead.

---

## ❌ Cancelled / Not Needed

* **Step Response Analyzer:** Transient analysis via band-limited steps to measure Rise/Fall Time and Overshoot for DAC filters.
    * **Status:** Not Needed
    * **Reason:** Its functionality can be largely substituted by the boxcar averager. Additionally, standard sound devices have I/O response issues due to anti-aliasing filters. While simple waveform viewing is fine, quantifying exact rise/fall times could lead to misleading interpretations.
* **Spectrum Analyzer: THD Hot-Tracking:** Dynamically tag and track fundamental and harmonics in real-time.
    * **Status:** Cancelled
    * **Reason:** There is already a dedicated distortion meter. Implementing this would overly complicate processing, and we want to ensure comfortable real-time operation even on low-spec PCs.

---

## 💤 Deferred / Reference (Not Planned)

* **DC Stability & Drift Logger:** Hardware is AC Coupled.
* **Wow & Flutter Meter:** Analog focus, deferred.
* **Room Acoustics (RT60) & T/S Parameters:** Acoustic focus, deferred.
* **EQ Designer & Polarity Tester:** Deferred.
* **AI-Based Audio Anomaly Detection:** No suitable API/algo found.
* **Digital Interface Analyzer (Jitter/Eye):** Requires wideband logic analyzer hardware.
