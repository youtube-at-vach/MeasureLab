# Settings

## Overview

In the Settings widget, you manage settings related to the operation of the entire application. Audio device selection, calibration, changing display language and themes, etc., are performed here.

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

Selects the input and output devices to be used.

* **Input Device**: Selects the input device with a measurement microphone, etc., connected.
* **Output Device**: Selects the output device with speakers, etc., connected.
* **Host API**: Selects the audio backend (API) (e.g., MME, WASAPI, ASIO, ALSA, JACK, etc.). Used to filter the device list to show only devices for the specific API.
* **Refresh Devices**: Updates the device list.

### Audio Configuration

* **PipeWire / JACK Mode (Resident)**: Enable when using PipeWire or JACK in a Linux environment. If checked, the audio engine continues to operate even if all widgets are closed, and the routing connection in an external patchbay (such as Graph) is maintained.
* **Sample Rate**: Selects the sampling frequency (e.g., 48000Hz, 192000Hz). A sampling rate as high as possible is recommended for high-precision measurement.
* **Buffer Optimization**: Selects the optimization level of the buffer size according to the application.
    * **FAST / MINIMUM**: Reduces latency, but sound may be interrupted under high load.
    * **STABLE**: Recommended setting. Emphasizes stability.
    * **LOW_FREQ / ULTRA**: Use when low-frequency phase accuracy is important or when extremely high stability is required.
* **Buffer Size**: Actual size of the audio buffer. It is automatically calculated based on the level selected in Buffer Optimization and the sampling rate, but it is also possible to select "Custom" and set it manually.
* **Input/Output Channels**: Selects the channel mode (Stereo, Left, Right).

## Calibration

Performs calibration to improve measurement accuracy. Pressing the "Wizard" button for each item allows you to perform calibration in an interactive format.

### Calibration Profiles

You can save the current calibration settings (Input Sensitivity, Output Gain, SPL Offset, etc.) as a named profile.
This is useful for quickly switching settings when using different audio interfaces or microphones.
The profile also records the device name and Host API used at the time of saving.

* **Select Profile**: Select a saved profile. When selected, the device name associated with that profile is displayed.
* **Load**: Loads the settings of the selected profile and applies them to the current settings.
* **Delete**: Deletes the selected profile.
* **Save As...**: Saves the current settings with a new name. Entering an existing name overwrites it.

### Input Sensitivity

Setting for correctly displaying the voltage level of the input signal. "1.0 V/FS" means that when a digital full scale (0dBFS) signal is input, it is 1.0V.

* **Wizard**: Automatically calculates by inputting a known voltage (for example, a 1Vrms sine wave) and inputting that value.

### Output Gain

Setting for correctly controlling the voltage level of the output signal. "1.0 V/FS" means that when a digital full scale (0dBFS) signal is output, the terminal voltage is 1.0V.

* **Wizard**: Automatically calculates by outputting a test signal (such as a 1kHz sine wave) and measuring the voltage with a tester and inputting it.

### SPL Offset

Offset (correction value) of the dB SPL value displayed by the Sound Level Meter, etc.

* **Wizard**: Automatically calculates the total correction value including microphone sensitivity by outputting noise from a speaker and inputting the value (dB SPL) measured with a commercially available sound level meter.
