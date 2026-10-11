# MeasureLab

[日本語](README.ja.md)

**Accurate measurement, free and accessible to everyone.** MeasureLab is an audio measurement workspace for your PC. The Rust edition focuses on reproducible Scope and Spectrum measurements, with acquisition, analysis and GPU rendering running separately.

**Status: Rust prototype, available from source.** Scope and Spectrum acquisition, calibration and result reuse are implemented. Software Loopback is available in normal builds; Lock-in is experimental. Hardware accuracy, long-duration behavior and platform coverage remain conditional. See the [roadmap](guide/rust/PLAN.md) and [validation records](guide/rust/validation/README.md).

## What you can use today

| Instrument / capability | Available in Rust |
| --- | --- |
| Audio input | 1–16 synchronous channels through CPAL; f64 samples after capture; supported nominal sample-rate selection |
| Scope | Any two channels, Auto/Normal/Single, Autoset, RMS/Peak/P-P, time cursors and held acquisition |
| Spectrum | 1,024–524,288 points, amplitude and PSD, band power/RMS, averaging, peak hold and frequency cursors |
| Spectrogram and XY | Independent STFT display and synchronous two-channel XY routing |
| Calibration and results | Channel gain/offset/unit definitions; versioned settings; held Scope/Spectrum JSON, CSV and PNG; reference comparison |
| Software Loopback | Known gain, phase, delay and noise through the common input path without physical audio output |
| Experimental Lock-in | Fundamental-frequency REF/response measurement, X/Y and R/θ, gain and settling status |

The measurement core uses f64; an optional f32 FFT path is available with separate numerical limits. Hiding a display does not stop analysis or averaging. Results retain their acquisition conditions and distinguish missing or invalid data from valid zero.

Physical signal output, THD/FRF/IR, VST3, actual sample-clock calibration and the Python edition's wider instrument collection are not implemented in Rust. Scope waveform axes and triggers use FS even when numerical readouts are calibrated. Lock-in hardware REF/timing validation is still pending.

## Run the prototype

Use Rust 1.95 or later and the native prerequisites for your OS. Rust integration currently targets `rewrite/rust`; this preparation does not yet move development to `main`.

```sh
git clone --branch rewrite/rust https://github.com/youtube-at-vach/MeasureLab.git
cd MeasureLab
cargo run --release --locked
```

This checks out the integrated Rust branch; newer work on topic branches may not be included yet. For a new macOS/Linux development environment, the [setup guide](guide/rust/SETUP.md) covers local tool installation:

```sh
./scripts/setup_dev_env.sh --install-os-deps --verify
source .tools/env.sh
./scripts/debug.sh
```

The application starts stopped. Select a device and press **Start input**, or choose **Input source → Software Loopback** to try it without hardware. Use **View → Scope + Spectrum**, adjust the plots through **Adjust**, then **Stop** and save settings/results through **File**. A complete 512k window at 48 kHz takes about 10.92 seconds even with frequent Live updates.

| Platform | Build prerequisites and current verification scope |
| --- | --- |
| macOS | Xcode Command Line Tools; allow microphone access for physical input. Existing macOS/BlackHole/GPU records cover specified conditions |
| Linux | C/C++ tools, pkg-config, ALSA, X11, Wayland and xkbcommon development libraries. CI target; device/GPU runtime verification remains pending |
| Windows | Rust MSVC toolchain and Visual Studio C++ Build Tools. CI target; device/GPU runtime verification remains pending |

The local macOS bundle script is `./scripts/bundle-macos.sh`. Public Rust installers, signing and supported OS/CPU combinations are part of [publication preparation](guide/rust/RELEASE_PREPARATION.md), not an available release promise. QA-only demo controls require `./scripts/debug.sh --demo`; Software Loopback does not require QA.

## Documentation and Python v0.9.1

| Edition | Start here | Distribution |
| --- | --- | --- |
| Rust prototype | [User manual source](docs-rust/index.en.md), [detailed operation guide](guide/rust/README.md), [setup](guide/rust/SETUP.md) | Build from source for now |
| Final Python edition | [Preserved online manual](https://youtube-at-vach.github.io/MeasureLab/en/) | [Download site](https://youtube-at-vach.github.io/MeasureLab/download/) and [v0.9.1 release](https://github.com/youtube-at-vach/MeasureLab/releases/tag/v0.9.1) |

Python development ended at v0.9.1. Its complete source and old build instructions remain in the [tag](https://github.com/youtube-at-vach/MeasureLab/tree/v0.9.1) and [archive branch](https://github.com/youtube-at-vach/MeasureLab/tree/archive/python-v0.9.1). Existing Python manual URLs will remain available when Rust is published. The new manual is prepared for `/MeasureLab/rust/` (English: `/MeasureLab/rust/en/`) and becomes public after the Pages deployment. Download links and `version.json` still describe Python v0.9.1.

## Development and feedback

Read [Current direction](guide/CURRENT_DIRECTION.md) → [implementation roadmap](guide/rust/PLAN.md). Repository, CI, packaging and documentation tasks live in [publication preparation](guide/rust/RELEASE_PREPARATION.md). The stack is Rust, CPAL, RustFFT, egui/eframe and wgpu; Python is used only for documentation and release tooling.

[Contributions](CONTRIBUTING.md), including AI-assisted changes, are welcome. Current PRs target `rewrite/rust`. CI checks three operating systems, normal/QA/headless configurations, the declared minimum Rust version, workflows, both manuals and downloads. Local commands are in [Tool Usage Guide](.agents/workflows/tool_usage.md); CI success is not a physical measurement certificate.

For [bug reports](https://github.com/youtube-at-vach/MeasureLab/issues), include the edition and commit/version, OS/GPU, input device, sample rate, channel routing, FFT settings and reproduction steps. Use the [security policy](SECURITY.md) for vulnerabilities.

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

- OpenAI: GPT-4.1, GPT-5, GPT-5.1 Codex Max, GPT-5.2, GPT-5.2 Codex, GPT-5.3-Codex, GPT-5.4, GPT-5.5, GPT-5.6, GPT-6 Astra
- Google: Gemini 2.5 Pro, Gemini 3 Pro, Gemini 3 Flash, Gemini 3.1 Pro, Gemini 3.5 Flash
- Anthropic: Claude 4.5 Sonnet
