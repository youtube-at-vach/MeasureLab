# Distortion Analyzer

![Distortion Analyzer](../assets/widgets/distortion_analyzer.png)

## Overview

This is the most fundamental tool for measuring the "performance" of audio equipment numerically.
It measures how accurately amplifiers, DACs, etc., are outputting the original signal (how much they are distorted).
It is an important measurement tool to grasp the basic performance indicators of the equipment.

## Common Features

This widget supports common features of the Detachable Wrapper. Please refer to the [Detachable Wrapper](detachable_wrapper.en.md) documentation for details.

## Meaning of Key Indicators

This tool measures the following values:

* **THD (Total Harmonic Distortion)**
    * Represents "how many extra overtones (harmonics) were mixed in" relative to a pure signal.
    * The smaller the value, the cleaner and more faithful the sound is to the original.
* **THD+N (Total Harmonic Distortion + Noise)**
    * Total level of contamination, including not only distortion but also noise like "hiss".
    * Most commonly used as a realistic performance indicator.
* **SINAD (Signal-to-Noise and Distortion ratio)**
    * THD+N expressed in dB as a reciprocal.
    * The larger the value, the higher the performance. (e.g., SINAD 100dB corresponds to THD+N 0.001%)
* **IMD (Intermodulation Distortion)**
    * Measures the muddiness that occurs when two different sounds are mixed. This indicator shows how clearly the equipment can play "complex music" where many sounds overlap, like an orchestra.

## Operation

### Starting and Stopping Measurements

1. Select the signal used for measurement (usually a Sine Wave) in the **Signal Generator**.
2. Press the **Start Measurement** button to output the signal and begin analysis.
3. Numerical values (such as THD+N) are displayed in real-time.
4. Stop with **Stop Measurement**.

### Measurement Modes (Mode)

Frequency Sweep and Amplitude Sweep retain single-tone THD analysis. Select **IMD amplitude sweep** for the separate two-tone procedure described below.

#### Real-time

Continues to measure the performance at the current moment.

* **Use Case**: Suitable for adjusting equipment or seeing changes in distortion due to volume position.
* **Meters**: Numerical values are displayed prominently on the left. Percentage values like THD+N automatically adjust their decimal precision based on magnitude (Dynamic Precision). When the measurement reaches its limit (e.g., THD+N is lower than THD), "LO" may be displayed next to the value.
    * Pressing the **Show Detailed** button displays the following additional information:
    * **Input level**: Level of the input signal (dBFS).
    * **Window**: The window function being used (usually Blackman-Harris).
    * **ENOB (Effective Number of Bits)**: Effective bit depth calculated from SINAD (calculated only when the input level is sufficiently high).
* **Spectrum**: In the graph tab, you can visually inspect distortion components (peaks at 2x and 3x the fundamental frequency).
* **Harmonics**: You can check the breakdown of distortion components (whether there is more 2nd-order or 3rd-order distortion) with a bar graph.

#### Frequency Sweep

Measures by continuously changing the frequency from low to high tones, like sweeping your fingers across a piano keyboard from left to right.

For both frequency and amplitude sweeps, an audio capture timeout stops the sweep and records a warning in the log. Previously completed points remain available; the interrupted point is not added, including when only part of its averaging has completed. Cancelling a sweep also discards the incomplete point.

* **Use Case**: Used to find the equipment's "weak spots" across different frequencies, such as "it's good at bass but distorts at high frequencies."
* **Settings**: Set Start (starting frequency), End (ending frequency), and Steps (number of measurement points).
* **Sweep Results**: Results are plotted on a graph. The Y-axis unit can be selected from `dB` or `Percent (%)`, and when displayed in percent, it automatically scales to an approximately logarithmic view.

#### Amplitude Sweep

Measures by changing the volume from small to large.

