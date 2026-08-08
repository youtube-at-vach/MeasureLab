# Hammerstein Feedforward Compensation (LICFF)

This document describes the current `LICFFEngine` implementation used by the Feedforward Compensator. LICFF means Linear-Inverse Compensated Feedforward: the engine first compensates the linear model response, then iteratively subtracts an input-referred estimate of the modeled nonlinear output.

The implementation is in [`src/gui/widgets/feedforward_compensator.py`](../../src/gui/widgets/feedforward_compensator.py). It operates on a loaded forward Parallel Hammerstein model, such as the JSON exported by the Nonlinear Analyzer.

## 1. Model representation

The loader requires five time-domain kernels: `h1` through `h5`. In the current implementation they are used directly as power-series kernels:

$$
q_0=0,
\qquad
q_p=h_p\quad (p=1,\ldots,5).
$$

There is no Chebyshev-to-power-series conversion in `LICFFEngine`. This is an important distinction from the amplitude-separation mathematics used by the Nonlinear Analyzer: the feedforward engine expects the exported kernels in the representation already used by its forward model.

An optional relative threshold can zero high-order kernels whose peak is below the selected fraction of the `h1` peak. The threshold is applied before scaling.

### Kernel normalization

The engine computes the peak magnitude of the linear kernel spectrum:

$$
G_{\mathrm{scale}}=\max_f|Q_1(f)|.
$$

If that value is near zero, it falls back to 1. All kernels are divided by this scale before the FFT buffers are built:

$$
q_{p,\mathrm{sc}}=q_p/G_{\mathrm{scale}}.
$$

The scaled `q0` sum is retained as a constant output offset. For models exported by the current Nonlinear Analyzer, `q0` is initialized to zero.

## 2. Frequency-domain model and anti-aliasing

For an input block $x$, the forward model forms the linear term directly and evaluates powers $x^2$ through $x^5$ after oversampling by $L=8$ through frequency-domain zero-padding:

$$
Y(f)=X(f)Q_1(f)+
\sum_{p=2}^{5}\mathcal{F}\{x(t)^p\}_{\mathrm{dealiased}}Q_p(f).
$$

The oversampled signal is transformed to the time domain, raised to the required power, transformed back, and truncated to the original positive-frequency bins. The modeled output is:

$$
y_{\mathrm{model}}(t)=\mathcal{F}^{-1}\{Y(f)\}+\sum_nq_{0,\mathrm{sc}}[n].
$$

The `nonlinear_spectrum()` helper omits the linear term and returns only orders 2–5 plus the constant offset when converted back to time domain. The Nyquist bin is forced to be real before inverse transformation.

## 3. Inverse-filter design

The engine builds length-dependent FFT buffers for the model kernels and an active-band filter. The active band defaults to 60 Hz–17 kHz and has cosine transitions:

- Below `f_min`, the transition runs from 0 at 10 Hz to 1 at `f_min`.
- Above `f_max`, the transition runs to 0 at `min(0.95 * Nyquist, 1.2 * f_max)`.

Let $B(f)$ be this band filter and $A_1(f)=|Q_1(f)|$. Optional octave smoothing changes the magnitude used for inversion but preserves the phase of $Q_1$:

$$
\widetilde{A}_1(f)=
\begin{cases}
\text{smoothed magnitude of }Q_1(f), & \text{if smoothing is enabled},\\
A_1(f), & \text{otherwise}.
\end{cases}
$$

The regularized raw inverse is:

$$
F_{\mathrm{raw}}(f)=
\frac{Q_1^*(f)}{|Q_1(f)|}
\frac{\widetilde{A}_1(f)}{\widetilde{A}_1(f)^2+\epsilon_f(f)},
$$

where the first factor preserves the conjugate phase and $\epsilon_f$ is:

$$
\epsilon_f(f)=\epsilon_{\mathrm{in}}+
(0.5-\epsilon_{\mathrm{in}})(1-B(f)).
$$

The regularization mode determines $\epsilon_{\mathrm{in}}$:

- `auto_broadband`: solve for a 3 dB maximum passband boost.
- `auto_tones`: solve for a 20 dB maximum passband boost.
- `manual_boost`: solve for the user-selected maximum boost in dB.
- `manual_tikhonov`: use the user-selected Tikhonov value directly.

The nonlinear feedback filter is active only inside the band:

$$
F_{\mathrm{inv,nl}}(f)=F_{\mathrm{raw}}(f)B(f).
$$

