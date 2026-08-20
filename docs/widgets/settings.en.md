# Settings

## Overview

In the Settings widget, you manage settings related to the operation of the entire application. Audio device selection, calibration, changing display language and themes, etc., are performed here.

## Common Features

This widget supports the common features of the Detachable Wrapper. Please refer to the [Detachable Wrapper](detachable_wrapper.en.md) documentation for details.

## General

### Language

Changes the display language of the application. A restart of the application is required to apply the changes.

### Appearance

Selects the theme color of the application.

* **System**: Follows the system settings.
* **Light**: Light theme (white-based).
* **Dark**: Dark theme (black-based).

### Screenshots

Specifies the destination folder for saving screenshots taken in each measurement widget. You can select a folder with the "Browse..." button.

### FFT Optimization

Performs optimization to improve the processing speed of FFT (Fast Fourier Transform).

* **Regenerate Optimization**: Executes the optimization process. Execution may take several seconds to several minutes.
* **Include Huge Sizes**: If checked, it also performs optimization for very large data sizes (up to 4M samples). It takes time to process, but it is advantageous when performing huge FFTs.

## Audio

### Audio Devices

Selects the input and output devices. Previous settings have been split into tabs.

* **Audio Devices Tab**:
    * **Host API**: Selects the audio backend (API) (e.g., MME, WASAPI, ASIO, ALSA, JACK, etc.).
    * **Input Device**: Selects the input device with a measurement microphone, etc., connected.
    * **Output Device**: Selects the output device with speakers, etc., connected.
    * **Refresh Devices**: Updates the device list. This is disabled when JACK is running on Linux for safety.
    * **Measure Bit Depth...**: Opens a dialog to measure and visualize the Effective Number of Bits (ENOB) and quantization noise characteristics of the audio device. Click "Start Analysis" to begin the measurement. Useful for verifying the actual bit depth based on real measurements.
        * **Effective Bit Depth History**: Displays the time series of ENOB (Effective Number of Bits).
        * **Bit Activity (LSB to MSB)**: Visualizes the activity of each bit (from LSB to MSB) as a heatmap. Useful for detecting stuck bits.
        * **Quantization Step (Delta) Distribution**: Displays the distribution of quantization steps (differences between adjacent samples).
* **Virtual / Offline Mode Tab**:
    * **Virtual Audio (No Hardware)**: Enables the virtual audio driver. Use this when no physical interface is available.
    * **Simulation Rate**: Sets the sampling rate for the Virtual Mode.

### Audio Configuration

* **PipeWire / JACK Mode (Resident)**: Enable when using PipeWire or JACK in a Linux environment. If checked, the audio engine continues to operate even if all widgets are closed, and external connections are maintained.
* **Sample Rate**: Selects the sampling frequency.
* **Buffer Optimization**: Selects the optimization level of the buffer size according to the application.
* **Buffer Size**: Actual size of the audio buffer.

* **Input/Output Channels**: Selects the channel mode (Stereo, Left, Right).
* **Enable Dithering (TPDF)**: Adds dither to the output signal to reduce quantization distortion.
* **Dithering Bit Depth**: Selects the bit depth for dithering application (8-bit, 16-bit, 24-bit).

## Calibration

Performs calibration to improve measurement accuracy. Pressing the "Wizard" button for each item allows you to perform calibration in an interactive format.

### Calibration Profiles

Calibration profiles recall all input, output, SPL, frequency, 1PPS, and lock-in calibration values as one state. Selecting a profile applies it immediately, and subsequent calibration changes are saved automatically to the active profile.

* **Current calibration (no profile)**: Keeps the current values without assigning them to a named profile.
* **New**: Creates and activates a safe, uncalibrated profile for the current input and output devices.
* **Duplicate**: Copies the current calibration values to a new named profile and activates it.
* **Rename**: Changes the active profile name without changing its values or device information.
* **Delete**: Deletes the active profile after confirmation. The current values remain active as an unnamed calibration.

The registered input and output devices are shown below the selector. If they differ from the active audio devices, a warning is displayed. Recalling a profile does not change the selected audio devices.

### Current Settings

* **Input Sensitivity**: Setting for the voltage level of the input signal. Can be automatically calculated with "Wizard".
* **Output Gain**: Setting for the voltage level of the output signal. Can be automatically calculated with "Wizard".
* **SPL Offset**: Correction value of the dB SPL value displayed by the Sound Level Meter, etc. Can be automatically calculated with "Wizard".

### Stored Calibration Values (Advanced Settings)

Visible when "Show stored calibration values" is checked.

* **Frequency Calibration Source**: Selects the reference source used for audio engine frequency correction (Configurable).
    * **Frequency Counter**: Uses the factor calibrated by the Frequency Counter widget.
    * **1PPS Monitor**: Uses the factor calibrated (Calibrate from Current) from the 1PPS Monitor widget. This provides higher precision calibration when a 1PPS reference is available.
* **Frequency Calibration**: Frequency deviation of the internal clock (ppm). (Read-only)
* **1PPS Frequency Calibration**: Deviation from an external reference based on the 1PPS signal (ppm). (Read-only)
* **Lock-in Gain Offset**: Internal gain correction value for lock-in amplifier measurements (mdB/dB). (Read-only)
