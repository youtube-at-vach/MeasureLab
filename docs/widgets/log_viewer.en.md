# Log Viewer

![Log Viewer](../assets/widgets/log_viewer.png)

## Overview

The Log Viewer is a monitoring window that displays real-time messages about background application events, warnings, and errors.
While normally closed, it is useful for diagnosing issues or checking the status of background operations.

## Key Features

* **Real-time Display**: Log messages appear immediately as they are generated.
* **Filtering**: Select the log level (importance) to display only relevant information.
* **Color-Coded Messages**: Messages are color-coded by severity (e.g., errors in red, warnings in yellow) for quick identification.
* **Clear Logs**: Clear the displayed logs to focus only on new messages.

## Operation

1. Click the "Logs" button located below the gear icon (Settings) in the left menu to open the "Log Viewer."
2. Select the desired log level from the dropdown menu at the top.
    * `All Logs (DEBUG)`: Displays all detailed logs. While it provides a large amount of information, it is the most helpful setting for developers when troubleshooting.
    * `Info`: Displays general information and more critical messages (default setting).
    * `Warnings`: Displays only warnings and errors.
    * `Errors Only`: Displays only error messages.
3. Click the "Clear Logs" button to completely clear the display.
