# Lock-in Frequency Counter: Kalman Filter Implementation

This document details the Kalman Filter implementation used in the Lock-in Frequency Counter module (`src/gui/widgets/lock_in_frequency_counter.py`) to estimate the NCO (Numerically Controlled Oscillator) frequency and its uncertainty.

## Overview

The goal is to provide a precise and stable frequency readout from a noisy feedback loop (FLL). To achieve this, we use a 1-Dimensional Kalman Filter to estimate the "true" frequency state from the noisy updates provided by the PID controller.

We further enhance the visual stability of the readout using a post-filter moving average.

## 1. Kalman Filter Model

We use a simple **Constant Value Model** (0th order derivative). We assume the true frequency is constant (or slowly varying) and that any rapid changes are due to measurement noise (jitter in the loop).

### State Vector

$$ x_k = [f_k] $$
Where $f_k$ is the frequency at time $k$.

### System Model (Prediction)

We assume the frequency does not change by itself between steps, except for some small process noise (drift).
$$ x_{k|k-1} = x_{k-1|k-1} $$
$$ P_{k|k-1} = P_{k-1|k-1} + Q $$

* $P$: Estimation Error Covariance (Uncertainty squared).
* $Q$: Process Noise Covariance (How much we think the true frequency wanders).

### Measurement Model (Update)

The PID loop gives us a "new frequency" update, which we treat as a noisy measurement of the true state.
$$ z_k = f_{PID} $$
$$ x_k = x_{k|k-1} + K_k (z_k - x_{k|k-1}) $$
$$ P_k = (1 - K_k) P_{k|k-1} $$

Where Kalman Gain $K_k$ is:
$$ K_k = \frac{P_{k|k-1}}{P_{k|k-1} + R} $$

* $R$: Measurement Noise Covariance (How noisy the PID loop is).

## 2. Adaptive Parameter Estimation

To make the filter robust without requiring manual tuning of variance values, we implement adaptive estimation for $Q$ and $R$.

### Q (Process Noise) - "Stiffness"

The Process Noise $Q$ determines how "stiff" the filter is.

* **High Q**: The filter expects the frequency to change rapidly. It trusts new measurements more. Fast response, low smoothing.
* **Low Q**: The filter expects the frequency to be constant. It ignores short-term fluctuations. Slow response, high smoothing.

We map the user-facing **"Avg Count"** setting to $Q$:
$$ Q \propto \frac{1}{(\text{Avg Count})^2} $$
Increasing the "Avg Count" makes the filter "stiffer" (smoother).

### R (Measurement Noise) - "Confidence"

The Measurement Noise $R$ represents the actual jitter in the system. If we assume a fixed $R$ that is too high or too low, our uncertainty estimate ($P$, and thus the displayed digits) will be wrong.

We estimate $R$ dynamically using the variance of the recent input history (buffer of $N=20$ samples):
$$ R_k \approx \text{Var}(z_{k-N}...z_k) $$

This ensures that:

1. When the loop is unstable/hunting, $R$ increases $\rightarrow$ Filter trusts measurements less $\rightarrow$ Uncertainty ($P$) increases $\rightarrow$ Display shows fewer digits.
2. When the loop is locked and stable, $R$ decreases $\rightarrow$ Filter tightens $\rightarrow$ Uncertainty ($P$) decreases $\rightarrow$ Display shows more digits.

## 3. Display Smoothing

While the Kalman Filter provides the optimal estimate of the state, the raw state estimate $x_k$ can still jitter slightly, which can be annoying for a human reading a digital display.

To solve this ("Scientifically Valid Smoothing"), we interpret the text display not as the *instantaneous* state, but as the **statistical mean of the recent state**.

We maintain a history buffer of the Kalman Filter estimates (length = Avg Count):

1. **Displayed Value**: $\mu = \text{Mean}(History)$
2. **Displayed Uncertainty**: $\sigma = \text{StdDev}(History)$
3. **Decimal Places**: Calculated from $\sigma$ (e.g., if $\sigma = 10^{-4}$, we show roughly 4-5 decimal places).

This provides a readout that is both statistically grounded and visually stable.
