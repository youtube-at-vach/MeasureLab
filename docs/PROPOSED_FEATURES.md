# Feature Proposals for MeasureLab

**Project Direction Update (2026):**
Focus is strictly **Signal Measurement** (analyzing audio signals, DAC/Amp performance, etc.) rather than Acoustic Measurement (speakers/rooms).

---

## 🔮 Future / Visionary Ideas (Experimental)

* **Generative AI Non-Linearity Cloner:** AI model trained via specialized excitation signals to replicate exact dynamic non-linearities/phase of analog gear.
* **Brainwave (EEG) Perceptual Correlator:** Syncing auditory test signals with real-time EEG metrics to measure perceived distortion versus mathematical distortion.
* **Headless / Web Remote Interface:** Decouple GUI for embedded (Raspberry Pi) web/mobile remote monitoring.
* **AI Component Degradation Predictor:** Analyzes harmonic drift over time to predict capacitor aging or thermal degradation in analog circuits before catastrophic failure.
* **Augmented Reality (AR) Probe Visualizer:** Overlaying signal paths, voltage levels, and distortion heatmaps directly onto a physical PCB view using a smartphone/webcam in real-time.
* **Real-time Active Distortion Nulling:** Synthesizing inverse distortion signals in real-time to cancel out inherent DAC/Amp non-linearities, pushing physical hardware beyond its specified limits.

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
* **Signal Generator & Spectrum Analyzer: J-Test Jitter Analysis:**
    * **Extension:** Add standard J-Test signal (fs/4 + low level toggle) to Generator and high-resolution zoomed view to Analyzer.
    * **Why:** Industry standard for evaluating DAC clock jitter without needing dedicated hardware analyzers.
* **Distortion Analyzer / Noise Profiler: AES17 Dynamic Range Mode:**
    * **Extension:** Add -60dBFS excitation and CCIR-2k weighting filter to automate standard DAC Dynamic Range measurements.
    * **Why:** Essential for modern DAC evaluation, currently requires manual calculation from noise floors.

---

## ✅ Already Implemented

* **Quantization / Bit Depth Analyzer** (Settings)
* **Crosstalk & Multitone Analyzer** (`NetworkAnalyzer` / `AdvancedDistortionMeter`)
* **Oscilloscope Persistence / Eye Pattern** (`Oscilloscope`)
* **Linearity Analyzer**

---

## ⏸️ Under Review / On Hold

* **Holographic Audio Topography:** On Hold (Current PC specs cannot smoothly drive 3D rendering).
* **3D Spectral Waterfall:** On Hold (Room acoustic tools like REW already exist).
* **Plugin / Scripting System:** On Hold (Core architecture needs finalization first).
* **AI Circuit Topology Reverse Engineer:** Under Investigation (Feasibility research ongoing).
* **Multimeter (AC Voltmeter):** Under Consideration (Exploring broader approaches).
* **Spectrum Analyzer: Cepstrum Analysis:** Under Consideration (May move to a dedicated vibration analysis widget).

---

## ❌ Cancelled / Not Needed

* **Step Response Analyzer:** Cancelled (Substitutable by Boxcar averager; anti-aliasing filters distort step responses).
* **Spectrum Analyzer: THD Hot-Tracking:** Cancelled (Dedicated distortion meter exists; real-time performance concerns).
* **Multi-Channel Phase/Delay Matrix:** Cancelled (Substitutable by `Network Analyzer` and `Oscilloscope` phase correlation features).

---

## 💤 Deferred / Reference (Not Planned)

* **DC Stability & Drift Logger:** Deferred (Hardware is AC Coupled).
* **Wow & Flutter Meter:** Deferred (Analog focus).
* **Room Acoustics (RT60) & T/S Parameters:** Deferred (Acoustic focus).
* **EQ Designer & Polarity Tester:** Deferred.
* **AI-Based Audio Anomaly Detection:** Deferred (No suitable API/algo).
* **Digital Interface Analyzer (Jitter/Eye):** Deferred (Requires logic analyzer hardware).
