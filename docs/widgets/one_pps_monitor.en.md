# 1PPS Monitor

![1PPS Monitor](../assets/widgets/one_pps_monitor.png)

## Overview

The 1PPS (Pulse Per Second) Monitor is an experimental tool designed to precisely measure the stability of sampling rates and clock deviations by monitoring 1PPS signals.

It accepts a 1PPS signal from a GPS receiver or high-precision clock source and analyzes the deviation (in PPM: Parts Per Million) from the audio interface's sample rate in real-time.

## Features

* **Sample Interval Measurement**: Measures the number of samples between rising edges of pulses and compares them to the nominal rate.
* **PPM Display**: Visualizes Instantaneous and Cumulative Average deviations in PPM.
* **Outlier Filter**: Robust filtering using Median Absolute Deviation (MAD) to reject glitches and noise.
* **Statistics**: Displays Mean, Standard Deviation, Max/Min deviation, and other statistical metrics.

## Operation

### Start and Stop

* **Start / Stop Button**: Starts or stops the measurement.
* **Sync with Audio Engine**: Automatically sets the nominal rate to match the current sample rate of the Audio Engine.

### Display

#### Graph

* **Instantaneous (Dotted Line)**: Shows the deviation for each pulse. Suitable for observing jitter and short-term fluctuations.
* **Cumulative Avg (Solid Line)**: Shows the cumulative average deviation since the start of measurement. Suitable for observing long-term clock drift (frequency offset).
* **Unit**: Switch the graph unit between `PPM` (Parts Per Million) and `Seconds`.

#### Statistics

* **Count**: Number of detected pulses.
* **Inst**: Current instantaneous deviation.
* **Cumul**: Cumulative average deviation.
* **Rate**: Effective sampling rate calculated from measurements.
* **Mean / Std Dev**: Mean and standard deviation of the deviation.
* **Min / Max**: Minimum and maximum deviation values.

### Calibration

Corrects the measurement offset.

* **Stored 1PPS Cal**: Shows the current stored calibration factor (ppm).

> [!IMPORTANT]
> **Calibrate from Current**: Currently, this function only **acquires and stores** the calibration factor in the settings. It does not automatically apply this factor to the measurement engine yet. To use the calibrated value, refer to the "Stored 1PPS Cal" display.

## Settings

### Sample Rate

* **Sync with Audio Engine**: Follows the audio engine's sample rate setting.
* **Nominal Rate (Hz)**: Manually sets the reference sample rate (when Sync is off).

### Threshold & Hysteresis

Adjusts the sensitivity of pulse detection.

* **Threshold (FS)**: Signal level threshold to be considered a pulse (0.0 to 1.0).
* **Hysteresis (FS)**: Hysteresis width to prevent chattering. The signal must drop below `Threshold - Hysteresis` to re-trigger.

### Outlier Rejection

Filter settings to reject sudden measurement errors or noise.

* **Enable Filter**: Enables the filter.
* **Window**: Number of recent samples used for filter calculation (window size).
* **Tolerance (Sigma)**: Tolerance range for identifying outliers relative to the median (multiples of standard deviation). Lower values are stricter, higher values are more lenient.
