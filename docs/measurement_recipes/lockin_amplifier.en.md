# High-Precision Gain and Phase Measurement (Lock-in Amplifier)

One of the standout features of this application is measurement using a **Lock-in Amplifier**.

Generally, an FRA (Frequency Response Analyzer) using FFT (Fast Fourier Transform) is used to measure frequency characteristics (gain and phase), but using a lock-in amplifier allows for measurements with relative precision that far exceeds that.

## ☕ Coffee Break: What is a "Lock-in Amplifier"?

Imagine you are looking for a friend in a very noisy crowd. You can't see or hear them well because of everyone else.
However, if your friend is waving a **"red flag at a steady rhythm of exactly once per second,"** you could find them immediately, right?
A Lock-in Amplifier uses this exact same principle!
It completely ignores noise by saying, "I will only look for the signal that changes at this exact specific rhythm (Reference Signal)." By doing this, it can dig up extremely faint signals buried in noise that normal FFTs cannot find. It is truly the ultimate **"Noise Canceling Microscope"**!

## Why a Lock-in Amplifier?

Measurements using FFT are fast, but the measurement precision depends on "frequency resolution (bin width)" and "noise floor". On the other hand, a lock-in amplifier uses a method called **Phase Sensitive Detection (PSD)** to extract only the components that are synchronized with the reference signal.

* **Overwhelming Noise Rejection**: Because it can cut out noise other than the target frequency to the utmost limit, even minute signals buried in noise can be accurately measured.
* **High-Precision Phase Measurement**: Because the phase difference with the reference signal is calculated directly, errors that depend on FFT bin boundaries do not occur.

This makes it possible to capture even minute changes on the order of 0.001dB.

---

## Measurement Procedure (Loopback Test)

Here, we will explain the procedure for directly connecting the input and output of the audio interface (loopback) and experiencing its high measurement precision.

### Connection and Setup

1. **Physical Connection**:
    * Connect the **Output L** of the audio interface to the **Input L**.
    * Connect the **Output R** of the audio interface to the **Input R**.
    * (Create a loopback for both L/R)
2. Launch the **Lock-in Amplifier** widget.
3. Configure **Generator Settings**.
    * **Mode**: `Internal`
    * **Output Channels**: `Stereo` (Outputs a signal from both L and R)
4. Configure **Input Settings**.
    * **Input Channel**: `Left` (Target signal to measure)
    * **Ref Channel**: `Right` (Reference signal)

### Setting Measurement Parameters

To perform high-precision measurements, the following settings are recommended.

* **Averaging**: `10` times
    * The more you increase the number of times, the more random noise is reduced, and the measurement values stabilize.
* **BPF Order**: `4` th
    * Using a steep filter effectively removes harmonic distortion and unnecessary noise.
* **Buffer Size**: Set to **Maximum value**
    * Please set the buffer size to a large value in the Settings widget. The larger the buffer size, the more stably low frequencies can be measured, and the computational load also decreases.

### Executing and Checking the Measurement

Press the **Start** button to begin measurement.

* **Relative Error**: With an appropriate loopback environment, measurements can be taken with an extremely small relative error of about **0.001dB**.
* **Automatic Adjustment of Significant Digits**: The number of digits displayed in the measurement values is **automatically calculated based on the variance (scatter) of the measurement values**. When the numerical value is stable, the number of digits increases, and when there is a lot of noise, the number of digits decreases.
    * **Mechanism**: The standard deviation (σ) of recent measurement values is calculated, and it identifies at which digit the fluctuation is occurring. For example, if the standard deviation is `0.001`, since the third decimal place is fluctuating, it displays up to that digit (`digits = -floor(log10(std))`). Even for dB display, the variance of the linear value is converted into the fluctuation in dB equivalent, and calculated similarly. This allows the user to intuitively read only the "meaningful digits".

---

## ! Recommended Settings for Linux Environments

When performing high-precision phase measurements, the stability of the audio backend is extremely important. With standard PulseAudio or some ALSA settings, minute **Phase Jumps** may occur at the buffer seams, and the lock-in amplifier may not achieve its precision.

### Recommended Environment

When performing high-precision measurements on Linux, we strongly recommend using the **JACK Audio Connection Kit** or **PipeWire (Pro Audio profile)**. This guarantees a completely continuous and stable stream at the sample level.

### How to Check Stability

You can confirm whether the environment is stable by the following methods.

1. **Transient Analyzer**: Check the scalogram (time-frequency graph) to see if there are any regular **vertical lines or noise (artifacts)**.
2. **Lock-in Frequency Counter**: Measure the frequency with this widget and confirm if the numerical value is stable. If there is a phase jump, the frequency measurement may fluctuate intermittently.

---

## More Advanced Measurement: FRA Mode

It is possible to sweep the frequency and measure the characteristics, not just a single frequency.

* **FRA Mode**: While using the functions of the Lock-in Amplifier, the frequency is automatically changed to draw a graph. It takes more time than the standard FRA widget, but you can obtain **ultra-precise gain and phase characteristics**.
* **Recommended Setting**: Setting the number of points to about `500` will give a very smooth and high-definition graph.
