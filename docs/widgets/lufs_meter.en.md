# LUFS & Level Meter

![Lufs Meter](../assets/widgets/lufs_meter.png)

## Overview

The LUFS Meter is a tool for measuring "Loudness" (the perceived volume by humans), which is the standard used in broadcasting and streaming services (YouTube, Spotify, Netflix, etc.). It uses an algorithm compliant with the international standard ITU-R BS.1770-4. It also simultaneously displays standard peak and RMS meters.

## Key Indicators

### LUFS (Loudness Units Full Scale)

The unit for perceived loudness.

* **Momentary (M)**: Instantaneous loudness (400ms window). Used for checking sharp fluctuations in level.
* **Short-term (S)**: Short-term loudness (3-second window). Suitable for understanding the recent loudness feel.
* **Integrated (I)**: The overall average loudness from the start of measurement to the present. This is the most important indicator for evaluating the volume of an entire program or track. Gating is applied to exclude silent periods.

### Other Indicators

* **RMS**: Root Mean Square value (electrical average level).
* **Peak (Pk)**: The maximum amplitude value of the signal.
* **Crest Factor (CF)**: The difference between Peak and RMS. It represents the width of the dynamic range.

## Operation

### Start Metering

Begins the measurement. Graph plotting and statistical calculations will start.

### Reset Functions

* **Reset Peaks**: Resets the peak hold display on the level meter.
* **Reset Stats**: Resets all LUFS statistical data (Integrated value, Min/Max history, etc.) and restarts calculations from zero.

### Show SPL

When checked, switches the units of the RMS level meter to "dB SPL" (requires prior SPL calibration in the Settings widget). LUFS values are always displayed on a dBFS basis (LUFS).

## Graphs and Statistics

### Statistics Tab

Provides a table of the current value (Current), minimum (Min), maximum (Max), and average (Avg) for each indicator.

### Graph Tab

Displays time-series changes in Momentary (cyan) and Short-term (yellow) loudness.

* **Green dashed line**: A typical target level reference (around -23 LUFS).
* Use this as a guide to check if the track or audio fits within the target range.

## Typical Target Levels

* **TV Broadcasting**: -23 LUFS (Integrated) / -24 LKFS
* **YouTube**: -14 LUFS
* **Spotify**: -14 LUFS
* **CD / Club Music**: -9 to -6 LUFS (Can be much higher due to the "loudness war")
