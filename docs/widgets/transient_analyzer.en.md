# Transient Analyzer (Transient Response & Wavelet Analysis)

![Transient Analyzer](../assets/widgets/transient_analyzer.png)

## Overview

A tool for detailed analysis of "transient sounds," such as instantaneous impact sounds or sounds whose frequency changes from moment to moment.
It uses the **Continuous Wavelet Transform (CWT)** to visualize sounds while maintaining temporal resolution—capturing "when and at what pitch a sound occurred"—which is often difficult for standard FFT analysis to achieve.

## Operation

### Recording

* **Record**: Pressing this button starts the recording. It stops automatically after acquiring data for the set **Record Time**.
* **Trigger**: Like an oscilloscope, recording can be started at the moment a sound volume beyond a certain **Level** is detected.

### Analysis

* After recording is complete, press the **Analyze** button to perform the Wavelet Transform.
  * **Note**: This process is computationally intensive and may take several seconds to show results.

### Reading the Charts

* **Transient Waveform (Top)**: The waveform of the recorded sound (Time axis).
* **Wavelet Scalogram (Bottom)**:
  * **Horizontal axis**: Time
  * **Vertical axis**: Frequency (Logarithmic display)
  * **Color**: Intensity at that moment.
  * Similar to a spectrogram, but it analyzes low-pitched sounds broadly in the time direction and high-pitched sounds sharply. This allows for a well-balanced simultaneous display of instantaneous click sounds (time information) and low hums (frequency information).

## Settings

* **Wavelet**: Selection of the waveform (mother function) type used for analysis. Generally, `cmor` (Complex Morlet) is suitable.
* **Min / Max Freq**: Specifies the frequency range to be analyzed.

## Use Cases

* **Impact Sound Analysis**: Examining the response when a pulse is input to a speaker (impulse response) or changes in sound components when something collides.
* **Evaluation of Instrument Attack**: Detailed observation of how harmonics appear at the moment a musical instrument starts sounding.