* **Use Case**: Ideal for finding the maximum output of an amplifier (how far you can raise it before it starts to distort = clipping point).
* **Settings**: Set Start (starting volume) and End (ending volume) in dBFS units.
* **Sweep Results**: Results are plotted on a graph. The Y-axis unit can be selected from `dB` or `Percent (%)`, and when displayed in percent, it automatically scales to an approximately logarithmic view.

## Settings

### Generator

Settings for the test signal used for measurement.

* **Signal Generator**:
    * **Sine Wave**: A basic sine wave. Used for THD measurement.
    * **SMPTE / CCIF**: Special pair signals for IMD measurement.
    * **AES17 Dynamic Range (-60dBFS)**: Special signal and measurement mode for testing Dynamic Range using a standard 1kHz tone at -60dBFS.
* **Frequency**: Frequency of the sine wave. Standard is `1000 Hz`.
* **Bin Center**: When checked, automatically snaps the frequency to the nearest FFT bin center based on the current FFT settings (buffer size) to prevent spectral leakage. Useful for accurate distortion measurements.
* **Actual Freq**: Displays the exact frequency being generated when the Bin Center feature is enabled.
* **Amplitude**: Strength of the signal. The following units can be selected:
    * **dBFS**: Relative to digital full scale.
    * **dBV**: Relative to 1Vrms.
    * **dBu**: Relative to 0.775Vrms.
    * **Vrms**: Voltage RMS.
    * When measuring an amplifier, do not set it to maximum volume immediately; raise it gradually from a low value.
* **Signal Generator Mode**: Select `Off (External Source)` when using an external CD player or similar as the sound source.

### Settings

* **Filter**
    * **None (20Hz-20kHz)**: Standard bandwidth.
    * **AES17 20kHz Standard LP**: Standard 20kHz low-pass filter defined by AES17.
    * **A-Weighting**: Human hearing perception curve weighting.
    * **C-Weighting**: Flatter human hearing perception curve weighting.

* **Input Ch / Output Ch**
    * Selects the audio channel (Left or Right) to use for measurement.

* **Averaging**
    * **Avg Count**: Sets how many measurements to average to stabilize the values.
    * Increasing the value stabilizes the display, but reaction to changes becomes slower.

## Usage Examples

### Checking the Maximum Power of an Amplifier

Investigate "up to how many watts" your amplifier can output cleanly.

1. Set **Mode** to `Real-time`.
2. Start **Amplitude** from a low value and gradually raise it.
3. Look at the **THD+N** value. It usually hovers around 0.01% to 0.1%.
4. The moment a certain volume is exceeded, the value jumps sharply to `1.0%` or `10%`. This is the "clipping (limit)".
5. By reading the voltage just before that, you can calculate the effective output (W).

### Seeing the Secret of Tube Amplifier Tone

Investigate the quality of distortion in tube amplifiers or effectors.

1. Connect the device and output sound.
2. Open the **Harmonics** tab.
3. Look at the bar graph.
    * **2nd (2nd order)** is high: Often described as a warm, pleasing distortion.
    * **3rd (3rd order)** is high: A hard, edgy distortion.

## IMD amplitude sweep

Select **IMD amplitude sweep** in Mode and choose a fixed method in Sweep:

| Method | Stimulus | Main ratio |
| --- | --- | --- |
| SMPTE stimulus / FFT sideband IMD | 60 Hz + 7000 Hz, 4:1 peak ratio | RSS of six sidebands f2 ± n·f1 (n=1–3), divided by f2 RMS |
| DIN stimulus / FFT sideband IMD | 250 Hz + 8000 Hz, 4:1 | Same six-sideband ratio |
| CCIF stimulus / d2 | 19000 Hz + 20000 Hz, 1:1 | 1000 Hz RMS divided by mean carrier RMS |

These are stimulus presets, not a declaration of DIN/SMPTE certification.
The FFT sideband method includes band noise and FM/PM contributions; it is not
an AM-demodulation compliance measurement. CCIF stores 18/21 kHz d3 separately
and does not add it to d2. Legacy real-time IMD remains unchanged: FFT peaks,
with CCIF using RSS(d2+d3) divided by the sum of carrier amplitudes.

