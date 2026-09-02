---
title: "Nonlinear Response Analyzer"
---

## Overview

The Nonlinear Response Analyzer is an advanced widget designed for detailed system identification and analysis of nonlinear characteristics in audio equipment, DSPs, and other systems.
It uses dynamic test signals (such as Uniform White Noise or Gaussian Noise) to identify the system behavior based on the Wiener model, separating the response into a linear filter component and a memoryless nonlinear polynomial component.

This widget provides the following analysis capabilities:

* **Wiener System Identification:** Identifies linear filters and nonlinear polynomials up to the 5th order.
* **Algorithm Selection:** Supports Multiple Identification Algorithms: Best Linear Approximation (BLA), Two-Stage Algorithm (TSA/SVD), and Bussgang Theorem (Cross-Correlation).
* **Bode Plot Display:** Plots the frequency response (Magnitude and Phase) of the identified linear filter.
* **Nonlinear Curve Display:** Visualizes the identified polynomial transfer function mapping the intermediate signal to the final output.

## Common Features

This widget supports common features of the Detachable Wrapper. Please refer to the [Detachable Wrapper](https://youtube-at-vach.github.io/MeasureLab/en/widgets/detachable_wrapper/) documentation for details.

## Settings

### Test Signal Parameters

* **Signal Type:** Sets the type of excitation signal (Uniform White Noise, Gaussian Noise, Pink Noise, Sine Sweep, PRBS).
* **Duration (s):** Sets the duration of the test signal.
* **Amplitude (dBFS):** Sets the output amplitude of the test signal.
* **Filter Range (Hz):** Limits the frequency band of the test signal to focus the analysis.

### System Identification

* **Polynomial Order:** Sets the order of the nonlinear polynomial (1st to 5th).
* **Algorithm:** Selects the identification method (BLA, TSA/SVD, Bussgang).

## Measurement Controls

* **Start Analysis Button:** Starts the measurement and identification sequence.
* **Stop Button:** Aborts the active measurement sequence.
