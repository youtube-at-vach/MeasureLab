# Inverse Filter

![Inverse Filter](../assets/widgets/inverse_filter.png)

## Overview

A tool for creating and applying a filter to an audio file that "cancels out" a system's frequency response (such as the idiosyncrasies of speakers or microphones) obtained through measurement.

For example, if you have an audio recording from a speaker with slightly weak high-frequency response, you can calculate and apply the inverse characteristic (boosting the high-frequency) to synthesize audio that is closer to an ideal flat response.

## Operations

### Load Calibration Data

*   **Reload from Memory**: Imports the latest calibration data measured by tools like the `Network Analyzer` and currently held in the application's memory.
*   **Load File**: Loads a previously saved calibration map in `.json` format.

### Filter Design

Adjust the shape of the correction filter based on the loaded data.
*   **Max Gain (Regularization)**: A limit value to suppress excessive amplification during correction. For example, if set to "10dB," even if the original signal has a 20dB drop, it will only be boosted by up to 10dB. This prevents excessive noise amplification.
*   **FIR Taps**: The resolution/fineness of the filter. Larger values allow for more precise correction but increase computational load. Usually, around `8192` is recommended.
*   **Smoothing**: Smooths out peaks and dips in the response characteristics.

### Audio Processing

*   **Input**: Select the audio file (WAV format) you wish to process.
*   **Process & Save**: Saves a new file with the filter applied.

## Settings

*   **Normalize Output (RMS)**: Automatically adjusts the output to match the perceived volume of the original file, preventing overall volume changes caused by correction.

## Usage Examples

*   **Microphone Correction**: If a microphone's frequency response is known, applying the inverse characteristic to a recorded voice can result in sound quality that is more faithful to the original.
*   **Simple Room Acoustic Correction**: Used in research to bring recording results closer to a flat response when played back in a specific room.
