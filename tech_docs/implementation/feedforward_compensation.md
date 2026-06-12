# Hammerstein Feedforward Distortion Compensation (Iterative LICFF)

This document details the feedforward distortion compensation algorithm based on the Hammerstein model. It is designed to linearize a nonlinear system (such as an audio power amplifier or speaker transducer) by applying a predistorted compensation signal at the system's input. The implementation details are based on `scratch/test_ff_compensation_simulation.py`.

## Overview

A Hammerstein system consists of a static nonlinearity followed by a linear dynamic system. In many physical systems, the dominant distortion is well-approximated by this structure.

To linearize such a system, we inject a compensation signal $u_{comp}$ such that the system output $y$ is as close as possible to the target linear response $y_{ref} = L(u_{in})$.

The **Iterative Linear-Inverse Compensated Feedforward (Iterative LICFF)** algorithm achieves this by iteratively estimating the nonlinear distortion components and projecting them back to the input side through a regularized linear inverse filter.

---

## 1. Model Representation

The system is characterized using a **Parallel Hammerstein model** with kernels up to the 5th order ($h_1$ to $h_5$), typically measured using methods like Synchronized Swept-Sine (SSS).

### Chebyshev to Power Series Conversion

The measured kernels $h_1 \dots h_5$ represent coefficients of Chebyshev polynomials (which are orthogonal under sinusoidal excitation). To facilitate arbitrary signal simulation, we convert these Chebyshev coefficients into standard power series kernels $q_0 \dots q_5$:

$$ q_0 = -0.5 h_2 + 0.125 h_4 $$
$$ q_1 = h_1 - 0.75 h_3 + 0.3125 h_5 $$
$$ q_2 = h_2 - h_4 $$
$$ q_3 = h_3 - 1.25 h_5 $$
$$ q_4 = h_4 $$
$$ q_5 = h_5 $$

Here:

* $q_1(t)$ represents the **true linear dynamic response** (impulse response).
* $q_2 \dots q_5$ represent the nonlinear power series kernels.
* $q_0$ represents the static DC offset kernel.

### Normalization

To prevent numerical instability and ensure consistent scaling, the kernels are normalized by the peak frequency response magnitude of the linear kernel $q_1$:

$$ G_{scale} = \max_f |Q_1(f)| $$
$$ q_{p, sc} = \frac{q_p}{G_{scale}} \quad (p = 0 \dots 5) $$

All subsequent calculations are performed on these scaled kernels.

---

## 2. Forward Model Simulation

The output $y(t)$ of the Hammerstein model for a given input $x(t)$ is computed in the frequency domain as:

$$ y(t) = \mathcal{F}^{-1} \left\{ \sum_{p=0}^{5} \mathcal{F}\{x(t)^p\} \cdot Q_p(f) \right\} $$

### Anti-Aliasing (Oversampled Power Evaluation)

Calculating $x(t)^p$ in discrete time generates high-frequency components that can cause aliasing if they exceed the Nyquist frequency ($f_s / 2$). To prevent this:

1. The input signal $x(t)$ is oversampled by a factor $L = 8$ via zero-padding in the frequency domain.
2. The power $x_{up}(t)^p$ is computed in the oversampled time domain.
3. The spectrum is filtered and downsampled back to the original sample rate before multiplying with the kernel frequency response $Q_p(f)$.

---

## 3. Linear Inverse Filter ($F_{inv}$) Design

The linear inverse filter $F_{inv}$ maps an output-referred distortion signal back to the input. It is the regularized inverse of the linear kernel $Q_1(f)$:

$$ F_{inv}(f) = \frac{Q_1^*(f)}{|Q_1(f)|^2 + \epsilon_f(f)} \cdot H_{bp}(f) $$

Where:

