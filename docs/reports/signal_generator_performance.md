# Signal Generator Performance Optimization Report

## Summary

The Signal Generator real-time path was optimized without removing waveforms,
modulation, filtering, calibration, routing, or channel independence.

The largest measured improvements were:

- Three-filter processing: 57% to 59% less callback time.
- Short Golay playback: 80% to 92% less callback time.
- Standard stereo sine generation: 26% to 30% less callback time.
- Starting previously selected grey noise: over 99.9% less start latency.

At 384 kHz with a 256-sample block, the LPF + HPF + Notch case decreased from
67.2% to 27.6% of the complete audio-block deadline. This leaves substantially
more time for analyzers sharing the same audio callback.

## Implemented Changes

### Combined SOS filter cascade

LPF, HPF, and Notch sections are combined when their settings change and are
processed with one `scipy.signal.sosfilt` call per channel and block. The filter
order and persistent state remain the same, while repeated SciPy validation and
axis preparation are avoided.

### Constant-time short-buffer reads

Short MLS, Golay, and PRBS periods previously wrapped through a Python loop many
times per audio block. A small expanded read cache now serves the block with one
slice. Long buffers use one contiguous slice or at most two copies at a wrap.

### Reused time and phase work areas

Sample offsets, block-relative time, and fixed-frequency phase work arrays are
reused. Unmodulated periodic signals can be written directly to the audio output
channel with NumPy `out` operations instead of allocating and copying several
temporary arrays.

### Buffer generation cache and deterministic stereo sharing

The complete buffered-waveform configuration is cached. Starting output no
longer regenerates a buffer already prepared by waveform selection. Inactive
routing channels are prepared only when activated.

Identically configured deterministic signals can share immutable sample data
between left and right while retaining independent read indices, modulation,
and filter state. Random noise remains independently generated per channel.

PRBS seed generation now uses a local random state and no longer resets NumPy's
process-wide random generator.

## Benchmark Method

Both revisions were measured with the same script, interpreter, dependencies,
and machine. The base source was checked out in a temporary Git worktree.

- Base revision: `6c9c924e` (`origin/main` at measurement time)
- Python: 3.12.13
- NumPy: 2.2.6
- Platform: macOS 13.7.8, x86-64
- Statistic: median of 5 runs
- Each callback run: 100 warm-up blocks and 3,000 measured blocks
- Output type: stereo `float32`
- Garbage collection: disabled only during the timed callback loop

The benchmark is available at
`tests/benchmarks/algorithms/benchmark_signal_generator.py`.

## Results at 48 kHz / 1024 Samples

The audio-block deadline is 21,333.33 microseconds.

| Case | Before (us) | After (us) | Reduction | Speedup |
| --- | ---: | ---: | ---: | ---: |
| Sine stereo | 61.25 | 45.16 | 26.3% | 1.36x |
| FM + PM + AM | 244.93 | 205.85 | 16.0% | 1.19x |
| LPF + HPF + Notch | 487.95 | 208.50 | 57.3% | 2.34x |
| Golay order 4 | 177.27 | 14.05 | 92.1% | 12.62x |
| Golay order 12 | 27.87 | 12.99 | 53.4% | 2.15x |

## Results at 384 kHz / 256 Samples

This configuration has a much tighter 666.67-microsecond audio-block deadline.

| Case | Before (us) | After (us) | Reduction | Budget before | Budget after |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sine stereo | 42.33 | 29.56 | 30.2% | 6.35% | 4.43% |
| FM + PM + AM | 176.07 | 139.00 | 21.1% | 26.41% | 20.85% |
| LPF + HPF + Notch | 448.23 | 184.21 | 58.9% | 67.23% | 27.63% |
| Golay order 4 | 59.38 | 11.82 | 80.1% | 8.91% | 1.77% |
| Golay order 12 | 21.71 | 11.47 | 47.2% | 3.26% | 1.72% |

## Start Latency and Memory

Grey noise was selected before timing `start_generation`, reproducing the normal
UI sequence where waveform selection prepares the signal before output starts.

| Configuration | Before | After |
| --- | ---: | ---: |
| 48 kHz grey-noise start | 19.63 ms | 0.01 ms |
| 384 kHz grey-noise start | 192.69 ms | 0.02 ms |

A PRBS order-23 buffer contains 8,388,607 `float64` samples, approximately
64 MiB. Identical stereo settings previously retained two independent buffers
(approximately 128 MiB); they now share one 64 MiB sample array. Each channel's
read index and downstream state remain independent.

## Numerical and Functional Verification

- Direct periodic generation was compared with the original general generation
  path for sine, square, triangle, sawtooth, pulse, and tone + noise. The maximum
  observed absolute difference was `5.3e-15`; sine, square, pulse, and tone +
  noise were exactly equal in the test configuration.
- The combined filter output was compared across multiple consecutive blocks
  with sequential LPF, HPF, and Notch `sosfilt` calls, including persistent
  filter state. The arrays were exactly equal.
- Noise buffers are never shared between channels.
- Buffer cache keys include every waveform input, sample rate, and applicable
  frequency-calibration value.
- Dedicated regression tests cover cache reuse, routing activation, shared
  deterministic buffers, modular short-buffer reads, direct periodic output,
  and combined filter equivalence.

## Reproduction

Default benchmark:

```bash
./.venv/bin/python tests/benchmarks/algorithms/benchmark_signal_generator.py \
  --iterations 3000 --warmup 100 --repeats 5
```

High-rate, low-buffer benchmark:

```bash
./.venv/bin/python tests/benchmarks/algorithms/benchmark_signal_generator.py \
  --sample-rate 384000 --block-size 256 \
  --iterations 3000 --warmup 100 --repeats 5
```

Results are machine-dependent. Relative comparisons should be made on the same
system with other CPU-intensive workloads stopped.
