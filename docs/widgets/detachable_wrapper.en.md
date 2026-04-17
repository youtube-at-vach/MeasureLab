# Detachable Wrapper (Common Header / Window Separation)

## Overview

Most widgets (measurement tools) in MeasureLab are wrapped in a common framework called the "Detachable Wrapper."
This is not just a decoration; it is a "multi-functional frame" provided to offer a screenshot function for saving measurement results and a window separation function for freely changing the screen layout.

Whether you are using tools such as the Spectrogram or Spectrum Analyzer, you can record data and rearrange layouts with the same operational feel.

## Operation

### Saving Screenshots (Screenshot)

Pressing the **"Screenshot"** button in the upper right of the widget instantly saves the current content of that widget (the graph or just the graph part) as an image file (PNG format).

* **Save Location**: By default, it is saved in the `screenshots` folder in the same directory as the executable file.
* **File Name**: Automatically named in the format `[Tool Name]_[Date]_[Time].png`.
* **Use Cases**: Ideal for creating experiment reports, posting to SNS, and recording evidence of measurement results.

### Viewing Logs (Logs)

Pressing the **"Logs"** button in the upper right of the widget opens the log viewer that displays application errors and information.

* **Use Cases**: Used to check warnings or errors during measurements, and to obtain debugging information.
* **Features**: You can filter the level of logs to display, such as all logs, info, warnings, or errors only.

### Window Separation (Detach Window)

Pressing the **"Detach Window"** button makes only that widget pop out into an independent individual window.

* **Utilization in Multi-monitors**: For example, you can use the main screen on the left to change signal settings while monitoring the spectrum's movement on a sub-screen on the right in full-screen display.
* **Restoring Docking**: By closing the separated window or pressing the **"Reattach"** button displayed in the original location on the main screen, it returns perfectly to its original position.

## Common Layout of Widgets

Each widget, such as the Spectrogram, consists of the following three areas:

1. **Common Header**:
    An area where the title, logs, screenshot, and separation buttons are lined up.
2. **Main Display Area**:
    The most important area where waveforms, graphs, and numerical values are displayed.
3. **Control Area**:
    A panel for changing settings (such as FFT size and averaging).

## Usage Examples

* **Record Instant Waveforms Without Missing Them**: Press "Screenshot" to record at the moment an interesting phenomenon occurs.
* **Build a Concentrated Monitoring Environment**: Use "Detach Window" to display multiple analyzers lined up to fill the screen.
