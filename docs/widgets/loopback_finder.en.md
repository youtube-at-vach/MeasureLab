# Loopback Finder

![Loopback Finder](../assets/widgets/loopback_finder.png)

## Overview

A tool for automatically identifying which "output channels" are connected (looping back) to which "input channels" within an audio interface.

When using multi-channel interfaces, this tool allows you to quickly verify if unintended loopbacks are occurring due to hardware or OS settings, or if the intended channels are correctly connected.

## Operations

1.  Press **Start Scan**.
2.  The software will emit test tones from each output channel in sequence and scan all input channels.
    *   **Note**: The normal measurement engine will pause during the scan. Also, be aware that sound may be emitted if the output is connected to speakers or other equipment.
3.  The detected paths will be displayed in the **Results Table**.
    *   **Output Channel**: The output that emitted the sound.
    *   **Input Channel**: The input where the sound was detected.
    *   **Signal Level**: The strength of the detected signal (dB).

## Limitations

*   **PipeWire / JACK Mode**: This tool cannot be used in certain Linux environments (PipeWire/JACK) when "Resident Mode" is enabled. It must be temporarily disabled in the settings.

## Usage Examples

*   **Verifying Wiring**: Verify if your assumption that "sound from Output 3 should be reaching Input 5" is correct without unplugging and replugging cables.
*   **Detecting Internal Leaks**: Identify signal leakage (crosstalk or internal loops) between channels that should not be connected.
