# Lock-in Harmonic Analyzer

The **Lock-in Harmonic Analyzer** is a module that utilizes the principles of a lock-in amplifier to measure Total Harmonic Distortion (THD) and THD+N with extremely low noise and high precision.

Unlike conventional FFT-based distortion measurements that rely on window functions, this widget performs **10-parallel IQ detection (lock-in measurement)** simultaneously for the fundamental wave and its harmonics. By strictly tuning into only the target frequency components, it can accurately extract signals buried in noise, enabling measurements in ultra-low distortion regimes (e.g., below -160 dBc) that exceed the limitations of traditional FFT analysis.

## Unique Measurement Principle

The most significant feature of this widget is its **multi-parallel lock-in detection** analysis approach (mathematically implemented as matrix projection).

1. **Precise Cycle Extraction**: The module precisely interpolates the zero-crossing points (rising edges) of the input Reference signal to extract exactly an integer number of signal cycles.
2. **Reference Signal Generation**: Based on the detected fundamental frequency $\omega$, it internally generates reference sine (I) and cosine (Q) waves synchronized with the DC component, the fundamental, and each harmonic component ($1\omega$ through $n\omega$).
3. **Parallel IQ Detection (Lock-in)**: By simultaneously multiplying the incoming measurement signal vector $Y$ by all these generated reference signals and integrating them (solving the system of equations via matrix projection), it directly calculates the amplitude and phase of each harmonic component all at once.
   $$ \text{Coefficients} = (B^T B)^{-1} B^T Y $$
4. **Harmonic and Residual Separation**: By subtracting all extracted harmonic components from the original signal, the pure residual noise component is cleanly separated.

Thanks to the lock-in amplifier's characteristic of acting as an extremely narrow bandpass filter tailored only for the target frequencies, this method fundamentally avoids the spectral leakage caused by window functions. It allows for the accurate separation and extraction of minuscule distortion components from the surrounding background noise floor.

## How to Use

### 1. Settings

* **Output Ch**: Select the channel to output the test signal (Left / Right / Stereo).
* **Buffer (Integ. Time)**: Select the length of data capture used for analysis. A larger buffer size means a longer integration time, which averages out random noise and improves the Signal-to-Noise Ratio (SNR) of the measurement. Large buffers (e.g., 262,144 or 524,288) are recommended for ultra-low distortion measurements.
* **Frequency**: Specify the fundamental frequency of the output test sine wave in Hz.
* **Amplitude**: Specify the output level of the test sine wave in dBFS. Set an appropriate level (e.g., -6.0 dBFS to -1.0 dBFS) to avoid clipping.
* **Start Analysis / Stop Analysis**: Toggles the measurement on and off. When started, it will display "Buffering..." until the buffer is filled, after which the analysis results will update.

### 2. Input Routing

* **Signal Input**: Select the channel where the target signal you want to measure for harmonic distortion is routed.
* **Reference Input**: Select the channel where the reference signal for lock-in analysis is routed. This should be the test signal source itself, either tapped before going through the Device Under Test (DUT) or a very stable, low-distortion signal. The fundamental frequency and phase are extracted with high precision from this reference.

### 3. Overview

* **THD**: Displays the measured Total Harmonic Distortion value (in dB and %).
* **THD+N**: Displays the measured total of THD plus residual noise value (in dB and %).
* **Fundamental**: Displays the amplitude level of the measured fundamental wave (1st harmonic) in dBFS.

### 4. Detail Analysis Tabs

* **Harmonics Table**: A tabular view showing the absolute amplitude (Amp dBFS), relative level to the fundamental (Level dBc), and phase (Phase deg) for each harmonic order.
* **Harmonics Plot**: A bar graph visually showing the level of each harmonic component (dBFS).
* **Residual**: Displays the waveform of the "residual components" (noise + other non-harmonic components). This is the original signal minus the calculated fundamental and all harmonic components.
