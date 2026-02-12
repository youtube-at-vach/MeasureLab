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
    * **Loopback (Ref Out)**: Uses the signal output from the device as the reference (FLL locking is disabled in this mode). Useful when measuring with physical cable loopback or internal loopback.
    * **Ref Output**: Selects the physical output channel (Ch 1 / Ch 2) providing the reference signal in Loopback mode.
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

* **Avg Count (KF-Q & Display)**: Sets the process noise (Q) for the Kalman Filter used in NCO frequency estimation, as well as the display averaging count. Increasing this value results in stronger smoothing (lower Q) and a more stable display.
* **Display Uncertainty (σ)**: Displays the uncertainty (standard deviation) of the current frequency estimate. This indicates the confidence interval estimated by the Kalman Filter. Additionally, the decimal precision of the NCO Frequency setting automatically adjusts based on measurement stability (uncertainty), displaying up to 8 decimal places.

### PID Control Loop

Adjusts the response characteristics of the FLL (Frequency Locked Loop).

* **Proportional (Kp)**: Proportional gain. Sets how strongly to react to the current deviation.
* **Integral (Ki)**: Integral gain. Reacts to the accumulation of past deviation to eliminate steady-state error.
* **Derivative (Kd)**: Derivative gain. Reacts to the rate of change of the deviation to suppress overshoot.

## Use Cases

* **Checking Oscillator Stability of Reference Signals**: Input a reference signal and observe how $\Delta f$ changes over time (e.g., thermal drift).
* **Observing Wow and Flutter in Rotating Equipment**: Play back a test signal (e.g., 3 kHz) and observe its frequency fluctuations on a time axis.
