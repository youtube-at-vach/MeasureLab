# Lock-in Frequency Counter (Precision Frequency & Phase Deviation Measurement)

![Lock In Frequency Counter](../assets/widgets/lock_in_frequency_counter.png)

## Overview

While a standard frequency counter captures "signal fluctuations" broadly, the Lock-in Frequency Counter compares the input signal with a reference signal (NCO: Numerically Controlled Oscillator) and **visualizes the "deviation" with extremely high resolution**.

It is suitable for observing the long-term stability (drift) of a clock source, wow and flutter in tape decks and record players, or minute frequency changes such as Doppler shifts.

## Operation

### Preparation

1.  **NCO Frequency**: Sets the reference frequency (e.g., 1000 Hz).
2.  **Reference Mode**:
    *   **Internal (NCO)**: Uses an internally generated ideal sine wave as the reference.
    *   **Loopback (Ref Out)**: Uses the signal output from the system as the reference.
3.  Press the **Start** button to begin measurement.

### Reading the Graphs

*   **Frequency Deviation Δf (Hz)**: Displays the current deviation from the reference frequency.
*   **Integrated Phase φ (deg)**: Displays the accumulated "phase change" resulting from the frequency deviation.
*   **I-Q Phase Space (Right side)**: Provides a vector representation of "phase stability." When the points are concentrated at a single spot, the signal is stable. Movement in a circular pattern indicates a slight frequency deviation.

## Settings

*   **NCO Frequency**: The reference frequency for comparison. Match it to the expected value of the target.
*   **Gate (dB)**: Stops measurement if the input level falls below this threshold.
*   **Filter/Smoothing**: Adjusts the stability of the display.

## Use Cases

*   **Checking Oscillator Stability of Reference Signals**: Input a reference signal and observe how $\Delta f$ changes over time (e.g., thermal drift).
*   **Observing Wow and Flutter in Rotating Equipment**: Play back a test signal (e.g., 3 kHz) and observe its frequency fluctuations on a time axis.
