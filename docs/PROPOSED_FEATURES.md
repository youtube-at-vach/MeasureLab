# Feature Proposals and Implementation Audit

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

**Status:** Selected; continuity monitoring is partially implemented.

The current AudioEngine latches input/output underflow and overflow conditions.
Event Detector detects input data gaps, invalidates affected measurements, and
exports event records to CSV or JSON.

Remaining scope:

* Record an input/output XRUN timeline with timestamps and category.
* Distinguish backend XRUNs from signal-level silence or discontinuity.
* Add signal dropout, click, and pop classification.
* Retain a short waveform around each detected incident.
* Export integrity incidents together with the existing event records.

This is directly useful when comparing devices, drivers, host APIs, sample
rates, and buffer sizes.

### 2. SMPTE, DIN, and CCIF IMD Sweeps

**Target:** Distortion Analyzer.

**Status:** Selected; real-time SMPTE and CCIF IMD are implemented.

The Distortion Analyzer already generates and measures SMPTE and CCIF dual-tone
signals. Its current frequency and amplitude sweep paths deliberately force a
single sine wave, so they do not perform IMD sweeps.

Remaining scope:

* Add amplitude sweeps for SMPTE, DIN, and CCIF modes.
* Add the DIN preset and its product calculation.
* Store IMD percentage, IMD dB, and individual product levels per step.
* Warn when CCIF tones approach the measured DAC/ADC bandwidth limit.

SMPTE and DIN are suitable for common audio devices. CCIF remains useful, but
results near 19 kHz and 20 kHz must be interpreted with the interface response
and Nyquist margin in mind.

### 3. True-Peak Histogram and Clipping Profiler

**Target:** LUFS Meter.

**Status:** Selected; True Peak and peak hold are implemented.

The LUFS Meter already calculates a four-times-oversampled True Peak for both
channels and maintains peak hold values.

Remaining scope:

* Add per-channel True-Peak histograms.
* Count threshold and 0 dBTP exceedances.
* Measure the longest continuous exceedance.
* Add a Sample Peak versus True Peak comparison and event timeline.
* Use continuous, stateful oversampling across audio callback boundaries.

For captured hardware signals, the result describes the ADC-observed waveform.
It must not be presented as proof of clipping inside a DAC before its analog
output stage.

### 4. Automatic Peak Markers

**Target:** Spectrum Analyzer.

**Status:** Selected.

The Spectrum Analyzer already provides FFT data, smoothing, peak hold, and raw
or display-downsampled traces. It does not currently create automatic labeled
peak markers.

Remaining scope:

* Mark the highest configurable number of peaks.
* Apply minimum prominence, minimum spacing, and noise-floor thresholds.
* Allow analysis of raw FFT data or smoothed display data.
* Optionally classify harmonics and sidebands around a selected fundamental.

This is a post-processing feature and therefore has low device dependence.

### 5. AES17 Dynamic Range Automator

**Target:** Distortion Analyzer.

**Status:** Selected as a workflow improvement; the measurement is implemented.

The existing analyzer provides the 997 Hz at -60 dBFS signal, 0 dBFS
calibration mode, AES17 20 kHz low-pass filter, and dynamic-range result.

Remaining scope:

* Combine calibration, clipping validation, settling, averaging, measurement,
  and report generation into a guided sequence.
* Record validation failures and calibration state in the result.

This item must not be implemented as a second AES17 measurement engine.

### 6. Long-Term Warm-up and Stability Logger

**Target:** Distortion Analyzer.

**Status:** Selected with renamed scope.

The original proposal called this a thermal drift logger. Without a temperature
sensor, MeasureLab cannot attribute a change to temperature. The feature should
therefore report gain, THD, THD+N, noise, and frequency as warm-up or stability
trends.

Where possible, a second reference channel should be used to separate DUT drift
from drift in the measurement interface.

## Confirmed Implemented or Covered Features

The following proposals must not be treated as new features.

