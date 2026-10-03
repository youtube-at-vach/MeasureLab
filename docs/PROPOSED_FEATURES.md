# Feature Proposals and Implementation Audit

## Overview

Audited and updated with the latest visionary and practical extensions.
This document prioritizes accurate measurement, free of charge, and full availability. It emphasizes extending existing widgets before adding new instruments.

## Scope and Selection Policy

> [!IMPORTANT]
> **Core Principle**
> Accurate measurement, free of charge, and all features available to everyone.

Focus on real-time offline analysis, performance optimization, robustness against noise, UI/UX improvements, and multi-language support.

## Selected Additions to Existing Widgets

### Network Analyzer

* **Output Impedance and Load Interaction:** Capture sweeps with known resistive loads to derive complex source impedance versus frequency.
* **Difference with Repeatability:** Group repeated A/B acquisitions and display mean gain difference alongside repeat scatter.

### Distortion Analyzer

* **Signal-Level Residual Map:** Measure level-dependent residual spectrum with explicit tone exclusion.
* **IMD Amplitude Sweeps:** Route amplitude sweeps through selected IMD analysis, storing IMD percent/dB together.

### Spectrogram

* **Transient / Onset Highlighting:** Add visual overlays to highlight sudden transient events (clicks/pops) based on short-term energy changes.

### Sound Level Meter

* **Event-Triggered Audio Capture:** Automatically trigger short audio recordings (e.g., 5s before/after) when instantaneous SPL exceeds a threshold.

### Sound Quality Analyzer

* **Demographic Hearing Loss Overlay:** Extend the analyzer to apply ISO 7029 age-based hearing threshold curves, visualising the "perceived" spectrum and loudness for different age demographics. (Transitioned from Visionary Ideas after implementability check).

## Future / Visionary Ideas

These ideas require concrete experiments before promotion.

* **Global Hardware Baseline Network:** Anonymously share and compare interface performance (noise floor, THD) globally to detect hardware degradation. (Requires external infrastructure).
* **Generative Adversarial Stimulus:** AI dynamically alters a test signal to specifically target and excite a DUT's weaknesses based on real-time feedback. (Highly experimental AI logic).
* **Acoustic Material Transfer Simulator:** Use neural networks to capture the non-linear material response of an object and apply it live to incoming audio.
* **Two-Input Noise Microscope:** Extract weak shared noise using synchronized input channels averaging complex cross-spectra.
* **Model Challenge Bench:** Extend Response Viewer with held-out frequency probes and prediction-error maps.
* **Time-Reversal Focus Experiment:** Replay an energy-normalized reversed IR and measure spatial concentration.
* **Spatial Acoustic Holography Viewer:** Visualize 3D acoustic fields using tracked microphones.
* **Psychoacoustic Sweet-Spot Visualizer:** Map optimal spatial imaging areas using binaural ITD/ILD metrics.
* **Perceptual Audio-Lens:** Separate and measure individual sources from a complex mixture using AI.

## Audit of Earlier Candidates

| Earlier candidate | Current disposition and evidence |
| --- | --- |
| True-Peak Histogram / Clipping Profiler | **Covered:** `LUFS Meter` has histogram, SP/TP intervals. |
| L10/L50/L90 | **Covered:** `Sound Level Meter` statistics UI. |
| Auto-peak markers | **Covered:** `Spectrum Analyzer` display/raw modes. |
| Multitone TD+N; Cable LCR Extractor | **Covered:** `Advanced Distortion Meter`, `Impedance Analyzer`. |
| AES17 automator; warm-up logger | **Retained, lower priority:** Automate calibration sequence. |
| XRUN timeline | **Partial:** `Event Detector` marks gaps. |
| RMS Volume History Graph | **Covered / Rejected:** `Sound Level Meter` SPL history and `LUFS Meter` already provide this functionality perfectly. |

### Other Earlier Vision Seeds (Not Scheduled)

Preserved for later workers, without treating speculation as a measurement capability:

* Psycho-Acoustic Emotional Impact Scorer
* AI-Driven Measurement Recipe Generator
* AI Golden Ear Component Fingerprinter
* Temporal Audio Micro-Lens
* Neuromorphic & Quantum Analysis
* Synesthetic Measurement Mapper / Haptic Translator
* Ultrasonic Acoustic Levitation Calibrator
* Holographic/AR Acoustic Mode visualization
* Bio-Acoustic Impedance Sonifier
* Brain-Computer Interface Audiophile Profiler

## Previously Audited / Rejected / On Hold

Items reviewed and either implemented, conditionally approved, put on hold, or deemed not suitable for the current focus. They remain here for historical context.

* **Implemented/Covered:** Group/Phase Delay, Frequency-Dependent Crosstalk, Pre-Ringing, True Peak, IMD, AES17, Volterra Kernel, Inter-Channel Phase, Binaural Tones, DAC Filters, Cumulative Spectral.
* **Partially Implemented:** Continuity/Data-Gap Detection.
* **Conditional:** Thiele/Small Extraction, Hum AM/FM, Dynamic Burst Linearity, Null Comparator, Dynamics Processor Profiler.
* **On Hold / Not Suitable:** Bandwidth- and Slew-Limited, Clock/Jitter Attribution, Hardware-Dominated tests, Lossy Codec, Listener Fatigue Index, PEAQ/ODG Estimator, AI Circuit Reverse Engineer, Acoustic Metamaterial Simulator.
* **Deferred Reference Topics:** ASRC Benchmark, DC Stability, Wow and Flutter, RT60, EQ Designer, AI Anomaly, Plugin System, Multimeter, Cepstrum Analysis.
