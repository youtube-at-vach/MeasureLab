# Audio Device Distortion (THD+N) Measurement

In this recipe, we will explain how to measure "distortion" in devices such as audio interfaces and amplifiers using the **Distortion Analyzer** widget.

The low "distortion" in audio equipment is an indicator of performance in how faithfully the original sound can be reproduced and recorded.

---

## What is Distortion Rate (THD+N)?

**THD+N (Total Harmonic Distortion + Noise)** is an indicator of the "purity" of a signal.
Even though a pure sine wave (single frequency) is supposed to be input, the output may contain other components (harmonics and noise).

* **THD (Total Harmonic Distortion)**: The sum of frequency (harmonic) components that are integer multiples of the input signal.
* **THD+N**: The sum of "all components other than the objective signal," which includes background noise in addition to THD.

The smaller this value (the lower the %, or the larger the absolute value of dB), the higher the performance of the equipment.

### ☕ Coffee Break: What if distortion was a "mirror"?

Imagine an audio device is a "mirror," and the input sound is the "scenery."
A perfect mirror (0% distortion) reflects the scenery exactly as it is. However, if the mirror is slightly warped or its surface is dirty, the reflected scenery will look different from the original, right?

* **Original Sound (Fundamental wave)**: The scenery you originally wanted to reflect.
* **THD (Distortion)**: The parts where the scenery looks "regularly" warped because the mirror is bent (like a funhouse mirror at an amusement park).
* **N (Noise)**: The parts where the whole scenery looks "irregularly" grainy or blurry due to dust or fog on the mirror's surface.

In short, THD+N represents the **overall poor image quality** combining "how bent the mirror is and how dirty it is." The lower the number, the shinier and straighter the mirror is!

---

## Measurement Procedure (Loopback Test)

First, perform a "loopback measurement" to measure the distortion of the audio interface itself. This becomes the limit value (baseline) that can be measured in that environment.

### Physical Connection and Preparation

1. Directly connect **Output L (or Ch 1)** of the audio interface to **Input L (or Ch 1)** with a cable.
2. Start the **Distortion Analyzer** widget.

### Measurement Settings and Execution

1. Set the following in the **Signal Generator** section:
    * **Signal**: `Sine Wave`
    * **Frequency**: `1000 Hz` (standard)
    * **Amplitude**: around `-6 dBFS`
        * *Distortion changes depending on amplitude. Distortion tends to increase near the maximum level.*
    * **Bin Center**: It is recommended to check this. It automatically snaps to the "FFT bin center frequency" that does not cause spectral leakage with the current FFT settings, enabling more accurate measurements.
2. Press the **Start Measurement** button.

### Confirmation of Results

Measurement results are displayed in real-time.

* **THD+N**: An indicator of overall distortion. (Displayed up to 5 decimal places)
* **Harmonics Tab**: The level (ratio to the fundamental wave) for each component, such as the 2nd harmonic (2nd), 3rd harmonic (3rd), etc., can be confirmed in the graph and table.

This numerical value is **"the lower measurement limit of your measurement environment (sound device)."** It is not possible to accurately measure equipment with distortion smaller than this.

---

## Measurement of DUT (Device Under Test)

Next, connect the device you want to measure (DUT: Device Under Test) in between.

1. Change the connection: `[Output] -> [DUT] -> [Input]`
2. Perform the measurement again.

If the distortion rate is larger than during the loopback measurement, that difference can be judged as the **distortion of the DUT itself**.
Conversely, if the value is the same as during loopback, the performance of the DUT is very high, and it is possible that it exceeds the measurement limit of the audio interface.

---

## Limits and Points to Note for This Instrument

### Regarding the Measurement Method

This Distortion Analyzer removes the fundamental wave (such as 1kHz) with a method called a **digital notch filter**, analyzes the remaining components with FFT, and calculates the distortion rate.

This method is versatile and fast, and due to algorithm improvements, measurement is now possible down to approximately **-150dB**.

### Visualization of the Measurement Limit

Try measuring by switching the signal output setting at the bottom right of the main window from "Physical Output" to **"Loopback (Virtual)"**.
The value displayed at this time (probably around -150dB) is the measurement lower limit of this algorithm itself. Noise and distortion lower than this are buried in calculation errors and the limits of the filter.

### When Even Higher Precision Measurement is Required

If you want to measure ultra-high performance DACs and amplifiers that fall below -150dB, consider using the **[LockinHarmonicAnalyzer](../widgets/lockin_harmonic_analyzer.md)**. By using the lock-in method, it is possible to observe even deeper noise floors, but for normal measurements, this Distortion Analyzer provides sufficient performance.

---

## Other Distortion Measurement Tools

The following widgets are also available for those who want to perform more advanced analysis.

* **Advanced Distortion Meter**:
    * **MIM (Multitone Intermodulation)**: Measures distortion in a state closer to a music signal by sounding multiple sounds simultaneously.
    * **PIM (Phase Intermodulation)**: Measures phase modulation distortion.
    * **SPDR (Spurious Free Dynamic Range)**: Measures spurious-free dynamic range.
