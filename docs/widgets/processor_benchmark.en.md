# Processor Benchmark

Processor Benchmark is a tool to test the FFT and UI rendering performance of your PC for real-time measurements, verifying safe processing limits.

## ☕ Coffee Break: What does it mean for a PC to "Run Out of Breath"?

Audio measurement is an extremely demanding task that involves continuously calculating (FFT) and drawing on the screen the stream of audio data flowing in real-time.
Let's compare this to a **"Conveyor Belt Sushi Kitchen"**.

* **Sampling Rate (Audio Data)**: These are the "plates of sushi" coming down the conveyor belt one after another. If the rate is high, like 192kHz, the plates flow at a furious speed.
* **FFT Size (Bucket Size)**: This is the number of "how many plates of sushi the chef gathers at once before calculating" to process them at the same time. A larger size allows for higher-definition analysis, but the calculation takes longer.
* **Processing Dropouts**: This is the state where the chef's (PC's CPU) calculation speed cannot keep up, and the sushi spills off the conveyor belt. When this happens, the measurement data is interrupted, and accurate results cannot be obtained.

This widget is a tool to test "up to what speed can your PC (the chef) handle the sushi without dropping it?" It is a very important "health check" to prevent the screen from stuttering or data from skipping during measurement!

## Primary Uses

* Evaluate the maximum FFT size your PC can process in real-time.
* Identify the recommended maximum FFT size for different sampling rates.

## How to Use

1. **Safety Factor**: Sets the fraction of total buffer time allowed for processing. Default is `0.8` (80%).
    * 💡 **Why not 100%?**: If the chef is always working at 100% capacity, a slight hiccup (like another app running in the background) will immediately cause the sushi to overflow. Setting it to 80% leaves a 20% "margin of safety."
2. **Extreme Sizes**: When enabled, performs testing with larger FFT sizes (up to 16M). This is an option for high-end PCs aiming for ultra-high-definition measurements.
3. **Start Benchmark**: Starts the test. Audio input is temporarily stopped during the test.
4. **Copy Results to Clipboard**: Copies the benchmark results, including system information and performance metrics, to the clipboard.

## Display Elements

* **System Information**: Displays the current operating system, CPU name, and architecture.
* **FFT Size**: The FFT size tested.
* **44.1kHz - 192kHz Columns**: Determines if the processing finishes within the specified safety factor for each sampling rate (OK, ⚠, NG).
* **Max FPS**: The maximum frame rate achievable for that FFT size.
    * 💡 **Screen Smoothness**: For example, if Max FPS is `10`, the graph on the screen will update a maximum of 10 times per second. The measurement itself is accurate, but it will look a bit choppy.
