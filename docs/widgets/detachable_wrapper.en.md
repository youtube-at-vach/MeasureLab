# Detachable Wrapper (Common Header / Window Separation)

## Overview

Most widgets (measurement tools) in MeasureLab are wrapped in a common framework called the "Detachable Wrapper."
This is not just a decoration; it is a "multi-functional frame" provided to offer a screenshot function for saving measurement results and a window separation function for freely changing the screen layout.

Whether you are using tools such as the Spectrogram or Spectrum Analyzer, you can record data and rearrange layouts with the same operational feel.

## Operation

### Saving Screenshots (Screenshot)

Pressing the **"Screenshot"** icon in the upper right of the widget (identified by its tooltip) instantly saves the current content of that widget (the graph or just the graph part) as an image file (PNG format).

* **Save Location**: By default, screenshots are saved to `~/Pictures/MeasureLab` on macOS and the application root's `screenshots` folder on Windows/Linux. You can change this in Settings.
* **File Name**: Automatically named in the format `[Tool Name]_[Date]_[Time].png`.
* **Use Cases**: Ideal for creating experiment reports, posting to SNS, and recording evidence of measurement results.

### Viewing Logs (Logs)

Choose **"Logs"** from the **"More"** menu in the upper right of the widget to open the log viewer that displays application errors and information.

* **Use Cases**: Used to check warnings or errors during measurements, and to obtain debugging information.
* **Features**: You can filter the level of logs to display, such as all logs, info, warnings, or errors only.

### Sending to Plot Comparer (Send to Comparer)

The **"Send to Comparer"** action appears in the **"More"** menu only for widgets that can export 1D/XY traces.
Selecting it adds the current measurement traces to Plot Comparer so they can be overlaid with other results.
A warning is shown when there is no data available to send.

### Splitting Windows (Split Window)

By pressing the **"Split Window"** button (available only for widgets that support this feature), the widget is split into two independent windows: a "display section" (such as waveforms) and a "control section" for settings.

* **Usage**: This is convenient when you want to monitor the display section in full screen while keeping the control section on a different monitor for operation.
* **How to Restore**: Closing either of the split windows or pressing the **"Reattach All"** button in the original location will restore the widget to its original single-window state.
* **Opening from Menu Only**: Double-clicking an already split tool in the sidebar brings both its display and control windows to the front.

### Window Separation (Detach Window)

Pressing the **"Detach Window"** button makes only that widget pop out into an independent individual window.

* **Utilization in Multi-monitors**: For example, you can use the main screen on the left to change signal settings while monitoring the spectrum's movement on a sub-screen on the right in full-screen display.
* **Restoring Docking**: By closing the separated window or pressing the **"Reattach"** button displayed in the original location on the main screen, it returns perfectly to its original position.

### Compact Mode

For supported widgets, the **"Compact"** button is always present in the common header. It is disabled in the normal main-window layout and becomes enabled while detached or split. In split mode, compact layout applies only to the display window.

* **Space-Saving Display**: Clicking this button minimizes the widget's footprint, displaying only critical numerical parameters (e.g., SPL values in Sound Level Meter, frequency counts in Frequency Counter) in a bold, easy-to-read format.
* **Auto-Reset on Reattach**: Reattaching the window back to the main layout automatically exits compact mode and restores the standard detailed layout.
* **Keyboard-Friendly Focus**: Focus policies are optimized for fast toggling, ensuring shortcut keys (such as 'C') function reliably without interference from input controls.

## Common Layout of Widgets

Each widget, such as the Spectrogram, consists of the following three areas:

1. **Common Header**:
    An area containing the title and direct icons for More, screenshot, compact, split, and detach actions. The More menu contains Logs and, for supported widgets, Send to Comparer.
2. **Main Display Area**:
    The most important area where waveforms, graphs, and numerical values are displayed.
3. **Control Area**:
    A panel for changing settings (such as FFT size and averaging).

## Usage Examples

* **Record Instant Waveforms Without Missing Them**: Press "Screenshot" to record at the moment an interesting phenomenon occurs.
* **Build a Concentrated Monitoring Environment**: Use "Detach Window" to display multiple analyzers lined up to fill the screen.
