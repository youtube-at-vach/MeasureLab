# Speaker Impedance Measurement

!!! Warning "Unverified Guide"
    This guide was created based on AI inference. Please be sure to read [**Appendix: This tool is not a "measuring instrument"**](../appendix.md) regarding the reliability of measurement results and the limitations of this tool.

This guide measures the electrical characteristics (impedance) of speaker units.
By plotting the impedance curve, you can obtain clues for identifying the speaker's lowest resonant frequency ($f_0$) and parameters necessary for enclosure (box) design.

## Measurement Scope and Limitations

This configuration is not optimized for measuring low-impedance loads such as speakers.
While it is possible to observe the shape of the impedance curve and resonance behavior, the accuracy of absolute values may be limited due to the output impedance of the audio interface.

If accurate impedance values or calculation of small-signal parameters is required, please use an external low-output impedance driver stage (such as a buffer or power amplifier).

## Purpose

* **Identify $f_0$ (Lowest Resonant Frequency)**: Identify the low frequency at which the speaker vibrates most efficiently.
* **Check Impedance Curve**: Confirm how the load on the amplifier changes.
* **Check for Disconnection/Failure**: If the impedance is abnormally high or low, you can discover abnormalities in the voice coil.

## Requirements

The following equipment is required for measurement.

* **Audio Interface**: One with 2 inputs and 2 outputs (line input/output).
* **Reference Resistor**: One resistor of about 10Ω to 100Ω.
  * High precision (1% error or less) is desirable, but even a normal 5% product can measure with high precision if you input the value measured by a tester.
  * For speaker measurement, about **10Ω to 47Ω** is easy to use.
* **Connection Cable**: Cables that are easy to connect to the object to be measured, such as alligator clips.

## Connection Setup (I-V Method)

MeasureLab's **Impedance Analyzer** uses the Current-Voltage Method (I-V Method).
Connect as follows.

![Connection Setup (I-V Method)](../assets/speaker_impedance_wiring.png)

1. Connect **Output L** to the positive terminal of the speaker.
2. Connect the **Ref Resistor** to the back of the speaker (negative terminal) and drop it to GND.
3. Measure the "voltage applied to the speaker" at **Input L** (across the speaker).
4. Measure the "voltage applied to the resistor" at **Input R** (this allows current to be calculated).

## Measurement Procedure

### 1. App Settings

1. Open the **Impedance Analyzer** widget.
2. Configure the settings in the **Settings** panel (left side).
    * **Voltage Ch**: `Left` (Ch 1)
    * **Current Ch**: `Right` (Ch 2)
    * **Ref Resistor**: Enter the measured value of the resistor used (e.g., `10.0`). **If this value is not correct, correct measurement is not possible.**

### 2. Calibration (Recommended)

Cancel the resistance of cables, etc. for more accurate measurement.

1. **Open Cal**: Remove the speaker and run `Run Open Cal` with the cables open.
2. **Short Cal**: Short the clips where the speaker is connected and run `Run Short Cal`.
3. **Load Cal** (Optional): If you have a resistor with a known accurate value (e.g., a 10Ω or 100Ω precision resistor), connect it and run `Run Load Cal` to further improve measurement accuracy.
4. After calibration, connect the speaker.

### 3. Sweep Measurement

Perform a sweep measurement to see changes by frequency.

1. Select the **Frequency Response (FRA)** tab.
2. **Frequency Range**: Set according to the characteristics of the speaker (e.g., `20Hz` to `20000Hz`).
3. **Points**: Resolution. Set to about `100` to `400`.
4. **Start Sweep** click.

## Interpretation of Results

The impedance curve is displayed on the graph (Bode Plot).

### Points to Watch

1. **Sharp Peak in Low Frequency ($f_0$)**:
    * A "mountain" where impedance rises sharply can be seen around 50Hz to 100Hz (for woofers) or several hundred Hz to 1kHz (for tweeters).
    * The frequency at the top of this mountain is **$f_0$ (Lowest Resonant Frequency)**. It indicates the basic low-frequency reproduction capability of the speaker without a box.

2. **Bottom Impedance (Nominal Impedance)**:
    * Impedance is lowest at a frequency slightly higher than $f_0$ (around 200Hz to 500Hz).
    * This is close to the catalog spec (nominal impedance) such as "4Ω" or "8Ω". It is slightly higher than the DC resistance (DCR).

3. **Rise in High Frequency**:
    * The gradual increase in impedance as the frequency gets higher is due to the **inductance component ($L$)** of the voice coil.

### Troubleshooting

* **Graph is jagged**: Poor contact or the influence of external noise is suspected. Try increasing the volume slightly or increasing the Average setting.
* **Values are strange**: Check if the `Ref Resistor` setting value matches the actual resistance value.

---

If you can perform this measurement, you can take the first step in full-scale acoustic design, such as designing crossover networks for DIY speakers and adjusting bass reflex ports (confirming the phenomenon where the mountain splits into two in impedance measurement with the speaker in a box).
