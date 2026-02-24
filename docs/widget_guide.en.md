# Guide by Purpose

Introduce numerous widgets included in MeasureLab, categorized by purpose.

---

## 🔍 Quick Search Guide {: #quick-search-guide }

Checklist to find the best tool for "what you want to do" quickly.

| What you want to do | Recommended Widget |
| :--- | :--- |
| **Output sound / Need a signal source** | [Signal Generator](widgets/signal_generator.md) |
| **View frequency components (spectrum)** | [Spectrum Analyzer](widgets/spectrum_analyzer.md) |
| **View original waveform shape** | [Oscilloscope](widgets/oscilloscope.md) |
| **Measure distortion (THD) of amps or components** | [Distortion Analyzer](widgets/distortion_analyzer.md) |
| **Measure frequency response of amps, etc.** | [Network Analyzer](widgets/network_analyzer.md) |
| **Measure impedance of speakers** | [Impedance Analyzer](widgets/impedance_analyzer.md) |
| **Measure ultra-low distortion (THD) with high precision** | [Lock-in Harmonic Analyzer](widgets/lockin_harmonic_analyzer.md) |
| **Manage loudness (LUFS)** | [LUFS Meter](widgets/lufs_meter.md) |
| **Know ambient noise level (SPL)** | [Sound Level Meter](widgets/sound_level_meter.md) |
| **Analyze noise types (1/f, etc.)** | [Noise Profiler](widgets/noise_profiler.md) |

---

## 📡 Signal Generation

Tools for outputting signals or generating reference signals.

* **[Signal Generator](widgets/signal_generator.md)**
    * Generates sine waves, noise, sweep signals, etc. It is the basic signal source for measurements.

* **[Timecode Monitor & Generator](widgets/timecode_monitor.md)**
    * Generates and monitors LTC (Linear Timecode). Used for checking synchronization with video equipment.

---

## 📊 Basic Analysis

Measures basic characteristics of audio signals (spectrum, level, frequency).

* **[Spectrum Analyzer](widgets/spectrum_analyzer.md)**
    * Real-time display of frequency components (spectrum) using FFT.

* **[Sound Level Meter](widgets/sound_level_meter.md)**
    * A sound level meter. Measures sound pressure level (SPL) and equivalent continuous sound level (Leq).

* **[LUFS Meter](widgets/lufs_meter.md)**
    * Measures loudness units relative to full scale (LUFS). Suitable for level management for broadcasting and distribution.

* **[Frequency Counter](widgets/frequency_counter.md)**
    * Counts the frequency of input signals with high precision. Statistical analysis such as Allan deviation is also possible.

* **[Spectrogram](widgets/spectrogram.md)**
    * Visualizes changes in frequency components over time with colors (voiceprint analysis, etc.).

---

## 📉 Distortion & Quality

Tools for evaluating equipment performance and sound quality.

* **[Distortion Analyzer](widgets/distortion_analyzer.md)**
    * Measures THD (Total Harmonic Distortion) or THD+N. Use this for basic distortion measurements.

* **[Linearity Analyzer](widgets/linearity_analyzer.md)**
    * Measures input/output level linearity. Used for verifying the low-level signal reproduction capability and dynamic range of DACs.

* **[Advanced Distortion Meter](widgets/advanced_distortion_meter.md)**
    * Performs more advanced distortion analysis, such as multitone measurement and IMD (Intermodulation Distortion).

* **[Lock-in Harmonic Analyzer](widgets/lockin_harmonic_analyzer.md)**
    * An extremely low-noise distortion measurement module using the principle of a lock-in amplifier and matrix projection without window functions.

* **[Sound Quality Analyzer](widgets/sound_quality_analyzer.md)**
    * Calculates psychoacoustic "sound quality" metrics such as sharpness and roughness.

* **[Noise Profiler](widgets/noise_profiler.md)**
    * Analyzes noise floor characteristics (1/f noise, white noise, etc.).

---

## 🔌 Circuit & Network

Measures transmission characteristics, impedance, etc., of electronic circuits and systems.

* **[Network Analyzer](widgets/network_analyzer.md)**
    * Measures frequency response (gain, phase, group delay). Useful for checking characterisics of amplifiers and filters.

* **[Impedance Analyzer](widgets/impedance_analyzer.md)**
    * Measures impedance characteristics (LCR) of speakers and components.

* **[Lock-in Amplifier](widgets/lock_in_amplifier.md)**
    * Detects infinitesimal signals buried in noise. Can also be used as an FRA (Frequency Response Analyzer).

* **[Lock-in Frequency Counter](widgets/lock_in_frequency_counter.md)**
    * Tracks minute frequency deviations or phase fluctuations relative to a reference signal.

* **[Loopback Finder](widgets/loopback_finder.md)**
    * Detects loopback paths of audio interfaces.

---

## 📈 Time Domain

Observes waveform shapes and transient changes on the time axis.

* **[Oscilloscope](widgets/oscilloscope.md)**
    * A general-purpose oscilloscope. Observes the waveform itself.

* **[Raw Time Series](widgets/raw_time_series.md)**
    * A tool like a chart recorder that records waveforms over a long period and allows you to check them by scrolling.

* **[Transient Analyzer](widgets/transient_analyzer.md)**
    * Triggers and analyzes transient phenomena such as impulse responses. Wavelet transform display is also possible.

* **[Boxcar Averager](widgets/boxcar_averager.md)**
    * Averages repetitive signals to remove noise and extract minute waveforms.

---

## 🎧 Spatial & Acoustics

Handles stereo image and spatial sound reverberation.

* **[Goniometer](widgets/goniometer.md)**
    * Displays phase relationship (spread) of stereo signals using Lissajous figures, etc.

* **[BNIM Meter](widgets/bnim_meter.md)**
    * Binaural Neural Image Map. Visualizes sound source localization (ITD/ILD) based on auditory models.

* **[HRTF Player](widgets/hrtf_player.md)**
    * Loads Head-Related Transfer Functions (HRTF/SOFA) and simulates 3D audio playback via convolution.

---

## 🛠️ Utilities

Other useful functions.

* **[Recorder & Player](widgets/recorder_player.md)**
    * Simple recording and playback function.
* **[Inverse Filter](widgets/inverse_filter.md)**
    * Creates an inverse filter to cancel out the characteristics of speakers and rooms.
* **[Detachable Wrapper](widgets/detachable_wrapper.md)**
    * A framework for detaching any widget into a separate window.
* **[Settings](widgets/settings.md)**
    * Configure audio device settings, language settings, theme changes, etc.
* **[Welcome](widgets/welcome.md)**
    * The startup screen.
