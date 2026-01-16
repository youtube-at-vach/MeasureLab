# Appendix

## This tool is not a "measurement instrument"

This software is a **simple signal analysis and observation tool** using a PC and an audio interface.
While it is useful for learning, hobbies, or initial estimations in development, it cannot be used for strict quality assurance or standards compliance testing.

### Reliable Range and Reference-Only Range
What this tool excels at is observing "relative changes."

*   **Reliable Use (Relative Use)**:
    *   **Relative Comparison**: Confirming changes such as "whether the noise level decreased before and after a countermeasure" or "which of A and B has less distortion."
    *   **Operation Check**: Visual confirmation of whether the signal is clipping, oscillating, or if the intended frequency is being output.
    *   **Troubleshooting**: Identifying 50Hz/60Hz hum noise contamination or sudden glitches.

*   **Reference Only**:
    *   **Absolute Values (Voltage, Sound Pressure)**: Physical quantities other than dBFS (V, dBu, SPL) are merely estimated values unless corrected using a calibrated reference instrument.
    *   **Measurement in Minute Domains**: Measurements of THD+N below -100dB or the noise floor are strongly affected by the performance limits of the PC and audio interface itself.

---

## Troubleshooting

If you have trouble, please check the following items.

### ❓ No sound / No response to input
- **Power and Connection**: Confirm that the audio interface is turned on and the USB cable is correctly plugged in.
- **Settings Widget**: Confirm that the correct device (ASIO/WASAPI, etc.) is selected.
- **OS Shared Mode**: Confirm that other recording software, browsers, or web conferencing tools are not occupying the device.

### ❓ Graph movement is jerky / Sound is intermittent
- **Buffer Size**: Change **Buffer Optimization** to `STABLE` or `ULTRA` in the Settings widget.
- **CPU Load**: Close other heavy applications.

### ❓ Screen appears to be frozen at startup
- **WISDOM Generation**: On the first launch, it may take several tens of seconds to calculate "WISDOM (FFT optimization)." It is not a malfunction, so please wait.

### ❓ Mountain appears at a different frequency even though a 1kHz signal is being output
- **Sampling Rate Mismatch**: Confirm that the sampling rate setting in MeasureLab and the setting on the audio interface side (or OS sound setting) are the same (e.g., 48kHz, 192kHz).

---

## Finally
If the problem is not resolved, please check the basic operation again with a loopback connection (direct connection from output to input) to see if there are any connection errors or cable defects.
