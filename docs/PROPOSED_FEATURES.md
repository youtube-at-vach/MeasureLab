# Feature Proposals and Implementation Audit

## Overview

Last audited against the current implementation: 2026-08-13.

## Scope and Selection Policy

> [!IMPORTANT]
> **Core Principle**
> Accurate measurement, free of charge, and all features available to everyone.

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

### 1. Signal Integrity Logger

**Target:** Event Detector and AudioEngine.

**Scope:** Record XRUN timeline with categories, distinguish backend XRUNs from signal discontinuity, add dropout/click/pop classification, and export integrity incidents.

### 2. SMPTE, DIN, and CCIF IMD Sweeps

**Target:** Distortion Analyzer.

**Scope:** Add amplitude sweeps for SMPTE, DIN, and CCIF modes, store IMD percentages/levels per step, and warn when approaching bandwidth limits.

### 3. True-Peak Histogram and Clipping Profiler

**Target:** LUFS Meter.

**Scope:** Add per-channel True-Peak histograms, count threshold exceedances, measure longest continuous exceedances, and compare Sample Peak vs True Peak.

### 4. Automatic Peak Markers

**Target:** Spectrum Analyzer.

**Scope:** Mark the highest configurable number of peaks applying prominence and noise-floor thresholds.

### 5. AES17 Dynamic Range Automator

**Target:** Distortion Analyzer.

**Scope:** Combine calibration, validation, settling, averaging, measurement, and report generation into a guided sequence.

### 6. Long-Term Warm-up and Stability Logger

**Target:** Distortion Analyzer.

**Scope:** Report gain, THD, THD+N, noise, and frequency as warm-up or stability trends.

### 7. Real-time Psychoacoustic Masking Overlay

**Target:** Spectrum Analyzer.

**Scope:** Visualize human auditory perception by overlaying simultaneous and temporal masking curves in real-time, showing what is audible versus raw FFT data. (Extended from visionary concepts).

### 8. Haptic Audio Synchronization Profiler

**Target:** Network Analyzer.

**Scope:** Add a "Subwoofer/Haptic Mode" with ultra-low frequency logarithmic sweeps (1-100Hz) and specialized group delay alignment visualization to measure tactile transducer latency. (Extended from visionary concepts).

### 9. Spatial 3D Soundstage Mapper

**Target:** Stereo Alignment Monitor.

**Scope:** Add a 3D soundstage visualization tab using Mid/Side analysis and HRTF deconvolution to map the perceived spatial position of sound sources in real-time. (Extended from visionary concepts).

## Future / Visionary Ideas

These ideas explore adventurous, next-generation concepts beyond standard audio measurement. They are currently brainstormed without constraints to expand future possibilities.

* **AI-Driven Automated Measurement Recipe Generator:** Use AI to listen to a brief sweep and automatically configure the optimal distortion, impedance, and alignment measurements for the connected DUT.
* **Brain-Computer Interface (BCI) Audiophile Profiler:** Measure human brainwave responses to different DACs/Amps to quantify perceptual audio quality directly from the listener.
* **Quantum Audio Entropy Analyzer:** Analyze the true randomness of analog noise floors using quantum mechanics models to classify analog noise sources versus digital dithering artifacts.
* **Holographic Soundstage Visualizer:** A fully immersive VR/AR holographic representation of sound topology.

## Confirmed Implemented or Covered Features

| Original proposal | Current implementation | Audit result |
| --- | --- | --- |
| Group/Phase Delay Plot | Network Analyzer calculates `-dPhi / (2*pi*dF)`. | Implemented. |
| Frequency-Dependent Crosstalk/Leakage | Network Analyzer provides L-to-R/R-to-L sweeps. | Implemented. |
| Pre-Ringing and Causality Quantifier | Transient Analyzer measures DAC Ringing. | Implemented. |
| True Peak | LUFS Meter performs oversampling and peak hold. | Implemented (histogram remains). |
| SMPTE and CCIF IMD | Distortion Analyzer handles both in real time. | Implemented (sweeps remain). |
| AES17 Dynamic Range | Distortion Analyzer includes calibration and filter. | Implemented (automation remains). |
| Continuity/Data-Gap Detection | AudioEngine tracks XRUNs; Event Detector records validity. | Partially implemented. |
| Volterra Kernel Extractor | Nonlinear Analyzer extracts Parallel Hammerstein kernels. | Covered. |
| Inter-Channel Phase Analysis | Stereo Alignment Monitor displays correlation and phase. | Implemented. |
| Binaural Tones | Signal Generator has independent L/R settings. | Covered. |
| DAC Digital Filter Classification | Transient Analyzer measures DAC ringing. | Partially covered. |
| Cumulative Spectral Visualization | Transient Analyzer provides CWT scalogram. | Covered. |

## Conditional Candidates

Useful only when measurement conditions are explicitly defined:

* **Thiele/Small Parameter Extraction** (Target: Impedance Analyzer)
* **Hum AM/FM Modulation Analysis** (Target: Noise Profiler)
* **Dynamic Burst Linearity** (Target: Linearity Analyzer)
* **Null Comparator** (Target: Recorder/Player / Transmission Analyzer)
* **Dynamics Processor Profiler** (Static gain compression available in Response Viewer)

## On Hold or Not Suitable

* **Bandwidth- and Slew-Limited Measurements:** TIM/DIM Mode, Slew Rate Calculator, Eye Diagram, Digital Protocol Decoder, DAC Aliasing and OOB Leakage, Ultrasonic Micro-Doppler.
* **Clock and Jitter Attribution:** TIE Jitter, Phase Noise Density, Clock Fingerprinting, Inter-Channel Sync Drift Logger.
* **Fixture- or Hardware-Dominated:** Damping Factor Profiler, Dual-ADC Cross-Correlation Noise, Thermal Stress, EMI/RFI Fingerprinting, Complex Load Distortion.
* **Outside Current Focus:** Lossy Codec Analyzer, Listener Fatigue Index, PEAQ/ODG Estimator, AI Circuit Reverse Engineer, Acoustic Metamaterial Simulator.

## Deferred Reference Topics

The following remain reference topics rather than active implementation proposals:

* ASRC Benchmark.
* DC Stability.
* Wow and Flutter.
* Room Acoustics and RT60.
* EQ Designer.
* AI Anomaly Detection.
* Plugin System.
* Multimeter.
* Cepstrum Analysis.
