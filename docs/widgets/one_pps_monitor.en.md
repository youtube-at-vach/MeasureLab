# 1PPS Monitor

![1PPS Monitor](../assets/widgets/one_pps_monitor.png)

## Overview

The 1PPS (Pulse Per Second) Monitor is an experimental tool designed to precisely measure the stability of sampling rates and clock deviations by monitoring 1PPS signals.

It accepts a 1PPS signal from a GPS receiver or high-precision clock source and analyzes the deviation (in PPM: Parts Per Million) from the audio interface's sample rate in real-time.

## Features

* **PPM Deviation Measurement**: Measures the number of samples between rising edges of pulses and compares them to the nominal rate to calculate deviation.
* **Support for Arbitrary Frequencies (Target PPS)**: Supports not only 1PPS but also 10PPS or any arbitrary pulse frequency.
* **Triggered Waveform View**: Visualizes the waveform around detected pulses, allowing for visual confirmation of trigger status.
* **PPM Display**: Visualizes Instantaneous and Cumulative Average deviations in PPM.
* **Outlier Filter**: Robust filtering using Median Absolute Deviation (MAD) to reject glitches and noise.
* **Input Latency Compensation**: Precision measurement accounting for audio interface input latency and manual offsets.
* **Statistics**: Displays Mean, Standard Deviation, Max/Min deviation, and other statistical metrics.

## Operation

### Start and Stop

* **Start / Stop Button**: Starts or stops the measurement.
* **Sync with Audio Engine**: Automatically sets the nominal rate to match the current sample rate of the Audio Engine.

### Tab Interface

The control panel is organized into several tabs.

#### Settings

* **Sample Rate**: Sets the reference sample rate.
* **Target PPS (Hz)**: Sets the frequency of the pulse signal to be measured (default is 1.0Hz). This allows for signals like 10PPS.
* **Outlier Rejection**: Filter settings to reject sudden measurement errors or noise.
    * **Enable Filter**: Enables the filter.
    * **Window**: Number of recent samples used for filter calculation (window size).
    * **Tolerance (Sigma)**: Tolerance range for identifying outliers relative to the median.

#### Waveform

Monitor the pulse waveform in real-time and adjust trigger settings.

* **Input Waveform (Triggered)**: Displays the waveform around the moment of a trigger (pulse detection) (default ±0.5s).
* **Threshold (FS)**: Signal level threshold for pulse detection. Indicated by a green line on the waveform plot.
* **Hysteresis (FS)**: Hysteresis width to prevent chattering. Indicated by a red dashed line on the waveform plot.
* **Latency Compensation**: Settings for latency compensation.
    * **Compensate Input Latency**: Automatically subtracts the input latency reported by the audio interface.
    * **Manual Offset (ms)**: Set an additional manual latency offset in milliseconds.

#### Display & Statistics

* **Unit**: Switch the graph unit between `PPM` and `Seconds`.
* **Show Instantaneous**: Toggle the visibility of the instantaneous deviation curve.
* **Calibration**: Calculate and store calibration factors from measurements.
    * **Stored 1PPS Cal**: Shows the current stored calibration factor.
    * **Calibrate from Current**: Performs calibration based on the current cumulative average.
* **Statistics**: Displays count, mean, standard deviation, max/min values, etc.

## Understanding the Graph

* **Instantaneous (Dotted Line - Yellow)**: Shows the deviation for each pulse. Suitable for observing jitter and short-term fluctuations.
* **Cumulative Avg (Solid Line - Cyan)**: Shows the cumulative average deviation since the start of measurement. Suitable for observing long-term clock drift (frequency offset).

> [!IMPORTANT]
> **Calibration Note**: When "Calibrate from Current" is executed, the calculated calibration factor is saved to the settings. This value is used in frequency settings of the audio engine, but it does not reset the graph display of the monitor itself.
