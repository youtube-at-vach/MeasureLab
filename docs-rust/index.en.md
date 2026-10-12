# MeasureLab Rust prototype

**Accurate measurement, free and accessible to everyone.** MeasureLab turns a PC and audio input into a signal measurement workspace. The Rust edition is a prototype focused on Scope and Spectrum, currently available to build from source.

## Available features

| Feature | Scope |
| --- | --- |
| Input | 1–16 synchronous channels through CPAL; f64 measurement after capture, using nominal sample rates |
| Scope | Any two input channels, Auto/Normal/Single, Autoset, raw-sample RMS/Peak/P-P and cursors |
| Spectrum | 1,024–524,288 points, amplitude/PSD, band power/RMS, averaging and peak hold |
| Spectrogram / XY | Time-frequency view and synchronous two-channel XY display |
| Save and compare | Channel calibration and versioned settings; held Scope/Spectrum results in JSON, CSV and PNG; reference JSON comparison |
| Software Loopback | Known gain, phase, delay and noise through the common input path without hardware |
| Lock-in (experimental) | Fundamental-frequency measurement using synchronous REF and response; X/Y, R/θ, Gain, settling and REF status; JSON/CSV with conditions and reference comparison |

Acquisition, measurement and rendering run separately. Hiding a display does not stop analysis or averaging. Held results retain their input, settings, calibration and loss information.

## Platform and measurement limits

Existing validation records cover specific macOS conditions. Windows and Linux are also CI build/test targets; CI success does not verify their GPUs or physical audio devices. Accuracy depends on the device, input range and calibration. The selectable ceiling of 768 kHz does not guarantee operation at that rate.

Lock-in hardware REF, timing and long-term stability remain unverified. Physical audio output, THD/FRF/IR, VST3, actual sample-rate calibration, free layout and translated application UI are not implemented. This edition does not provide all Python features. Scope waveform axes and triggers use FS; calibrated numerical readouts can use physical units.

## Try it and report problems

Start with Software Loopback in the [quick start](quickstart.md) to acquire, stop and save a result. Include the Rust edition, commit, OS/GPU, audio device, sample rate, channels, FFT settings and reproduction steps in [bug reports](https://github.com/youtube-at-vach/MeasureLab/issues).

Detailed operation, development and validation records live under `guide/rust/` in the [repository](https://github.com/youtube-at-vach/MeasureLab). Rust work targets `rewrite/rust` until the main transition.

## Final Python edition

[Python v0.9.1 downloads](https://youtube-at-vach.github.io/MeasureLab/download/) and the [archived manual](https://youtube-at-vach.github.io/MeasureLab/en/) remain available at their existing URLs. The source is preserved in the [v0.9.1 tag](https://github.com/youtube-at-vach/MeasureLab/tree/v0.9.1).
