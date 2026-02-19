[**🇯🇵 日本語版**](README.ja.md)

# 🚀 **MeasureLab (Audio Measurement Suite)** 🎶

![CI](https://github.com/youtube-at-vach/MeasureLab/actions/workflows/ci.yml/badge.svg) ![Linux Build](https://github.com/youtube-at-vach/MeasureLab/actions/workflows/build_appimage.yml/badge.svg) ![Windows Build](https://github.com/youtube-at-vach/MeasureLab/actions/workflows/build_windows.yml/badge.svg) ![macOS Build](https://github.com/youtube-at-vach/MeasureLab/actions/workflows/build_macos.yml/badge.svg) [![Docs](https://github.com/youtube-at-vach/MeasureLab/actions/workflows/deploy_docs.yml/badge.svg)](https://youtube-at-vach.github.io/MeasureLab/) [Online Manual](https://youtube-at-vach.github.io/MeasureLab/)

[![MeasureLab Demo](docs/assets/banner.png)](https://youtu.be/9fkJLfK5v0M)

A collection of DIY audio measurement and analysis tools, grown organically as needed. This software is compatible with standard audio devices.

**MeasureLab** provides these tools bundled into a single GUI application. Built with Python and PyQt6, it allows for intuitive high-precision signal generation, analysis, and measurement. This software works with standard audio devices.

This project aims to reach more people as an alternative for audio enthusiasts who cannot afford expensive measurement equipment.

## ✨ Features

### 🛠️ Widgets / Measurement Modules

The following modules/widgets are integrated.
Due to the large number of features, we recommend starting with the [**Widget Guide: Index by Purpose**](docs/widget_guide.md#quick-search-guide).

For details on each function, please refer to the [**Widget Guide**](docs/widget_guide.md), and for actual measurement examples, see the [**Measurement Recipes**](docs/measurement_recipes/index.md).

| No. | Widget | Description |
| :--- | :--- | :--- |
| 1 | **Welcome** | Shows main features at startup. |
| 2 | **Signal Generator** | Generates sine, square, triangle, sawtooth (rising/falling), white/pink noise, and frequency sweep signals. Supports phase control, amplitude control, stereo output, and snap to bin center. |
| 3 | **Spectrum Analyzer** | Real-time spectrum analysis using fast FFT. Supports PSD/RMS display, SI unit display, frequency range limiting, memory function, and cursor measurement. |
| 4 | **Sound Level Meter** | Advanced sound level meter with A/C/Z frequency weighting and FAST/SLOW/IMPULSE/10ms time weighting. Supports 20Hz–20k/12.5k/8k band selection, Lp/Leq/LE/Lmax/Lmin/Lpeak display, and calibration offset. |
| 5 | **LUFS Meter** | Real-time loudness (LUFS/LKFS) measurement. Includes crest factor and dynamic range display. |
| 6 | **Loopback Finder** | Tool to detect loopback paths of audio interfaces. |
| 7 | **Distortion Analyzer** | Measures THD, THD+N, SINAD, and IMD (SMPTE/CCIF). Includes built-in signal generator, frequency sweep, snap to bin center, harmonic bar graph, and averaging function. |
| 8 | **Linearity Analyzer** | Measures gain linearity relative to signal level (AES17 Linearity Deviation). Used for verifying DAC low-level signal reproducibility, bit accuracy, and dynamic range. |
| 9 | **Advanced Distortion Meter** | Advanced distortion analysis including MIM (Multi-tone Intermodulation), SPDR (Spurious-free Dynamic Range), and PIM (Passive Intermodulation) measurement. |
| 10 | **Network Analyzer** | Measures frequency response (gain, phase, group delay). Supports sweep measurement, multiple trace display, and frequency range limiting. |
| 11 | **Oscilloscope** | 2-channel waveform display with trigger function, cursor measurement, math waveforms (A+B, A-B), and real-time low-pass/high-pass filtering. |
| 12 | **Raw Time Series** | 2-channel scroll waveform monitor that holds long-term spans in a ring buffer. |
| 13 | **Transient Analyzer** | Transient analysis with trigger recording + CWT, flexible analysis band/scale specification. |
| 14 | **Lock-in Amplifier** | Small signal measurement using Phase Sensitive Detection (PSD). Includes Frequency Response Analysis (FRA) mode, harmonic demodulation (2nd-10th order), and calibration function. |
| 15 | **Lock-in THD+N Analyzer** | Dedicated module for THD/THD+N measurement using lock-in detection. Visualizes distortion components with integer period windowing and averaging, residual history/plot display, and harmonics/residual bar graph. |
| 16 | **Impedance Analyzer** | Impedance measurement and OSL (Open/Short/Load) calibration. Supports multiple plot modes (Z/θ, R/X, Q, C/L, Nyquist, Smith Chart), sweep measurement, and calibration interpolation. |
| 17 | **Inverse Filter** | Deconvolution tool that designs inverse characteristic FIR from calibration map and applies it to audio files. Supports regularization with gain limit, tap count/smoothing specification, response preview, and batch processing with output peak normalization. |
| 18 | **Frequency Counter** | High-precision frequency and period measurement. Includes Allan variance plot, jitter histogram and statistics, and calibration function. |
| 19 | **Lock-in Frequency Counter** | High-precision frequency/phase deviation tracking using lock-in detection (PSD). Capable of visualizing minute deviations and evaluating stability. |
| 20 | **1PPS Monitor** | Monitors 1PPS signal intervals and measures sampling rate deviation with high precision. Supports statistical display of jitter and cumulative drift. |
| 21 | **Spectrogram** | Time-frequency spectrogram display. Supports frequency range limiting and colormap selection. |
| 22 | **Boxcar Averager** | Noise reduction and transient response analysis using boxcar averaging. Supports internal pulse/step generation and external reference synchronization (rising/falling edge). |
| 23 | **Goniometer** | Visualizes stereo signal phase correlation and spatial distribution. Supports Lissajous display, phosphor display mode (afterimage effect), and custom color palette. |
| 24 | **Noise Profiler** | Detailed noise characteristic analysis tool. Automatic detection and quantification of 1/f noise, hum noise, and white noise. Supports averaging mode, LNA gain correction, thermal noise limit display, and equivalent resistance display. |
| 25 | **Recorder & Player** | Recording and playback of audio files (WAV/MP3/FLAC/OGG, etc.). Includes resampling, loop playback, and software loopback function. |
| 26 | **Sound Quality Analyzer** | Numeric and graphical display of sound quality metrics (Integrated/Momentary Loudness, Zwicker Sharpness, Roughness, Tonality). |
| 27 | **Timecode Monitor & Generator** | LTC timecode encoding/decoding and real-time monitoring. Features frame-based calculation, drop frame rate, multiple FPS display, timezone/offset, and generator with JAM memory. |
| 28 | **BNIM Meter** | Meter that visualizes "neural map" of ITD/ILD from stereo input and observes binaural localization tendencies. |
| 29 | **HRTF Player** | Reads and visualizes SOFA files. Supports heatmap display of HRTF metrics (ITD/ILD/high-frequency energy/envelope peak), sound source position specification by click, and real-time rotation playback (spatial localization by convolution) using arbitrary music files. |
| 30 | **Ultrasound AM Modulator** | Amplitude modulates (AM) audio signal and outputs as ultrasound on a carrier wave (40kHz). Can be used for parametric speaker experiments, etc. |
| 31 | **Detachable Wrapper** | UI utility that allows detaching and reconnecting any widget as an independent window. |
| 32 | **Settings** | Device settings, calibration, theme selection, language switching, etc. |

### 🌍 Localization

Major languages from around the world are supported. You can switch languages from the settings screen.

- English
- Japanese
- Chinese
- Spanish
- French
- German
- Portuguese
- Russian
- Korean

### ⚙️ Advanced Settings

- **Input/Output Settings**: Device selection, sampling rate (44.1kHz - 192kHz), buffer size change. **Virtual / Offline Mode** allows free simulation rate setting.
- **Dithering**: Supports TPDF dithering and output bit depth (8 / 16 / 24 bit) settings. Reduces quantization noise and supports high-precision measurement.
- **Calibration**: Input sensitivity and output gain correction wizard included, enabling accurate readings in voltage (Vrms, Vpeak, dBu, dBV). Also supports clock deviation recording using 1PPS signal.
- **Channel Routing**: Supports individual assignment of input/output channels.
- **Theme Settings**: Light/Dark/System theme switching is possible.

## 💻 Supported Operating Systems

| OS | Status | Notes |
| --- | --- | --- |
| Linux (x86_64) | ✅ Supported | Tested on Ubuntu 22.04 / 24.04 |
| Windows 10/11 | ✅ Supported | Official binary available |
| macOS (arm64) | ✅ Supported | Official binary available (M1/M2/M3) |

---

## 🚀 Installation & Usage

### 📦 Using Pre-built Packages

Please download the latest version from the **Releases** page.

- **Windows**: Download `MeasureLab-<version>-windows-x64-onefile.zip` (or `MeasureLab-<version>-windows-x64-onedir.zip`), unzip it, and run `MeasureLab.exe`.
- **Linux**: Download `MeasureLab-<version>-linux-x86_64.AppImage`, grant execution permission, and run it.

    ```bash
    chmod +x MeasureLab-*-linux-x86_64.AppImage
    ./MeasureLab-*-linux-x86_64.AppImage
    ```

- **macOS (arm64)**: Download `MeasureLab-<version>-macos-arm64.dmg` (or `.app`).
    - **Important: Bypassing Gatekeeper**
    - Since this app is currently unsigned, the normal procedure will display "cannot be opened because the developer cannot be verified".
    - To launch the app, **"Right-click (or Control + Click) and select 'Open'"**. A confirmation dialog will appear, select "Open" again to run.

#### Linux (Optional): Notes on using JACK / PipeWire

On Linux, you can usually use the **PortAudio** backend as is, but depending on the environment, **phase jumps may occur at buffer boundaries** (phase continuity is broken).
When performing measurements where phase continuity is important (phase, group delay, lock-in, etc.), it is recommended to specify **JACK** or **PipeWire** as the input/output destination.

However, if you use JACK / PipeWire, sound may not be output or input/output may not be connected after startup. In that case, check and set the routing (connection) with **QJackCtl** etc.

*This item is just an option. It can be used normally with PortAudio.*

### 🐍 Running from Source / For Developers

For instructions on running from source code and setting up the development environment, please refer to the following document.

- [**Developer Guide**](docs/development.md)

---

## 📜 License

This project is released into the public domain under **The Unlicense**.
You are free to copy, modify, distribute, and use it for any commercial or non-commercial purpose.

> **Note**: This is free and unencumbered software released into the public domain.

## 👥 Contributors

### 🧑‍💻 Special Thanks (Thanks to everyone who helped improve this software)

- [fantastictaste6171](https://www.youtube.com/@fantastictaste6171)
- [vach-at-youtube](https://www.youtube.com/@va-ch)

### 🤖 AI Models

- OpenAI: GPT-4.1, GPT-5, GPT-5.1 Codex Max, GPT-5.2, GPT-5.3-Codex
- Google: Gemini 2.5 Pro, Gemini 3 Pro, Gemini 3 Flash
- Anthropic: Claude 4.5 Sonnet
