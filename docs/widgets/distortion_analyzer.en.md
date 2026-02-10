# Distortion Analyzer

![Distortion Analyzer](../assets/widgets/distortion_analyzer.png)

## Overview

This is the most fundamental tool for measuring the "performance" of audio equipment numerically.
It measures how accurately amplifiers, DACs, etc., are outputting the original signal (how much they are distorted).
It is like a "blood test" in a health checkup, allowing you to know the basic strength of the equipment.

## Meaning of Key Indicators

This tool measures the following values:

* **THD (Total Harmonic Distortion)**
    * Represents "how many extra overtones (harmonics) were mixed in" relative to a pure signal.
    * The smaller the value, the cleaner and more faithful the sound is to the original.
* **THD+N (Total Harmonic Distortion + Noise)**
    * Total level of contamination, including not only distortion but also noise like "hiss".
    * Most commonly used as a realistic performance indicator.
* **SINAD (Signal-to-Noise and Distortion ratio)**
    * THD+N expressed in dB as a reciprocal.
    * The larger the value, the higher the performance. (e.g., SINAD 100dB corresponds to THD+N 0.001%)
* **IMD (Intermodulation Distortion)**
    * Measures the muddiness that occurs when two different sounds are mixed. This indicator is closer to the performance during playback of complex music signals.

## Operation

### Starting and Stopping Measurements

1. Select the signal used for measurement (usually a Sine Wave) in the **Signal Generator**.
2. Press the **Start Measurement** button to output the signal and begin analysis.
3. Numerical values (such as THD+N) are displayed in real-time.
4. Stop with **Stop Measurement**.

### Measurement Modes (Mode)

#### Real-time

Continues to measure the performance at the current moment.

* **Use Case**: Suitable for adjusting equipment or seeing changes in distortion due to volume position.
* **Meters**: Numerical values are displayed prominently on the left. Percentage values like THD+N automatically adjust their decimal precision based on magnitude (Dynamic Precision).
    * Pressing the **Show Detailed** button displays the following additional information:
    * **Input level**: Level of the input signal (dBFS).
    * **Window**: The window function being used (usually Blackman-Harris).
    * **ENOB (Effective Number of Bits)**: Effective bit depth calculated from SINAD (calculated only when the input level is sufficiently high).
* **Spectrum**: In the graph tab, you can visually inspect distortion components (peaks at 2x and 3x the fundamental frequency).
* **Harmonics**: You can check the breakdown of distortion components (whether there is more 2nd-order or 3rd-order distortion) with a bar graph.

#### Frequency Sweep

Measures by continuously changing the frequency from low to high tones.

* **Use Case**: Used to investigate changes in characteristics for each frequency, such as "good at bass but distorts at high frequencies."
* **Settings**: Set Start (starting frequency), End (ending frequency), and Steps (number of measurement points).
* **Sweep Results**: Results are plotted on a graph.

#### Amplitude Sweep

Measures by changing the volume from small to large.

* **Use Case**: Ideal for finding the maximum output of an amplifier (how far you can raise it before it starts to distort = clipping point).
* **Settings**: Set Start (starting volume) and End (ending volume) in dBFS units.

## Settings

### Generator

Settings for the test signal used for measurement.

* **Signal Generator**:
    * **Sine Wave**: A basic sine wave. Used for THD measurement.
    * **SMPTE / CCIF**: Special pair signals for IMD measurement.
* **Frequency**: Frequency of the sine wave. Standard is `1000 Hz`.
* **Amplitude**: Strength of the signal. The following units can be selected:
    * **dBFS**: Relative to digital full scale.
    * **dBV**: Relative to 1Vrms.
    * **dBu**: Relative to 0.775Vrms.
    * **Vrms**: Voltage RMS.
    * When measuring an amplifier, do not set it to maximum volume immediately; raise it gradually from a low value.
* **Signal Generator Mode**: Select `Off (External Source)` when using an external CD player or similar as the sound source.

### Settings

* **Input Ch / Output Ch**
    * Selects the audio channel (Left or Right) to use for measurement.

* **Averaging**
    * Sets how many measurements to average to stabilize the values.
    * Increasing the value stabilizes the display, but reaction to changes becomes slower.

## Usage Examples

### Checking the Maximum Power of an Amplifier

Investigate "up to how many watts" your amplifier can output cleanly.

1. Set **Mode** to `Real-time`.
2. Start **Amplitude** from a low value and gradually raise it.
3. Look at the **THD+N** value. It usually hovers around 0.01% to 0.1%.
4. The moment a certain volume is exceeded, the value jumps sharply to `1.0%` or `10%`. This is the "clipping (limit)".
5. By reading the voltage just before that, you can calculate the effective output (W).

### Seeing the Secret of Tube Amplifier Tone

Investigate the quality of distortion in tube amplifiers or effectors.

1. Connect the device and output sound.
2. Open the **Harmonics** tab.
3. Look at the bar graph.
    * **2nd (2nd order)** is high: Often described as a warm, pleasing distortion.
    * **3rd (3rd order)** is high: A hard, edgy distortion.
