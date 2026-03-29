# Feature Proposals for MeasureLab

**Project Direction Update (2026):**
Focus is strictly **Signal Measurement** (analyzing audio signals, DAC/Amp performance, etc.) rather than Acoustic Measurement (speakers/rooms).

---

## 🔮 Future / Visionary Ideas (Experimental)

* **Psychoacoustic AI-MOS Predictor:** AI model predicting MOS from DAC/Amp output without listeners.
* **Digital Twin Synthesizer:** Virtual, real-time model of analog components via lock-in analysis.
* **Quantum Jitter Tomography:** QRNG excitation to measure absolute determinism and micro-jitter.
* **Generative AI Non-Linearity Cloner:** AI model replicating dynamic non-linearities via specialized signals.
* **Brainwave (EEG) Perceptual Correlator:** Syncing test signals with real-time EEG metrics.
* **Headless / Web Remote Interface:** Decouple GUI for embedded web/mobile monitoring.
* **AI Component Degradation Predictor:** Analyzes harmonic drift to predict aging.
* **Augmented Reality (AR) Probe Visualizer:** Overlaying signal paths/distortion onto PCB views.
* **Real-time Active Distortion Nulling:** Synthesizing inverse signals to cancel non-linearities.
* **Neuromorphic Codec Evaluator:** Brain-inspired spiking neural network processing to evaluate lossy codec transparency in real-time.
* **Holographic Intermodulation Topology:** 4D visualization of IMD products evolving dynamically through spatial multi-tone excitations.
* **Quantum Entropy Analyzer:** Statistical analysis of random noise floors to measure inherent system stochasticity and true entropy generation.

---

## 🚀 Active / High Priority (Signal Focus)

### 🆕 New Proposals

* **Test Sequence Automator:** Macro engine to script unattended 2D/3D sweeps.
* **Dynamics Processor Profiler:** Measures static I/O transfer curves and attack/release.
* **Bit-Perfect Verifier:** PRBS/watermark generator for 100% bit-accurate loopback verification.
* **Realtime/Offline Null Comparator:** Channel inversion with sub-sample matching for difference listening.
* **Wireless / Bluetooth Codec Analyzer:** End-to-end latency, jitter, and psychoacoustic degradation profiling for digital wireless audio links.

### 🛠️ Extensions to Existing Widgets

* **Oscilloscope:** Add CMRR/PSRR Mode and **Slew Rate Calculator** (automatic V/µs measurement for power amps).
* **Spectrum Analyzer:** Add DAC Filter Classifier.
* **Frequency Counter:** Add Thermal Drift Logger and Phase Noise Plot.
* **Network Analyzer:** Add Amplifier Stability Margins, Impulse Response & Coherence, and **RIAA EQ Curve Matcher** (Phono preamp RIAA deviation overlay).
* **Signal Generator:** Add Psychoacoustic Masking Tones.
* **Impedance Analyzer:** Add Cable Tester Mode.
* **Distortion Analyzer:** Add J-Test & AES17.
* **LUFS Meter:** Add **True Peak (ISKb) Detection** with inter-sample oversampling detection.

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
* **Phase/Polarity Checker:** Duplicate. Can be verified via Oscilloscope (A/B inversion) or Transient Analyzer impulse polarity.
* **Multitone THD Analyzer:** Duplicate. Covered by Advanced Distortion Meter (MIM).

---

## 💤 Deferred / Reference (Not Planned)

* DC Stability & Drift Logger, Wow & Flutter Meter, Room Acoustics (RT60) & T/S Parameters, EQ Designer, AI-Based Audio Anomaly Detection, Digital Interface Analyzer.
