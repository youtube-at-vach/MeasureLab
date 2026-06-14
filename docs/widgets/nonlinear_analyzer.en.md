# Nonlinear Analyzer

The Nonlinear Analyzer is an advanced widget designed for detailed measurement of nonlinear characteristics in audio equipment, amplifiers, and other systems.
It uses Synchronized Swept Sine (SSS) signals to separate and extract the linear component (fundamental) and higher-order harmonic components (kernels) from the system response, generating Parallel Hammerstein model data.
Based on the Parallel Hammerstein model, this nonlinear analysis allows for the evaluation of complex distortion characteristics.

## ☕ Coffee Break: What is the Hammerstein Model?

The Hammerstein model represents distortion in audio equipment as a series structure: a "nonlinear element" (the part that distorts) followed by a "linear element" (a filter with frequency characteristics).
This module uses this model to reverse-calculate and separate distortion components (kernels) from the measured signal.

## Overview

This widget provides the following analysis capabilities:

* **Hammerstein Kernel Extraction:** Extracts kernels from 1st (linear) up to 5th order from the measured response.
* **Bode Plot (Magnitude/Phase) Display:** Plots the gain frequency response (Magnitude) and phase frequency response (Phase) of each extracted kernel.
* **Impulse Response Display:** Allows viewing the impulse response of each kernel in the time domain.
* **Model Caching and Exporting:** Once a measurement is complete, the extracted model is automatically saved to the active model cache. This allows other modules (e.g., [Response Viewer](response_viewer.md)) to use it for advanced analysis or simulation. It can also be exported locally as a JSON file.

## Settings

### SSS Parameters

* **Start Freq (Hz):** Sets the start frequency for the sweep signal (2.0 to 20000 Hz).
* **End Freq (Hz):** Sets the end frequency for the sweep signal (20 to 24000 Hz).
* **Sweep Time (s):** Sets the duration of a single sweep (0.5 to 30.0 s).
* **Averages (Time-Sync):** Sets the number of Time Synchronized Averaging (TSA) iterations (1 to 20). Increasing averages effectively reduces the impact of environmental noise.
* **Measure Noise Floor:** If checked, inserts a 1-second silence at the end of the measurement to calculate the environmental noise floor (dBFS) within the 20Hz–20kHz range.

### Nonlinear Modeling

* **Max Amp (dBFS):** Sets the maximum peak amplitude level for the sweep signal (-60.0 to 0.0 dBFS).
* **Amplitude Steps (Max Order 5):** Sets the number of amplitude scanning steps used for Parallel Hammerstein Model separation (5 to 10 steps, typically 5).
* **Graph Smoothing:** Sets the smoothing filter strength for drawing graphs ("None", "Low Smoothing", "Medium Smoothing", "High Smoothing"). Applies a Savitzky-Golay filter to smooth measurement noise.

### Routing & Calibration

* **Output Ch:** Sets the channel to output the sweep signal ("Left", "Right", "Stereo").
* **Input Mode:** Sets the capture mode for the input signal.
    * **Single Ch (Left Ch1):** Uses channel 1 only.
    * **Single Ch (Right Ch2):** Uses channel 2 only.
    * **2-Ch Relative (Ref=L, Meas=R):** Transfer function measurement using channel 1 as reference and channel 2 as measurement target.
    * **2-Ch Relative (Ref=R, Meas=L):** Transfer function measurement using channel 2 as reference and channel 1 as measurement target.
* **Delay Time:** Displays the measured loopback latency time in milliseconds (ms).
* **Measure Delay Button:** Measures and calibrates the input/output latency using the physical loopback path of the device (only active when Input Mode is set to `Single Ch (Left Ch1)` or `Single Ch (Right Ch2)`. It is disabled in 2-Ch Relative modes since the delay/phase difference is automatically canceled).

## Measurement Controls

* **Start Analysis Button:** Starts the amplitude scanning and sweep measurement sequence using the configured parameters. During measurement, the main audio engine stream is temporarily occupied.
* **Stop Button:** Aborts the active measurement sequence.
* **Export Model... Button:** Exports the extracted Hammerstein model to a JSON file once a measurement has successfully completed.
* **Progress Bar:** Displays the progress of the entire measurement sequence as a percentage.

## Reading the Graphs and Tabs

The plot area is divided into tabs, allowing you to view three types of analysis data:

### 1. Bode Magnitude

Displays the gain frequency response of the separated 1st to 5th order harmonic kernels (dB vs Hz, logarithmic X-axis).

### 2. Bode Phase

Displays the phase frequency response of the separated 1st to 5th order harmonic kernels (deg vs Hz, logarithmic X-axis).

### 3. Hammerstein Kernels

Displays the separated impulse responses $h_1(t) \sim h_5(t)$ in the time domain.
To observe impulse response peak details closely, the time axis (X-axis) is automatically zoomed to a range of -5 ms to +35 ms.

## To Analyze Responses and Run Simulations

To perform more detailed analysis using the measured Parallel Hammerstein model—such as THD maps, gain compression curves, tone response simulations, and Wiener representation conversion—please use the [Response Viewer](response_viewer.md) module.
Once a measurement completes, the model is automatically kept in the active cache. Simply open the Response Viewer and click **Load Live Cache** to start analyzing.
