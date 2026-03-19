# Network Analyzer

![Network Analyzer](../assets/widgets/network_analyzer.png)

## Overview

The Network Analyzer is a tool for measuring the frequency response (amplitude and phase characteristics) of equipment and systems. It uses the "Fast Chirp" method (logarithmic chirp signal) to perform high-precision measurements of the entire band in a short time.

Primary uses:

* Measuring frequency response (f-response) of amplifiers and filters.
* Measuring characteristics of speakers and headphones.
* Measuring phase difference and delay between two signals.

## Basic Operation

### Starting Measurement

1. Set the measurement range (**Start/End Freq**) and **Amplitude** in the **"Settings"** tab.
2. Adjust the **Duration** of the chirp signal. Longer durations generally improve the S/N ratio.
3. Set the number of **Averages**. Multiple sweeps are performed and averaged to reduce noise.
4. Click the **"Start Sweep"** button to begin measurement. Progress is shown on the progress bar.
5. Click the button again to stop the measurement midway.

## Routing and XFER Mode

### Input/Output Settings

* **Output Ch**: Select the channel to output the measurement signal (L, R, or Stereo).
* **Input Mode**: Select where to receive the signal returning from the measurement target.
    * **Left (Ch1)** / **Right (Ch2)**: Measures the signal of the selected channel. In "Absolute (Level)" mode, it displays the input level in various units.
    * **XFER (Ref=L, Meas=R)**: Uses the Left channel as a "reference signal" and the Right channel as a "measurement signal," calculating their ratio (H = Meas / Ref). This allows for measuring pure device characteristics by canceling out the inherent traits of the audio interface (relative measurement).
    * **XFER (Ref=R, Meas=L)**: Reverse transfer function mode using Right as reference.
    * **Crosstalk L -> R / R -> L**: Pre-configured macros for measuring crosstalk between channels.

## Display and Analysis

Customize the graph display in the **"Display"** tab.

### Graph Types

* **Magnitude Response**: Displays gain (amplification factor) or absolute level for each frequency. Units can be selected from dBFS, dBV, dBu, Vrms, or Vpeak.
* **Phase Response**: Displays the phase shift for each frequency.
* **Group Delay**: Displays the delay time for each frequency, calculated from the slope of the phase (check "Show Group Delay").
* **Coherence**: Displays the correlation (reliability) between input and output. Values closer to 1.0 indicate high reliability. Low coherence suggests noise, distortion, or timing issues (check "Show Coherence").

### Display Options

* **Smoothing**: Smooths out fine jaggedness (noise) in the graph. Selectable from Off/Light/Medium/Heavy.
* **Max/Min Freq**: Limits the frequency range displayed on the graph.
* **Single-Ch Mode**: When using a single input channel, choose between **Relative (Gain)** (normalized to the output) or **Absolute (Level)**.

## Calibration

### Latency and IR SNR

* **Calibrate Latency**: Measures the total input/output delay of the system. This is crucial for accurate phase measurement.
* **IR SNR**: Displays the Signal-to-Noise Ratio of the Impulse Response for the most recent sweep. Higher values indicate a cleaner measurement.

### Reference Trace

Saves the current measurement result as a "reference" to compare with subsequent measurements.

* **Store Reference**: Saves the current graph as a reference.
* **Apply Reference**: Subtracts the saved reference from the current measurement result. Useful for checking relative changes or "flattening" a response.

## Troubleshooting

* **Audio stream failed to start. Check ASIO settings**: This error message indicates that the audio stream failed to start. Please verify that the ASIO settings (Sample Rate and Block Size) match your audio interface's configuration.
