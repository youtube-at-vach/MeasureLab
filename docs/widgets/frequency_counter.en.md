# Frequency Counter

![Frequency Counter](../assets/widgets/frequency_counter.png)

## Overview

This tool measures and displays the frequency of input signals with high precision.
It achieves extremely high measurement accuracy through the adoption of the Blackman window function and automatic optimization of segment length.
In addition to simply showing the "current frequency," it allows for detailed analysis of frequency fluctuations (jitter) and variations over time (drift).
It can be used for measuring the stability of crystal oscillators, instrument tuning, rotation speed measurement, and more.

## ☕ Coffee Break: What exactly is "Frequency"?

Hearing the word "Frequency (Hz: Hertz)" might sound complicated, but it's actually very simple. It just means "how many times something repeats in one second."
Imagine standing at the beach and watching the waves. If one wave crashes ashore every second, that's "1 Hz." If two waves crash every second, that's "2 Hz." If your heart beats 60 times a minute, that's 1 beat per second, or "1 Hz."

Sound works the same way. The "pitch" of a sound is determined by how many times the air vibrates per second. A typical human voice ranges from about 100 Hz to 1000 Hz. It's pretty amazing to think that the air is vibrating hundreds of times every single second!
The Frequency Counter is like an ultra-reliable stopwatch that flawlessly counts these "invisible, super-fast waves" for you.

## Compact Mode

When detached using the Detachable Wrapper, pressing the "Compact" button switches the widget to Compact Mode, displaying only the frequency and statistical values in an extra-large font. This is highly useful for monitoring values from a distance.

## Operation

### Starting and Stopping Measurements

- **Start / Stop Button**: Toggles the measurement on and off.
    - While measuring, the numerical values on the main display are updated, and the history is recorded in the graph.

### Understanding the Main Display

The large numbers displayed at the top of the screen are the measurement results. It features a high-visibility LED-style design.

- **Green Numbers**: The current frequency (or period).
- **dB Display (bottom right)**: The current signal level (dBFS). Measurements are not taken if the signal is too small (below the Gate setting).

## Screen Configuration and Features

### Display Mode

The numerical display format can be switched according to the application.

- **Frequency**: Displays in Hertz (Hz). This is normally used.
- **Period**: Displays the period (s, ms, µs, ns). Used when you want to know the time taken for one wave cycle.

### Statistics (Stats)

Indicators showing the stability of the measurement are displayed in real-time below the display.

- **Std Dev**: Standard Deviation. Indicates the amount of frequency variation. The smaller the value, the more stable it is.
- **Allan Dev**: Allan Deviation. An indicator of short-term stability, used for evaluating oscillators, etc.

### Graphical Analysis (Tab Switching)

By switching the tabs at the bottom of the screen, you can analyze the data from different perspectives.

1. **Frequency Drift**
    - Records how the frequency changes over time (horizontal axis).
    - Ideal for observing frequency drift due to device warm-up (changes caused by heat).

2. **Allan Deviation**
    - For advanced stability analysis.
    - Displays stability on a log-log graph when the integration time (Tau) is varied, such as "fluctuation over 1 second" or "fluctuation over 10 seconds."
    - A downward-sloping graph means that precision improves as you average over longer periods.

3. **Jitter Histogram**
    - Displays frequency variation as a frequency distribution (histogram).
    - You can check how the measured values are distributed around the mean (whether it is a normal distribution or biased toward a specific frequency).
    - **Baseline Setting**: Choose whether to center the distribution on the "Mean" or an arbitrary "Reference" value.
    - **X-axis Setting**: Choose whether the horizontal axis unit is "Hz/s (Native)" or the deviation rate "ppm".

## Settings

- **Gate (dB)**
    - Sets the "threshold" of the signal level for measurement.
    - Prevents nonsensical numbers from being displayed when there is no input signal or only noise (e.g., -60dB).

- **Channel**
    - Select the audio channel (Ch 1 / Ch 2) to be measured.

- **Update Rate**
    - Sets the frequency of measurement and display updates.
    - **Fast (10Hz)**: Reacts quickly. Useful during circuit adjustment.
    - **Slow (2Hz)**: Updates slowly. Uses a larger buffer, allowing for more stable, high-precision measurements.

- **Calibrate**
    - A function to compensate measured values using a reference signal (an accurate base signal).
    - Since computer audio interface clocks have errors, if strict measurement is required, input a known frequency (e.g., 10MHz rubidium oscillator or GPS standard) and set the correction factor using this function.

## Usage Examples

### Checking the Stability of an Oscillation Circuit

Check how much the frequency of a DIY analog synthesizer or oscillation circuit shifts due to temperature changes (drift).

1. Input the signal and press **Start**.
2. Open the **Frequency Drift** tab.
3. Leave it for several to tens of minutes and observe the movement of the graph.
4. You can observe how the frequency moves significantly immediately after power-on and eventually stabilizes (warm-up characteristics).

### Precise Frequency Tuning

1. Set the **Update Rate** to **Fast**.
2. Look at the **Jitter Histogram** tab.
3. Adjust the circuit so that the histogram peak becomes sharp (reducing variation) and the peak comes to the target center.
4. Switching the units to **ppm** makes it easier to determine if it falls within the tolerable error range (e.g., within ±20ppm).
