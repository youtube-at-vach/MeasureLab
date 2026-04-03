# Processor Benchmark

Processor Benchmark is a tool to test the FFT and UI rendering performance of your PC for real-time measurements, verifying safe processing limits.

## Primary Uses

- Evaluate the maximum FFT size your PC can process in real-time.
- Identify the recommended maximum FFT size for different sampling rates.

## How to Use

1. **Safety Factor**: Sets the fraction of total buffer time allowed for processing. Default is 0.8 (80%).
2. **Extreme Sizes**: When enabled, performs testing with larger FFT sizes (up to 16M).
3. **Start Benchmark**: Starts the test. Audio input is temporarily stopped during the test.

## Display Elements

- **FFT Size**: The FFT size tested.
- **44.1kHz - 192kHz Columns**: Determines if the processing finishes within the specified safety factor for each sampling rate (OK, ⚠, NG).
- **Max FPS**: The maximum frame rate achievable for that FFT size.
