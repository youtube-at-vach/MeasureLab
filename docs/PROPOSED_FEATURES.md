# Feature Proposals for MeasureLab

After investigating the existing codebase and widget library, the following features are proposed to enhance the application's capabilities as a sound device measurement tool.

## 1. Room Acoustics Analyzer (RT60)

**Current State:**
The existing `TransientAnalyzer` utilizes Wavelet transforms (CWT) for time-frequency analysis. While powerful for visualizing transient events, it does not perform the industry-standard Schroeder integration required for reverberation time (RT60) measurements.

**Proposal:**
Create a new widget `RoomAcousticsAnalyzer`.

**Key Features:**
- **Impulse Response Recording:** Support for Sine Sweep (with deconvolution) and Impulse (balloon pop/clapper) recording.
- **Schroeder Integration:** Calculate the energy decay curve using backward integration.
- **Metrics:** Automatically calculate T20, T30, and T60 decay times.
- **Visualization:** Decay curves and Waterfall plots (Decay vs Frequency).

---

## 2. Loudspeaker Parameter Calculator (Thiele/Small)

**Current State:**
The `ImpedanceAnalyzer` (`src/gui/widgets/impedance_analyzer.py`) accurately measures Impedance (Z), Phase, and Resonance Frequency ($F_s$). However, it stops at raw data and does not calculate the electromechanical parameters required for loudspeaker enclosure design.

**Proposal:**
Extend `ImpedanceAnalyzer` or create a "Loudspeaker Wizard" wrapper.

**Key Features:**
- **Workflow:** Guided steps to measure "Free Air" impedance, followed by "Added Mass" (or Sealed Box) measurement.
- **Calculation:** Derive $Q_{ms}$, $Q_{es}$, $Q_{ts}$, $V_{as}$, $R_e$, $B_l$, $M_{ms}$, and $C_{ms}$ from the shift in resonance.
- **Export:** Save parameters to JSON/Text for simulation software.

---

## 3. Multitone Analyzer

**Current State:**
The `SignalGenerator` (`src/gui/widgets/signal_generator.py`) already supports generating optimized Multitone signals (log-spaced, crest-factor optimized). However, the `DistortionAnalyzer` is limited to Single-Tone THD or Dual-Tone IMD and does not support multi-bin analysis.

**Proposal:**
Extend `DistortionAnalyzer` or create `MultitoneAnalyzer`.

**Key Features:**
- **Synchronized Analysis:** Configure analysis bins to match the generator's multitone frequencies.
- **Metrics:** Calculate TD+N (Total Distortion + Noise) across the full bandwidth in a single shot.
- **Speed:** Provides a comprehensive "System Health" check (Freq Response + Distortion) in < 2 seconds, compared to minutes for a stepped sine sweep.

---

## 4. EQ Designer / Target Match

**Current State:**
The `SpectrumAnalyzer` and `NetworkAnalyzer` provide excellent visualization of the current frequency response. However, users often measure systems to correct them, and currently, there is no built-in tool to calculate the necessary corrections.

**Proposal:**
Extend `SpectrumAnalyzer` or `NetworkAnalyzer`.

**Key Features:**
- **Target Import:** Load "House Curves" (e.g., Harman Target) or custom text files.
- **Difference Calculation:** Real-time display of the delta between measured response and target.
- **Auto-EQ:** Calculate Biquad filter coefficients (PEQ) to minimize the error.

---

## 5. Loudspeaker Polarity Tester

**Current State:**
The `Goniometer` provides phase correlation statistics, which is useful for general stereo checking. However, determining the absolute polarity of a driver (e.g., "Is this tweeter wired correctly?") often requires a dedicated impulse test.

**Proposal:**
Create a simple utility widget `PolarityTester`.

**Key Features:**
- **Signal:** Generate a specific asymmetric pulse (positive-going).
- **Detection:** Analyze the step response to determine if the initial transient is positive or negative.
- **UI:** Simple "Green (+)" / "Red (-)" indicator.
