# Lock-in Spectrum Finder

## Overview

The **Lock-in Spectrum Finder** is a widget that uses the principles of lock-in detection (matrix projection) to calculate and display the spectrum of a specified frequency band with extremely high resolution.
It is specialized for detecting weak signals at low noise floors or observing specific narrow bands where standard FFT-based spectrum analyzers lack sufficient resolution.

> [!WARNING]
> **Important Note on Measured Values**
> This widget is specialized for "finding" the presence and frequency of weak signals buried in noise.
> Due to the nature of lock-in detection, if the frequency of the actual signal does not perfectly match one of the specified analysis frequencies (Basis Points), the displayed amplitude may be lower than the true value. Therefore, despite long integration times, please treat the amplitude values on the screen as a **rough guide** for locating peak positions. If you need strictly accurate measurements of amplitude and phase at a specific frequency, use this widget to identify the frequency first, and then use the dedicated **Lock-in Amplifier** widget to measure in perfect synchronization with that target frequency.

## Usage Comparison with Other Widgets

This widget is specialized for "finding" weak signals within a specific narrow band. For effective measurement, use it in combination with the following widgets depending on your goals:

* **[Spectrum Analyzer](spectrum_analyzer.md)**
    If you want to quickly grasp the frequency components and noise distribution over a wide frequency band, use the Spectrum Analyzer first. When you find a minor peak or noise that you want to examine in more detail with extremely high resolution, switch to this widget (especially utilizing the Zoom mode) for a deeper analysis.
* **[Lock-in Amplifier](lock_in_amplifier.md)**
    Once you have identified the exact frequency of the target signal using this widget, use the Lock-in Amplifier. By perfectly synchronizing (locking) to the identified frequency, you can measure the actual accurate amplitude and phase, and evaluate long-term stability.

## Modes

You can select between two analysis modes based on your needs.

* **Scan Mode**
    * Calculates the spectrum from a specified start frequency to a stop frequency.
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

### Scan Mode Specific Settings

* **Start Freq**
    * Specifies the starting frequency (Hz) for the analysis.
* **Stop Freq**
    * Specifies the stopping frequency (Hz) for the analysis.
* **Spacing**
    * Choose the spacing of points between `Log` (logarithmic), `Lin` (linear), `Integer` (rounded to nearest integer), `Int x Sync` (integer multiple of the sample sync frequency), or `Octave` bands (from `1/3 Octave` down to `1/96 Octave`). The X-axis of the plot switches automatically to match this setting.
    * **Integer**: Ensures that all analysis frequencies are exact integers, making it easier to accurately capture peaks of artificially generated signals (which are often set to natural numbers like 1000Hz).
    * **Int x Sync**: Rounds frequencies so they correspond exclusively to exact multiples of the analysis buffer resolution (`fs / buffer_size`). Ideal for precision tracking of signals generated synchronously with the measurement buffer.
    * **Octave Bands**: Calculates frequencies strictly based on the specified fractional octave bands relative to the **Octave Ref Freq**.
* **Scan Targets:**
    * **Include Scan Targets**: When checked, the frequencies defined in the **Scan Targets** tab are automatically added to the analysis, guaranteeing that important frequencies (e.g., mains harmonics up to the 16th order) are accurately measured regardless of the base spacing settings.
    * **Octave Ref Freq**: Reference frequency for Octave band calculations.

### Scan Targets Tab

The **Scan Targets** tab provides target management features for specific frequencies.

* **Predefined Targets**: By default, it includes common frequencies like power line fundamentals and their harmonics up to the 16th order.
* **Add / Delete**: You can manually add or remove specific target frequencies with custom notes.
* **Import / Export**: Save and load target lists as JSON files.
* **Zoom to Selected**: Quickly transitions to Zoom Mode centered on the selected target frequency.

### Zoom Mode Specific Settings

* **Zoom Center**
    * Specifies the center frequency (Hz) for the zoom analysis.
* **Track Peak**
    * When checked, the center frequency is automatically updated to the frequency of the highest peak detected after each analysis sweep. This is useful for tracking drifting peaks or precisely converging on the true center frequency.
* **Zoom Span (±)**
    * Specifies the analysis width (±Hz) from the center frequency. (e.g., if Center=1000Hz and Span=10Hz, it analyzes the range from 990Hz to 1010Hz).

## How to Read the Graph

* **Horizontal Axis (Frequency)**: Represents the frequency (Hz).
* **Vertical Axis (Amplitude)**: Represents the amplitude level in the specified unit (dBFS, dBV, or dB SPL). If calibration has been applied, offsets such as the input offset or microphone offset are included.
* **Scatter Plot Tooltips**: Clicking on the red target markers in the plot will display a rich tooltip showing the exact Frequency, Magnitude, Phase, and any associated cause/note for that target.
* During calculations, a red vertical line (sweep line) appears on the graph to indicate the current progress, and the spectrum is updated progressively. If Averages is enabled, the current averaging count is also displayed alongside the progress.
