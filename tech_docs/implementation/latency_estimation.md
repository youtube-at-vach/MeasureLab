# System Latency Estimation and Measurement Precision

This document describes the latency-estimation paths currently implemented in MeasureLab, the sub-sample peak detector they share, and how the resulting delay is used by the nonlinear analyzer.

## 1. Why latency estimation matters

The recorded response is delayed relative to the generated excitation by the audio I/O path, device buffering, and any physical loopback wiring. A delay error becomes a frequency-dependent phase error:

$$
\Delta\phi(f) = -2\pi f\,\Delta t.
$$

The error therefore becomes increasingly visible at high frequencies. In a swept-sine measurement, the reference and measured channels must also remain aligned when harmonic impulse responses are gated and separated.

## 2. Implemented calibration paths

MeasureLab currently contains two related latency-calibration implementations. They should not be conflated.

### 2.1 Nonlinear Analyzer calibration

`NonlinearAnalyzer.calibrate_latency()` in [`src/gui/widgets/nonlinear_analyzer.py`](../../src/gui/widgets/nonlinear_analyzer.py) uses a short logarithmic chirp:

1. Generate a 0.5 s logarithmic chirp from 20 Hz to 10 kHz at amplitude 0.3.
2. Append 0.5 s of zeros so that delayed samples can still be recorded.
3. Play and record the signal in one audio session.
4. Cross-correlate the selected measurement channel with the time-reversed chirp:

   $$
   c[n] = y[n] * \operatorname{reverse}(s)[n].
   $$

   The implementation computes this with `scipy.signal.fftconvolve(..., mode="full")`.
5. Detect the correlation peak with `find_subsample_peak()` and convert the lag to seconds. Negative results are clamped to zero.

This path uses cross-correlation directly; it does not call `deconvolve_signal()`.

### 2.2 Realtime SSS latency measurement

`measure_system_latency()` in [`src/core/realtime_sss_core.py`](../../src/core/realtime_sss_core.py) uses the Novak-style SSS generator from [`src/core/nonlinear_analyzer_core.py`](../../src/core/nonlinear_analyzer_core.py):

1. Clamp the calibration band to a start frequency of at least 20 Hz and an end frequency of at least 100 Hz.
2. Generate an SSS and its analytical inverse filter. The default requested sweep duration is 0.25 s, and the recorder adds a 0.3 s margin.
3. Play the sweep and record the selected input channel through a temporary audio callback.
4. Deconvolve the recording with the SSS, then locate the impulse-response peak.
5. Clamp a negative peak to zero and return the result in samples.

The SSS deconvolution is:

$$
H(f) = \frac{Y(f)S^*(f)}{|S(f)|^2 + \epsilon},
\qquad
\epsilon = 10^{-4}\max_f |S(f)|^2 + 10^{-12}.
$$

The FFT length is the next power of two that is at least the recorded length plus the SSS length.

## 3. Sub-sample peak detection

Both paths use `find_subsample_peak(ir)`:

1. Find the integer index of the largest absolute impulse-response sample.
2. Circularly shift the response so that this peak is at the center of the buffer.
3. Extract a 32-sample window centered on the peak and apply a Tukey window with `alpha=0.25`.
4. Compute a 32-point DFT, zero-pad it to 100 times the length, and take the inverse DFT.
5. Locate the maximum of the interpolated magnitude and map it back to the original circular index.

The returned value is a floating-point sample index with a nominal 0.01-sample grid. This is an interpolation result, not a guarantee of 0.01-sample physical accuracy; noise, bandwidth, and peak shape still determine the actual uncertainty.

At 48 kHz, one sample is approximately 20.83 microseconds. The sub-sample result is used to avoid throwing away useful timing information during alignment.

## 4. Applying the calibrated delay

For single-channel nonlinear measurements, `process_amplitude_responses()` applies the stored delay to every frequency bin:

$$
H_{\mathrm{corr}}(f)
 = H_{\mathrm{meas}}(f)
   \exp\left(j2\pi f\frac{\Delta t\,f_s}{f_s}\right)
 = H_{\mathrm{meas}}(f)\exp(j2\pi f\Delta t).
$$

Here, `latency_sec` is converted to samples by `latency_sec * sample_rate`. In the two-channel `XFER` and `XFER_REV` modes, the measured response is divided by the reference fundamental, so an independent latency calibration is not required for the relative transfer function.

## 5. Verification status

The repository contains automated simulations for fractional-sample latency and peak recovery in [`tests/core/test_realtime_sss_core.py`](../../tests/core/test_realtime_sss_core.py). The current source does not contain the linear/logarithmic/hyperbolic sweep experiment or the ZOOM UAC-232 result table that appeared in an earlier version of this document. Those historical values are therefore not presented as current implementation guarantees.

## 6. Related source files

- [`src/gui/widgets/nonlinear_analyzer.py`](../../src/gui/widgets/nonlinear_analyzer.py): GUI calibration path and single-channel latency usage.
- [`src/core/realtime_sss_core.py`](../../src/core/realtime_sss_core.py): realtime SSS latency calibrator.
- [`src/core/nonlinear_analyzer_core.py`](../../src/core/nonlinear_analyzer_core.py): SSS generation, deconvolution, sub-sample peak detection, and frequency-domain delay correction.
- [`tests/core/test_realtime_sss_core.py`](../../tests/core/test_realtime_sss_core.py): automated latency and fractional-delay tests.
