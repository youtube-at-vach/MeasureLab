# Quickstart

This guide explains the flow from setting up MeasureLab to performing your first measurement.

---

## Hardware Preparation (Loopback)

Before starting the measurement, let's prepare to confirm **"whether the sound is being recorded correctly."**

1. **Cable Connection**: Connect the **Output** and **Input** of the audio interface directly with a cable (this is called a loopback connection).
2. **Equipment Protection**: Initially, set the output volume (OUT) and input gain (IN) of the audio interface to the minimum.

!!! note
    By using this loopback connection, you can perform a test to "analyze the sound you output yourself" without using external equipment. This is the basis of all measurements.

---

## Starting the Software

MeasureLab works on Windows and Linux.
Please download the latest version for your OS from the [Releases](https://github.com/vach/MeasureLab/releases) page.

### For Windows

1. Download `MeasureLab-<version>-windows-x64-onefile.zip` (or `onedir.zip`).
2. Extract the ZIP file.
3. Double-click `MeasureLab.exe` in the folder to run it.

### For Linux

1. Download `MeasureLab-<version>-linux-x86_64.AppImage`.
2. Grant execution permission to the file.

   ```bash
   chmod +x MeasureLab-*-linux-x86_64.AppImage
   ```

3. Run it directly.

   ```bash
   ./MeasureLab-*-linux-x86_64.AppImage
   ```

!!! important
    **Note for the first launch: FFT Optimization (WISDOM)**

    On the first launch, preparation (WISDOM generation) is performed to speed up measurement calculations.
    - **The screen may appear to be frozen for several tens of seconds, but it is not a malfunction.** Heavy calculations are being performed in the background.
    - From the next time, the cache will be used, and it will start instantly.

---

## UI Display Settings

In the Settings widget, you can change the UI language and color scheme to make it easier to use.

### Language Settings

It may be in English by default.
Select **Japanese** from the **Languages** combo box to switch the interface to Japanese.

### Theme Settings

You can change the color scheme according to your environment and preference.
Please select from the **Themes** combo box.

* **Dark**: Dark mode that is easy on the eyes even in dark places (recommended).
* **Light**: Bright display.
* **System**: Follows the OS settings.

---

## Sound Device Settings

After starting, first configure the audio input/output settings.
Open the **Settings** widget (gear icon) from the left menu.

### For Windows

Select the audio interface you want to use from the device list.

* **ASIO**: If there is a dedicated driver for the audio interface, selecting this is the most stable.
* **WASAPI**: Recommended setting if there is no dedicated driver or when using standard Windows functions.
* **MME / DirectSound**: Large latency, not very suitable for measurement.

### For Linux

When performing high-precision measurements in a Linux environment, we strongly recommend using **JACK** or **PipeWire**.

1. Select the `jack` or `pipewire` device.
2. Please turn the **"Jack/Pipewire mode"** checkbox **ON**.
   * If you forget this, the measurement data may become intermittent, and accurate analysis may not be possible.

### Recommendations for Input/Output and Sampling Settings

* **Input/Output Channels**
    * Basically, leave it at the default and select **Stereo (2ch)**.
* **Sampling Rate**
    * As long as your PC specs allow, we recommend selecting a high rate (high-resolution setting) such as **192kHz**.
* **Buffer Size / Buffer Optimization**
    * **We strongly recommend setting it to "Long (STABLE or higher)".**
    * Since this software is for "measurement," prioritize data stability over latency.

---

## First Measurement (Hello Loopback!)

After the settings are finished, let's actually output sound and look at the graph.

### Step A: Output a Signal

1. Open **Signal Generator** from the left menu.
2. Set `Frequency` to `1000 Hz` (1kHz).
3. Press the `Output` button and gradually increase the interface volume.

### Step B: View on Graph

1. Open **Spectrum Analyzer** from the left menu.
2. Increase the input gain of the interface and confirm that a **"sharp peak at 1000Hz"** appears on the screen.
3. **If you see the peak, it's a success!** Your PC has now started to function as a proper measurement instrument.

---

## Next Steps

Once you are familiar with the basic operations, proceed to more detailed guides.

* **To measure accurate voltage or SPL** → [Calibration](calibration.en.md)
* **If you are unsure which tool to use** → [Widget Guide](widget_guide.md)
* **To know how to measure in practice** → [Measurement Recipes](measurement_recipes/index.md)
* **To see the waveform directly** → [Oscilloscope](widgets/oscilloscope.md)
