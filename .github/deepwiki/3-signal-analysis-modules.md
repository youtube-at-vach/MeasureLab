# Signal Analysis Modules

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.agent/skills/ci_prechecker/SKILL.md](../../.agent/skills/ci_prechecker/SKILL.md)
- [src/core/analysis.py](../../src/core/analysis.py)
- [src/gui/widgets/advanced_distortion_meter.py](../../src/gui/widgets/advanced_distortion_meter.py)
- [src/gui/widgets/distortion_analyzer.py](../../src/gui/widgets/distortion_analyzer.py)
- [src/gui/widgets/frequency_counter.py](../../src/gui/widgets/frequency_counter.py)
- [src/gui/widgets/hrtf_player.py](../../src/gui/widgets/hrtf_player.py)
- [src/gui/widgets/lock_in_amplifier.py](../../src/gui/widgets/lock_in_amplifier.py)
- [src/gui/widgets/noise_profiler.py](../../src/gui/widgets/noise_profiler.py)
- [src/gui/widgets/one_pps_monitor.py](../../src/gui/widgets/one_pps_monitor.py)
- [src/measurement_modules/__init__.py](../../src/measurement_modules/__init__.py)
- [src/measurement_modules/base.py](../../src/measurement_modules/base.py)
- [tests/logic_verification/analysis/test_c_weighting_design.py](../../tests/logic_verification/analysis/test_c_weighting_design.py)
- [tests/logic_verification/analysis/test_imd.py](../../tests/logic_verification/analysis/test_imd.py)

</details>



MeasureLab provides a comprehensive suite of real-time and sweep-based signal analysis modules. These modules are built upon a standardized architecture that ensures consistent data handling, UI behavior, and high-performance DSP execution.

The system uses a pluggable architecture where each instrument is a subclass of `MeasurementModule` `src/measurement_modules/base.py:4-9`. This base class defines the interface for identification and GUI integration `src/measurement_modules/base.py:11-28`.

### Measurement Module Architecture

The relationship between the core engine and specific analysis modules is illustrated below:

**Module Integration Flow**
```mermaid
graph TD
    subgraph "Core Entity Space"
        AE["AudioEngine"]
        MM["MeasurementModule (Base)"]
        AC["AudioCalc (DSP Utilities)"]
        FFTM["FFTManager"]
    end

    subgraph "Signal Analysis Modules"
        DA["DistortionAnalyzer"]
        LIA["LockInAmplifier"]
        FC["FrequencyCounter"]
        NP["NoiseProfiler"]
    end

    AE -- "Audio Callback" --> MM
    MM <|-- DA
    MM <|-- LIA
    MM <|-- FC
    MM <|-- NP
    
    DA -- "Harmonic Analysis" --> AC
    NP -- "PSD Calculation" --> FFTM
    LIA -- "Demodulation" --> AC
```
Sources: `src/measurement_modules/base.py:4-29`, `src/core/analysis.py:172-175`, `src/gui/widgets/distortion_analyzer.py:41-43`

---

