# Appendix

## Overview

This page is an appendix summarizing the precautions (limitations as a measurement instrument) and common troubleshooting when using MeasureLab.

## This tool is not a "measurement instrument"

This software is a **simple signal analysis and observation tool** using a PC and an audio interface.
While it is useful for learning, hobbies, or initial estimations in development, it cannot be used for strict quality assurance or standards compliance testing.
Unlike expensive dedicated measuring instruments that possess an "absolutely unwavering standard," MeasureLab is designed specifically for observing relative changes rather than providing legally binding absolute precision.

### Reliable Range and Reference-Only Range

What this tool excels at is observing "relative changes."

* **Reliable Use**: Relative comparison (e.g., noise reduction before and after countermeasures), operation checks (clipping or oscillation), and troubleshooting (hum noise or glitches).
* **Reference Only**: Absolute values (physical quantities like voltage or sound pressure without calibration) and minute domain measurements (distortion below -100dB, dependent on PC or audio interface limits).

---

## Troubleshooting

If you have trouble, please check the following items.

### ❓ No sound / No response to input

* **Power and Connection**: Confirm that the audio interface is turned on and the USB cable is correctly plugged in.
* **Settings Widget**: Confirm that the correct device (ASIO/WASAPI, etc.) is selected.
* **OS Shared Mode**: Confirm that other recording software, browsers, or web conferencing tools are not occupying the device.

### ❓ Graph movement is jerky / Sound is intermittent

* **Buffer Size**: Change **Buffer Optimization** to `STABLE` or `ULTRA` in the Settings widget.
* **CPU Load**: Close other heavy applications.
* **I/O Buffer Warning**: Measurements made while the red "I/O BUFFER ERROR" indicator is present may contain dropped or repeated samples. Correct the buffer settings or CPU load, click the warning to acknowledge it, and repeat the measurement. The warning will reappear if the problem continues.

### ❓ Screen appears to be frozen at startup

* **WISDOM Generation**: On the first launch, it may take several tens of seconds to calculate "WISDOM (FFT optimization)." It is not a malfunction, so please wait.

### ❓ Mountain appears at a different frequency even though a 1kHz signal is being output

* **Sampling Rate Mismatch**: Confirm that the sampling rate setting in MeasureLab and the setting on the audio interface side (or OS sound setting) are the same (e.g., 48kHz, 192kHz).

### ❓ I want to check detailed Error Logs (Command-Line Options)

If you encounter unexpected errors or need to provide debugging information, you can check the application logs. By default, logs are displayed in the "Logs" window within the application, but you can also output them to a file or change the log level using command-line arguments when launching the application:

* `--log-level`: Set the logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). Default is `INFO`.
* `--log-file`: Specify the path to save the log file. If not specified, logs are automatically saved to `measurelab.log` in the user data directory.

Example (macOS/Linux):

```bash
python main_gui.py --log-level DEBUG --log-file ./debug.log
```

---

## Finally

If the problem is not resolved, please check the basic operation again with a loopback connection (direct connection from output to input) to see if there are any connection errors or cable defects.
