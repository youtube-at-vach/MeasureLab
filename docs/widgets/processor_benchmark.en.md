# Processor Benchmark

## Overview

A tool that tests FFT and UI rendering performance for Real-Time measurement. It helps determine the optimal FFT size settings that your processor can handle without dropping audio frames.

## Operation

### Benchmark Controls

- **Start Benchmark**: Starts the sequential benchmark process.
- **Safety Factor**: Sets the fraction of the total buffer time allowed for processing. A value of `0.8` means the processing must complete within 80% of the audio buffer cycle time.
- **Enable Extreme Sizes (Max 16M)**: Enables benchmarking for extremely large FFT sizes up to 16,777,216.

### Benchmark Results

- **Results Table**: Displays the maximum theoretical real-time frames per second (FPS) for each tested FFT size. For various sample rates (44.1kHz, 48kHz, 96kHz, 192kHz), it evaluates whether real-time processing is possible.
    - **OK**: Processing completes within 80% of the safety limit.
    - **⚠**: Processing completes within the safety limit but exceeds the 80% warning threshold.
    - **NG**: Processing time exceeds the safety limit and real-time processing is not possible.

- **Render Test View**: Plots the magnitude spectrum of simulated audio data during the render test phase to measure plotting performance.

- **Recommendations**: Based on the benchmark scores, suggests the optimal FFT size for each sample rate and provides the maximum achievable real-time resolution (Hz).