The linear filter has a selectable out-of-band policy:

$$
F_{\mathrm{inv,lin}}(f)=
\begin{cases}
F_{\mathrm{raw}}(f)B(f)+F_{\mathrm{thru}}(f)(1-B(f)), & \texttt{bypass\_aligned},\\
F_{\mathrm{raw}}(f)B(f)+1\cdot(1-B(f)), & \texttt{bypass\_pure},\\
F_{\mathrm{raw}}(f)B(f), & \texttt{cut},
\end{cases}
$$

where:

$$
F_{\mathrm{thru}}(f)=\frac{Q_1^*(f)}{|Q_1(f)|}
$$

is the unit-gain, phase-aligned bypass.

## 4. LICFF compensation algorithm

Given an input block $u_{\mathrm{in}}$, the engine first computes the base linear compensation:

$$
u_{\mathrm{comp,lin}}=
\mathcal{F}^{-1}\{\mathcal{F}\{u_{\mathrm{in}}\}F_{\mathrm{inv,lin}}\}.
$$

When `bypass_linear_eq=True`, the base is simply $u_{\mathrm{in}}$. This is the GUI's “Nonlinear Only (No Linear EQ)” mode.

For the ordinary nonlinear path:

1. Initialize $u_{\mathrm{comp}}$ with $u_{\mathrm{comp,lin}}$ and clip it to $[-V_{\mathrm{limit}},V_{\mathrm{limit}}]$.
2. Evaluate the nonlinear spectrum for the current $u_{\mathrm{comp}}$:

   $$
   Y_{\mathrm{nl}}(f)=
   \sum_{p=2}^{5}\mathcal{F}\{u_{\mathrm{comp}}^p\}_{\mathrm{dealiased}}Q_p(f).
   $$

3. Project the output-referred nonlinear component back to the input with the nonlinear inverse:

   $$
   y_{\mathrm{comp,nl}}=
   \mathcal{F}^{-1}\{Y_{\mathrm{nl}}F_{\mathrm{inv,nl}}\}.
   $$

4. Update and clip:

   $$
   u_{\mathrm{comp,raw}}=u_{\mathrm{comp,lin}}-y_{\mathrm{comp,nl}},
   \qquad
   u_{\mathrm{comp}}=\operatorname{clip}(u_{\mathrm{comp,raw}},-V_{\mathrm{limit}},V_{\mathrm{limit}}).
   $$

If `iterative=False`, the implementation performs one nonlinear update. If `iterative=True`, it repeats the update `iters` times. The compensation function's default clip limit is 1.5, while the current GUI simulation and WAV-export paths pass a clip limit of 2.0.

The `linear_only=True` path returns the base linear compensation after clipping and performs no nonlinear update. The GUI exposes three modes:

- `Linear & Nonlinear`: use the linear inverse and nonlinear correction.
- `Nonlinear Only (No Linear EQ)`: bypass linear equalization but retain nonlinear correction.
- `Linear Only`: apply only the linear inverse.

## 5. Stability and processing details

The engine marks a block as unstable when an intermediate result contains NaN or infinity, or exceeds ten times the clip limit in magnitude. The caller may either report this condition or abort export using the GUI's instability option. Clipping counts are also tracked per channel.

Offline WAV processing uses 65536-sample blocks with 4096 samples of overlap. Input audio is resampled to the model sample rate when the rates differ by more than 1 Hz. The output is written at the model rate, and the exporter can optionally RMS-match the output to the original.

The GUI defaults are an active band of 60 Hz–17 kHz, no linear smoothing, automatic 3 dB broadband regularization, iterative compensation disabled, and three iterations when iterative mode is enabled. These are UI defaults; the engine API accepts other values.

## 6. What the current UI measures

The simulation tab compares three forward-model spectra:

- the uncompensated input,
- the compensated input,
- the ideal linear output from `linear_output()`.

The current LICFF implementation does not calculate the THD and SDR metrics described in older versions of this document. Those metrics should not be treated as values produced by the current Feedforward Compensator.

## 7. Related tests and source files

- [`src/gui/widgets/feedforward_compensator.py`](../../src/gui/widgets/feedforward_compensator.py): `LICFFEngine`, GUI settings, simulation, and offline processing.
- [`tests/logic_verification/gui/widgets/test_feedforward_compensator.py`](../../tests/logic_verification/gui/widgets/test_feedforward_compensator.py): direct kernel mapping, inverse behavior, regularization modes, clipping, instability handling, and export behavior.
