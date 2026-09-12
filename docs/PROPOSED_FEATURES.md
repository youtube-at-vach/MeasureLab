# Feature Proposals and Implementation Audit

## Overview

Last audited against the current implementation: 2026-08-13.

## Scope and Selection Policy

> [!IMPORTANT]
> **Core Principle**
> Accurate measurement, free of charge, and all features available to everyone.

MeasureLab focuses on signal measurement for audio devices, DACs, amplifiers, and related analog paths. Features should be meaningful on common 44.1/48 kHz devices, distinguish the DUT from the measurement interface, and prefer relative two-channel measurements. Sound device diagnostics are acceptable if clearly presented as such.

## Status Legend

* **Implemented / Partially implemented**: User-facing measurement is present or core exists.
* **Selected**: Suitable for addition to an existing widget.
* **Conditional**: Useful only with restricted use cases.
* **On hold / Not suitable**: Not selected or outside current scope.

## Selected Additions to Existing Widgets

Highest-value remaining additions grouped by target widgets.

### 1. Distortion Analyzer Extensions

* **SMPTE, DIN, and CCIF IMD Sweeps:** Amplitude sweeps storing IMD percentages/levels.
* **AES17 Dynamic Range Automator:** Sequence for calibration, validation, and measurement.
* **Long-Term Warm-up and Stability Logger:** Trend tracking for gain and THD.
* **Multi-Tone Distortion (TD+N) & Doppler (Phase IMD) Profilers:** Simultaneous noise/distortion evaluation and driver excursion demodulation.
* **Class-D Switching Artifact Profiler:** Sweep for out-of-band switching noise and aliasing common in Class-D amplifiers. (NEW)

### 2. LUFS & Sound Level Meter Extensions

* **True-Peak Histogram and Clipping Profiler:** Histogram and exceedance tracking.
* **Percentile Noise Statistics (L10/L50/L90):** Environmental noise tracking over time.

### 3. Spectrum & Transient Analyzer Extensions

* **Peak & Dynamics Profilers:** Auto-peak markers, Burst Envelope Dynamics, and Micro-dynamics Profiler for punchiness.
* **Psychoacoustic Masking Overlay:** Real-time human auditory perception curves.

### 4. Network & Impedance Analyzer Extensions

* **Specialized Measurements:** Haptic Audio Sync Profiler, Thermal Power Compression Logger (Re drift), and Cable LCR Extractor.
* **Loudspeaker Polar/Directivity 3D Plotter:** Automated turntable control and multi-angle acoustic response capturing. (NEW)

### 5. Integrity & Spatial Visualization

* **Integrity Logger & Audiograms:** XRUN timeline (Event Detector) and Interactive Psychoacoustic Audiograms.
* **Spatial & 3D Mapping:** HRTF deconvolution (Stereo Alignment Monitor) and 6DOF Head-Tracking Room Simulation (Spatial Binaural Mixer).

## Future / Visionary Ideas

Adventurous, next-generation concepts beyond standard audio measurement, currently brainstormed without constraints.

* **Psycho-Acoustic Emotional Impact Scorer:** Analyze the signal to estimate human emotional response (e.g. excitement, relaxation) based on frequency content, tempo, and dynamic range.
* **Temporal Audio Micro-Lens:** Use AI to interpolate and visualize acoustic events that happen between the samples (shorter than a single sample).
* **Neuromorphic & Quantum Analysis:** Event-based audio transient capture and quantum mechanics modeling for true randomness of noise floors.
* **Multimodal & Spatial:** Synesthetic Measurement Mapper (haptics/visuals), Ultrasonic Acoustic Levitation Calibrator, and Holographic/AR Acoustic Mode visualization.
* **AI & Automation:** AI-Driven Measurement Recipe Generator, AI Golden Ear Component Fingerprinter.
* **Bio & BCI Interfaces:** Bio-Acoustic Impedance Sonifier, Brain-Computer Interface (BCI) Audiophile Profiler.

## Previously Audited / Rejected / On Hold

Items reviewed and either implemented, conditionally approved, put on hold, or deemed not suitable for the current focus. They remain here for historical context.

* **Implemented/Covered:** Group/Phase Delay, Frequency-Dependent Crosstalk, Pre-Ringing, True Peak, IMD, AES17, Volterra Kernel, Inter-Channel Phase, Binaural Tones, DAC Filters, Cumulative Spectral.
* **Partially Implemented:** Continuity/Data-Gap Detection.
* **Conditional:** Thiele/Small Extraction, Hum AM/FM, Dynamic Burst Linearity, Null Comparator, Dynamics Processor Profiler.
* **On Hold / Not Suitable:** Bandwidth- and Slew-Limited, Clock/Jitter Attribution, Hardware-Dominated tests, Lossy Codec, Listener Fatigue Index, PEAQ/ODG Estimator, AI Circuit Reverse Engineer, Acoustic Metamaterial Simulator.
* **Deferred Reference Topics:** ASRC Benchmark, DC Stability, Wow and Flutter, RT60, EQ Designer, AI Anomaly, Plugin System, Multimeter, Cepstrum Analysis.