## 3.1 Spectrum and Time-Domain Analyzers
These modules provide fundamental visualization of signals in both time and frequency domains. They utilize the centralized `FFTManager` for optimized transforms and `AudioCalc` for envelope detection and windowing.
*   **Key Components**: FFT, PSD/RMS, min-max envelope rendering, and phase visualization.
*   For details, see [Spectrum and Time-Domain Analyzers](#3.1).

## 3.2 Distortion and Linearity Analyzers
Focuses on quantifying system non-linearities. The `DistortionAnalyzer` `src/gui/widgets/distortion_analyzer.py:41` supports THD, THD+N, and SINAD using advanced sine-fitting and harmonic extraction `src/gui/widgets/distortion_analyzer.py:103-195`. The `AdvancedDistortionMeter` `src/gui/widgets/advanced_distortion_meter.py:31` adds support for Multitone (MIM) and Intermodulation (PIM) tests.
*   **Key Algorithms**: Coherent multitone generation `src/gui/widgets/advanced_distortion_meter.py:206-210`, SMPTE/CCIF IMD analysis `tests/logic_verification/analysis/test_imd.py:24-132`.
*   For details, see [Distortion and Linearity Analyzers](#3.2).

## 3.3 Lock-in Suite
A family of high-precision detection tools based on dual-phase demodulation. The `LockInAmplifier` `src/gui/widgets/lock_in_amplifier.py:40` extracts signal magnitude and phase even when buried in noise, utilizing an IIR post-mix LPF cascade for high dynamic reserve `src/gui/widgets/lock_in_amplifier.py:79-85`.
*   **Key Components**: `LockInHarmonicAnalyzer`, `LockInFrequencyCounter`, and `LockInModeler`.
*   For details, see [Lock-in Suite](#3.3).

## 3.4 Network and Impedance Analyzers
These modules characterize the transfer functions of devices. The `NetworkAnalyzer` produces Bode plots (Magnitude/Phase) and Group Delay, while the `ImpedanceAnalyzer` utilizes dual-channel lock-in detection to calculate equivalent circuits (ESR, L, C).
*   For details, see [Network and Impedance Analyzers](#3.4).

## 3.5 Nonlinear System Identification
Advanced modeling tools for nonlinear systems. They use Synchronized Swept Sine (SSS) excitation to extract Parallel Hammerstein Model (PHM) kernels.
*   **Key Components**: `RealtimeSSSEngine`, `NonlinearResponseAnalyzer`, and kernel deconvolution.
*   For details, see [Nonlinear System Identification](#3.5).

## 3.6 Feedforward Compensator
Implements the Iterative LICFF (Linear-Inverse Compensated Feedforward) algorithm. It uses extracted Hammerstein kernels to pre-distort signals, effectively cancelling hardware nonlinearities.
*   For details, see [Feedforward Compensator](#3.6).

## 3.7 Acoustic and Loudness Meters
A set of tools for environmental and broadcast standards. Includes the `NoiseProfiler` `src/gui/widgets/noise_profiler.py:32` for PSD and 1/f noise analysis, and the `FrequencyCounter` `src/gui/widgets/frequency_counter.py:122` for high-precision tracking with Allan Deviation `src/gui/widgets/frequency_counter.py:82-83`. The `OnePPSMonitor` `src/gui/widgets/one_pps_monitor.py:30` provides experimental sample-clock drift monitoring.
*   **Standards**: A/C weighting (IEC 61672:2003) `src/core/analysis.py:15-20`, LUFS (BS.1770).
*   For details, see [Acoustic and Loudness Meters](#3.7).

## 3.8 Spatial Audio and Binaural Tools
Tools for rendering and measuring spatial audio. The `HRTFPlayer` `src/gui/widgets/hrtf_player.py:162` loads SOFA files `src/gui/widgets/hrtf_player.py:48-50` and performs real-time binaural convolution, calculating metrics like ITD and ILD `src/gui/widgets/hrtf_player.py:95-116`.
*   For details, see [Spatial Audio and Binaural Tools](#3.8).

## 3.9 Utility and Auxiliary Widgets
Auxiliary tools for signal management and system benchmarking, including `Recorder`, `BoxcarAverager`, and the `TransmissionAnalyzer` for bit-perfect loopback tests.
*   For details, see [Utility and Auxiliary Widgets](#3.9).

---

### Core DSP Utilities
Most modules rely on the `AudioCalc` static utility class for standardized DSP operations:

| Function | Description | File Reference |
| :--- | :--- | :--- |
| `resample` | Polyphase filtering for sample rate conversion | `src/core/analysis.py:195` |
| `design_a_weighting` | SOS coefficients for A-weighting filter | `tests/logic_verification/analysis/test_c_weighting_design.py:63` |
| `calculate_imd_smpte` | SMPTE Intermodulation Distortion analysis | `tests/logic_verification/analysis/test_imd.py:24` |
| `calculate_noise_profile` | Statistical noise characterization | `src/gui/widgets/noise_profiler.py:162` |

Sources: `src/core/analysis.py:172-214`, `src/gui/widgets/noise_profiler.py:162`, `tests/logic_verification/analysis/test_imd.py:24-36`

---
