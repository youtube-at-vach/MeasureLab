# MeasureLab Rust prototype

**Accurate measurement, free and accessible to everyone.** MeasureLab turns a PC and audio input into a signal measurement workspace. The Rust edition is a prototype focused on Scope and Spectrum, currently available to build from source.

## Available features

| Feature | Scope |
| --- | --- |
| Input | 1–16 synchronous channels through CPAL; f64 measurement after capture, using nominal sample rates |
| Scope | Any four input channels, independent visibility and vertical scales, Auto/Normal/Single, Autoset, raw-sample RMS/Peak/P-P and cursors |
| Spectrum | 1,024–524,288 points, amplitude/PSD/ESD, band power/RMS or window energy, averaging and peak hold |
| Spectrogram / XY | Time-frequency view and synchronous two-channel XY display |
| Save and compare | Channel calibration and versioned settings; held Scope/Spectrum results in JSON, CSV and PNG; reference JSON comparison |
| Software Loopback | Known gain, phase, delay and noise through the common input path without hardware |
| Generator (experimental) | Two sine signals with live frequency/amplitude/phase controls; actual generated f64 samples through the common input path. Output up to two signals internally or through a CPAL audio device, with device/format selection and OFF restoration |
| Lock-in (experimental) | Fundamental-frequency measurement using synchronous REF and response; X/Y, R/θ, Gain, settling and REF status; JSON/CSV with conditions and reference comparison |
| Synchronous comparison (experimental) | Any REF/response pair; auto/cross PSD, H1 gain/phase, coherence, wrapped phase delay and conditional phase-slope fit; held JSON/CSV and reference comparison |

Acquisition, measurement and rendering run separately. Hiding a display does not stop analysis or averaging. Held results retain their input, settings, calibration and loss information.

## Platform and measurement limits

Quality assessment currently focuses on macOS; Windows/Linux hardware acceptance is deferred to future work. Existing validation records cover specific macOS conditions. Windows and Linux are also CI build/test targets; CI success does not verify their GPUs or physical audio devices. Accuracy depends on the device, input range and calibration. The selectable ceiling of 768 kHz does not guarantee operation at that rate.

BlackHole and UAC-232 physical loopback records on macOS cover input REF, independent numerical comparisons and conditional result reuse, including UAC-232 GUI save/restart/remeasurement. Earlier 600-second headless records and the current approximately 270-second GUI observation use different conditions. These are limited tests using nominal sample rates and uncalibrated FS; physical calibration accuracy, level-dependent phase, absolute delay and hardware guarantees on other operating systems remain unverified. Normal Generator audio output is undergoing conditional stage 4.5 evaluation. External input results retain observed output history and failures, with uncalibrated input-window correspondence and no numerical reference differences. Output calibration, input/output sample-clock mapping, THD/FRF/IR, VST3, actual sample-rate calibration, free layout and translated application UI are not implemented. This edition does not provide all Python features. Scope waveform axes and triggers use FS; calibrated numerical readouts can use physical units.

## Try it and report problems

Start with Software Loopback in the [quick start](quickstart.md) to acquire, stop and save a result. Include the Rust edition, commit, OS/GPU, audio device, sample rate, channels, FFT settings and reproduction steps in [bug reports](https://github.com/youtube-at-vach/MeasureLab/issues).

Detailed operation, development and validation guidance live under `guide/rust/` in the [repository](https://github.com/youtube-at-vach/MeasureLab). The Rust edition is developed on `main`.

## Final Python edition

[Python v0.9.1 downloads](https://youtube-at-vach.github.io/MeasureLab/download/) and the [archived manual](https://youtube-at-vach.github.io/MeasureLab/en/) remain available at their existing URLs. The source is preserved in the [v0.9.1 tag](https://github.com/youtube-at-vach/MeasureLab/tree/v0.9.1).
