# MeasureLab — Audio Measurement Lab

[日本語](README.ja.md)

[![CI](https://github.com/youtube-at-vach/MeasureLab/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/youtube-at-vach/MeasureLab/actions/workflows/ci.yml?query=branch%3Amain)
[![Windows release build](https://github.com/youtube-at-vach/MeasureLab/actions/workflows/build_windows.yml/badge.svg?event=pull_request)](https://github.com/youtube-at-vach/MeasureLab/actions/workflows/build_windows.yml?query=event%3Apull_request)
[![Linux release build](https://github.com/youtube-at-vach/MeasureLab/actions/workflows/build_linux.yml/badge.svg?event=pull_request)](https://github.com/youtube-at-vach/MeasureLab/actions/workflows/build_linux.yml?query=event%3Apull_request)
[![macOS release build](https://github.com/youtube-at-vach/MeasureLab/actions/workflows/build_macos.yml/badge.svg?event=pull_request)](https://github.com/youtube-at-vach/MeasureLab/actions/workflows/build_macos.yml?query=event%3Apull_request)
[![Rust 1.95+](https://img.shields.io/badge/Rust-1.95%2B-dea584?logo=rust&logoColor=white)](Cargo.toml)
[![Rust prototype](https://img.shields.io/badge/status-Rust_prototype-8b5cf6)](guide/rust/PLAN.md)
[![License: Unlicense](https://img.shields.io/badge/license-Unlicense-27d3a2)](LICENSE)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/youtube-at-vach/MeasureLab/badge)](https://securityscorecards.dev/viewer/?uri=github.com/youtube-at-vach/MeasureLab)

**Accurate measurement, free and accessible to everyone.**

Turn your PC and audio interface into a place to explore signals. See the waveform, inspect its spectrum, watch frequencies evolve, and explore the relationship between two channels—all in one measurement workspace.

**MeasureLab is developed in Rust on `main`, with v0.10.0 in preparation.** The prototype combines reproducible measurements, responsive controls and GPU plots. Scope, four-channel Spectrum, Spectrogram and XY are implemented, together with experimental Generator, Lock-in and synchronous two-channel comparison. You can build it from source today and help shape the next version.

[![Rust manual](https://img.shields.io/badge/Rust_Manual-Read_online-2563eb?style=for-the-badge)](https://youtube-at-vach.github.io/MeasureLab/rust/en/)
[![Try the prototype](https://img.shields.io/badge/Try_the_Prototype-Build_from_source-16856b?style=for-the-badge)](#try-the-prototype)
[![Roadmap](https://img.shields.io/badge/Roadmap-See_whats_next-7c3aed?style=for-the-badge)](guide/rust/PLAN.md)

[![MeasureLab Rust Scope with instrument navigation and console tabs](.github/assets/readme/rust-workspace.png)](.github/assets/readme/rust-workspace.png)

*The current Rust console showing Scope, instrument navigation and tabs used when the requested layout does not fit. This screenshot uses synthetic QA fixtures. Click any screenshot to view it at full size.*

## Built to measure, built to explore

- **Follow the signal.** Move between time, frequency, time–frequency and XY views, or focus on Scope and Spectrum together. Choose the channels you need from a 1–16 channel input.
- **Keep analysis moving.** Audio capture, measurement workers and GPU rendering run separately. Switching or hiding a view keeps enabled analysis and averaging running; individual Spectrum channels can be turned off to stop their FFT processing.
- **Keep more than a picture.** Save measurement settings, export held Scope/Spectrum results as JSON, CSV or PNG, then load a saved JSON reference for comparison. JSON results retain channel calibration, units and acquisition conditions.
- **Start without extra hardware.** Software Loopback lets you explore known gain, phase, delay and noise through the common input path. It is available in normal builds and produces no physical audio output.

## What you can use today

| Instrument / capability | Available in the Rust prototype |
| --- | --- |
| Audio input | 1–16 synchronous channels through CPAL; supported nominal sample-rate selection |
| Scope | Any four channels with independent visibility/scales, Auto/Normal/Single triggers, Autoset, RMS/Peak/P-P, time cursors and held acquisition |
| Spectrum | Up to four overlaid channels, 1,024–524,288 point FFT, amplitude/PSD/ESD, band power/RMS or window energy, averaging and frequency cursors |
| Spectrogram | Independent STFT, color/range controls, bounded history, Hold/Live, time A/B linked to Spectrum and input-gap display |
| XY / Lissajous | Synchronous two-channel plots with selectable channel routing |
| Calibration and results | Channel gain/offset/units, versioned settings, held Scope/Spectrum JSON, CSV and PNG, reference comparison |
| Software Loopback | Known signals and a virtual DUT for exploring gain, phase, delay and noise |
| Experimental Generator | Two sine signals with live frequency/peak amplitude/phase editing, internal or CPAL device output, independent Stop and OFF restoration |
| Experimental synchronous comparison | Auto/cross PSD, H1 gain/phase, coherence and conditional delay estimates; held JSON/CSV and reference comparison |
| Experimental Lock-in | Fundamental-frequency REF/response measurement, X/Y and R/θ, gain and settling status |

The measurement core uses **f64** after capture. An optional f32 FFT path has separate numerical limits. Results retain their acquisition conditions and distinguish missing or invalid data from valid zero.

## A closer look

| Scope + Spectrum | Experimental Lock-in |
| --- | --- |
| [![Scope with two acquired channels alongside a harmonic spectrum](.github/assets/readme/rust-scope-spectrum.png)](.github/assets/readme/rust-scope-spectrum.png) | [![Experimental Lock-in displaying amplitude and phase from Software Loopback](.github/assets/readme/rust-lockin.png)](.github/assets/readme/rust-lockin.png) |
| Inspect a waveform and its frequency content, with readouts and cursors inside the plots. | Explore reference-based amplitude and phase measurement with dedicated R/θ and X/Y views. |

*Screenshots captured from the current Rust QA build. Scope/Spectrum uses synthetic fixtures; Lock-in uses Software Loopback. These illustrate the interface, not physical-device accuracy.*

## Where we are heading

The next step is to make a small audio measurement lab dependable from input to saved result. The [roadmap](guide/rust/PLAN.md) grows from that foundation:

1. **Finish the essentials.** Refine two-channel Scope/Spectrum workflows and evaluate calibration, long runs, real devices and the experimental Lock-in.
2. **Evaluate generation and comparison together.** Validate the implemented Generator and synchronous gain/phase/delay comparison through internal, virtual and physical paths, including stop, disconnect and saved-result reuse.
3. **Build complete measurement flows.** Use generation and comparison for a future response-measurement flow, then evaluate candidates such as distortion, impulse response and sample-clock calibration.

Generator and synchronous comparison remain experimental while integration acceptance continues. Response-measurement flows and later candidates are not yet available. The immediate focus is accuracy, reproducibility and a useful two-channel workflow, while preserving the 1–16 channel foundation.

> [!NOTE]
> **This is a prototype available from source.** Hardware accuracy, long-duration behavior and OS/device coverage still have unverified areas; see the [validation scope](guide/rust/VALIDATION.md). Generator, Lock-in and synchronous comparison are experimental. High-load Spectrogram runs have shown long GUI stalls and STFT/Generator-input loss; device start-up loss also remains under investigation. THD/FRF/IR, VST3, output calibration and actual sample-clock calibration are not implemented in Rust. Scope waveform axes and triggers use FS even when numerical readouts are calibrated. Lock-in hardware REF/timing validation is limited to the documented conditions.

## Try the prototype

The [download selector](https://youtube-at-vach.github.io/MeasureLab/download/?edition=rust&lang=en) distinguishes the Rust prototype from the final Python edition. Rust v0.10.0 is not yet published, and its download buttons remain disabled. Packaging is implemented for Windows 10/11 x64 Setup/ZIP, glibc 2.35+ Linux x86_64 AppImage/tar.gz, and macOS 13+ Intel/Apple Silicon DMGs. No Python or Rust installation is needed to run a binary. See the [binary installation guide](https://youtube-at-vach.github.io/MeasureLab/rust/en/install/) for permissions and signing limits. Package-level hardware acceptance is still pending.

The release-build badges above show the latest pull-request package checks. These workflows build the normal desktop app, verify the packages and retain preview artifacts for 14 days. macOS checks cover both Intel and Apple Silicon. See [publication preparation](guide/rust/RELEASE_PREPARATION.md) for the remaining acceptance checks and release process.

To build from source, use **Rust 1.95 or later** and the native prerequisites for your OS. The Rust prototype is available directly from `main`:

```sh
git clone --branch main https://github.com/youtube-at-vach/MeasureLab.git
cd MeasureLab
cargo run --release --locked
```

For a new macOS/Linux development environment, the [setup guide](guide/rust/SETUP.md) covers local tool installation:

```sh
./scripts/setup_dev_env.sh --install-os-deps --verify
source .tools/env.sh
./scripts/debug.sh
```

Your first measurement:

1. The app starts stopped. Select a device under **I/O / Input**, or choose **Software Loopback** to try it without hardware.
2. Press **Start input**, open **Scope**, then choose **Pair with… / Spectrum**.
3. Select a pane to edit its details. Use the instrument controls for CH/time scale and the right details for FFT/window/averaging. Start with the default 8,192-point FFT.
4. Press **Stop input** to hold the result, then use **File** to save settings or export results.

A complete 512k window at 48 kHz takes about 10.92 seconds; faster Live updates do not shorten that observation time. The [Rust manual](https://youtube-at-vach.github.io/MeasureLab/rust/en/) explains the controls and measurement conditions.

| Platform | Build prerequisites and current verification scope |
| --- | --- |
| macOS | Xcode Command Line Tools; microphone permission for physical input. Existing macOS/BlackHole/GPU records cover specified conditions |
| Linux | C/C++ tools, pkg-config, ALSA, X11, Wayland and xkbcommon development libraries. AppImage startup and real-GPU readback confirmed in one X11 condition; physical I/O and save/restore remain pending |
| Windows | Rust MSVC toolchain and Visual Studio C++ Build Tools. VM startup confirmed with GNU/dev-fast; MSVC release physical I/O and save/restore remain pending |

The local macOS bundle script is `./scripts/bundle-macos.sh`; `./.venv/bin/python scripts/macos_package.py build` creates a DMG for the current Mac architecture. Windows, Linux and macOS prototype packages, microphone permissions, signing limitations and remaining acceptance checks are described in [publication preparation](guide/rust/RELEASE_PREPARATION.md). QA-only demo controls require `./scripts/debug.sh --demo`; Software Loopback does not require QA.

## Documentation and the Python edition

| Edition | Start here | Distribution |
| --- | --- | --- |
| Rust prototype | [Online manual](https://youtube-at-vach.github.io/MeasureLab/rust/en/), [detailed operation guide](guide/rust/README.md), [setup](guide/rust/SETUP.md) | Build from source on `main`; v0.10.0 is in development |
| Final Python edition | [Preserved online manual](https://youtube-at-vach.github.io/MeasureLab/en/) | [Download site](https://youtube-at-vach.github.io/MeasureLab/download/) and [v0.9.1 release](https://github.com/youtube-at-vach/MeasureLab/releases/tag/v0.9.1) |

Python development ended at **v0.9.1**. Its complete source and old build instructions remain in the [tag](https://github.com/youtube-at-vach/MeasureLab/tree/v0.9.1) and [archive branch](https://github.com/youtube-at-vach/MeasureLab/tree/archive/python-v0.9.1). The Python manual and downloads remain available alongside the new Rust manual. `version.json` preserves Python v0.9.1; separate `rust-release.json` keeps Rust downloads unpublished during preparation. The Python edition's wider instrument collection has not been ported to Rust.

## Help shape the next MeasureLab

Try the prototype, share a measurement use case, report a reproducible issue, or contribute code and documentation. Feedback from audio enthusiasts, builders and measurement users helps decide what to finish next. [Contributions](CONTRIBUTING.md), including AI-assisted changes, are welcome.

For [bug reports](https://github.com/youtube-at-vach/MeasureLab/issues), include the edition and commit/version, OS/GPU, input device, sample rate, channel routing, FFT settings and reproduction steps. Use the [security policy](SECURITY.md) for vulnerabilities.

For development, read [Current direction](guide/CURRENT_DIRECTION.md) → [implementation roadmap](guide/rust/PLAN.md). The stack is Rust, CPAL, RustFFT, egui/eframe and wgpu. CI covers static checks, normal/QA/headless numerical and regression tests, the minimum Rust version, workflows and documentation, with separate three-OS release builds. Local commands are in [Tool Usage Guide](.agents/workflows/tool_usage.md).

## 📜 License

This project is released into the public domain under **The Unlicense**, continuing MeasureLab's original license for the Rust edition. See [LICENSE](LICENSE) for the full text.

## 👥 Contributors

### 🧑‍💻 Special Thanks (Thanks to everyone who helped improve this software)

- [Dominique Michel](https://github.com/domichel)
- [Major Wong(diyAudio)](https://www.diyaudio.com/community/members/major-wong.345860/)
- [TNT (diyAudio)](https://www.diyaudio.com/community/members/tnt.4571/)
- [fantastictaste6171](https://www.youtube.com/@fantastictaste6171)
- [vach@YouTube](https://www.youtube.com/@va-ch)

### 🤖 AI Models

- OpenAI: GPT-4.1, GPT-5, GPT-5.1 Codex Max, GPT-5.2, GPT-5.2 Codex, GPT-5.3-Codex, GPT-5.4, GPT-5.5, GPT-5.6, GPT-6, GPT-6.1, GPT-6 Astra
- Google: Gemini 2.5 Pro, Gemini 3 Pro, Gemini 3 Flash, Gemini 3.1 Pro, Gemini 3.5 Flash
- Anthropic: Claude 4.5 Sonnet
