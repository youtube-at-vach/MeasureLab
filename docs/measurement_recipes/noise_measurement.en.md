# Noise Measurement

This is a comprehensive guide to measuring and analyzing "noise" in audio equipment and circuits. Select the optimal tool (widget) according to your purpose and perform the measurement according to the procedure.

## Tool Selection Guide by Purpose

The widget to use depends on what kind of noise you want to see.

| Purpose | Recommended Tool | Overview |
| :--- | :--- | :--- |
| **View noise spectrum** | [Spectrum Analyzer](../widgets/spectrum_analyzer.md) | Confirm at which frequencies and how much noise is included (distribution). This is the most common measurement. |
| **Analyze noise types** | [Noise Profiler](../widgets/noise_profiler.md) | Decompose into components such as "hiss (white noise)" and "hum," and quantify their respective contributions. |
| **View time-series changes in noise** | [Raw Time Series](../widgets/raw_time_series.md) | Monitor changes over time, such as "occasional pop noise" or "fluctuation of DC offset." |

---

## View Noise Spectrum (Spectrum Analyzer)

Graphs the strength of noise per frequency (spectrum display). You can see things like "whether high sounds are noisy or low sounds are noisy" and "whether there is a peak at a specific frequency."

### Preparation

* **Equipment Connection**: Connect the device under test (DUT) to the input of the audio interface.
* **Input Short (for self-noise measurement)**: When measuring the noise of the audio interface itself or the residual noise of an amplifier, short the inputs or connect a dummy load to prevent external noise from entering.

### Measurement Procedure

1. Launch **Spectrum Analyzer**.
2. Configure **Analysis Settings** as follows:
    * **Mode**: Select `PSD` (Power Spectral Density).
        * *Note*: For noise measurement, the `PSD` mode, which is less affected by bandwidth, is recommended over the normal `Spectrum` mode.
    * **Window**: Select `hanning` (default) or `Multitaper` (recommended).
        * Turning ON **Multitaper** makes the noise graph smoother and improves reliability.
    * **Avg (Averaging)**: Raise the slider to about `50%` to `90%`.
        * Since noise fluctuates randomly, averaging suppresses fluctuations and makes it easier to see the true noise level (noise floor).
3. Press **Start Analysis** to begin measurement.

### How to Read Results

* **What is PSD (Power Spectral Density)?**
  * `Spectrum mode` is suitable for measuring the level of "sine wave-like signals," while `PSD mode` measures the density (power per 1 Hz) of "noise-like signals". The unit is $/√Hz$.

* **What Can You See?**
  * **Hum Noise**: If sharp peaks stand at 50Hz or 60Hz (and their harmonics), it is induction noise from the power supply.
  * **White Noise**: If the graph is upward-sloping (showing higher energy at higher frequencies), it is white noise (equal energy across all bands). *Note: White noise is flat on a linear frequency axis but appears upward-sloping on a logarithmic axis.*
  * **Pink Noise (1/f Noise)**: If the graph appears generally flat (decreasing slightly to the right), the 1/f noise component is dominant.

### Precautions

* **Ground Loop**: If the grounds of the computer and the device under test form a loop, a huge amount of hum noise may be present. In that case, try using a USB isolator or battery power for the laptop.

---

## Analyze Noise Types (Noise Profiler)

Automatically decomposes noise into three elements: "white noise," "1/f noise," and "hum noise," and quantitatively evaluates each amount.

### Preparation

* **Temperature Check**: If you want to compare with the thermal limit (thermal noise), check the room temperature.
* **Impedance Check**: Checking the output impedance of the device under test (e.g., 150 Ω to 600 Ω for a microphone) allows comparison with theoretical limits.

### Measurement Procedure

1. Launch **Noise Profiler**.
2. Check **Settings** (left tab).
    * **Measurement > Average Mode**: Turn ON `Enable Averaging` and set the Count to about `100` to `1000`. The more you increase it, the higher the precision.
    * **Measurement > Input Z**: If known, enter the impedance value.
3. Press **Start Profiling** to begin measurement.
4. Look at the **Noise Contribution** bar below the graph.

### How to Read Results

* **Cycle (Hum)** (Cyan):
  * Specific frequency components, such as hum noise entering from power lines. If this is large, suspect defective cable shielding or a ground loop.
* **White** (Green):
  * Noise that occurs uniformly regardless of frequency, such as thermal noise from resistors or shot noise from semiconductors. It shows the basic capability of the amplifier.
* **1/f** (Red):
  * Noise that increases at lower frequencies. It is often caused by the quality of transistors or DC instability.

### Precautions

* **Convergence Time**: Until averaging progresses, the numbers may vary. Wait for the count value to be reached (until the progress bar is full) before reading the value.

---

## View Time-Series Changes in Noise (Raw Time Series)

Records how voltage fluctuates with time like a chart recorder, rather than spectrum (frequency). It is suitable for capturing sudden phenomena or slow fluctuations, rather than continuous "hiss" noise.

### Preparation

* **DC Coupling**: If you want to see the fluctuation (drift) of DC offset, the audio interface must support DC coupling. Since general audio interfaces are AC-coupled (with a high-pass filter), ultra-low frequencies or DC may not be visible.

### Measurement Procedure

1. Launch **Raw Time Series**.
2. Configure **Settings** as follows:
    * **Time Span**: Select a long time (`60s` or `300s`).
    * **Scale**: Since noise is minute compared to signals, enlarge it significantly (e.g., `10.0x` or `100.0x`) so that minute movements can be seen.
    * **Show DC Offset**: Turning it `ON` is convenient.
3. Press **Start** to begin monitoring.

### How to Read Results

* **Pop Noise / Click Noise**:
  * Sudden "pop" noises remain clearly as "spikes" in a time-series plot.
* **DC Drift**:
  * If the line of the entire graph is slowly waving up and down, the DC offset (direct current component) is not stable. Circuit drift due to temperature changes or leakage current of capacitors is suspected.
* **Rustling Noise**:
  * Irregular voltage fluctuations due to poor contact are also obvious when viewed in time series.

### Precautions

* **Misses**: Behavior while the widget is not displayed (e.g., in the background) depends on environment settings, but basically, drawing continues. However, very short spike noises may fall between screen drawing update intervals (aliasing). If you want to capture them reliably, consider using the trigger function of the oscilloscope widget as well.
