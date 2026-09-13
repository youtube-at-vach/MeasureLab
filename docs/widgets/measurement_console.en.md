# Measurement Console (Experimental)

## Overview

The Measurement Console is a dockable workspace for observing and operating multiple
measurement widgets in one window. It reuses the same widget instances shown in the main
window, so moving an instrument into the console does not create a second real-time audio
processor.

Open it with **Measurement Console** at the top of the main-window sidebar.

## Working with Instruments

* **Add Instrument**: Adds a widget to the console. A widget already in the console is
  unavailable in this menu.
* **Close an instrument dock**: Returns that widget to its normal page in the main window;
  its state and current measurement are retained.
* **Show in Console**: On a widget page that is currently hosted in the console, use this
  button to bring its dock to the front.
* **Stop All**: Stops every compatible instrument currently running in the console. It does
  not affect instruments that are already stopped or have no single primary start/stop action.

The initial preset contains Oscilloscope, Spectrum Analyzer, Spectrogram, and Goniometer.
Use **Layout → Default Console** to restore that set deliberately.

## Layouts and Controls

Choose a diagram button in the toolbar to apply a layout in one click. The same
presets are available by name in the **Layout** menu. The outlined button identifies
the selected preset; click it again to restore its proportions after dragging dividers.

| Preset | Arrangement |
| --- | --- |
| **Tabbed View** | One pane with tabs for all instruments. |
| **Side by Side** | Two equally sized columns. |
| **2 x 2 Grid** | Two columns and two rows. |
| **2 Columns x 3 Rows** | Six panes arranged vertically. |
| **3 Columns x 2 Rows** | Six panes arranged horizontally. |
| **Main + 3 Right** | A large main pane using two thirds of the width, with three stacked panes on the right. |
| **Main + 3 Below** | A large main pane using two thirds of the height, with three panes below. |

Grid instruments follow reading order, from left to right and top to bottom. Unused
panes collapse when there are fewer instruments; extra instruments share the panes
as tabs. Switching presets keeps the same instruments, settings, and running measurements.

* **Layout → Main Instrument**: Choose which instrument occupies the large pane in
  either main layout. The first instrument is used initially.
* **Layout → Reapply Layout**: Restore the selected preset's proportions.
* **Undo Layout**: Restore the arrangement before the last preset or main-instrument
  change, including manually adjusted dividers. Also available with **Alt+Backspace**.
  Adding or removing an instrument clears this undo history.
* **Layout → Default Console**: Restore the initial four instruments in a 2 x 2 grid.

Drag docks or tab them as needed. Enable **Lock Layout** after arranging the workspace to
prevent accidental additions, removals, or preset changes. Measurement controls remain usable.

For compatible modules, the dock title bar shows the module's main start/stop action. Its
label, icon, enabled state, and running state stay synchronized with the original control.
The console does not show a primary action for modules that do not have one safe,
single-button start/stop operation, and **Stop All** does not include those modules.

## Restoring a Workspace

The console stores its membership, dock arrangement, size, lock state, and compatible
compact-mode selections, along with the selected preset and main instrument. When a saved
layout cannot be restored safely, MeasureLab falls back to a visible default layout.
On small displays, the default arrangement is adjusted to
remain usable. The arrangement from the larger screen is retained for the next return to
a larger display, including after restarting the application. You can explicitly select
a different preset on a small screen.

## Limitations

This is an experimental workspace feature. It is designed for one main MeasureLab window:
an instrument can be either on its normal page or in the console, not in both locations at
the same time.
