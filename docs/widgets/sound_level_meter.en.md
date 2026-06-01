# Sound Level Meter

![Sound Level Meter](../assets/widgets/sound_level_meter.png)

## Overview

The Sound Level Meter is a precision tool for measuring environmental noise and the sound pressure level (SPL) of audio equipment. It features weighting filters and time response characteristics compliant with common sound level meter standards (such as IEC 61672).

## ☕ Coffee Break: What is dB?

Sound level is expressed in \"dB (decibels),\" but decibels itself is a logarithmic scale representing a ratio.
The \"dB SPL\" measured by a sound level meter uses the minimum sound pressure that humans can hear as \"0 dB,\" and represents how many times greater the pressure is compared to that baseline.

For example, 40 dB SPL and 70 dB SPL differ by 30, but in terms of sound pressure energy, there is a 1000-fold difference.
The human ear can hear a very wide range of sound pressures, so a logarithmic scale is used to make the numbers easier to handle.

## Compact Mode

When the window is detached using the Detachable Wrapper, pressing the "Compact" button enters Compact Mode. Only the primary numerical values, such as SPL and Leq, are displayed largely across the screen, providing visibility similar to dedicated sound level meter hardware.

## Basic Operation

### Starting Measurement

* **Start Button**: Begins the measurement.
* **Reset Button**: Resets measurement values (such as Leq and Lmax) and recalculates from zero.

### Main Display

The large numbers displayed at the top of the screen.

* **Instantaneous (Lp)**: The current instantaneous sound pressure level.
* **Equivalent (Leq)**: Equivalent continuous sound level. Shows the "average" energy level from the start of measurement to the present. Often used for evaluating fluctuating noise.

### Detail Tabs

* **Histogram (LN)**: Displays the distribution of sound pressure levels in a bar graph.
* **Statistics**: Displays statistical indicators.
    * **L50**: Median value (level exceeded 50% of the time).
    * **L5 / L95**: Represent levels close to the noise peaks and background noise (ambient noise), respectively.
* **Details**: Displays detailed data such as Lmax (maximum value), Lmin (minimum value), Lpeak (peak value of the waveform), and LE (sound exposure level for single events).

## Settings

### Channel

Select the input channel (L or R) to be used for measurement.

### Freq Weight (Frequency Weighting)

Select filters to match human hearing characteristics.

* **A-Weighting**: Characteristics close to the sensitivity of the human ear. Most commonly used for general noise measurement (environmental sounds, noise regulation, etc.).
* **C-Weighting**: Characteristics that do not cut low frequencies as much as A-weighting. Used for measuring loud sounds or mechanical noise.
* **Z-Weighting**: No correction (flat) characteristics. Used for measuring physical sound pressure itself.

### Time Weight (Time Weighting)

Select the follow-up speed for level fluctuations.

* **FAST (125ms)**: For general-purpose measurement. Captures fluctuating sounds.
* **SLOW (1s)**: Suitable for observing the average level of slow fluctuations.
* **IMPULSE**: A special mode for measuring impact sounds (hitting sounds, etc.) (very fast rise, slow decay).
* **10ms**: Unique setting for capturing extremely fast fluctuations.

### Bandwidth

Limits the frequency bandwidth to be measured.

* **20Hz - 20kHz (Wide)**: Entire audible range.
* **20Hz - 12.5kHz** / **8kHz**: Used when matching specific sound level meter standards, etc.

### Duration

Sets the time to automatically end measurement (e.g., 1 minute, 10 minutes, etc.). Setting it to "Continuous" continues measurement until manually stopped.

### Lp Interval

Sets the sampling interval of the instantaneous value (Lp) used for calculating statistical information (histogram and LN values). A smaller value increases the time resolution but also increases the calculation load (Default: 0.1s).

## About Calibration

To display accurate "dB SPL" values, please calibrate the "SPL Offset" in the "Calibration" tab of the **Settings widget** beforehand. If not calibrated, the values displayed are relative to the digital full scale (dBFS).