* $Q_1^*(f)$ is the complex conjugate of $Q_1(f)$.
* $H_{bp}(f)$ is a bandpass filter (`bp_filter`) restricting the inversion to the active band of the transducer (e.g., 60 Hz to 17 kHz). Inversion outside this band is restricted to avoid amplifying noise or out-of-band signals.
* $\epsilon_f(f)$ is a frequency-dependent regularization parameter (Tikhonov regularization) that prevents extreme gains at frequencies where the response is weak (e.g., notches or band edges):
  $$ \epsilon_f(f) = \epsilon_{in} + (\epsilon_{out} - \epsilon_{in}) \cdot (1 - H_{bp}(f)) $$
  With $\epsilon_{in} = 10^{-6}$ inside the passband, and $\epsilon_{out} = 0.5$ in the transition/stopbands.

---

## 4. Compensation Algorithm (Iterative LICFF)

Instead of using a complex analytical inverse of the Hammerstein nonlinearity (which is mathematically difficult and prone to instability), the algorithm uses an iterative feedback-like structure to compute the predistorted input $u_{comp}$.

Let the target linear output be:
$$ y_{ref} = L(u_{in}) = \mathcal{F}^{-1}\{ \mathcal{F}\{u_{in}\} \cdot Q_1 \} $$

### Step-by-Step Iterative Loop

1. **Initialization ($k=0$):**
   Initialize the compensated signal as the bandpass-filtered target input:
   $$ u_{comp}^{(0)} = u_{in} * h_{bp} $$

2. **Iteration ($k = 1 \dots N_{iters}$):**
   For each iteration (typically $N_{iters} = 3$ is sufficient):

   a. **Estimate Nonlinear Distortion:**
      Compute the nonlinear distortion components $y_{nl}$ produced by the current compensated input $u_{comp}^{(k-1)}$:
      $$ y_{nl} = \text{NonlinearForwardModel}(u_{comp}^{(k-1)}) $$
      $$ y_{nl}(t) = \mathcal{F}^{-1} \left\{ \mathcal{F}\{1\} \cdot Q_0(f) + \sum_{p=2}^{5} \mathcal{F}\{(u_{comp}^{(k-1)})^p\} \cdot Q_p(f) \right\} $$

   b. **Project Distortion to Input:**
      Filter the output-referred distortion $y_{nl}$ through the linear inverse filter $F_{inv}$ to estimate the input-referred compensation signal $y_{comp\_nl}$:
      $$ y_{comp\_nl} = \mathcal{F}^{-1} \left\{ \mathcal{F}\{y_{nl}\} \cdot F_{inv} \right\} $$

   c. **Update Compensated Signal:**
      Subtract the compensation signal from the target input to pre-compensate for the upcoming distortion:
      $$ u_{comp}^{(k)} = u_{in} * h_{bp} - y_{comp\_nl} $$

   d. **Stability Limiter (Clipping):**
      To prevent the iteration from running into positive feedback and causing numerical blowup, the output is clipped to a safe range:
      $$ u_{comp}^{(k)} = \max(-V_{limit}, \min(V_{limit}, u_{comp}^{(k)})) $$
      *(Typically $V_{limit} \approx 1.5$ in simulation)*

3. **Output Generation:**
   The final predistorted signal $u_{comp}^{(N_{iters})}$ is sent to the physical system.

---

## 5. Performance Metrics

To evaluate the compensation performance, two primary metrics are used:

* **Total Harmonic Distortion (THD)**: Measures the suppression of specific harmonics (e.g., 2nd to 5th) under single-tone excitation.
* **Signal-to-Distortion Ratio (SDR)**: Measures the alignment between the compensated system output and the ideal linear response for arbitrary signals (e.g., multi-tone or broadband noise). Calculated as:
  $$ \text{SDR} = 20 \log_{10} \frac{\text{RMS}(y_{ref})}{\text{RMS}(y_{out, scaled} - y_{ref})} $$
  Where $y_{out, scaled}$ is time-aligned and gain-normalized relative to $y_{ref}$ to ensure linear gains/delays do not penalize the metric.
