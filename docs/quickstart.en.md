# Quickstart

This guide explains the flow from setting up MeasureLab to performing your first measurement.

---

## Hardware Preparation (Loopback)

Before starting the measurement, let's prepare to confirm **"whether the sound is being recorded correctly."**

1. **Cable Connection**: Connect the **Output** and **Input** of your audio interface directly with a cable. This is called a "loopback connection."
2. **Equipment Protection**: To prevent loud noises from suddenly damaging your equipment, initially set the output volume (OUT) and input gain (IN) of the audio interface to "minimum (zero)."

!!! note
    By using this loopback connection, you can test "whether the PC can correctly receive the sound it outputted itself" without connecting any other external equipment. This is a very important step that forms the basis of all future measurements.

### ☕ Coffee Break: Why start with a loopback?

Why do we connect the "output" directly to the "input" first, instead of immediately connecting the thing we want to measure (like an amp or a microphone)?
This is because it's a "health check for the measurement instrument (your PC and audio interface) itself"!

For example, before looking at the stars with an astronomical telescope, you first check if the lens is cloudy and if the focus dial works properly, right? In the same way, loopback is a very important, and somewhat interesting, "first ritual" to confirm whether you can accurately pick up the sound you outputted yourself.

---

## Starting the Software

MeasureLab works on Windows and Linux.
Please download the latest version for your OS from the [Releases](https://github.com/youtube-at-vach/MeasureLab/releases) page.

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

### For macOS (Apple Silicon / Intel)

1. Download `MeasureLab-<version>-macos-arm64.dmg` for Apple Silicon or `MeasureLab-<version>-macos-x64.dmg` for Intel Macs.
2. **Gatekeeper Bypass**:
   - On the first launch, you may see a message saying the application "cannot be opened because the developer cannot be verified."
   - To open it, **"Right-click (or Control + click) the app and select 'Open'."**
   - A confirmation dialog will appear. Click **"Open"** again to start the application.
3. **If the "Open" option still doesn't appear**:
   - Go to **System Settings > Privacy & Security**. Scroll down to find the message stating "MeasureLab.app was blocked..." and click **"Open Anyway"**.
   - Alternatively, manually remove the quarantine flag via Terminal: `xattr -d com.apple.quarantine /path/to/MeasureLab.app` (You can drag the app icon into the terminal window to paste its path).

!!! important
    **Note for the first launch: FFT Optimization ([WISDOM](glossary.en.md#fft-wisdom-initial-optimization))**

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

- **Dark**: Dark mode that is easy on the eyes even in dark places (recommended).
- **Light**: Bright display.
- **System**: Follows the OS settings.

---

## Sound Device Settings

After starting, first configure the audio input/output settings.
Open the **Settings** widget (gear icon) from the left menu.

### For Windows

Select the audio interface you want to use from the device list.

- **ASIO**: If there is a dedicated driver for the audio interface, selecting this is the most stable.
- **WASAPI**: Recommended setting if there is no dedicated driver or when using standard Windows functions.
- **MME / DirectSound**: Large latency, not very suitable for measurement.

### For Linux

When performing high-precision measurements in a Linux environment, we strongly recommend using **JACK** or **PipeWire**.

1. Select the `jack` or `pipewire` device.
2. Please turn the **"Jack/Pipewire mode"** checkbox **ON**.
   - If you forget this, the measurement data may become intermittent, and accurate analysis may not be possible.

### Recommendations for Input/Output and Sampling Settings

### ☕ Knowledge Boost: Why do we use 192kHz?

You might wonder, "Humans can only hear up to 20kHz, so isn't 48kHz (like in movies) enough?"
For just "listening" to music, you are absolutely right. However, for "measuring," a higher sampling rate acts like a **"high-speed camera for sound."**
For example, when measuring extremely high-frequency noise or analyzing the sharp attack of an impulse response, capturing the waveform as finely as possible gives us more accurate graphs. Since we are turning the PC into a measuring instrument, let's use the highest performance it can offer!

- **Input/Output Channels**
    - Basically, leave it at the default and select **Stereo (2ch)**.
- **Sampling Rate**
    - This determines the "fineness" or resolution of the recorded sound. The larger the number, the higher the definition. As long as your PC specs allow, we recommend selecting a high rate (high-resolution setting) such as **192kHz**.
- **Buffer Size / Buffer Optimization**
    - This is the size of the "bucket" that temporarily stores audio data.
    - **We strongly recommend setting it to "Long (STABLE or higher)".**
    - In music production or gaming, people make this bucket small to avoid "latency" (audio delay). However, MeasureLab is for "measurement." Even if the sound is slightly delayed, please prioritize stable, uninterrupted data processing (data stability) above all else.

!!! tip
    **Using Dithering**

    When outputting at low bit depths (e.g., 16-bit) or measuring extremely low distortion (THD+N), enable **Dithering** in the **Audio** tab of the **Settings**. This converts quantization distortion into noise, improving the linearity of low-level signals.

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

## No Audio Interface? (Virtual Mode)

If you don't have an audio interface or want to analyze existing audio files without any hardware, you can use the **Virtual / Offline Mode**.

1. Go to **Settings** (gear icon) > **Audio** tab > **Driver** section.
2. Check the **Virtual / Offline Mode** option.
3. Use the **Simulation Rate** to set your desired sampling rate.
    - When analyzing high-quality audio files (e.g., 24-bit/192kHz), setting the Simulation Rate to match the file's rate ensures analysis without degradation from downsampling.

In this mode, you can load audio files into the **Player** widget or generate signals internally, and analyzed results will appear in the analyzer widgets just like real hardware.

---

## Next Steps

Once you are familiar with the basic operations, proceed to more detailed guides.

- **To measure accurate voltage or SPL** → [Calibration](calibration.en.md)
- **If you are unsure which tool to use** → [Widget Guide](widget_guide.md)
- **To know how to measure in practice** → [Measurement Recipes](measurement_recipes/index.md)
- **To see the waveform directly** → [Oscilloscope](widgets/oscilloscope.md)
