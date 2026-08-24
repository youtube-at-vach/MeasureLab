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

The initial preset contains Oscilloscope, Spectrum Analyzer, Spectrogram, and Goniometer.
Use **Layout → Default Console** to restore that set deliberately.

## Layouts and Controls

The **Layout** menu provides these presets:

* **Side by Side**: Places two instruments next to each other.
* **2 x 2 Grid**: Arranges up to four instruments in a grid.
* **Default Console**: Restores the four-instrument preset.

Drag docks or tab them as needed. Enable **Lock Layout** after arranging the workspace to
prevent accidental additions or layout changes.

For compatible modules, the dock title bar shows the module's main start/stop action. Its
label, icon, enabled state, and running state stay synchronized with the original control.
The console does not show a primary action for modules that do not have one safe,
single-button start/stop operation.

## Restoring a Workspace

The console stores its membership, dock arrangement, size, lock state, and compatible
compact-mode selections. When a saved layout cannot be restored safely, MeasureLab falls
back to a visible default layout. On small displays, the default arrangement is adjusted to
remain usable.

## Notes

This is an experimental workspace feature. It is designed for one main MeasureLab window:
an instrument can be either on its normal page or in the console, not in both locations at
the same time.
