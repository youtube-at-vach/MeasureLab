# Nonlinear System Analyzer

The Nonlinear System Analyzer is an advanced widget designed for detailed analysis of nonlinear characteristics in audio equipment, amplifiers, and other systems.
It uses Synchronized Swept Sine (SSS) signals to separate and extract the linear component (fundamental) and higher-order harmonic components (kernels) from the system response.
Based on the Parallel Hammerstein model, this nonlinear analysis allows for the evaluation of complex distortion characteristics.

## ☕ Coffee Break: What is the Hammerstein Model?

The Hammerstein model is a mathematical approach to represent distortion in real-world audio equipment, such as speakers or vacuum tube amplifiers.
It assumes a series structure where the input signal first passes through a "nonlinear element" (the part that distorts) and then through a "linear element" (a filter with frequency characteristics).
This module uses this model to reverse-calculate and separate the distortion components (kernels) of each order from the measured signal, revealing precise distortion profiles.

## Overview

This widget provides the following analysis capabilities:

* **Hammerstein Kernel Extraction:** Extracts kernels from 1st (linear) up to 5th order from the measured response.
* **Bode Plot (Magnitude/Phase) Display:** Plots the gain frequency response (Magnitude) and phase frequency response (Phase) of each extracted kernel.
* **Impulse Response Display:** Allows viewing the impulse response of each kernel in the time domain.
* **Harmonic Simulator:** Predicts and simulates output harmonic components (1st to 5th) and their spectrum in real time based on measured data when a sine wave of arbitrary frequency and amplitude is input.

## Settings

### SSS Parameters

* **Start Freq (Hz):** Sets the start frequency for the sweep signal (2.0 to 20000 Hz).
* **End Freq (Hz):** Sets the end frequency for the sweep signal (20 to 24000 Hz).
* **Sweep Time (s):** Sets the duration of a single sweep (0.5 to 30.0 s).
* **TSA Averages:** Sets the number of Time Synchronized Averaging (TSA) iterations (1 to 20). Increasing averages effectively reduces the impact of environmental noise.

### Hammerstein Modeling

* **Max Amp (dBFS):** Sets the maximum peak amplitude level for the sweep signal (-60.0 to 0.0 dBFS).
* **Amp Scans (P=5):** Sets the number of amplitude scanning steps used for Parallel Hammerstein Model separation (5 to 10 steps, typically 5).
* **Display Smoothing:** Sets the smoothing filter strength for drawing graphs ("None", "Light", "Medium", "Heavy"). Applies a Savitzky-Golay filter to smooth measurement noise.

### Routing & Calibration

* **Output Ch:** Sets the channel to output the sweep signal ("Left", "Right", "Stereo").
* **Input Mode:** Sets the capture mode for the input signal.
    * **Left (Ch1):** Uses channel 1 only.
    * **Right (Ch2):** Uses channel 2 only.
    * **XFER (Ref=L, Meas=R):** Transfer function measurement using channel 1 as reference and channel 2 as measurement target.
    * **XFER (Ref=R, Meas=L):** Transfer function measurement using channel 2 as reference and channel 1 as measurement target.
* **Latency:** Displays the measured loopback latency time in milliseconds (ms).
* **Calibrate Delay Button:** Measures and calibrates the input/output latency using the physical loopback path of the device (only active when Input Mode is set to `Left (Ch1)` or `Right (Ch2)`. It is disabled in XFER modes since the delay/phase difference is automatically canceled).

## Measurement Controls

* **Start Analysis Button:** Starts the amplitude scanning and sweep measurement sequence using the configured parameters. During measurement, the main audio engine stream is temporarily occupied.
* **Stop Button:** Aborts the active measurement sequence.
* **Progress Bar:** Displays the progress of the entire measurement sequence as a percentage.

## Reading the Graphs and Tabs

The plot area is divided into tabs, allowing you to view four types of analysis data:

### 1. Bode Magnitude

Displays the gain frequency response of the separated 1st to 5th order harmonic kernels (dB vs Hz, logarithmic X-axis).
Once measurement is complete, a gray vertical dashed line (`Sim Freq`) is shown for setting the simulation frequency. Dragging this line left or right updates the input frequency of the Harmonic Simulator in real time.

### 2. Bode Phase

Displays the phase frequency response of the separated 1st to 5th order harmonic kernels (deg vs Hz, logarithmic X-axis).
A synchronized simulation frequency line is also displayed here, sharing positioning with `Bode Magnitude`.

### 3. Hammerstein Kernels

Displays the separated impulse responses $h_1(t) \sim h_5(t)$ in the time domain.
To observe impulse response peak details closely, the time axis (X-axis) is automatically zoomed to a range of -5 ms to +35 ms.

### 4. Harmonic Simulator

Predicts the output response numerically and spectrally when an arbitrary sine wave is input to the system, utilizing the measured Hammerstein kernel gain and phase data.
It becomes active after a measurement has successfully completed.

* **Input Parameters:**
    * **Input Frequency:** Sets the fundamental frequency $f_0$ of the input sine wave (20.0 to 20000.0 Hz). Can be changed using the slider or numeric spin box. It also bidirectionally links with the `Sim Freq` cursor drag on Bode Magnitude/Phase plots.
    * **Input Amplitude:** Sets the amplitude of the input sine wave (-60.0 to 0.0 dBFS).
    * **Include Audio Interface Phase:** When checked, factors the reference loopback phase of the audio interface itself into the simulation result for correction.
* **Prediction Results Table:**
    * Computes and displays the predicted frequency, amplitude (dBFS), and phase (relative to the fundamental) for each distortion component (Fundamental, 2nd Harmonic to 5th Harmonic) in real time.
    * If a harmonic's frequency exceeds the Nyquist frequency (half the sampling rate), it will automatically display `N/A (Nyquist)` and be excluded from predictions.
* **Output Prediction Spectrum:**
    * Renders the simulated level of each harmonic component as colored vertical bars (with dots) on the frequency spectrum, letting you visually evaluate the distortion profile.
