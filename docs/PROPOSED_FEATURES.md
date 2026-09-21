# Feature Proposals and Implementation Audit

## Overview

Audited 2026-09-21 against checkout `8e6c15c2`; incoming proposals at locally available `origin/main` (`52ae2aea`) were also reviewed. This is a source/documentation audit, not hardware validation. The historical review record below is preserved verbatim.

## Scope and Selection Policy

> [!IMPORTANT]
> **Core Principle**
> Accurate measurement, free of charge, and all features available to everyone.

Follow the [current direction](../guide/CURRENT_DIRECTION.md): improve useful measurements and readable results on ordinary 44.1/48 kHz interfaces. Prefer relative two-channel measurements, distinguish the DUT from the acquisition path, and extend existing widgets before adding another instrument. Follow the [design boundaries](../guide/MEASUREMENT_INSTRUMENT_DESIGN_GUIDELINES.md#15-理想的な測定器と実装要件の境界); do not add duplicate background monitoring.

**Proposed** means ready for review, not approved or scheduled. **Vision** requires an experiment before promotion. **Covered** rejects a duplicate proposal. Historical rejected/deferred topics remain inactive; new audit judgments below do not imply a human review decision.

## Proposed Extensions

Three new proposals, followed by one clarified existing proposal. No new standalone widget is justified by this audit.

### 1. Output Impedance and Load Interaction — Network Analyzer

* **Question:** Will a headphone or line output change its frequency response with a different load? Capture two sweeps with manually exchanged known resistive loads and a common input reference. Derive complex source impedance versus frequency; optionally use a measured load impedance to predict its voltage-divider response.
* **Existing / missing:** [Network Analyzer](widgets/network_analyzer.en.md) supplies XFER, phase and references; [Impedance Analyzer](widgets/impedance_analyzer.en.md) measures passive loads using a shunt. Neither derives an active output's source impedance from two loaded transfer functions. Add a paired-load mode to Network Analyzer, reusing its acquisition and plots.
* **First delivery / proof:** Start with low-voltage, single-ended outputs, two entered effective loads including analyzer input loading, unchanged gain and common phase alignment. Show the measured response difference even when source impedance is unresolved. Validate with a known series resistor and predict a third load; mark ill-conditioned results when the difference is within repeat scatter. Bridged/power outputs and load-dependent nonlinear behavior are outside this first model.

### 2. Signal-Level Residual Map — Distortion Analyzer

* **Question:** Does the noise remaining between tones rise when a DAC or amplifier reproduces a signal? Add a fixed-frequency level sequence with quiet captures before/after it; show residual power density versus frequency and stimulus level, plus band-integrated absolute residual levels.
* **Existing / missing:** [Noise Profiler](widgets/noise_profiler.en.md) characterizes the selected input; Distortion Analyzer reports THD+N; [Advanced Distortion Meter](widgets/advanced_distortion_meter.en.md) already measures multitone TD+N. The new result is the level-dependent residual spectrum with explicit tone/harmonic exclusion, not another aggregate distortion score. Reuse the distortion sweep and shared spectral calculations.
* **First delivery / proof:** Keep ADC gain, bandwidth, FFT window and exclusion bands fixed; average linear power and report the retained bandwidth. Include a matching loopback baseline without subtracting distortion powers. Test constant-noise and amplitude-dependent-noise signals, plus off-bin leakage. Label the result “residual,” since unresolved spurs remain; quiet auto-muting and interface noise prevent automatic DUT attribution. [Audio Precision explains why idle noise and noise in a signal's presence differ](https://www.ap.com/category/news/signal-to-noise-ratio-snr-dynamic-range-and-noise).

### 3. Difference with Repeatability — Plot Comparer

* **Question:** Is a small response change larger than this setup's run-to-run variation? Group repeated A/B acquisitions and display their mean gain difference alongside each group's repeat scatter, retaining every original trace.
* **Existing / missing:** [Plot Comparer](widgets/plot_comparer.en.md) overlays, normalizes and exports traces; Network Analyzer applies a reference. Neither groups independent runs or computes their spread. Add offline comparison of unsmoothed Network Analyzer gain traces first; this needs no new acquisition widget.
* **First delivery / proof:** Show run count and sample standard deviation, not an audibility or full-uncertainty verdict. Require compatible frequency coverage and acquisition settings; extend exported metadata with rate, level, gain/calibration identity and quality flags. Missing metadata stays “unverified”; no extrapolation or implicit normalization. Verify identical runs, a known gain shift, missing bins and mismatched settings. Manual repeat capture is enough for the first version.

### 4. IMD Amplitude Sweeps — Distortion Analyzer (Carried Forward)

[The implementation](../src/gui/widgets/distortion_analyzer.py) has SMPTE/CCIF real-time metrics, but `SweepWorker.run()` calls harmonic analysis and sweep plots/exports read THD+N fields. Route amplitude sweeps through the selected IMD analysis, store IMD percent/dB and actual tone frequencies/ratio, and update plots/export together. Validate against the same captured signal's real-time result. Treat DIN as a separately specified preset/metric, not an already supported standard. This is the smallest implementation candidate; AES17 measurement itself is already present.

## Future / Visionary Ideas

These ideas are separated from the implementation candidates. Each has a concrete experiment and a reuse check.

### Two-Input Noise Microscope — New Vision

Make weak shared noise emerge as two synchronized input channels average complex cross-spectra. Noise Profiler currently averages one channel's magnitude; this would be a new estimator there, not another spectrum widget. [Published low-frequency experiments](https://arxiv.org/abs/1408.2470) support the principle, but do not establish performance on consumer interfaces. First test known common noise plus independent noise, then a split physical source. Display both auto-spectra, cross-spectrum phase/sign and convergence. Shared interference, loading and [cross-spectral cancellation](https://www.nist.gov/publications/phase-inversion-and-collapse-cross-spectral-function) must be characterized before claiming a lower usable noise floor.

### Model Challenge Bench — New Vision

Let a measured model propose where it might be wrong, then ask the real DUT. Extend [Response Viewer](widgets/response_viewer.en.md) with held-out frequency/level probes and a prediction-error map; select additional probes within user-set output limits. Existing THD maps, simulations and adaptive predistortion already cover modeling and correction. The new capability is independent experimental validation and adaptive probe selection. First demonstrate a known virtual model passing, and an intentionally inadequate model failing; retain measured, predicted and unexplored regions separately. This neither infers circuit topology nor replaces the deferred generic AI-anomaly proposal.

### Time-Reversal Focus Experiment — Refined Existing Vision

Turn the existing focusing idea into a measurable experiment: reuse Network Analyzer's impulse response and Recorder & Player to replay an energy-normalized reversed response, then measure concentration at the target and nearby positions. [Single-loudspeaker focusing has been demonstrated](https://pubmed.ncbi.nlm.nih.gov/28764440/), but a captured room response is not a guarantee of a spatially isolated focus. The missing extension is paired capture/replay and spatial verification. Promote only after a repeatable low-level test with unchanged geometry; do not promise levitation or a universal inverse filter.

## Audit of Earlier Candidates

| Earlier candidate | Current disposition and evidence |
| --- | --- |
| True-Peak Histogram / Clipping Profiler | **Covered:** [LUFS Meter](widgets/lufs_meter.en.md) has histogram, SP/TP intervals and incomplete-run flags. |
| L10/L50/L90 | **Covered:** [Sound Level Meter](../src/gui/widgets/sound_level_meter.py), `calculate_ln_statistics()` and statistics UI. |
| Auto-peak markers | **Covered:** [Spectrum Analyzer](../src/gui/widgets/spectrum_analyzer.py), `configure_peak_markers()`, display/raw modes. |
| Multitone TD+N; Cable LCR Extractor | **Covered:** Advanced Distortion Meter MIM; Impedance Analyzer L/C/R, OSL and sweep. A specialized name adds no measurement. |
| AES17 automator; warm-up/stability logger | **Retained, lower priority:** automate the existing calibration/measurement sequence; separately retain periodic gain/THD with acquisition conditions. Neither requires a new widget. |
| XRUN timeline | **Partial:** Event Detector already marks gaps and censored events; only a timeline linked to existing engine loss metadata remains a potential extension. |
| Class-D switching artifact profiler | **Not selected in this audit:** ordinary-rate capture cannot identify out-of-band switching noise from aliased in-band components. Spectrum observation is covered; causal attribution needs a specified wider-band front end. |
| Thermal power compression / Re drift; Phase IMD / Doppler | **Conditional:** impedance time series and two-tone IMD already exist. Actual thermal compression needs controlled drive and acoustic response; Doppler needs specified phase demodulation. No new implementation commitment. |
| Burst Envelope / Micro-dynamics; Haptic Audio Sync | **Conditional:** Transient Analyzer and Boxcar already capture/average transients. Define an additional observable metric and, for haptics, a sensor before reconsidering. |
| Loudspeaker Polar/Directivity 3D Plotter; HRTF deconvolution; 6DOF Room Simulation | **Retained as vision:** reuse Network Analyzer, HRTF Player and Spatial Binaural Mixer. Acquisition geometry, fixtures/tracking and validation remain prerequisites. |
| Psychoacoustic Masking Overlay; Perceptual Residue Auralizer; Interactive Audiograms | **Retained as vision:** require a specified perceptual model and calibrated listening protocol. A separated residue becoming audible does not establish that it was audible in the original mixture. |

### Other Earlier Vision Seeds (Not Scheduled)

Preserved for later workers, without treating speculation as a measurement capability:

* **Perception / AI:** Psycho-Acoustic Emotional Impact Scorer; AI-Driven Measurement Recipe Generator; AI Golden Ear Component Fingerprinter. Define a testable output before promotion; no emotion or component-identification accuracy is established.
* **Temporal Audio Micro-Lens:** Interpolated displays may illustrate band-limited reconstruction; AI cannot establish unrecorded sub-sample events as measured facts.
* **Neuromorphic & Quantum Analysis:** Event-based transient capture is covered by Event Detector; quantum modeling of noise has no defined observable here.
* **Multimodal / Spatial:** Synesthetic Measurement Mapper; Synesthetic Haptic Translator; Ultrasonic Acoustic Levitation Calibrator; Holographic/AR Acoustic Mode visualization. Additional hardware and an experiment remain undefined.
* **Bio / BCI:** Bio-Acoustic Impedance Sonifier; Brain-Computer Interface Audiophile Profiler. Retained as speculative concepts only.

## Previously Audited / Rejected / On Hold

Items reviewed and either implemented, conditionally approved, put on hold, or deemed not suitable for the current focus. They remain here for historical context.

* **Implemented/Covered:** Group/Phase Delay, Frequency-Dependent Crosstalk, Pre-Ringing, True Peak, IMD, AES17, Volterra Kernel, Inter-Channel Phase, Binaural Tones, DAC Filters, Cumulative Spectral.
* **Partially Implemented:** Continuity/Data-Gap Detection.
* **Conditional:** Thiele/Small Extraction, Hum AM/FM, Dynamic Burst Linearity, Null Comparator, Dynamics Processor Profiler.
* **On Hold / Not Suitable:** Bandwidth- and Slew-Limited, Clock/Jitter Attribution, Hardware-Dominated tests, Lossy Codec, Listener Fatigue Index, PEAQ/ODG Estimator, AI Circuit Reverse Engineer, Acoustic Metamaterial Simulator.
* **Deferred Reference Topics:** ASRC Benchmark, DC Stability, Wow and Flutter, RT60, EQ Designer, AI Anomaly, Plugin System, Multimeter, Cepstrum Analysis.
