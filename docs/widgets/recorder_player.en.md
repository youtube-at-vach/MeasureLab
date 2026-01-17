# Recorder & Player

![Recorder Player](../assets/widgets/recorder_player.png)

## Overview

A simple audio recording and playback tool.
It allows you to play test signals (such as sweeps or noise) to input into a circuit, or record output results and save them to files.
It supports loading common audio files such as WAV, MP3, FLAC, and OGG.

## Operations

### Playback

Load and play files.

* **Load File**: Opens an audio file.
    * **Sampling Rate Conversion**: If the file's sample rate differs from the application's operating rate (e.g., opening a 44.1kHz file while the app is set to 48kHz), you will be asked whether to automatically resample it. Usually, loading it as-is is fine.
* **Play / Stop**: Starts and stops playback.
* **Loop**: When checked, the file will repeat from the beginning after reaching the end. Useful for continuously outputting test signals.
* **Player Progress**: A bar indicating the current playback position.

* **Output Mode**
    * **Stereo**: Outputs the file's L/R channels as-is.
    * **Left / Right**: Outputs only the specified single channel.
    * **Mono**: If the file is stereo, it mixes the left and right channels to mono and outputs the same sound from both output channels.

* **Playback Gain**: Adjusts playback volume digitally (-60dB to +12dB).

### Recording

Records input signals to memory and exports them as files.

* **Record / Stop Recording**: Starts and stops recording.
* **Save Recording**: Saves recorded data to a file. This can only be pressed when recording is stopped.
* **Input Mode**
    * **Stereo**: Records both L/R channels.
    * **Left / Right**: Records only the specified single channel.

* **Recorded Info**: Displays the current recording duration in seconds.

## Usage Examples

### Using as a Signal Source

Prepare a WAV file containing pink noise or a sine sweep, play it with this tool, and observe it with a measurement instrument (such as a Spectrum Analyzer).

1. Load a test signal file using **Load File** in the **Playback** section.
2. Check **Loop** if you want to output the signal continuously.
3. Press **Play** to start playback.
4. Open another widget (such as the Spectrum Analyzer) and verify that the input signal is being received correctly.
5. By switching the **Output Mode**, you can send a signal only to the left channel to measure crosstalk (leakage into the right channel), for example.

### Capturing Abnormalities

If a circuit is producing abnormal sounds, you can record them to keep as evidence or for detailed analysis later.

1. Verify the input settings in the **Recording** section.
2. Press the **Record** button and reproduce the situation where the abnormal sound occurs.
3. Once enough data is recorded, press **Stop Recording**.
4. Press **Save Recording** and save it with a name like `evidence.wav`.
5. The saved file can later be loaded and played back in this tool or opened in waveform editing software.
