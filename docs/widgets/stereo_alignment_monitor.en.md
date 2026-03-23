# Stereo Alignment Monitor

![Stereo Alignment Monitor](../assets/widgets/stereo_alignment_monitor.png)

## Overview

A comprehensive tool for analyzing the alignment and consistency between L/R channels.  
It monitors L/R balance, frequency response match, center focus, and phase issues in real-time, providing both quantitative and visual evaluations. Extremely useful for verifying speaker setups and measuring channel imbalances in audio equipment.

## Operation

### Start and Stop Analysis

* **Start/Stop Button**: Toggles the analysis on and off.

### Parameter Settings

* **Smoothing**: Adjusts the amount of temporal smoothing applied to the plots and analysis metrics. Higher values result in slower, more stable readings, making it easier to evaluate consistent trends.

## Reading the Plots

### L/R Difference FFT (Tone Color Shift)

Displays the spectra of both L and R channels and highlights the "difference" between them.

* **Green line**: Left channel spectrum.
* **Yellow line**: Right channel spectrum.
* **Shaded area**: Indicates the level difference (tonal variance) between channels. When both channels match perfectly, the shaded area disappears.

### Band-specific Phase Correlation

Displays the phase correlation coefficient (-1.0 to 1.0) across the frequency range.

* **1.0**: Perfectly in-phase (monaural signal).
* **0**: Uncorrelated (fully independent channels).
* **-1.0**: Perfectly out-of-phase (phase inversion).
Allows you to visually identify which frequency bands are experiencing phase alignment issues.

## Analysis Metrics and Judgments

The panel on the right provides judgments based on four key metrics:

| Metric | Description | Judgment Thresholds |
| :--- | :--- | :--- |
| **L/R Balance** | Displays the difference in total energy between L and R in dB. | < ±0.5dB: Excellent / < ±3.0dB: Good |
| **Freq Match** | Displays the correlation of frequency responses between L and R as a percentage. | > 95%: Professional / > 80%: Good |
| **Center Focus** | Displays the "center localization (M/S ratio)" of the overall signal. | > 85%: Mono / > 50%: Wide |
| **Phase Issues** | Displays the percentage of energy with negative correlation (out-of-phase components). | < 1%: Safe / < 10%: Minor |

## M/S Ratio Bar

A visual bar representing the ratio between center localization (Mid) and spatial components (Side).

* **Towards 100% Mid (Mono)**: The signal is concentrated in the center.
* **Towards 100% Side (Wide)**: The signal is spread widely across the stereo field.
* **Around Center**: Indicates a natural stereo image.