| Original proposal | Current implementation | Audit result |
| --- | --- | --- |
| Group/Phase Delay Plot | Network Analyzer has a `Show Group Delay` control, a linked group-delay axis, and calculates `-dPhi / (2*pi*dF)` from the displayed phase. Bode phase is also present. | Implemented. A separate phase-delay curve is not present, but the original group-delay request is satisfied. |
| Frequency-Dependent Crosstalk/Leakage | Network Analyzer provides L-to-R and R-to-L crosstalk transfer sweeps. | Implemented as a more readable 2D frequency plot; a 3D plot is unnecessary. |
| Pre-Ringing and Causality Quantifier | Transient Analyzer measures pre/post impulse energy, their ratio, crest-factor validity, and estimates minimum-, linear-, or mixed-phase behavior. | Implemented as DAC Ringing analysis. Do not claim proof of physical causality. |
| True Peak | LUFS Meter performs four-times oversampling and peak hold. | Implemented; only the histogram and clipping profile remain. |
| SMPTE and CCIF IMD | Distortion Analyzer generates and measures both standards in real time. | Implemented; IMD sweeps and DIN remain. |
| AES17 Dynamic Range | Distortion Analyzer includes calibration, the -60 dBFS test signal, AES17 filtering, and the DR result. | Implemented; only guided automation remains. |
| Continuity/Data-Gap Detection | AudioEngine tracks XRUN categories and count. Event Detector records data-gap validity and exports measurement metadata and events. | Partially implemented; a unified integrity timeline and signal-dropout classifier remain. |
| Volterra Kernel Extractor | Nonlinear Analyzer extracts first- through fifth-order Parallel Hammerstein kernels and exports the model. Response Viewer provides gain-compression analysis. | Covered by a practical diagonal/Parallel Hammerstein model. A full Volterra model with cross-kernels is not implemented. |
| Inter-Channel Phase Analysis | Stereo Alignment Monitor displays band-specific correlation, phase issues, frequency matching, and a volume gang-error logger. | Implemented for phase/balance analysis; this is not an independent-clock sync-drift logger. |
| Binaural Tones | Signal Generator has independent left and right channel signal parameters. | Covered by existing routing and per-channel frequency settings; a preset would be UI convenience only. |
| DAC Digital Filter Classification | Transient Analyzer measures DAC ringing and estimates minimum-, linear-, or mixed-phase behavior. | Partially covers the proposal. A general high-bandwidth alias/OOB profiler is not implemented. |
| Cumulative Spectral Visualization | Transient Analyzer provides a CWT wavelet scalogram. | Related visualization exists, but it is not a CSD waterfall. |

Other features already present include Transmission Analyzer PRBS, Allan
Deviation, Bit Depth estimation, Oscilloscope Persistence, Linearity analysis,
J-Test, RIAA EQ comparison, impulse response, LUFS, amplitude sweeps, and
frequency-response comparison.

Primary implementation references used for this audit:

* `src/gui/widgets/network_analyzer.py`: group delay, Bode phase, delay
  compensation, coherence, and crosstalk routing.
* `src/gui/widgets/distortion_analyzer.py`: SMPTE/CCIF IMD, sine-only sweeps,
  AES17 calibration, filtering, and dynamic range.
* `src/gui/widgets/lufs_meter.py`: four-times-oversampled True Peak and peak
  hold.
* `src/core/audio_engine.py` and `src/gui/widgets/event_detector.py`: XRUN
  status, data-gap handling, measurement validity, and event export.
* `src/gui/widgets/transient_analyzer.py`: pre/post-ringing energy and wavelet
  scalogram.
* `src/gui/widgets/nonlinear_analyzer.py` and
  `src/core/nonlinear_analyzer_core.py`: Parallel Hammerstein kernel extraction.

## Conditional Candidates

These proposals can produce useful results, but only after their measurement
conditions are explicitly defined.

### Thiele/Small Parameter Extraction

**Target:** Impedance Analyzer.

Added-Mass and Known-Volume extraction are feasible at ordinary sample rates.
They require a known series resistor, calibrated two-channel routing, a suitable
low-output-impedance driver, wiring guidance, and fit-quality reporting. The
audio interface output must not be assumed to be an ideal voltage source.

