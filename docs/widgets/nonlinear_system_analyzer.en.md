# Nonlinear System Analyzer

The Nonlinear System Analyzer is an advanced widget designed for detailed analysis of nonlinear characteristics in audio equipment, amplifiers, and other systems.
It uses Synchronized Swept Sine (SSS) signals to separate and extract the linear component (fundamental) and higher-order harmonic components (kernels) from the system response.
Based on the Hammerstein model, this nonlinear analysis allows for the evaluation of complex distortion characteristics.

---

## ☕ Coffee Break: What is the Hammerstein Model?

The Hammerstein model is a mathematical approach to represent distortion in real-world audio equipment, such as speakers or vacuum tube amplifiers.
It assumes a series structure where the input signal first passes through a "nonlinear element" (the part that distorts) and then through a "linear element" (a filter with frequency characteristics).
This module uses this model to reverse-calculate and separate the distortion components (kernels) of each order from the measured signal, revealing precise distortion profiles.

---

## Overview

This widget provides the following analysis capabilities:

* **Hammerstein Kernel Extraction:** Extracts kernels from 1st (linear) up to 5th order from the measured response.
* **Frequency Response Display:** Plots the frequency response (magnitude) of each extracted kernel.
* **THD / Harmonic Distortion Analysis:** Measures the level of each harmonic component relative to the fundamental to evaluate the frequency dependence of distortion.
* **Impulse Response Display:** Allows viewing the impulse response of each kernel in the time domain.

## How to Use

1. **Ref. Channel / Meas. Channel:** Select the reference channel and the channel connected to the device under test (DUT).
2. **Start Frequency / End Frequency:** Set the start and end frequencies for the swept sine signal.
3. **Sweep Duration:** Set the duration for a single sweep. A longer sweep improves the signal-to-noise ratio.
4. **Num Amplitudes:** Set the number of amplitude steps (typically around 5) used for analysis.
5. **Average:** Set the number of averages for the measurement.
6. **Analyze Button:** Click to start the measurement sequence.

## Reading the Graphs

* **Fundamental (Linear Kernel h1):** Shows the linear frequency response (fundamental) of the system.
* **2nd Order (Kernel h2) - 5th Order (Kernel h5):** Shows the frequency characteristics of the 2nd to 5th order nonlinear kernels (distortion components).
