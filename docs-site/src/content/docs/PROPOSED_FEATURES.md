---
title: "Feature Proposals and Implementation Audit"
---

## Overview

Last audited against the current implementation: 2026-08-13.

## Scope and Selection Policy

:::note
**Core Principle**

Accurate measurement, free of charge, and all features available to everyone.
:::

MeasureLab focuses on signal measurement for audio devices, DACs, amplifiers,
and related analog paths. Feature selection follows these rules:

* The result should remain meaningful on common 44.1 kHz and 48 kHz audio
  devices whenever possible.
* Optional high sample rates do not imply that every device has a flat or
  calibrated measurement bandwidth near Nyquist.
* A measurement should distinguish the device under test from the DAC, ADC,
  clock, driver, and analog front end used by MeasureLab.
* Relative two-channel measurements are preferred when they can remove the
  measurement interface response.
* Features that mainly measure the sound device itself are acceptable only
  when they are clearly presented as sound-device diagnostics.

## Status Legend

* **Implemented**: The user-facing measurement is already present.
* **Partially implemented**: The core measurement exists, but the proposed
  workflow, aggregation, or presentation is incomplete.
* **Selected**: Suitable for addition to an existing widget and expected to
  produce meaningful results on common audio devices.
* **Conditional**: Useful only with a defined fixture, reference path, or
  restricted use case.
* **On hold**: Not selected for the current measurement-focused roadmap.
* **Not suitable**: The result is too dependent on measurement hardware or is
  outside the current scope.

## Selected Additions to Existing Widgets

These are the highest-value remaining additions after comparison with the
current implementation.

### 1. Distortion Analyzer Extensions

* **SMPTE, DIN, and CCIF IMD Sweeps:** Add amplitude sweeps and store IMD percentages/levels.
* **AES17 Dynamic Range Automator:** Combine calibration, validation, and measurement into a sequence.
* **Long-Term Warm-up and Stability Logger:** Report gain and THD trends over time.
* **Multi-Tone Distortion (TD+N) Profiler:** Measure total distortion and noise simultaneously across the spectrum.
* **Doppler Distortion (Phase IMD) Profiler:** Demodulate high-frequency carriers modulated by low-frequency driver excursion to measure Doppler distortion.

### 2. LUFS & Sound Level Meter Extensions

* **True-Peak Histogram and Clipping Profiler:** Add True-Peak histograms and count threshold exceedances (LUFS Meter).
* **Percentile Noise Statistics (L10/L50/L90):** Track environmental noise percentiles over time (Sound Level Meter).

### 3. Spectrum & Transient Analyzer Extensions

* **Automatic Peak Markers:** Mark peaks applying prominence and noise-floor thresholds.
* **Real-time Psychoacoustic Masking Overlay:** Visualize human auditory perception masking curves.
* **Burst Envelope Dynamics Profiler:** Measure attack/release envelopes and gain reduction recovery curves.

### 4. Network & Impedance Analyzer Extensions

* **Haptic Audio Synchronization Profiler:** Low-frequency sweeps to measure tactile transducer latency.
* **Thermal Power Compression Logger:** Track DC resistance (Re) drift over long sweeps to estimate voice coil temperature.

### 5. Integrity & Spatial Visualization

* **Signal Integrity Logger:** Record XRUN timeline, categorize discontinuities (Event Detector).
* **Spatial 3D Soundstage Mapper:** HRTF deconvolution to map perceived spatial positions (Stereo Alignment Monitor).
* **Interactive Psychoacoustic Audiogram:** Apply personalized equal-loudness contours to analysis (Sound Quality Analyzer).

## Future / Visionary Ideas

These ideas explore adventurous, next-generation concepts beyond standard audio measurement. They are currently brainstormed without constraints to expand future possibilities.

* **Ultrasonic Acoustic Levitation Calibrator:** Phase-aligning 40kHz ultrasonic channels to create 3D acoustic levitation focal points in mid-air.
* **Bio-Acoustic Impedance Sonifier:** Measuring micro-fluctuations in organic subjects (e.g., plants) and sonifying them via high-resolution parameter mapping.
* **AI-Driven Automated Measurement Recipe Generator:** Use AI to listen to a brief sweep and automatically configure the optimal distortion, impedance, and alignment measurements for the connected DUT.
* **Brain-Computer Interface (BCI) Audiophile Profiler:** Measure human brainwave responses to different DACs/Amps to quantify perceptual audio quality directly from the listener.
* **Quantum Audio Entropy Analyzer:** Analyze the true randomness of analog noise floors using quantum mechanics models to classify analog noise sources versus digital dithering artifacts.
* **Holographic Soundstage Visualizer:** A fully immersive VR/AR holographic representation of sound topology.
* **Augmented Reality (AR) Acoustic Mode Mapper:** Project visual room modes and nulls onto a physical space using AR glasses to optimize speaker placement.
* **AI Golden Ear Component Fingerprinter:** Identify specific op-amps, capacitors, or vacuum tube models in a circuit strictly by analyzing the micro-nonlinearities and harmonic signature.

## Previously Audited / Rejected / On Hold

The following items have been reviewed and either implemented, conditionally approved, put on hold, or deemed not suitable for the current focus. They remain here for historical context.

* **Implemented/Covered:** Group/Phase Delay Plot, Frequency-Dependent Crosstalk/Leakage, Pre-Ringing and Causality Quantifier, True Peak, SMPTE and CCIF IMD, AES17 Dynamic Range, Volterra Kernel Extractor, Inter-Channel Phase Analysis, Binaural Tones, DAC Digital Filter Classification, Cumulative Spectral Visualization.
* **Partially Implemented:** Continuity/Data-Gap Detection.
* **Conditional Candidates:** Thiele/Small Parameter Extraction, Hum AM/FM Modulation Analysis, Dynamic Burst Linearity, Null Comparator, Dynamics Processor Profiler.
* **On Hold / Not Suitable:** Bandwidth- and Slew-Limited Measurements, Clock and Jitter Attribution, Fixture- or Hardware-Dominated tests, Lossy Codec Analyzer, Listener Fatigue Index, PEAQ/ODG Estimator, AI Circuit Reverse Engineer, Acoustic Metamaterial Simulator.
* **Deferred Reference Topics:** ASRC Benchmark, DC Stability, Wow and Flutter, Room Acoustics and RT60, EQ Designer, AI Anomaly Detection, Plugin System, Multimeter, Cepstrum Analysis.
