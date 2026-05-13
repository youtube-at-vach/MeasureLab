# Ultrasound Modulator

![Ultrasound Modulator](../assets/widgets/ultrasound_modulator.png)

## ☕ Coffee Break: Riding Sound on an "Ultrasonic Rocket"

"Ultrasound" is inaudible to humans. However, if you piggyback normal sounds (like voices or music) onto this ultrasound and transmit it, a mysterious phenomenon occurs where the sound is restored in mid-air, making it "audible only in a specific location" (Parametric Speaker).
This widget is a tool (modulator) to put your voice onto an "ultrasonic rocket" (carrier wave). With this, you can conduct cutting-edge "acoustic laser" experiments using just a normal PC and an audio interface!

## Overview

The Ultrasound Modulator is a widget that amplitude-modulates (AM) audio signals into the ultrasonic range, making them suitable for playback on ultrasonic reference speakers (typically centered at 40kHz).

It is used for experiments with parametric speakers and acoustic measurements in the ultrasonic band.

Key Features:

* **Real-time AM Modulation**: Modulates a carrier wave (default 40kHz) using the input audio signal.
* **Safety Features**: Displays safety status (SAFE, CAUTION, DANGEROUS) based on output gain and warns if levels are high.
* **Flexible Routing**: Supports arbitrary selection of input/output channels (L/R/Stereo).
* **Pre-distortion**: Supports square-root processing to reduce distortion caused by demodulation.

## Basic Operation

### Starting and Stopping Modulation

Click the **"Start Modulation"** button at the bottom of the screen to start the modulation process.

!!! warning
    Although ultrasound is inaudible, high-intensity emission can be dangerous to hearing and pets. Always start with a low gain and use appropriate protection. A safety confirmation dialog will appear upon starting.

### Parameter Settings

Configure signal processing parameters in the **"Modulation"** tab.

* **Input Gain**: Adjusts the gain of the input signal. Use the input level meter to set an appropriate level without clipping.
* **Carrier Freq**: The frequency of the carrier wave. Set this to match the resonant frequency of your ultrasonic transducer (e.g., 40000 Hz).
* **Audio LPF**: The cutoff frequency of the Low Pass Filter applied to the audio signal before modulation. Adjust this to prevent sidebands from exceeding the bandwidth limits.
* **Mod. Depth (k)**: The modulation depth (0.0 to 1.0). 1.0 indicates 100% modulation.
* **Output Gain**: The output gain after modulation. **Operate with caution for safety.**
* **Carrier Mode**: Select the modulation mode.
    * **DSB (AM)**: Standard Amplitude Modulation (Double Sideband).
    * **USB**: Upper Sideband modulation. Used for bandwidth saving or specific experimental purposes.
    * **LSB**: Lower Sideband modulation.

### Routing and Settings

Configure input/output routing in the **"Settings"** tab.

#### Input/Output Channel

Select the input source and output destination.

* **L / R**: Processes as mono.
* **Stereo**: Processes as stereo signals (carrier phase is identical for both).

#### Advanced Options

* **Enable √ Pre-distortion**: Applies square-root processing ($\sqrt{1+km(t)}$) to the signal beforehand to correct distortion that occurs during amplitude demodulation. This is useful for reducing distortion during self-demodulation in parametric speakers.

* **Bypass Modulation**: Outputs the input signal directly without modulation (gain is still applied). Use this for checking settings or as a pass-through output.

## Signal Meters

The Input Level and Output Level are displayed at the bottom of the screen. You can verify if the signal is input correctly or if the output is saturating.

* **Input Level**: The audio signal level before modulation.
* **Output Level**: The ultrasonic signal level after modulation.
