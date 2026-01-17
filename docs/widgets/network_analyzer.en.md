# Network Analyzer

![Network Analyzer](../assets/widgets/network_analyzer.png)

## Overview

The Network Analyzer is a tool for measuring the frequency response (amplitude and phase characteristics) of equipment and systems. It features two modes: "Stepped Sine," which measures by changing a sine wave incrementally, and "Fast Chirp," which measures the entire band instantaneously.

Primary uses:

* Measuring frequency response (f-response) of amplifiers and filters.
* Measuring characteristics of speakers and headphones.
* Measuring phase difference and delay between two signals.

## Basic Operation

### Starting Measurement

1. Set the measurement range (Start/End Freq) and Amplitude in the **"Sweep Settings"** tab.
2. Click the **"Start Sweep"** button to begin measurement. Progress is shown on the progress bar during measurement.
3. Click the button again to stop the measurement midway.

### Selecting Measurement Mode

Two modes can be selected according to the application.

* **Stepped Sine**: Measures by changing the frequency one by one in steps. Although it takes more time, it has a high S/N ratio and allows for very high-precision measurements.
* **Fast Chirp**: Uses a signal (chirp signal) that changes rapidly from low to high frequencies. Since measurement of the entire band can be completed in just a few seconds, it is convenient for measuring while making adjustments.

## Routing and XFER Mode

### Input/Output Settings

* **Output Ch**: Select the channel to output the measurement signal.
* **Input Mode**: Select where to receive the signal returning from the measurement target.
    * **Left (Ch1)** / **Right (Ch2)**: Measures the signal of the selected channel as is (absolute level measurement).
    * **XFER (Transfer Function Mode)**: Uses the Left channel as a "reference signal" and the Right channel as the "measurement signal," calculating their ratio (H = Meas / Ref). This allows for measuring pure device characteristics by canceling out the inherent traits of the audio interface itself (relative measurement).

## Display and Analysis (Display)

Customize the graph display in the **"Display Settings"** tab.

### Graph Types

* **Magnitude Response**: Displays gain (amplification factor) for each frequency. Units can be selected from dBFS, dBV, dBu, etc.
* **Phase Response**: Displays the phase shift for each frequency.
* **Group Delay**: Displays the delay time for each frequency, calculated from the slope of the phase (check "Show Group Delay").

### Display Options

* **Smoothing**: Smooths out fine jaggedness (noise) in the graph. Selectable from Light/Medium/Heavy.
* **Limit Max/Min**: Limits the frequency range displayed on the graph.

## Calibration

### Latency

Press the "Calibrate Latency" button to measure the input/output delay time of the system. It is recommended to perform this in advance with a loopback connection to ensure accurate phase measurement (especially at high frequencies).

### Reference Trace

Saves the current measurement result as a "reference" to compare with subsequent measurements or to subtract it.

* **Store Reference**: Saves the current graph as a reference.
* **Apply Reference**: Subtracts the saved reference from the current measurement result and displays it (useful for checking changes from a flat state).
