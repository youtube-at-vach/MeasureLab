# Lock-in Modeler

## Overview

The Lock-in Modeler performs real-time frequency response and distortion sweeps using Synchronized Swept Sine (SSS) signals and digital lock-in detection algorithms to measure the magnitude and phase response of a device under test (DUT) with extremely high precision and speed.

In addition to standard frequency sweep measurements (tracking the fundamental and up to 5th-order harmonics simultaneously), this tool features a **nonlinear Hammerstein model identification capability** and allows exporting identified models to JSON files.

## Operation Procedure

### 1. Latency Calibration (Mandatory)

Before running any sweep, the round-trip latency of the audio input and output channels must be measured and compensated. The sweep start button remains disabled until calibration is complete.

1. Click the **Calibrate Latency** button.
2. A test signal is sent, and the system latency (in samples and milliseconds) is automatically calculated and displayed.
3. Once calibration is successful, the **Start Sweep** button will be enabled.

### 2. Running a Sweep Measurement

1. Configure parameters such as `Sweep Mode` and frequency range in the `Settings` tab.
2. Click the **Start Sweep** button to begin the measurement.
3. During the sweep, progress, current signal frequency, analysis frequency, and Equivalent Noise Bandwidth (ENBW) are displayed in the `Overview` panel.
4. Click **Stop Sweep** to halt the measurement early.

---

## Settings

### Settings Tab

* **Sweep Mode**: Choose between two measurement modes:
    * `Sweep Measurement (Default)`: Performs a standard frequency sweep, plotting the magnitude and phase responses for the fundamental and configured harmonics.
    * `Nonlinear Model`: Identifies a Hammerstein nonlinear model by automatically performing multiple sweeps at different test amplitude levels to resolve higher-order kernels.
* **Start Freq / End Freq (Hz)**: Sets the frequency boundaries for the sweep (20.0 Hz to 20,000.0 Hz).
* **Duration (s)**: The duration of a single sweep cycle (2.0 s to 600.0 s).
* **Amplitude (dBFS)**: Sets the output signal level in dBFS (-100.0 dBFS to 0.0 dBFS).
* **Max Harmonic**: Sets the highest harmonic order to analyze alongside the fundamental (1st to 5th).
* **Averages**: Sets the number of sweep cycles to average for each amplitude level, which improves the SNR.
* **Amplitude Steps**: Active only in the Nonlinear Model mode. Specifies the number of amplitude steps (5 to 10) to use for system identification.

### Display Tab

* **Show Relative to Fundamental**: When enabled, the magnitude and phase of the harmonics are plotted relative to the fundamental frequency response (in dB / degrees) rather than as absolute values.
* **Unwrap Phase**: When enabled, phase transitions over $\pm 180$ degrees are smoothed out into a continuous curve instead of wrapping.
* **Show Raw Lock-in (Unprocessed)**: When enabled, displays the raw, unprocessed data points from the lock-in amplifier before any smoothing or interpolation is applied (disabled in Hammerstein mode).
* **Graph Smoothing**: Selects the smoothing level (None, Low, Medium, or Heavy) for the plotted curves, applying a Savitzky-Golay filter.

### Routing Tab

* **Output Ch**: Selects the physical channel to output the sweep signal (Left, Right, or Stereo).
* **Input Mode**: Configures how the input signal is acquired:
    * `Single Ch (Left Input)`: Absolute measurement using the left input channel only.
    * `Single Ch (Right Input)`: Absolute measurement using the right input channel only.
    * `2-Ch Relative (Ref=Left, Meas=Right)`: Dual-channel Transfer Function (XFER) mode. Measures the ratio between the left channel (reference) and right channel (measurement). This cancels out systemic response variations and nonlinearity in the test gear.
    * `2-Ch Relative (Ref=Right, Meas=Left)`: Dual-channel Transfer Function mode with the right channel as reference and the left as measurement.

### Advanced Tab

* **Analysis Cycles**: Sets the analysis window size in cycles per frequency bin for the digital lock-in calculation (2.0 to 2048.0 cycles). A larger number improves frequency resolution and noise rejection, but increases vulnerability to transient settling time.
* **Meas Points**: Total number of frequency sample points measured in the sweep (100 to 5000 points).
* **Min Window (ms)**: The minimum analysis window duration in milliseconds. This prevents the window from becoming excessively short at high frequencies, which would inflate the ENBW.
* **Real-time Display**: When enabled, plots and updates curves in real-time during the sweep. When disabled, analysis calculations are buffered during the sweep and plotted all at once after completion, which reduces CPU load and prevents audio buffer underruns (dropouts).

---

## Analysis Results & Model Export

### Plot Views

* **Frequency Response Tab**:
  Displays the magnitude and phase responses for the fundamental and harmonics (up to 5th-order, based on `Max Harmonic`). Harmonic characteristics can be viewed as absolute values or relative to the fundamental.
* **Impulse Responses (Kernels) Tab**:
  Enabled after a Hammerstein (Nonlinear Model) sweep. Displays the identified 1st-order to maximum 5th-order time-domain impulse response kernels ($h_1(t)$ to $h_5(t)$).

### Saving and Sharing Models

Upon completing a Nonlinear Model (Hammerstein) sweep, the **Export Model...** button is enabled.

1. Click **Export Model...**.
2. Specify the path and filename (JSON) in the file save dialog.
3. The exported JSON model contains metadata (sample rate, sweep duration, parameters, etc.) alongside both time-domain and frequency-domain kernel datasets.
4. Saving the model also automatically registers it to MeasureLab's active model cache, making it instantly available for other processing components (e.g. distortion compensation).
