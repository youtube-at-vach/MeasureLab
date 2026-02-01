# Lock-in Frequency Counter (Precision Frequency & Phase Deviation Measurement)

![Lock In Frequency Counter](../assets/widgets/lock_in_frequency_counter.png)

## Overview

While a standard frequency counter captures "signal fluctuations" broadly, the Lock-in Frequency Counter compares the input signal with a reference signal (NCO: Numerically Controlled Oscillator) and **visualizes the "deviation" with extremely high resolution**.

It is suitable for observing the long-term stability (drift) of a clock source, wow and flutter in tape decks and record players, or minute frequency changes such as Doppler shifts.

## Operation

### Preparation

1. **NCO Frequency**: Sets the reference frequency (e.g., 1000 Hz).

    !!! warning
        The NCO Frequency represents the value of the internal software numeric oscillator and is unrelated to the device's physical output.
        Note that locking the NCO frequency merely means the measurement reference is tracking the input; it does not imply that all frequencies used by the audio device are locked to this reference.
2. **Reference Mode**:
    * **Internal (NCO)**: Uses an internally generated ideal sine wave as the reference.
    * **Loopback (Ref Out)**: Uses the signal output from the system as the reference (FLL lock is disabled in this mode).
3. **Input Settings**:
    * **Channel**: Selects the input channel for measurement (Ch 1 / Ch 2).
    * **Gate Threshold**: Stops measurement if the input level falls below this threshold (in dB). Used to prevent operation on noise.
4. Press the **Start** button to begin measurement.

### Reading the Graphs

* **Frequency Deviation Δf (Hz)**: Displays the current deviation from the reference frequency.
    * **Smoothing**: Use the slider to smooth the plot rendering. Moving it to the right increases averaging.
* **Integrated Phase φ (deg)**: Displays the accumulated "phase change" resulting from the frequency deviation.
* **I-Q Phase Space (Right side)**: Provides a vector representation of "phase stability." When the points are concentrated at a single spot, the signal is stable. Movement in a circular pattern indicates a slight frequency deviation.

## Settings

### Statistics & Averaging

* **NCO Avg Count**: Sets the number of averages for the NCO frequency display. Increasing this value stabilizes the display, and dynamic decimal precision increases.
* **NCO Std Dev (σ)**: Displays the standard deviation (magnitude of fluctuation) of the current frequency.

### PID Control Loop

Adjusts the response characteristics of the FLL (Frequency Locked Loop).

* **Proportional (Kp)**: Proportional gain. Sets how strongly to react to the current deviation.
* **Integral (Ki)**: Integral gain. Reacts to the accumulation of past deviation to eliminate steady-state error.
* **Derivative (Kd)**: Derivative gain. Reacts to the rate of change of the deviation to suppress overshoot.

## Use Cases

* **Checking Oscillator Stability of Reference Signals**: Input a reference signal and observe how $\Delta f$ changes over time (e.g., thermal drift).
* **Observing Wow and Flutter in Rotating Equipment**: Play back a test signal (e.g., 3 kHz) and observe its frequency fluctuations on a time axis.
