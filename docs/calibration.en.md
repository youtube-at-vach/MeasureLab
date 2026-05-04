# Calibration

MeasureLab features the ability to calibrate the input and output voltages of your audio interface, as well as the sound pressure level (SPL) of microphones and speakers.
This allows you to associate digital values (dBFS) with physical units (V, dBu, dBV, dB SPL).

## ☕ Coffee Break: What is Calibration?

In the world of digital audio, signal magnitude is typically expressed in **dBFS (Decibels relative to Full Scale)**. This is a relative value where the absolute maximum representable digital limit (the ceiling) is set to 0 dBFS.

However, knowing only this can be slightly inconvenient.
For example, if someone tells you a cup is "100% full (0 dBFS)," you still don't know the actual volume of water (voltage or sound pressure) unless you know if it's a **tiny espresso cup** or a **large bucket**.
Depending on the performance of the audio interface used and the gain knob settings, the "size of this cup" changes.

Calibration is the process of measuring this relationship—"how many Volts (or Pascals) in the real world corresponds to 100% in the digital world"—and informing the software.
By doing this, you can read waveforms directly in actual "Voltage (V)" or "Sound Pressure (dB SPL)" instead of just a "percentage (dBFS)."

## Relationship between dBFS / dBV / dBu 📏

MeasureLab supports the following units. Let's introduce them with a bit of historical context.

* **dBFS**: Relative level to digital full scale. Always available without calibration. The maximum value is 0 dBFS.
* **dBV**: Unit of voltage where 1 Vrms is the reference (0 dBV). ($20 \log_{10}(V / 1.0)$) This is a standard commonly used in consumer (home) audio equipment.
* **dBu**: Unit of voltage where 0.775 Vrms is the reference (0 dBu). ($20 \log_{10}(V / 0.775)$)
  💡 **Why the odd number 0.775 V?**
  This actually originates from old telephone line standards. The voltage required to deliver 1 milliwatt of power into a 600-ohm resistor is approximately 0.775 V. Even today, this unit remains the standard in professional audio equipment.
* **dB SPL**: Sound Pressure Level. A unit of sound pressure where the threshold of human hearing—an extremely tiny pressure of $20 \mu Pa$—is set as 0 dB SPL. It becomes available after performing microphone input calibration (SPL calibration).

To perform displays and measurements in these units, **Input Sensitivity** and **Output Gain** calibration are required.

## Equipment for the Adventure 🎒

Required equipment varies depending on the items being calibrated.

* **Input/Output Voltage Calibration**:
    * **Voltmeter (Multimeter)**: A **TrueRMS** compatible one is best. Cheaper meters may produce errors for non-sine waves or may not be able to read small voltages.
        * 💡 **Knowledge Boost: What is TrueRMS?**<br>Cheap multimeters measure the "average" of a wave and calculate assuming it's a perfect sine wave. However, with complex waveforms like music or noise, this calculation gets thrown off. TrueRMS is a smart multimeter that accurately calculates "how much actual power there is (root mean square)" regardless of the wave's shape!
    * **Audio Cables**: Required to connect the output and input of the audio interface or to apply the voltmeter.
* **Sound Pressure Level (SPL) Calibration**:
    * **Speaker**: Required to play pink noise.
    * **Sound Level Meter**: Required to measure the reference sound pressure. Smartphone apps can be used as a substitute to some extent, but a dedicated measurement instrument is preferred.
    * Measurement Microphone: The microphone to be calibrated.

## Basic Procedure

All settings are performed from the **Calibration** tab of the **Settings** widget found on the widget screen.

### Calibration of Input Sensitivity

Ensures that the voltage level of external input signals can be measured correctly.

1. Open the **Settings** widget and select the **Calibration** tab.
2. Press the **[Wizard]** button next to Input Sensitivity.
3. **Step 1**: Connect a signal source with a known voltage (such as an oscillator or another player outputting a known voltage) to the input terminal.
    * Alternatively, you can use MeasureLab's Signal Generator (if output-calibrated) and loop it back into the input, but using an external reference voltage is more reliable initially.
4. **Step 2**: Press **[Start Measurement]** and measure the input level. Wait for the Input Level display to stabilize.
5. **Step 3**: Enter the voltage value of the signal being input. You can choose from Vrms, mVrms, dBV, or dBu. It is recommended to measure the voltage with a voltmeter at that time and enter it.
6. **Step 4**: Press **[Calculate & Save]** to calculate and save the voltage equivalent of 1.0 FS (0 dBFS).

### Calibration of Output Gain

Allows MeasureLab to output specific voltages.

1. In the **Calibration** tab of the **Settings** widget, press the **[Wizard]** button for Output Gain.
2. **Step 1**: Connect a voltmeter (multimeter) to the output terminal of the audio interface.
3. **Step 2**: Set the test signal frequency (usually 1000 Hz) and level (e.g., -12 dBFS). A larger volume that doesn't clip is suitable.
4. **Step 3**: Press **[Start Tone]** to output the signal.
5. **Step 4**: Measure the voltage at the output terminal with the voltmeter and enter that value.
6. **Step 5**: Press **[Calculate & Save]** to save.

### Calibration of Sound Pressure Level (SPL)

Enables microphone input to be displayed as Sound Pressure Level (dB SPL).

1. Set up the measurement microphone and speaker.
2. In the **Calibration** tab of the **Settings** widget, press the **[Wizard]** button for SPL Offset.
3. Follow the instructions on the screen to configure settings:
    * **Test Signal Band**: Choose according to your speaker's reproduction capability (usually Speaker 500-2000Hz).
    * **Output Level**: Set the volume of the test signal (band-limited pink noise).
    * **Averaging Time**: The averaging time for the measurement.
4. Press **[Start]** to play the noise from the speaker.
5. Place the microphone of the Sound Level Meter very close to (at the same position as) the measurement microphone, and read the dB SPL value shown on the sound level meter.
6. Enter the sound level meter value in the **Measured SPL** field.
7. Press **[Calculate & Save]**. This records the difference (offset) between the input voltage level and the actual sound pressure.

## Calibration Profiles

Calibration settings (Input Sensitivity, Output Gain, SPL Offset) can be saved as named **profiles**.
This allows you to switch settings for different combinations of microphones and audio interfaces.

* **Saved Items**:
    * Device Name
    * Host API (ASIO, WASAPI, etc.)
    * Input Sensitivity
    * Output Gain
    * SPL Offset

In particular, even with the same audio interface, different driver types (Host API) (e.g., WASAPI vs. ASIO) may have different input/output behavior or scaling.
MeasureLab now records **Host API** information in profiles, and when you select a profile in the settings, it is displayed as `Device: [Device Name] ([Host API])`.
This helps distinguish which driver setting the calibration was performed with.

## Cases Where Re-calibration is Necessary

Even if you have calibrated once, re-calibration is required in the following cases:

* **When changing the audio interface**: Because the specified levels for input and output differ.
* **When moving hardware gain knobs**: Moving the Input Gain or Output Volume knobs on the interface itself changes the relationship between voltage and digital values. We recommend fixing the knob positions (e.g., with tape) when performing measurements and calibrating in that state.
* **When changing microphones or speakers**: Because microphone sensitivity or speaker efficiency changes, SPL calibration needs to be redone.
