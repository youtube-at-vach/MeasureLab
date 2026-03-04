# Lock-in Spectrum Finder

## Overview

The **Lock-in Spectrum Finder** is a widget that uses the principles of lock-in detection (matrix projection) to calculate and display the spectrum of a specified frequency band with extremely high resolution.
It is specialized for detecting weak signals at low noise floors or observing specific narrow bands where standard FFT-based spectrum analyzers lack sufficient resolution.

> [!WARNING]
> **Important Note on Measured Values**
> This widget is specialized for "finding" the presence and frequency of weak signals buried in noise.
> Due to the nature of lock-in detection, if the frequency of the actual signal does not perfectly match one of the specified analysis frequencies (Basis Points), the displayed amplitude may be lower than the true value. Therefore, despite long integration times, please treat the amplitude values on the screen as a **rough guide** for locating peak positions. If you need strictly accurate measurements of amplitude and phase at a specific frequency, use this widget to identify the frequency first, and then use the dedicated **Lock-in Amplifier** widget to measure in perfect synchronization with that target frequency.

## Modes

You can select between two analysis modes based on your needs.

* **Basic Mode**
    * Calculates the spectrum from a specified start frequency to a stop frequency using logarithmic (Log) or linear (Lin) spacing.
    * Best used when you want to view a highly accurate spectrum across a broad bandwidth.
* **Zoom Mode**
    * Calculates the spectrum with ultra-high resolution only around a specific center frequency (span).
    * It internally combines Digital Down Conversion (DDC) with downsampling, making it ideal for detailed observation around specific peaks.

## Controls & Settings

### Common Settings

* **Start Analysis / Stop Analysis Button**
    * Click to toggle the measurement on or off.
* **Mode**
    * Select between `Basic` or `Zoom`.
* **Buffer Size**
    * Specifies the amount of data captured and processed at once.
    * Larger sizes improve frequency resolution but reduce the calculation update rate (up to 512k in Basic mode, up to 8M in Zoom mode).
* **Input Ch**
    * Select the channel to analyze (`Left (Ch 1)` or `Right (Ch 2)`).
* **Averages**
    * Specifies the number of Exponential Moving Averages (EMA) applied to the spectrum calculation results (1 to 1000). This suppresses measurement variations and improves plot accuracy.
* **Basis Points**
    * Sets the number of points (bins) for which the spectrum is calculated (from 16 to 1024).
    * More points provide finer detail but increase computational load.
* **Window**
    * Select the window function used for analysis (`none`, `blackmanharris`, `hann`, `hamming`).
* **Display Unit**
    * Select the vertical axis display unit from `dBFS`, `dBV`, and `dB SPL`.
    * Calibration values (Input offset or SPL offset) from Settings are applied when using `dBV` or `dB SPL`.

### Basic Mode Specific Settings

* **Start Freq**
    * Specifies the starting frequency (Hz) for the analysis.
* **Stop Freq**
    * Specifies the stopping frequency (Hz) for the analysis.
* **Spacing**
    * Choose the spacing of points between `Log` (logarithmic) or `Lin` (linear). The X-axis of the plot switches automatically to match this setting.

### Zoom Mode Specific Settings

* **Zoom Center**
    * Specifies the center frequency (Hz) for the zoom analysis.
* **Zoom Span (±)**
    * Specifies the analysis width (±Hz) from the center frequency. (e.g., if Center=1000Hz and Span=10Hz, it analyzes the range from 990Hz to 1010Hz).

## How to Read the Graph

* **Horizontal Axis (Frequency)**: Represents the frequency (Hz).
* **Vertical Axis (Amplitude)**: Represents the amplitude level in the specified unit (dBFS, dBV, or dB SPL). If calibration has been applied, offsets such as the input offset or microphone offset are included.
* During calculations, a red vertical line (sweep line) appears on the graph to indicate the current progress, and the spectrum is updated progressively. If Averages is enabled, the current averaging count is also displayed alongside the progress.