1. Stop other signal generators and select input/output channels in Settings.
   Enable output and unmute the engine. Check the DUT connection and gain.
2. Set start/end levels (default −40 to −3 dBFS, 20 equally spaced points).
   Ascending and descending sweeps are supported; equal endpoints are rejected.
3. Use 500 ms settling, 500 ms records and four power averages initially.
   Settling can be 100–30000 ms, records 200–2000 ms in 100 ms increments,
   and averages 1–32. The output fade is at least 20 ms; choose a longer time
   when your setup requires it. Settling begins after the fade completes.
4. Start Measurement. Conditions are locked during the run. Cancel interrupts
   settling or acquisition without freezing the interface. Save or compare
   completed points after the procedure has stopped.

The X axis is **dBFS (sum peak)**, not single-sine Vrms or watts.
For level L, the peak sum is A=10^(L/20), with A1=A·r/(r+1) and A2=A/(r+1).
Levels must be −100 to 0 dBFS, with 2–1000 points. Continuous phase and output
fades limit abrupt transitions; they cannot guarantee freedom from analog
saturation or clipping after mixing with another source.

Each record removes DC and uses a periodic four-term Blackman–Harris window.
N=ceil(sample rate × record seconds), df=sample rate/N, and each component
integrates bins within ±(4·df+0.001·f) Hz. Component RMS power is
2·sum(abs(FFT bins)^2)/(N·sum(window^2)); records are averaged in linear power.
Records are consecutive and non-overlapping. Weighting, AES17, frequency
correction and the real-time average count do not apply.
Both carriers must exceed 1e-6 RMS FS, stand at least 20 dB above the local
median bin noise and have a peak near the expected frequency. No noise is
subtracted, and no hardware detection floor is guaranteed.

All component bands must fit below Nyquist without overlap. CCIF at 32 kHz
is rejected; 44.1 kHz is permitted with a near-Nyquist warning; 48 kHz is
permitted without that numerical warning. The warning starts at 90% of
Nyquist and is a product choice. Neither 44.1 nor 48 kHz guarantees the
DAC/ADC high-frequency response or a calibrated measurement bandwidth.

A missing carrier or an audio data gap invalidates its point. Input samples
at or above 1−1e-7 FS, observed output overload, non-finite input, timeout,
stream loss, exceptions or a change in acquisition conditions stop the run.
Previously completed points retain their original conditions. Cancel marks
an unfinished point invalid. Invalid points are gaps, never connected across
in plots or comparison. Warnings, quality and end status remain in the result.
Reset clears this result; a new run creates an independent snapshot. Existing
comparison copies are unchanged.

**Export** writes JSON (`measurelab.imd_sweep`, schema version 1) or
UTF-8 CSV. JSON is the canonical result with run/step identifiers, times,
acquisition conditions, sample intervals, validity, levels and components.
CSV has one row per step/component (including `aggregate`), with complete run
conditions in `run_metadata_json`. Missing values are null in JSON and blank
in CSV; NaN/Infinity are never saved. Zero ratio is stored as zero with null
dB and `zero_numerator=true`; the −160 dB plot floor is a display convention.
Incomplete runs and rejected starts can be saved for diagnosis. A save error
keeps the result available for retry.

Input component levels use **dBFS_sine_rms** (0 dBFS = 1/√2 RMS FS).
With explicit input sensitivity calibration, Vrms=RMS_FS × Vpeak_per_FS and
dBV are also saved. Without calibration, V/dBV are null and relative results
remain usable with a warning. Comparison uses captured dBFS peak-sum levels,
method, reference and end state, split into contiguous valid sections.

Expand Acquisition to change record length and averaging. Hover over the method, status, or readout for details. Click a plot point to inspect its result.
