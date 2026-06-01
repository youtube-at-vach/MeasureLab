# Transmission Analyzer

> [!WARNING]
> **Experimental Feature**
> This widget is currently an experimental feature under active development. Its interface, algorithms, and specifications are subject to significant changes in future updates.

---

## Overview

**Transmission Analyzer** is a specialized module designed to verify and diagnose the operational integrity of audio transmission paths, audio interfaces, and DAC/ADC systems using pseudo-random binary sequences (PRBS) based on Linear Feedback Shift Registers (LFSR).

It supports both digital and analog signal paths—such as USB cables, Bluetooth connections, or physical analog circuits—measuring sampling synchronization delay, clock jitter, and signal integrity in real-time.

---

## ☕ Coffee Break: Why Measure Audio with "PRBS"?

When we think of audio measurements, we usually picture a pure sine wave ("beep") or a frequency sweep.

However, complex digital issues like "occasional single-bit flips" or "silent DSP intervention (volume scaling/EQ) breaking bit-perfect transmission" are extremely difficult to detect using simple sine waves.

This is where **PRBS (Pseudo-Random Binary Sequence)** comes into play. While it sounds like pure white noise to the ear, it is a highly deterministic digital sequence where every subsequent value is mathematically "completely predictable."

By transmitting this sequence and comparing the received signal with the "expected sequence," we can simultaneously and precisely evaluate:

1. **Digital Integrity**: Confirming if the transmission is 100% "bit-perfect" (free from even a single sample/bit deviation) and exactly which bits are flipping.
2. **Analog Characteristics**: Extracting non-linear distortion, phase deviation, physical delay down to the millisecond, and sub-sample clock jitter.

This allow us to diagnose the entire transmission path instantly and with extreme precision!

---

## Key Features & Measurement Modes

The Transmission Analyzer offers two distinct measurement modes tailored to different testing objectives.

### 1. Digital Integrity Mode

Mainly diagnoses whether a digital audio transmission path (USB, S/PDIF, network, OS mixer, or internal app routing) is **bit-perfect (lossless)**.

* **Bit-Perfect Verification**: Real-time checking of whether transmitted and received samples match perfectly.
* **Bit Error Rate (BER) Calculation**: Calculates the ratio of flipped bits over the total number of transmitted samples.
* **Error Bit Histogram**: Visualizes which specific bits among the 24-bit representation (from LSB to MSB) are experiencing errors, aiding in tracking hardware and driver anomalies.
* **Automatic DSP Detection**:
    * If the signal is altered, an advanced heuristic algorithm analyzes the error structure to identify the cause: "Volume scaling (gain adjustment)," "Bit depth truncation (to 16-bit or 8-bit)," "Dither/noise-shaping application," or "Heavy EQ/compression."

### 2. Analog Transmission Mode

Evaluates the signal quality of physical analog transmission paths, including cables, amplifiers, and DAC-to-ADC loopback setups.

* **Error Vector Magnitude (EVM) Measurement**:
    * Applies EVM (a standard metric in digital communications) to audio signals, displaying the waveform deviation caused by noise and distortion as a percentage (%).
* **Equalized EVM**:
    * Automatically estimates and compensates for the linear frequency response (amplitude ripples, group delay) of the analog path before computing EVM. This isolates non-linear distortion and noise, removing the impact of volume attenuation or harmless linear filters.
* **Impulse Response**:
    * Extracts the channel's impulse response instantly via regularized FFT deconvolution and displays it in the time domain.
* **Frequency Response**:
    * Capitalizes on the wide bandwidth of the PRBS sequence to plot real-time amplitude frequency response simultaneously.

### Shared Capabilities (Sync, Delay, and Jitter)

The widget automatically establishes and tracks synchronization at the sample level.

* **Physical Delay Measurement**: Automatically measures the total propagation delay of the path in both samples and milliseconds.
* **Jitter & Drift Tracking**: Tracks sub-sample delay fluctuations (jitter) and cumulative clock drift caused by clock rate discrepancies between playback and recording devices.
* **Buffer-Skip Recovery (Warp Recovery)**: If heavy CPU load or driver anomalies cause sudden buffer drops/skips, the warp algorithm detects the jump destination and automatically re-aligns without losing synchronization.

---

## Control & Configuration Settings

Adjust the analyzer's behavior using the left control panel.

### 1. Test Controls

* **Start/Stop Diagnostics**:
    Toggles the PRBS signal generation and analysis. When started, the PRBS signal is played through the selected output channel.
* **Reset Statistics**:
    Resets the accumulated bit errors, error rate, and bit histograms, starting the measurement fresh.

### 2. Analyzer Settings

* **Analysis Mode**:
    * `Digital Integrity`: Optimizes for bit-perfect validation, error tracing, and DSP diagnostics.
    * `Analog Transmission`: Optimizes for analog metrics such as EVM, impulse response, and frequency response.
* **Input Channel**:
    Selects the input channel (`Left Channel (CH1)` or `Right Channel (CH2)`) to analyze.
* **PRBS Pattern**:
    Selects the LFSR polynomial degree (sequence period).
    * `PRBS-7`: Very short period (127 samples), optimized for fast sync.
    * `PRBS-9`: For low-latency paths.
    * `PRBS-15`: Industry standard. Balanced and ideal for most measurements.
    * `PRBS-23`: Long period (8,388,607 samples). Suited for long-term sweeps and high-load diagnostic tests.
    * `PRBS-31`: Ultra-long period, used for extreme stress tests.
* **Bit Depth**:
    Selects the PRBS signal amplitude resolution (`16-bit` or `24-bit`).
* **Response Smoothing**:
    Smooths the frequency response plot from `None (Raw)` up to `1/3 Octave`.
* **Averaging Mode**:
    Controls the averaging filter to suppress noise fluctuations:
    * `None (Instant)`: No averaging, plots real-time values.
    * `Fast (EMA)` / `Slow (EMA)`: Applies Exponential Moving Average.
    * `Infinite (Accumulate)`: Performs cumulative averaging over all processed data.

---

## 📈 Interpreting the Charts

* **Impulse Response / Freq Response Tab**:
    Visualizes the physical path characteristics (time and frequency domains) when in Analog mode.
* **Trend Charts Tab**:
    Displays scrolling timelines of "Gain Deviation (dB)," "Bit Error Rate (BER %)," and "Clock Jitter/Drift (Samples)" to evaluate long-term system stability.
* **Bit Histogram Tab**:
    In Digital mode, this chart reveals which bit depths are affected. Errors confined to the lower bits (LSB side) indicate dithering or quantization effects, whereas errors spread evenly across all bits suggest buffer drops or clipping.
