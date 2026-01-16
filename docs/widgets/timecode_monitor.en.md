# Timecode Monitor

![Timecode Monitor](../assets/widgets/timecode_monitor.png)

## Overview
This is a tool for reading and displaying timecode (LTC: Linear Timecode) recorded as an audio signal.
It can be used for checking synchronization between video and audio, and also as a timecode generator.

Since it can monitor timecode on independent left and right channels (L / R), it is also suitable for checking timecode discrepancies between different devices.

## Operation

### Starting and Stopping Measurement
* **Start Monitor / Stop Monitor Button**: Starts and stops monitoring (reading) the timecode.

### How to Read the Screen

#### Main Display (Left / Right)
At the top of the screen, the timecode information for each of the left and right channels is displayed largely.

* **Timecode (00:00:00:00)**:
    The time of the timecode currently being read (Hour:Minute:Second:Frame).
* **SYNC Lamp**:
    Lights up in green when the timecode signal is correctly locked (synchronized). It goes out if the signal is interrupted or if there is a lot of noise.
* **FPS**:
    The frame rate estimated from the input signal.
* **dB (Level)**:
    The volume level of the input signal. Ideally, the timecode signal should be input at a relatively high level (around -10dB to -20dB).
* **JAM Button**:
    "Jams (sync copies)" the current input timecode.
    When this is pressed, the timecode value at that moment is saved in the internal memory, and the generator (output) can be synchronized to that value and started immediately (see "JAM Function").

#### Inter-channel Discrepancy Display (CH Δ)
* **CH Δ (R-L)**:
    Displays the discrepancy between the timecodes of the right and left channels.
    * If perfectly synchronized, `0 fr (0.0 ms)` is displayed.
    * This is convenient for checking if the timecodes between cameras are not out of sync in multi-camera recordings, etc.

## Settings

Detailed settings are possible within the tabs for each channel (Left / Right).

### Channel Settings
* **Frame Rate**:
    Manually sets the frame rate of the timecode (e.g., `24.00`, `29.97`, `30.00`, etc.).
    * Normally it is automatically detected, but if it does not lock correctly, please set it manually.

* **Display Local Time**:
    Interprets the timecode (Hour:Minute:Second) as the current time and displays it converted to the time of the specified time zone.
    * **Display TZ**: Target time zone to convert to (e.g., `Asia/Tokyo` for Japan time).
    * Example: Used when the timecode is recorded in "UTC time" and you want to display it corrected to "Japan time."

### Generator (Generator Function)
A function for outputting a timecode signal from MeasureLab. After performing settings in this tab and pressing `Enable Generator`, a timecode sound will flow from the audio output.

* **Gen Mode (Generation Mode)**:
    * **Time of Day (TOD)**: Outputs the current time of the computer as timecode.
    * **Free Run**: Starts counting up from `00:00:00:00` or a specified time.
    * **JAM**: Outputs in synchronization with the external timecode captured with the JAM button.

* **Link Stereo Output**:
    A checkbox in the center of the main screen.
    When this is enabled, the generator settings of one channel (Source) are copied to the other, and exactly the same timecode is output from both left and right.

## Usage Examples

### Checking Timecode
Input an LTC signal output from a camera or recorder into the audio interface and check if the timecode is correctly recorded and if the time is correct.

### Synchronization Check for Multi-camera
Input the timecode outputs of two cameras into the L and R channels, respectively.
By looking at the display of **CH Δ (R-L)**, you can see at a glance if the two cameras match perfectly (are synchronized) in frame units.

### Timecode Playback Instead of a Slate (Clapperboard)
By running this tool as a generator in "Time of Day" mode during video shooting and sending that audio to the camera's audio input, it can be used as "audio timecode" to make it easier to automatically synchronize video and audio during editing.
