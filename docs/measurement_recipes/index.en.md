# Measurement Recipes

![Banner](../assets/banner.png)

Measurement recipes are a collection of guides that systematically explain **"which widgets to use and how to combine them for specific purposes (e.g., analyzing noise, evaluating equipment performance)."**

Please use them as practical procedures to maximize the diverse measurement tools included in MeasureLab and use them for actual audio engineering, hobbyist development, and maintenance.

---

## ☕ Coffee Break: Why call them "Recipes"?

Imagine going to cook and being handed just "ingredients" and a "frying pan." You'd be at a loss! It's only with a **recipe (instruction manual)** that tells you "use these tools, and cook them in this order" that you can create a delicious dish.

Audio measurement is exactly the same. MeasureLab offers many powerful tools (widgets), but "how to combine them" is the crucial part. On this page, we've compiled the know-how of measurement professionals into "recipes" that anyone can easily follow. What menu shall we cook up today?

---

## How to Use Measurement Recipes

The most important thing in measurement is not just reading numbers, but **"measuring with the correct method and interpreting the results correctly."** Each recipe explains according to the following steps:

* **Purpose and Tool Selection**: Confirm which widget is best for what you want to evaluate.
* **Setup (Preparation)**: Summarize the connection method with the device under test (DUT) and notes on environment settings.
* **Measurement Procedure**: Explain the specific operation flow and recommended setting values.
* **Interpretation of Results**: Explain what characteristics of the hardware can be read from the obtained graphs and numbers.

---

## 🧪 Available Recipes

The following guides are currently available:

* **[Noise Measurement Recipe](noise_measurement.md)**
    * Detailed analysis of residual noise (hiss) and hum noise from amplifiers and circuits. We explain techniques for identifying and evaluating causes for each component, such as 1/f noise, thermal noise, and external induction noise.
* **[High-Precision Gain/Phase Measurement (Lock-in Amplifier)](lockin_amplifier.md)**
    * Explains how to measure gain and phase with higher precision than FFT. Introduces precision demonstration at the 0.001 dB level through loopback tests and ultra-precise frequency response measurement using FRA mode.
* **[Distortion (THD+N) Measurement](distortion_measurement.md)**
    * Explains basic procedures for measuring distortion in audio equipment. Also touches on measurement limits using the digital notch filter method and choosing between it and the lock-in THD analyzer.
* **[Speaker Impedance Measurement](speaker_impedance.md)**
    * Explains how to measure the $f_0$ (lowest resonant frequency) and impedance characteristics of a speaker unit. Introduces the connection diagram using the I-V method and how to read the measurement results step by step.

---

## 📅 Future Expansion

Measurement recipes are scheduled to be added and updated sequentially according to user needs and the expansion of widget functions.

---

## References

* The precision of the measurement values obtained in each recipe depends heavily on the performance of the audio interface used and the calibration status.
* For the reliability of measurements and the limitations of this tool, please be sure to read [**Appendix: This tool is not a "measurement instrument"**](../appendix.md).
