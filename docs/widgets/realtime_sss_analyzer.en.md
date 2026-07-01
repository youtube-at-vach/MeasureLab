# Realtime SSS Lockin Analyzer

## Overview

The Realtime SSS Lockin Analyzer performs real-time frequency response and distortion sweeps using Synchronized Swept Sine (SSS) and digital Lock-in techniques. It allows measuring magnitude and phase responses over a specified frequency range and can track harmonics.

## Operation

### Starting and Stopping Measurement

* **Start Sweep / Stop Sweep Button**: Starts and stops the SSS measurement sweep. The button will indicate progress and disable itself momentarily upon completion while finishing up asynchronous processing.

### Calibrating Latency

* **Calibrate Latency**: Before running a sweep (especially in Relative XFER modes), it is crucial to align the input and output timing. Clicking this button sends a test signal to measure and compensate for system latency, updating the label with the measured delay. The "Start Sweep" button is only enabled after a valid latency measurement is obtained.

## Settings

### Settings Tab

* **Start Freq / End Freq (Hz)**: Sets the frequency boundaries for the sweep.
* **Duration (s)**: The time it takes to complete a single sweep.
* **Amplitude (dBFS)**: The output signal level.
* **Max Harmonic**: The highest harmonic order to analyze alongside the fundamental.
* **Averages**: The number of sweep cycles to average, improving SNR.

### Routing Tab

* **Output Ch**: Selects which channel to output the sweep signal (Left, Right, or Stereo).
* **Input Mode**: Configures the input reference and measurement channels.
    * **Single Ch (Left / Right Input)**: Simple single-channel measurement.
    * **2-Ch Relative (Ref=Left, Meas=Right / Ref=Right, Meas=Left)**: Dual-channel Transfer Function (XFER) mode.

### Advanced Tab

* **Analysis Cycles**: Number of cycles per frequency bin for the digital lock-in analysis (up to 512.0 cycles).
* **Meas Points**: Total number of frequency points measured in the sweep.
* **Prevent Buffer Underrun**: When enabled, automatically pauses data processing during high CPU load to avoid audio dropouts.
* **Asynchronous Calculation**: Runs the heavy SSS math in a background thread to keep the UI responsive.
* **Unwrap Phase**: Toggles phase unwrapping for phase plots. When enabled, phase transitions over ±180 degrees are smoothed out into a continuous curve.
* **Relative to Fundamental**: When enabled, the magnitude and phase of the harmonics are plotted relative to the fundamental frequency response, rather than as absolute values.