### Hum AM/FM Modulation Analysis

**Target:** Noise Profiler.

Noise Profiler already detects hum fundamentals and harmonics. AM/FM analysis
would require long, phase-continuous capture and demodulation. The result is
conditional because hum from the interface, grounding, and environment can be
indistinguishable from DUT behavior without a reference measurement.

### Dynamic Burst Linearity

**Target:** Linearity Analyzer.

Burst testing is valid in the audio band, but requires triggered alignment,
defined on/off windows, settling rules, crest-factor validation, and explicit
detection of limiting in the measurement interface.

### Null Comparator

**Target:** Recorder/Player or Transmission Analyzer.

A null test is useful when both signals share a clock or when sample alignment,
gain, polarity, fractional delay, and clock drift are corrected. Without these
conditions, the residual is dominated by synchronization error.

### Dynamics Processor Profiler

Static gain compression is already available from the measured Parallel
Hammerstein model in Response Viewer. A time-domain profiler for threshold,
ratio, attack, release, and look-ahead remains conditional because it requires
carefully specified burst and envelope tests. The cancelled multi-band
compressor proposal is not revived by this item.

### Other Conditional or Lower-Priority Items

* Test Sequence Automator, after individual measurements have stable result and
  validation schemas.
* Multi-Band Goniometer, as a display-oriented extension rather than a new
  measurement.
* CSD/Waterfall, mainly for speaker, room, and decay analysis rather than
  DAC/amplifier signal measurement.
* Polar Pattern/Directivity Mapper, which belongs to angular acoustic capture
  and is outside the primary signal-only focus.

## On Hold or Not Suitable for General Sound-Device Measurement

### Bandwidth- and Slew-Limited Measurements

* TIM/DIM Mode.
* Slew Rate Calculator.
* Eye Diagram.
* Digital Protocol Decoder.
* DAC Aliasing and OOB Leakage as general-purpose measurements.
* Ultrasonic Micro-Doppler excursion measurement.

These require bandwidth, edge rate, or analog front-end behavior that common
audio DAC/ADC paths do not preserve reliably. High sample-rate selection alone
does not make the measurement valid.

### Clock and Jitter Attribution

* TIE Jitter as an absolute product measurement.
* Phase Noise Density.
* Clock Fingerprinting.
* Inter-Channel Sync Drift Logger across unrelated devices.

Frequency Counter and Transmission Analyzer already expose frequency stability,
Allan deviation, jitter histograms, and sample-alignment drift. A sound-device
loopback cannot generally separate source-clock, DAC-clock, ADC-clock, and
algorithmic timing error. TIE logic also exists in hardware validation tests,
but not as a general user-facing measurement.

### Fixture- or Hardware-Dominated Measurements

* Damping Factor Profiler.
* Dual-ADC Cross-Correlation Noise Measurement as a promise to exceed hardware
  limits.
* Thermal Stress testing.
* EMI/RFI Fingerprinting.
* Complex Load/Back-EMF Distortion Profiler.

These require controlled loads, independent low-noise channels, temperature or
power sensing, RF instrumentation, or protection hardware. Implementing the DSP
alone would not make the result safe or attributable to the DUT.

### Outside the Current Signal-Measurement Focus

* Lossy Codec Artifact Analyzer.
* Listener Fatigue Index.
* PEAQ/ODG Score Estimator.
* AI Circuit Reverse Engineer.
* BCI Audiophile Profiler and AI "Golden Ear" concepts.
* Holographic, psycho-kinetic, tachyon, quantum, and synesthetic concepts.
* Room de-reverberation and acoustic metamaterial simulation.

Lossy codec and perceptual quality tools may be valid offline software-analysis
projects, but they are not measurements of a DAC or amplifier through a general
sound device.

## Deferred Reference Topics

The following remain reference topics rather than active implementation
proposals:

* ASRC Benchmark.
* DC Stability.
* Wow and Flutter.
* Room Acoustics and RT60.
* EQ Designer.
* AI Anomaly Detection.
* Plugin System.
* Multimeter.
* Cepstrum Analysis.
