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

1. Set the measurement range (Start/End Freq) and Amplitude in the **"Sweep Settings"** tab.
2. Click the **"Start Sweep"** button to begin measurement. Progress is shown on the progress bar during measurement.
3. Click the button again to stop the measurement midway.

## Routing and XFER Mode

### Input/Output Settings

* **Output Ch**: Select the channel to output the measurement signal (Selectable L/R/Stereo even in XFER mode).
* **Input Mode**: Select where to receive the signal returning from the measurement target.
    * **Left (Ch1)** / **Right (Ch2)**: Measures the signal of the selected channel as is (absolute level measurement).
    * **XFER (Ref=L, Meas=R)**: Uses the Left channel as a "reference signal" and the Right channel as the "measurement signal," calculating their ratio (H = Meas / Ref). This allows for measuring pure device characteristics by canceling out the inherent traits of the audio interface itself (relative measurement).
    * **XFER_REV (Ref=R, Meas=L)**: Reverse transfer function mode using Right as reference and Left as measurement signal.
    * **XTALK (Crosstalk)**: Drives one channel and measures the leakage into the other channel.

## Display and Analysis (Display)

Customize the graph display in the **"Display Settings"** tab.

### Graph Types

* **Magnitude Response**: Displays gain (amplification factor) for each frequency. Units can be selected from dBFS, dBV, dBu, etc.
* **Phase Response**: Displays the phase shift for each frequency.
* **Group Delay**: Displays the delay time for each frequency, calculated from the slope of the phase (check "Show Group Delay").
* **Coherence**: Displays the correlation (reliability) between input and output. Values closer to 1.0 indicate less influence from noise or distortion (check "Show Coherence").

### Display Options

* **Smoothing**: Smooths out fine jaggedness (noise) in the graph. Selectable from Light/Medium/Heavy.
* **Limit Max/Min**: Limits the frequency range displayed on the graph.

## Calibration

### Latency

Press the "Calibrate Latency" button to measure the input/output delay time of the system. It is recommended to perform this in advance with a loopback connection to ensure accurate phase measurement (especially at high frequencies).

Additionally, when running a normal sweep measurement, the Impulse Response S/N Ratio (IR SNR) for that measurement will also be displayed in this section.

### Reference Trace

Saves the current measurement result as a "reference" to compare with subsequent measurements or to subtract it.

* **Store Reference**: Saves the current graph as a reference.
* **Apply Reference**: Subtracts the saved reference from the current measurement result and displays it (useful for checking changes from a flat state).
