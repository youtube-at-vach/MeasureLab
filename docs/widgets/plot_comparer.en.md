# Plot Comparer

## Overview

The `Plot Comparer` is a utility designed to plot and overlay multiple data traces acquired from different measurement modules (such as the [Spectrum Analyzer](spectrum_analyzer.en.md), [Network Analyzer](network_analyzer.en.md), or [Oscilloscope](oscilloscope.en.md)) onto a single unified graph for detailed comparison and analysis.

To help visualize differences between measurements, it features powerful comparison-assist tools, including manual gain offset adjustments (in dB), dynamic X-axis shifts (for frequency or time), dual Y-axis mapping (Y1/Y2), logarithmic scale toggles (Log X/Log Y), and a "Normalize" function to align peaks automatically.

## Key Features

* **Hierarchical Trace Management (Tree View)**
    * Displays imported traces in a structured tree. You can easily rename a trace by double-clicking its name.
    * Allows you to toggle the visibility of each trace as a whole, or toggle individual components separately (such as primary Y1 data or secondary Y2 phase/distortion data).
* **Powerful Alignment and Adjustments**
    * **Gain Offset (dB)**: Allows you to manually apply a vertical offset to a trace's amplitude, making it easy to align curves visually.
    * **Axis Shift (Frequency/Time Shift)**: Shifts a trace horizontally along the X-axis (in Hz for frequency, or seconds for time) to compensate for phase shifts or timing offsets.
    * **Normalize (Align Peaks)**: Automatically aligns the maximum peak of all checked traces, simplifying the comparison of frequency response shapes and peak positions.
* **Full Secondary Y-Axis (Y2) Support**
    * Map different physical dimensions within a single trace (e.g., gain and phase, or amplitude and distortion) to the left Y-axis (Y1) and right Y-axis (Y2) independently.
* **Import / Export**
    * Import measurement traces captured from other modules, or export your adjusted/compared traces as JSON files to save them for future use.
* **Interactive Cursor & Global Readout**
    * Hovering your mouse over the plot dynamically overlays red dashed vertical and horizontal cursor lines.
    * Automatically interpolates Y-values (Y1 and Y2) for all active traces at the current cursor X-position, displaying a clear list of values in the status panel below the plot.

## How to Use

### Importing and Managing Data

1. **Add Traces from Measurement Modules**:
   Use the "Send to Comparison" feature inside individual measurement modules (e.g., Network Analyzer) to dispatch captured data directly to the Plot Comparer.
2. **Import File Button**:
   Directly load previously exported trace data (JSON format) from your local filesystem.
3. **Delete / Clear All Buttons**:
   Remove the currently selected trace from the tree, or wipe all loaded traces at once.
4. **Export Selected Button**:
   Save specific selected traces (or all checked traces if none are selected) to a local JSON file.

### Adjusting Range and Scale (Plot Range)

* **X / Y1 / Y2 Axis Settings**:
    * **Auto**: Automatically scales the axes so that all checked traces fit perfectly within the visible plot area.
    * **Log X / Y Axis**: Displays the X-axis or Y1-axis in logarithmic scale. When analyzing frequency response traces, Log X is automatically enabled by default.
    * **Min / Max Spin Boxes**: Turn "Auto" off to lock or manually fine-tune the boundaries (minimum/maximum values) of each axis.
* **Normalize (Align Peaks)**:
    * When you only want to compare the overall shape of amplitude responses, check this option to automatically shift all traces so their peaks align at 0 dB (or equivalent reference).

### Toggling the Control Panel

* Click the sleek collapse button (`‹` or `›`) on the right side of the plot to hide the control panel, maximizing the visible graph area.
