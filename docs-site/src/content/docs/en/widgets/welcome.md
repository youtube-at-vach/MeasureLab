---
title: "Welcome (Welcome Screen)"
---

## Overview

This is the dashboard screen displayed first when MeasureLab is started. It lists the major measurement tools included in this software and displays the development concept.

If you are using this tool for the first time, grasp the overall picture of each widget (measurement tool) from here and select the target tool from the sidebar on the left.

## Common Features

This widget supports common features of the Detachable Wrapper. Please refer to the [Detachable Wrapper](https://youtube-at-vach.github.io/MeasureLab/en/widgets/detachable_wrapper/) documentation for details.

## Operation

* **Selection of Tools**: You can switch to each measurement widget by clicking the icon or name in the sidebar on the left.
* **Activity Indicator**: Tools that are currently running processes like measurement or recording are highlighted (bold and highlight color) in the sidebar. You can hover over them to see the detailed status (active, detached in a separate window, etc.) in a tooltip.
* **I/O Buffer Warning**: A red "I/O BUFFER ERROR" indicator appears when dropped or starved audio samples are detected. The warning remains after measurement stops or the audio stream restarts. Click it to acknowledge and clear it; it will appear again if the problem continues.
* **Confirmation of Screen**: The tool logo and overview are displayed in the central main area.

## Functions

* **Preview of Major Tools**: Lists the major measurement functions of MeasureLab (Spectrum Analyzer, Signal Generator, Oscilloscope, etc.).
* **Version Information and Update Notifications**: Displays the current version number. If a new release is available on GitHub, a notification will appear. Clicking the notification opens the release page.
