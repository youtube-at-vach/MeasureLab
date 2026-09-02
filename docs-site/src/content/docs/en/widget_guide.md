---
title: "Guide by Purpose"
---

## Overview

Introduce numerous widgets included in MeasureLab, categorized by purpose.

---

## 🔍 Quick Search Guide {#quick-search-guide}

Checklist to find the best tool for "what you want to do" quickly.

| What you want to do | Recommended Widget |
| :--- | :--- |
| **Output sound / Need a signal source** | [Signal Generator](https://youtube-at-vach.github.io/MeasureLab/en/widgets/signal_generator/) |
| **Synthesize complex waveforms / Blend specific harmonics** | [Arbitrary Harmonic Generator](https://youtube-at-vach.github.io/MeasureLab/en/widgets/arbitrary_harmonic_generator/) |
| **View frequency components (spectrum)** | [Spectrum Analyzer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/spectrum_analyzer/) |
| **Check specific frequencies with extremely high resolution** | [Lock-in Spectrum Finder](https://youtube-at-vach.github.io/MeasureLab/en/widgets/lockin_spectrum_finder/) |
| **View original waveform shape** | [Oscilloscope](https://youtube-at-vach.github.io/MeasureLab/en/widgets/oscilloscope/) |
| **Measure distortion (THD) of amps or components** | [Distortion Analyzer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/distortion_analyzer/) |
| **Apply feedforward distortion compensation to an audio signal** | [Feedforward Compensator](https://youtube-at-vach.github.io/MeasureLab/en/widgets/feedforward_compensator/) |
| **Measure real-time distortion / frequency response sweeps and build system models** | [Lock-in Modeler](https://youtube-at-vach.github.io/MeasureLab/en/widgets/lock_in_modeler/) |
| **Measure frequency response of amps, etc.** | [Network Analyzer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/network_analyzer/) |
| **Measure impedance of speakers** | [Impedance Analyzer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/impedance_analyzer/) |
| **Measure ultra-low distortion (THD) with high precision** | [Lock-in Harmonic Analyzer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/lockin_harmonic_analyzer/) |
| **Manage loudness (LUFS)** | [LUFS Meter](https://youtube-at-vach.github.io/MeasureLab/en/widgets/lufs_meter/) |
| **Know ambient noise level (SPL)** | [Sound Level Meter](https://youtube-at-vach.github.io/MeasureLab/en/widgets/sound_level_meter/) |
| **Analyze noise types (1/f, etc.)** | [Noise Profiler](https://youtube-at-vach.github.io/MeasureLab/en/widgets/noise_profiler/) |
| **Count rare anomalies such as popcorn noise** | [Event Detector](https://youtube-at-vach.github.io/MeasureLab/en/widgets/event_detector/) |
| **Precisely align L/R acoustic characteristics** | [Stereo Alignment Monitor](https://youtube-at-vach.github.io/MeasureLab/en/widgets/stereo_alignment_monitor/) |
| **Overlay and compare multiple plot traces from different measurements** | [Plot Comparer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/plot_comparer/) |
| **Evaluate digital/analog transmission path quality, latency, and integrity** | [Transmission Analyzer (Experimental)](https://youtube-at-vach.github.io/MeasureLab/en/widgets/transmission_analyzer/) |

---

## 📡 Signal Generation

Tools for outputting signals or generating reference signals.

- **[Signal Generator](https://youtube-at-vach.github.io/MeasureLab/en/widgets/signal_generator/)**
    - Generates sine waves, noise, sweep signals, etc. It is the basic signal source for measurements.

- **[Arbitrary Harmonic Generator](https://youtube-at-vach.github.io/MeasureLab/en/widgets/arbitrary_harmonic_generator/)**
    - An advanced signal generator that allows synthesizing complex waveforms by precisely controlling the amplitude and phase of multiple harmonic components (up to the 50th order) relative to the fundamental frequency.

- **[Timecode Monitor & Generator](https://youtube-at-vach.github.io/MeasureLab/en/widgets/timecode_monitor/)**
    - Generates and monitors LTC (Linear Timecode). Used for checking synchronization with video equipment.

---

## 📊 Basic Analysis

Measures basic characteristics of audio signals (spectrum, level, frequency).

- **[Spectrum Analyzer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/spectrum_analyzer/)**
    - Real-time display of frequency components (spectrum) using FFT.

- **[Lock-in Spectrum Finder](https://youtube-at-vach.github.io/MeasureLab/en/widgets/lockin_spectrum_finder/)**
    - Uses lock-in detection to analyze the spectrum of a specified frequency band with high resolution. Ideal for magnifying specific peaks buried in noise.

- **[Sound Level Meter](https://youtube-at-vach.github.io/MeasureLab/en/widgets/sound_level_meter/)**
    - A sound level meter. Measures sound pressure level (SPL) and equivalent continuous sound level (Leq).

- **[LUFS Meter](https://youtube-at-vach.github.io/MeasureLab/en/widgets/lufs_meter/)**
    - Measures loudness units relative to full scale (LUFS). Suitable for level management for broadcasting and distribution.

- **[Frequency Counter](https://youtube-at-vach.github.io/MeasureLab/en/widgets/frequency_counter/)**
    - Counts the frequency of input signals with high precision. Statistical analysis such as Allan deviation is also possible.

- **[Spectrogram](https://youtube-at-vach.github.io/MeasureLab/en/widgets/spectrogram/)**
    - Visualizes changes in frequency components over time with colors (voiceprint analysis, etc.).

---

## 📉 Distortion & Quality

Tools for evaluating equipment performance and sound quality.

- **[Distortion Analyzer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/distortion_analyzer/)**
    - Measures THD (Total Harmonic Distortion) or THD+N. Use this for basic distortion measurements.
- **[Nonlinear Analyzer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/nonlinear_analyzer/)**
    - An advanced distortion analysis tool that uses the Hammerstein model to separate and extract 1st (linear) to 5th order harmonic kernels from equipment responses.

- **[Lock-in Modeler](https://youtube-at-vach.github.io/MeasureLab/en/widgets/lock_in_modeler/)**
    - Performs real-time frequency response and distortion sweeps using SSS (Synchronized Swept Sine) and digital Lock-in techniques for building Hammerstein system models.

- **[Feedforward Compensator](https://youtube-at-vach.github.io/MeasureLab/en/widgets/feedforward_compensator/)**
    - Applies feedforward distortion compensation (LICFF) to audio signals using Hammerstein system models.

- **[Nonlinear Response Analyzer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/nonlinear_response_analyzer/)**
    - Identifies Wiener models to analyze dynamic nonlinear system behavior.
- **[Linearity Analyzer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/linearity_analyzer/)**
    - Measures input/output level linearity. Used for verifying the low-level signal reproduction capability and dynamic range of DACs.

- **[Advanced Distortion Meter](https://youtube-at-vach.github.io/MeasureLab/en/widgets/advanced_distortion_meter/)**
    - Performs more advanced distortion analysis, such as multitone measurement and IMD (Intermodulation Distortion).

- **[Lock-in Harmonic Analyzer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/lockin_harmonic_analyzer/)**
    - An ultra-low distortion (THD) measurement module utilizing the principle of a lock-in amplifier. It achieves high precision by performing multi-parallel IQ detection (up to 200th order) strictly tuned to the fundamental and harmonics.

- **[Sound Quality Analyzer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/sound_quality_analyzer/)**
    - Calculates psychoacoustic "sound quality" metrics such as sharpness and roughness.

- **[Noise Profiler](https://youtube-at-vach.github.io/MeasureLab/en/widgets/noise_profiler/)**
    - Analyzes noise floor characteristics (1/f noise, white noise, etc.).

---

## 🔌 Circuit & Network

Measures transmission characteristics, impedance, etc., of electronic circuits and systems.

- **[Network Analyzer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/network_analyzer/)**
    - Measures frequency response (gain, phase, group delay). Useful for checking characteristics of amplifiers and filters. Supports RIAA curve overlay for phono-equalizer testing.

- **[Impedance Analyzer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/impedance_analyzer/)**
    - Measures impedance characteristics (LCR) of speakers and components.

- **[Lock-in Amplifier](https://youtube-at-vach.github.io/MeasureLab/en/widgets/lock_in_amplifier/)**
    - Detects infinitesimal signals buried in noise. Can also be used as an FRA (Frequency Response Analyzer).

- **[Lock-in Frequency Counter](https://youtube-at-vach.github.io/MeasureLab/en/widgets/lock_in_frequency_counter/)**
    - Tracks minute frequency deviations or phase fluctuations relative to a reference signal.

- **[Loopback Finder](https://youtube-at-vach.github.io/MeasureLab/en/widgets/loopback_finder/)**
    - Detects loopback paths of audio interfaces.

- **[Transmission Analyzer (Experimental)](https://youtube-at-vach.github.io/MeasureLab/en/widgets/transmission_analyzer/)**
    - An experimental module that utilizes PRBS sequences (pseudo-random noise) to comprehensively measure digital audio bit-integrity (bit-perfection and DSP detection) as well as analog path metrics like EVM, impulse response, propagation delay, and clock jitter.

---

## 📈 Time Domain

Observes waveform shapes and transient changes on the time axis.

- **[Oscilloscope](https://youtube-at-vach.github.io/MeasureLab/en/widgets/oscilloscope/)**
    - A general-purpose oscilloscope. Observes the waveform itself.

- **[Raw Time Series](https://youtube-at-vach.github.io/MeasureLab/en/widgets/raw_time_series/)**
    - A tool like a chart recorder that records waveforms over a long period and allows you to check them by scrolling.

- **[Event Detector](https://youtube-at-vach.github.io/MeasureLab/en/widgets/event_detector/)**
    - Continuously monitors rare threshold events and measures their count and rate per minute.

- **[Transient Analyzer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/transient_analyzer/)**
    - Triggers and analyzes transient phenomena such as impulse responses. Wavelet transform display is also possible.

- **[Boxcar Averager](https://youtube-at-vach.github.io/MeasureLab/en/widgets/boxcar_averager/)**
    - Averages repetitive signals to remove noise and extract minute waveforms.

---

## 🎧 Spatial & Acoustics

Handles stereo image and spatial sound reverberation.

- **[Goniometer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/goniometer/)**
    - Displays phase relationship (spread) of stereo signals using Lissajous figures, etc.

- **[BNIM Meter](https://youtube-at-vach.github.io/MeasureLab/en/widgets/bnim_meter/)**
    - Binaural Neural Image Map. Visualizes sound source localization (ITD/ILD) based on auditory models.

- **[HRTF Player](https://youtube-at-vach.github.io/MeasureLab/en/widgets/hrtf_player/)**
    - Loads Head-Related Transfer Functions (HRTF/SOFA) and simulates 3D audio playback via convolution.

- **[Stereo Alignment Monitor](https://youtube-at-vach.github.io/MeasureLab/en/widgets/stereo_alignment_monitor/)**
    - Monitors the consistency of L/R level, frequency response, and phase in real-time to verify stereo alignment.

- **[Spatial Binaural Mixer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/spatial_binaural_mixer/)**
    - A high-quality offline multitrack spatial audio renderer. Load stems and independently position them in 3D space using HRTF, avoiding real-time processing artifacts.

---

## 🛠️ Utilities

Other useful functions.

- **[Recorder & Player](https://youtube-at-vach.github.io/MeasureLab/en/widgets/recorder_player/)**
    - Simple recording and playback function.
- **[Waveform Loop Player](https://youtube-at-vach.github.io/MeasureLab/en/widgets/waveform_loop_player/)**
    - A tool that allows you to load an audio file, inspect its waveform, and loop a selected region. Useful for repeatedly observing transient responses.

- **[Detachable Wrapper](https://youtube-at-vach.github.io/MeasureLab/en/widgets/detachable_wrapper/)**
    - A framework for detaching any widget into a separate window.
- **[Measurement Console (Experimental)](https://youtube-at-vach.github.io/MeasureLab/en/widgets/measurement_console/)**
    - Arranges multiple existing measurement widgets in a dockable workspace without duplicating audio processing.
- **[Plot Comparer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/plot_comparer/)**
    - Imports measurement traces saved/exported from other modules (Spectrum Analyzer, Network Analyzer, Oscilloscope, etc.) and allows detailed comparison by overlaying them with adjustable gain offsets, axis shifts, and peak alignment.
- **[Processor Benchmark](https://youtube-at-vach.github.io/MeasureLab/en/widgets/processor_benchmark/)**
    - Tests the FFT and rendering performance of your PC to verify real-time processing limits.
- **[Settings](https://youtube-at-vach.github.io/MeasureLab/en/widgets/settings/)**
    - Configure audio device settings, language settings, theme changes, etc.
- **[Log Viewer](https://youtube-at-vach.github.io/MeasureLab/en/widgets/log_viewer/)**
    - Displays real-time application logs, warnings, and errors for diagnostics and troubleshooting.
- **[Welcome](https://youtube-at-vach.github.io/MeasureLab/en/widgets/welcome/)**
    - The startup screen.
