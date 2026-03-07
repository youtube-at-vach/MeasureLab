# Feature Proposals for MeasureLab

**Project Direction Update (2026):**
Focus is strictly **Signal Measurement** (analyzing audio signals, DAC/Amp performance, etc.) rather than Acoustic Measurement (speakers/rooms).

---

## 🔮 Future / Visionary Ideas (Experimental)

* **Generative AI Non-Linearity Cloner:** AI model trained via specialized excitation signals to replicate exact dynamic non-linearities/phase of analog gear.
* **Holographic Audio Topography:** 3D spherical evolution of Goniometer visualizing phase, amplitude, and frequency mapping.
* **Brainwave (EEG) Perceptual Correlator:** Syncing auditory test signals with real-time EEG metrics to measure perceived distortion versus mathematical distortion.
* **AI Circuit Topology Reverse Engineer:** Analyzes extreme complex test signal responses (e.g., dynamic IMD) to predict the internal analog circuit topology (Class A vs A/B, feedback depth, capacitor types).
* **Headless / Web Remote Interface:** Decouple GUI for embedded (Raspberry Pi) web/mobile remote monitoring.
* **Plugin / Scripting System:** Python hooks for custom DSP audio buffer processing.
* **3D Spectral Waterfall:** Spectrogram extension adding Z-axis depth for resonance decay.

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
* **Multimeter (AC Voltmeter):**
    * **Concept:** Dedicated digital multimeter widget (Vrms, Vpeak, Crest Factor, Freq, Phase).
* **Step Response Analyzer:**
    * **Concept:** Transient analysis via band-limited steps to measure Rise/Fall Time and Overshoot for DAC filters.

### 🛠️ Extensions to Existing Widgets

* **Network Analyzer: Amplifier Stability Margins:**
    * **Extension:** Calculate and display Gain Margin (dB) and Phase Margin (degrees) from Bode plots.
    * **Why:** Critical for evaluating custom amplifier stability under complex loads.
* **Spectrum Analyzer: THD Hot-Tracking:**
    * **Extension:** Dynamically tag and track the fundamental peak and its Nth harmonics in real-time, displaying a floating THD estimate directly on the plot.
    * **Why:** Instant visual feedback without needing the full Distortion Analyzer sweep.
* **Frequency Counter: Phase Noise Plot:**
    * **Extension:** FFT-based phase deviation plot (dBc/Hz).
* **Signal Generator: Psychoacoustic Masking Tones:**
    * **Extension:** Pure tone + narrow-band noise generation modes.
* **Impedance Analyzer: Cable Tester Mode:**
    * **Extension:** Measure Capacitance, Inductance, and Resistance per meter.
* **Network Analyzer: Impulse Response & Coherence:**
    * **Extension:** Time-domain IR and 0.0-1.0 Coherence plot.
* **Spectrum Analyzer: Cepstrum Analysis:**
    * **Extension:** "Cepstrum" mode for pitch and harmonic structure analysis.

---

## ✅ Already Implemented

* **Quantization / Bit Depth Analyzer** (Settings)
* **Crosstalk & Multitone Analyzer** (`NetworkAnalyzer` / `AdvancedDistortionMeter`)
* **Oscilloscope Persistence / Eye Pattern** (`Oscilloscope`)
* **Linearity Analyzer**

---

## 💤 Deferred / Reference (Not Planned)

* **DC Stability & Drift Logger:** Hardware is AC Coupled.
* **Wow & Flutter Meter:** Analog focus, deferred.
* **Room Acoustics (RT60) & T/S Parameters:** Acoustic focus, deferred.
* **EQ Designer & Polarity Tester:** Deferred.
* **AI-Based Audio Anomaly Detection:** No suitable API/algo found.
* **Digital Interface Analyzer (Jitter/Eye):** Requires wideband logic analyzer hardware.
