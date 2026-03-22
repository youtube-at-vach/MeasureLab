# Feature Proposals for MeasureLab

**Project Direction Update (2026):**
Focus is strictly **Signal Measurement** (analyzing audio signals, DAC/Amp performance, etc.) rather than Acoustic Measurement (speakers/rooms).

---

## 🔮 Future / Visionary Ideas (Experimental)

* **Psychoacoustic AI-MOS Predictor:** AI model that predicts Mean Opinion Score (MOS) directly from DAC/Amp output without human listeners.
* **Digital Twin Synthesizer:** Create a virtual, real-time running model of the measured analog component based on lock-in harmonic analysis.
* **Quantum Jitter Tomography:** Using QRNG excitation to measure absolute system determinism and micro-jitter.
* **Generative AI Non-Linearity Cloner:** AI model trained via specialized excitation signals to replicate exact dynamic non-linearities.
* **Brainwave (EEG) Perceptual Correlator:** Syncing auditory test signals with real-time EEG metrics.
* **Headless / Web Remote Interface:** Decouple GUI for embedded web/mobile remote monitoring.
* **AI Component Degradation Predictor:** Analyzes harmonic drift over time to predict component aging.
* **Augmented Reality (AR) Probe Visualizer:** Overlaying signal paths and distortion heatmaps onto a PCB view.
* **Real-time Active Distortion Nulling:** Synthesizing inverse distortion signals to cancel inherent non-linearities.

---

## 🚀 Active / High Priority (Signal Focus)

### 🆕 New Proposals

* **Test Sequence Automator:**
    * **Concept:** A macro engine to script and automate test sequences across multiple widgets.
    * **Why:** Enables unattended 2D/3D parameter sweeps.
* **Dynamics Processor Profiler:** Measures static I/O transfer curves and time-domain attack/release.
* **Bit-Perfect Verifier:** PRBS/watermark generator to verify 100% bit-accurate loopback.
* **Realtime/Offline Null Comparator:** Channel inversion with sub-sample delay/gain matching for difference listening.

### 🛠️ Extensions to Existing Widgets

* **Oscilloscope: CMRR/PSRR Mode:**
    * **Extension:** Dedicated Common-Mode and Power Supply Rejection Ratio calculations.
* **Spectrum Analyzer: DAC Filter Classifier:**
    * **Extension:** Automatically classify DAC reconstruction filters (Brickwall, Minimum Phase, etc.) via impulse response pre/post-ringing analysis.
* **Frequency Counter: Thermal Drift Logger:**
    * **Extension:** Long-term logging of clock frequency to evaluate oscillator temperature stability.
* **Network Analyzer: Amplifier Stability Margins:** Calculate Gain/Phase Margin from Bode plots.
* **Frequency Counter: Phase Noise Plot:** FFT-based phase deviation plot (dBc/Hz).
* **Signal Generator: Psychoacoustic Masking Tones:** Pure tone + narrow-band noise generation.
* **Impedance Analyzer: Cable Tester Mode:** Measure Capacitance/Inductance/Resistance per meter.
* **Network Analyzer: Impulse Response & Coherence:** Time-domain IR and Coherence plot.
* **Distortion/Spectrum Analyzer: J-Test & AES17:** Industry standard jitter/dynamic range automated modes.

---

## ✅ Already Implemented

* Quantization / Bit Depth Analyzer
* Crosstalk & Multitone Analyzer
* Oscilloscope Persistence / Eye Pattern
* Linearity Analyzer

---

## ⏸️ Under Review / On Hold

* Holographic Audio Topography, 3D Spectral Waterfall, Plugin System, AI Circuit Reverse Engineer, Multimeter, Cepstrum Analysis.

---

## ❌ Cancelled / Not Needed

* Step Response Analyzer, Spectrum Analyzer: THD Hot-Tracking, Multi-Channel Phase/Delay Matrix.

---

## 💤 Deferred / Reference (Not Planned)

* DC Stability & Drift Logger, Wow & Flutter Meter, Room Acoustics (RT60) & T/S Parameters, EQ Designer, AI-Based Audio Anomaly Detection, Digital Interface Analyzer.
