---
title: "Network Analyzer"
---

![Network Analyzer](../../../../assets/widgets/network_analyzer.png)

## Overview

The Network Analyzer is a tool for measuring the "frequency response" (amplitude and phase characteristics) of equipment and systems.
Simply put, it is a feature that graphs **"how accurately (how loud or quiet) a device can transmit sounds of various pitches, from low to high."**

It uses the "Fast Chirp" method (logarithmic chirp signal) to perform high-precision measurements of the entire band in a short time.

Primary uses:

* Measuring frequency response (f-response) of amplifiers and filters.
* Measuring characteristics of speakers and headphones.
* Measuring phase difference and delay between two signals.

## Common Features

This widget supports common features of the Detachable Wrapper. Please refer to the [Detachable Wrapper](https://youtube-at-vach.github.io/MeasureLab/en/widgets/detachable_wrapper/) documentation for details.

## Basic Operation

### Starting Measurement

1. Set the measurement range (**Start/End Freq**) and **Amplitude** in the **"Settings"** tab. The maximum frequency limit dynamically adjusts to the Nyquist frequency (half the sample rate) based on the current audio sample rate.
2. Adjust the **Duration** of the chirp signal (Default: 10.0s). Longer durations generally improve the S/N ratio.
3. Set the number of **Averages**. Multiple sweeps are performed and averaged to reduce noise.
4. Click the **"Start Sweep"** button to begin measurement. Progress is shown on the progress bar.
5. Click the button again to stop the measurement midway.

## Routing and XFER Mode

### Input/Output Settings

* **Output Ch**: Select the channel to output the measurement signal (L, R, or Stereo).
* **Input Mode**: Select where to receive the signal returning from the measurement target.
    * **Left (Ch1)** / **Right (Ch2)**: Measures the signal of the selected channel. In "Absolute (Level)" mode, it displays the input level in various units.
    * **XFER (Ref=L, Meas=R)**: Uses the Left channel as a "reference signal" (the original sound before entering the device) and the Right channel as a "measurement signal" (the sound after passing through), calculating the ratio of change (H = Meas / Ref). This powerful mode allows for measuring pure device characteristics by canceling out the inherent traits of the audio interface, showing strictly "how the device altered the sound" (relative measurement).
    * **XFER (Ref=R, Meas=L)**: Reverse transfer function mode using Right as reference.
    * **Crosstalk L -> R / R -> L**: Pre-configured macros for measuring crosstalk between channels.

## Display and Analysis

Customize the graph display in the **"Display"** tab.

### Graph Types

* **Magnitude Response**: Displays gain (amplification factor) or absolute level for each frequency. Units can be selected from dBFS, dBV, dBu, Vrms, or Vpeak.
* **Phase Response**: Displays the phase shift for each frequency.
* **Group Delay**: Displays the delay time for each frequency, calculated from the slope of the phase (check "Show Group Delay"). It allows intuitive confirmation of arrival time differences across frequency bands in seconds (or milliseconds).
* **Coherence**: Displays the correlation (reliability) between input and output (valid only in XFER and Crosstalk transfer modes). Values closer to 1.0 indicate high reliability. Low coherence suggests noise, distortion, or timing issues (check "Show Coherence").
* **ETC (Energy Time Curve)**: Displays how the energy of the impulse response decays over time (in the "ETC" tab). It is suitable for observing energy decay, such as ringing in filters or amplifiers.
* **Impulse Response**: Displays the impulse response of the measurement target in the time domain (in the "Impulse Response" tab). It allows confirmation of the system\'s transient response and reflections on the time axis.
* **Harmonics**: Displays the harmonic components (2nd to 5th, and THD) of the measurement target for each frequency (in the "Harmonics" tab). It uses the Farina method, extracting distortion components across all frequencies simultaneously from a single logarithmic chirp measurement.

### Display Options

* **Smoothing**: Smooths out fine jaggedness (noise) in the frequency response graph using fractional-octave smoothing. Selectable from None, 1/1, 1/3, 1/6, 1/12, or 1/24 Octave.
* **Display as % (Harmonics Tab)**: Toggle the Y-axis of the Harmonics plot to display distortion levels as a percentage (%) relative to the fundamental, plotted on a logarithmic scale.
* **ETC Smoothing**: Smooths the noise in the ETC graph. Selectable from Off/Light/Medium/Heavy.
* **Max/Min Freq**: Limits the frequency range displayed on the graph.
* **Single-Ch Mode**: When using a single input channel, choose between **Relative (Gain)** (normalized to the output) or **Absolute (Level)**.

## Reference Curves (RIAA)

The Network Analyzer includes specialized support for RIAA curve comparison, which is essential for testing phono-equalizers.

* **Show RIAA Curve**: Overlays the standard RIAA playback curve on the magnitude plot.
* **Enable IEC Amendment**: Adds the IEC amendment (sub-sonic filter) to the RIAA curve. This adds a pole at 20.02 Hz (7950μs time constant) to the response.
* **Alignment Mode**:
    * **Auto (200Hz - 5kHz Fit)**: Automatically shifts the RIAA curve vertically to match the average level of your measurement between 200 Hz and 5 kHz. This is the recommended mode for quick evaluation.
    * **Manual**: Allows you to manually adjust the **Gain Offset** of the reference curve for precise alignment.

## Calibration

### Latency and IR SNR

* **Calibrate Latency**: Measures the total input/output delay of the system. This is crucial for accurate phase measurement.
* **Delay Mode**: Configures how latency is handled during measurements. Options include "Auto (Align to Peak)" to automatically align the impulse response to its peak, "Calibration (Fixed Delay)" to use the static delay value measured via Calibrate Latency, or "None" to apply no delay compensation.
* **Calibration Delay (ms)**: Displays the fixed delay value measured during latency calibration. This value is used when Delay Mode is set to Calibration.
* **IR SNR**: Displays the Signal-to-Noise Ratio of the Impulse Response for the most recent sweep. Higher values indicate a cleaner measurement.

### Reference Trace

Saves the current measurement result as a "reference" to compare with subsequent measurements.

* **Store Reference**: Saves the current graph as a reference.
* **Apply Reference**: Subtracts the saved reference from the current measurement result. Useful for checking relative changes or "flattening" a response.

## Troubleshooting

* **Audio stream failed to start. Check ASIO settings**: This error message indicates that the audio stream failed to start. Please verify that the ASIO settings (Sample Rate and Block Size) match your audio interface's configuration.
