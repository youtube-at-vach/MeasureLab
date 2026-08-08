# Lock-in Frequency Counter: Kalman Filter Implementation

This document describes the one-dimensional Kalman filter used by [`src/gui/widgets/lock_in_frequency_counter.py`](../../src/gui/widgets/lock_in_frequency_counter.py) to smooth the NCO frequency while the frequency-locked loop (FLL) is enabled.

## 1. Role of the filter

The frequency counter estimates a frequency deviation from a block of input samples. When FLL lock is enabled, a PID controller converts that deviation into a new NCO-frequency command. The Kalman filter smooths those commands and provides an internal covariance estimate.

The filter is not used to produce the unlocked display value: while FLL lock is disabled, the module reports the configured NCO frequency and sets the displayed uncertainty to zero.

## 2. One-dimensional constant-value model

The state contains only the NCO frequency:

$$
x_k=[f_k].
$$

The constant-value prediction is:

$$
x_{k|k-1}=x_{k-1|k-1},
\qquad
P_{k|k-1}=P_{k-1|k-1}+Q.
$$

The PID-updated NCO command is the measurement:

$$
z_k=f_{\mathrm{NCO,command}}.
$$

The scalar update is:

$$
K_k=\frac{P_{k|k-1}}{P_{k|k-1}+R},
$$

$$
x_k=x_{k|k-1}+K_k(z_k-x_{k|k-1}),
\qquad
P_k=(1-K_k)P_{k|k-1}.
$$

On the first update after construction or reset, the implementation initializes `x` directly from the measurement and sets `P` to `R`. A reset sets the first-run flag and restores `P` to 1.0.

## 3. Process-noise schedule (`Q`)

The UI setting `Avg Count (KF-Q & Display)` controls both the process-noise schedule and the display-history length. With count $N$:

$$
Q=\frac{10^{-6}}{N^2}.
$$

The default count is 10, which gives $Q=10^{-8}$. A count of 100 gives $Q=10^{-10}$. A larger count therefore assumes a more stable NCO, produces stronger Kalman smoothing, and also retains a longer display history. A smaller count responds more quickly to new commands.

This is a deterministic mapping from the user setting, not an online estimate of process noise.

## 4. Adaptive measurement noise (`R`)

While the FLL is locked, the controller performs the following steps for each valid frequency estimate:

1. Compute the PID correction from the measured frequency deviation.
2. Add the correction to the current NCO frequency.
3. Clamp the command to 20–20,000 Hz.
4. Append the clamped command to a history buffer with a maximum length of 20.

After at least two commands are available, the measurement-noise covariance is updated as:

$$
R=\operatorname{Var}(f_{\mathrm{NCO,command,history}})+10^{-12}.
$$

Thus, the code estimates the jitter of recent PID/NCO commands, not the variance of the raw audio samples. A hunting loop normally increases `R`, so the Kalman gain decreases. A stable loop normally decreases `R`, so the filter can follow the command more closely.

## 5. Display averaging and uncertainty

The instantaneous Kalman estimate is stored in a second history buffer whose maximum length is the current Avg Count. The UI uses this post-Kalman history for the displayed frequency:

$$
f_{\mathrm{display}}=\operatorname{mean}(x_{k-N+1},\ldots,x_k),
$$

$$
\sigma_{\mathrm{display}}
 =\operatorname{std}(x_{k-N+1},\ldots,x_k).
$$

The displayed uncertainty label uses $\sigma_{\mathrm{display}}$, the standard deviation of the filtered history. The raw Kalman standard deviation $\sqrt{P_k}$ is also retained internally as `nco_std`, but it is not the value shown in that label.

The frequency spin box chooses decimal places from the displayed standard deviation:

$$
\text{places}=-\lfloor\log_{10}(\sigma_{\mathrm{display}})\rfloor,
$$

bounded by 0–12 places, with a default of 5 when the standard deviation is zero or unavailable.

## 6. Related smoothing in the plots

The frequency-deviation plot has a separate exponential moving average controlled by a fixed two-second time constant. The plot smoothing slider then optionally applies a simple moving average to the stored plot data. These plot operations are separate from the Kalman filter and from the NCO display-history average.

## 7. Related source and tests

- [`src/gui/widgets/lock_in_frequency_counter.py`](../../src/gui/widgets/lock_in_frequency_counter.py): `KalmanFilter1D`, PID/FLL update path, adaptive `R`, display averaging, and formatting.
- [`tests/logic_verification/gui/widgets/test_kalman_filter_1d.py`](../../tests/logic_verification/gui/widgets/test_kalman_filter_1d.py): first update, reset, and uncertainty behavior.
