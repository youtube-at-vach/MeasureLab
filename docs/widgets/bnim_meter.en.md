# BNIM Meter (Binaural Neural Interferometric Meter)

![Bnim Meter](../assets/widgets/bnim_meter.png)

## Overview

This is a unique meter that simulates and visualizes how the human "hearing (brain)" processes the discrepancy between the sounds entering the left and right ears to perceive the "direction of sound."
More intuitively than a standard phase meter (Lissajous waveform), it displays "which frequency of sound is heard from which direction (left or right)" in a heat map like a thermogram.
It is ideal for checking the sense of localization and spread of stereo sound images, and for checking binaural recordings.

## Compact Mode

When detached using the Detachable Wrapper, pressing the "Compact" button switches the widget to Compact Mode, maximizing only the image map display. This is useful when you only want to monitor the spatial spread.

## ☕ Coffee Break: How do owls find mice in the dark?

In a pitch-black forest, how does an owl pinpoint the exact location of a mouse on the ground? Interestingly, an owl's left and right ears are positioned at slightly different 'heights'.

When a sound source (like a mouse's footsteps) is off to one side, the sound reaches the closer ear 'just a tiny bit earlier'. This is called **ITD (Interaural Time Difference)**.
Furthermore, because the head acts as an obstacle, the sound is 'slightly quieter' in the farther ear. This is called **ILD (Interaural Level Difference)**.
The brain of an owl (and humans too!) calculates this minute 'time difference' and 'volume difference' at ultra-high speed to determine the direction of the sound in 3D space. The BNIM meter is a tool that mimics this exact 'brain calculation' to project the direction of sound onto your screen.

## How to Read the Screen

### Main Graph (Neural Map)

* **Horizontal Axis (ITD - Interaural Time Difference)**: Represents the direction of sound arrival.
    * **Center (0 ms)**: Components localized in the front (center).
    * **Left side (- ms)**: Components where sound reaches the left ear first, meaning they are heard from the "left."
    * **Right side (+ ms)**: Components where sound reaches the right ear first, meaning they are heard from the "right."
* **Vertical Axis (Frequency)**: Represents the frequency (pitch). Up is high sound, down is low sound.
* **Color**: Represents the "strength of localization" at that position and height. The brighter (yellow to white) it is, the more strongly the sound is heard from that direction.

For example, you can see the positional relationship of sound sources, such as "vocals are in the middle (central vertical line)" and "hi-hat is slightly to the right (upper right bright spot)."

## Operation

### Basic Operation

1. Press the **Start** button to begin the measurement (simulation).
2. When you play music or microphone input, green or yellow lights (neuron excitation patterns) appear on the screen.
3. Stop with **Stop**.

### BNIM Controls (Settings)

#### Adjustment of Display

* **Persistence**: Adjusts the length of the afterimage on the screen. Moving it to the right makes it stay longer, making it suitable for seeing overall trends.
* **Gain**: Adjusts the sensitivity of the response to the input signal. If the color is too dark, increase it.
* **Neural Glow**: Blurs the light. Increasing the value makes it easier to see as a "cluster" of fine points connected together.

#### Adjustment of Hearing Model

* **Enable ILD weighting (Consideration of volume difference)**
    * Normally, this meter calculates direction using only "time difference (ITD)," but checking this box also adds "volume difference (ILD)."
    * In the high-frequency range, humans perceive direction based on volume difference rather than time difference, so turning this ON makes the display closer to how it actually sounds.
    * **ILD Strength**: Adjusts the degree of influence of the volume difference.

* **Max Freq**: Sets the upper limit of the frequency to be analyzed (1000Hz to 10000Hz). Since localization is particularly important in the mid-low range, the default of around 5000Hz is common.

### Click-to-play Test Signal

By clicking on the graph, you can actually sound a test tone corresponding to that location (frequency and direction). It can be used to check "what kind of sound is this light?" or to test how your own ears hear.

* **Enable click-to-play**: Enables this function. When you click or drag with the mouse on the graph, a burst signal (intermittent sound) such as "beep, beep" corresponding to the coordinates is played.
    * **Horizontal direction**: The left and right delay of the sound (ITD) changes, and the sound is heard moving left and right.
    * **Vertical direction**: The pitch of the sound changes.
* **Loop last click**: Continues to sound at the last position touched even after releasing the click.
* **On/Off cycles**: Adjusts the length of the test sound and the length of the pause.
* **Playback ILD**: Adds an artificial volume difference (ILD) to the test sound.

## Usage Examples

### Checking Localization in Mixes

When mixing down a song, you can check if each instrument is placed in the targeted position.

* Are vocals and bass firmly centered (central line)?
* Are the chorus and reverb components spreading beautifully to the left and right?
* Is there any frequency band that is unintentionally wavering to the left or right?

### Finding Phase Discrepancy

* If "the sound is heard but the center of the screen is dark, and only the left and right ends are bright," it may be **Out of Phase**. Check if the polarities of the left and right speaker cables match.

### Education and Learning of Binaural Effects

* Try dragging the graph using the **Click-to-play** function.
* You can experience that "moving it horizontally (changing the time difference) moves the sound from left to right inside your head."
* When operating at high frequencies (at the top), you can experience the mystery of the human ear, such as the sense of direction becoming difficult to understand with time difference alone, or the sense of direction suddenly appearing when ILD (volume difference) is added.
