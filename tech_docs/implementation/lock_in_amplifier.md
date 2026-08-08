# Lock-in Amplifier: Measurement Principle and Reference Requirements

This document describes the software Lock-in Amplifier implemented in [`src/gui/widgets/lock_in_amplifier.py`](../../src/gui/widgets/lock_in_amplifier.py), including its phase reference, demodulation path, and operating modes.

## 1. Measurement principle

For a sinusoidal signal

$$
V_{\mathrm{sig}}(t)=A_{\mathrm{sig}}\cos(\omega t+\phi_{\mathrm{sig}}),
$$

the lock-in detector projects the signal onto an orthogonal complex oscillator:

$$
z_{\mathrm{sig}}=2\,\operatorname{mean}\left(V_{\mathrm{sig}}(t)w(t)e^{-j\omega t}\right)/\operatorname{mean}(w),
$$

where the implementation uses a Hann window $w(t)$. The complex result encodes the in-phase and quadrature components:

$$
X=\operatorname{Re}(z_{\mathrm{sig}}),
\qquad
Y=\operatorname{Im}(z_{\mathrm{sig}}),
$$

$$
R=\sqrt{X^2+Y^2},
\qquad
\theta=\operatorname{atan2}(Y,X).
$$

`R` is the estimated sinusoidal peak magnitude. `theta` is meaningful only relative to the phase reference used to rotate the signal phasor.

The detector supports a harmonic ratio $n/d$. The signal is demodulated at:

$$
f_{\mathrm{demod}}=f_{\mathrm{ref}}\frac{n}{d}.
$$

The GUI permits numerator and denominator values from 1 to 63.

## 2. Reference-channel processing

The module always reads a signal channel and a reference channel from its input ring buffer. The default channels are signal = Left (Ch 1) and reference = Right (Ch 2). A reference RMS level below 0.001 (approximately -60 dBFS for a full-scale reference) is treated as no reference: the displayed magnitude, phase, X, Y, and reference frequency are cleared and the averaging history is discarded.

When a reference is present, the implementation:

1. Estimates the reference frequency with an AR(2) single-tone estimator.
2. Projects the fundamental reference component with the same Hann-windowed complex projection.
3. Tracks the reference phase across ring-buffer updates using the absolute sample index and phase unwrapping.
4. Scales the tracked phase by $n/d$ to construct the requested fractional-harmonic reference phasor.
5. Rotates the measured signal phasor by the conjugate of that reference phasor.

In simplified form, the final rotation is:

$$
z_{\mathrm{result}}=z_{\mathrm{sig}}\,e^{-j\phi_{\mathrm{ref}}n/d}.
$$

For the fundamental, the code also compensates the projection's Hann-window scalloping loss using the time-domain reference RMS estimate.

## 3. Internal and external modes

The UI labels external mode as `External Mode (No Output)`. The difference is how the output is handled:

- **Internal mode:** the audio callback generates a continuous cosine at the configured frequency and amplitude on the selected output channel(s). The input reference channel is still analyzed and its measured phasor is still used for phase correction. In this mode, the code forces the reference frequency to the configured generator frequency and sets the displayed coherence to 1.0.
- **External mode:** the callback does not generate output. The user supplies the excitation and a reference signal externally, and the input reference channel is analyzed normally.

The current implementation does not provide a software-only phase fallback when the reference input is absent. A nonzero reference input is required for any result. For an absolute phase measurement of a physical DUT, the reference input should be a physical copy of the excitation delivered to the DUT, for example:

1. Split the excitation output.
2. Connect one branch to the DUT input.
3. Connect the other branch to the reference input.
4. Connect the DUT output to the signal input.

If both paths share the same excitation-path delay, the measured phase is approximately:

$$
\theta_{\mathrm{result}}
 = (\phi_{\mathrm{latency}}+\phi_{\mathrm{DUT}})
   -\phi_{\mathrm{latency}}
 =\phi_{\mathrm{DUT}}.
$$

Without a physical reference that represents the excitation at the DUT, the phase is only relative to whatever waveform is present on the selected reference channel. It should not be interpreted as an absolute DUT phase.

## 4. Filtering and averaging

The default integration buffer contains 65,536 samples. After demodulation, the complex baseband result can pass through a cascaded one-pole IIR low-pass filter. The order is selectable from 0 (off) to 8 and defaults to 4. Its time constant defaults to the buffer duration, or can be set explicitly.

The filtered complex result is appended to a history buffer. The displayed result is the complex mean of the most recent `averaging_count` values, with a GUI range of 1–300:

$$
z_{\mathrm{display}}=\operatorname{mean}(z_1,\ldots,z_N),
\qquad
R_{\mathrm{display}}=|z_{\mathrm{display}}|,
\qquad
\theta_{\mathrm{display}}=\arg(z_{\mathrm{display}}).
$$

The module also reports the standard deviation of the magnitudes and an unwrapped phase standard deviation over the averaging history.

## 5. Calibration and frequency sweeps

When calibration is enabled, the audio calibration map supplies a magnitude correction and phase correction at the generator frequency. The engine applies the magnitude correction in linear scale and subtracts the phase correction from the displayed phase.

The frequency-response sweep reuses the same lock-in processing for each configured test frequency. It therefore inherits the reference-channel requirement and the distinction between absolute and relative phase described above.

## 6. Implementation notes

- Output generation uses a continuous phase accumulator to avoid discontinuities between audio blocks.
- A Hann window reduces spectral leakage when the buffer does not contain an integer number of cycles.
- Reference frequency is estimated with the relation $r[n-1]+r[n+1]=2\cos(\omega)r[n]$ rather than a Hilbert transform.
- If the reference is lost, stale averaged values are cleared instead of being held on screen.

## 7. Related source files

- [`src/gui/widgets/lock_in_amplifier.py`](../../src/gui/widgets/lock_in_amplifier.py): output generation, reference estimation, demodulation, filtering, averaging, and calibration.
- [`src/gui/widgets/lock_in_frequency_counter.py`](../../src/gui/widgets/lock_in_frequency_counter.py): separate lock-in frequency-counter implementation and FLL/Kalman processing.
