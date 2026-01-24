# Feature Proposals for MeasureLab

**Project Direction Update (2025):**
The primary focus of this project has shifted towards **Signal Measurement** (analyzing audio signals directly, e.g., DAC/Amp performance, generated signal integrity) rather than Acoustic Measurement (speakers/rooms).
The features listed below have been categorized based on this new direction.

---

## 🚀 Active / High Priority (Signal Focus)

### 1. Multitone Analyzer

**Status:** Planned (Extend `DistortionAnalyzer`)
**Description:** Use log-spaced multitone signals (already supported by `SignalGenerator`) to measure TD+N (Total Distortion + Noise) across the full bandwidth in a single shot (< 2 seconds).
**Gap:** `DistortionAnalyzer` currently only supports Single-Tone THD or Dual-Tone IMD and does not support multi-bin analysis.

### 2. Linearity Analyzer (Gain vs Level)

**Status:** Proposed (Extend `DistortionAnalyzer`)
**Description:** Measure output level accuracy and linearity error by sweeping input amplitude from -120 dBFS to 0 dBFS. This is critical for verifying DAC dynamic range, noise floor, and bit-depth performance (AES17).
**Gap:** `DistortionAnalyzer` supports Amplitude Sweep but currently plots THD+N vs Amplitude, not the Deviation (Linearity Error) vs Amplitude.

### 3. Crosstalk Analyzer

**Status:** Proposed (Extend `NetworkAnalyzer`)
**Description:** Measure signal leakage between channels vs. Frequency (e.g., Stimulate Left -> Measure Right).
**Gap:** `NetworkAnalyzer` focuses on Transfer Function (Input vs Output) or Single Channel analysis. It requires a dedicated "Crosstalk" mode to handle the specific routing and plotting of relative isolation (dB).

### 4. Wow & Flutter Meter

**Status:** Proposed (Extend `FrequencyCounter` or New Widget)
**Description:** Measure frequency fluctuation of analog playback devices (Turntables, Tape). Needs FM demodulation and standard weighting filters (IEC 60386 / DIN 45507).
**Gap:** `FrequencyCounter` measures raw Jitter (Std Dev) but lacks the specific demodulation, weighting, and ballistics required for standard W&F measurements.

### 5. Oscilloscope Eye Pattern / Persistence

**Status:** Proposed (Extend `Oscilloscope`)
**Description:** Add an "Infinite Persistence" mode to visualize signal integrity, jitter, and ISI (Inter-Symbol Interference) by overlaying multiple trigger cycles without clearing the screen.
**Gap:** The current `Oscilloscope` clears and replaces the trace on every update.

---

## 💤 Deferred / Reference (Acoustic & Correction)

*Features related to physical acoustics are preserved here for reference but are **not currently planned**.*

### 6. Room Acoustics Analyzer (RT60)

**Status:** Deferred
**Description:** Schroeder integration for T20/T30/T60 decay times, Impulse Response recording, and Waterfall plots.
**Current State:** `TransientAnalyzer` uses Wavelets, not Schroeder integration.

### 7. Loudspeaker Parameter Calculator (Thiele/Small)

**Status:** Deferred
**Description:** Derive $Q_{ms}$, $Q_{es}$, $Q_{ts}$, $V_{as}$, etc., from impedance sweeps (Free Air + Added Mass/Sealed Box).
**Current State:** `ImpedanceAnalyzer` measures raw Z-curves but lacks parameter derivation logic.

### 8. EQ Designer / Target Match

**Status:** Deferred
**Description:** Auto-calculate PEQ filters to minimize the delta between measured response and a target curve (e.g., Harman Target).

### 9. Loudspeaker Polarity Tester

**Status:** Deferred
**Description:** Detect absolute polarity (positive/negative) using asymmetric pulses.
