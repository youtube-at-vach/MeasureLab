# MeasureLab

[日本語](README.ja.md)

MeasureLab is a DIY audio measurement and analysis suite. This branch contains the initial Rust implementation, with live audio input, a GPU oscilloscope, FFT spectrum analysis, and internal demo signals.

The final Python/PyQt6 edition is [v0.9.1](https://github.com/youtube-at-vach/MeasureLab/releases/tag/v0.9.1). Its complete source remains available through that tag and the [archive/python-v0.9.1 branch](https://github.com/youtube-at-vach/MeasureLab/tree/archive/python-v0.9.1).

## Downloads and manuals

- [Download website](https://youtube-at-vach.github.io/MeasureLab/download/)
- [Online manual](https://youtube-at-vach.github.io/MeasureLab/)
- [Python v0.9.1 source and development guide](https://github.com/youtube-at-vach/MeasureLab/blob/v0.9.1/docs/development.en.md)

The download website and existing manuals continue to describe the Python edition.

## Rust rewrite status

The Python application, tests, and application build environment have been retired from this branch. Rust development uses pull requests targeting `rewrite/rust`; the published Python edition remains available separately.

With Rust 1.95 or later and your operating system's build tools installed, run:

```sh
./scripts/cargo.sh run --release --locked -- --demo
```

See the [Rust operation and build guide](guide/rust/README.md) and [development plan](guide/rust/PLAN.md) for supported features, live input, and platform requirements.

This repository retains `download-site/`, the manual generation files, project history, measurement/design references, and the project icon. See [Rust rewrite preparation](guide/RUST_REWRITE_PREPARATION.md) for the retained files and archive details, and [Contributing](CONTRIBUTING.md) for the current validation commands.

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
