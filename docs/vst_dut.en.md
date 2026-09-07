# Using VST3 as a Device Under Test (DUT)

You can input MeasureLab test signals into a VST3 effect and observe its output using existing measurement instruments.
Insert it into the virtual device under "Settings → Audio → Virtual / Offline Mode".
No physical audio device or remote audio connection is required.

## Installation

When running from source, install the arbitrary VST host dependencies in addition to the standard dependencies.

```bash
./.venv/bin/python -m pip install -r requirements-vst.txt
```

You can also use `pip install '.[vst]'` if installing as a package.
Traditional MeasureLab features remain available even without these additional dependencies.
Pre-built applications may not include these extra dependencies.

## Operation

1. Stop measurements and enable "Virtual Audio" in the settings.
2. Set the sample rate in the same tab. Select the block size in the audio settings.
3. Open "VST3 Device Under Test (DUT)" and select a plugin from "Installed VST3".
   Standard folders are automatically scanned. You can filter with the search bar, and update using "Rescan" after installing new plugins.
   Expand "Manual plugin selection" to specify paths outside standard folders or specific plugin names within a bundle.
4. Click "Load VST3". After loading is complete, the plugin's native control panel will automatically open in a separate window.
   You can configure it using the same knobs and presets as in a DAW. The control panel can remain open and be used during measurements.
   Since you are directly editing the loaded plugin used for measurement, changed settings are applied immediately to the measurement.
   To close only the panel, use the window's close button or click "Close plugin editor".
   To show it again, click "Open plugin editor". You can open and close it during measurements as well.
5. To change routing, expand "Routing" and select Mono/Stereo, the input source for the DUT, and the return destination for the left/right measurement inputs.
6. Close the DUT startup dialog and use the Signal Generator, FFT, Oscilloscope, Network Analyzer, etc.
   Since the plugin's control panel remains available, you can adjust knobs while viewing the measurement results.

VST3 settings are configured using the plugin's native control panel. A generic parameter screen is not provided.
An error is indicated for plugins without a native panel or in environments where the editor cannot be displayed.

Changes made in the native panel are reflected in the audio even during measurement. For measurements comparing fixed settings, change the settings and then remeasure.
Operations for routing, bypassing, and loading/unloading should be performed while measurement is stopped.
When unloading, replacing with another plugin, or closing the application, the control panel is also closed.
Bypass passes the DUT input directly to the DUT output, maintaining the routing.
Unloading returns the system to a normal virtual loopback.
Plugins are not automatically reloaded, and parameter settings are not persistently saved, so they must be reconfigured after restarting the application.

### Example Screenshots

A screenshot showing the expanded routing in Japanese, and the startup screen in English with the dark theme.
Manual selection and routing are collapsed by default.

![VST3 routing screen in Japanese](assets/vst_dut/routing-ja.png)

![VST3 startup screen in dark theme](assets/vst_dut/launcher-dark.png)

## Automatically Scanned Folders

User folders and shared folders are scanned, including manufacturer subfolders.

| OS | Search Locations (in order) |
| --- | --- |
| Windows | `%LOCALAPPDATA%\Programs\Common\VST3`, `%CommonProgramFiles%\VST3` (usually `C:\Program Files\Common Files\VST3`) |
| macOS | `~/Library/Audio/Plug-Ins/VST3`, `/Library/Audio/Plug-Ins/VST3`, `/Network/Library/Audio/Plug-Ins/VST3` |
| Linux | `~/.vst3`, `/usr/lib64/vst3`, `/usr/lib/vst3`, `/usr/local/lib64/vst3`, `/usr/local/lib/vst3` |

Search locations reference the [Steinberg standard placement specifications](https://steinbergmedia.github.io/vst3_dev_portal/pages/Technical%2BDocumentation/Locations%2BFormat/Plugin%2BLocations.html).
On Windows, the common folder corresponding to the running process is used, and folders with different bitness are not additionally scanned.
Other DAW-specific folders are not scanned.

Scanning runs in the background and does not execute plugin code.
The list displays detected files/bundles. Compatibility, authentication, and effect support are verified upon loading, so mere presence in the list does not guarantee usability. Bundles containing multiple plugins require the specific name to be entered manually.
Different files with the same name are distinguished by their folder names, and duplicates referencing the same entity via symbolic links are excluded.
Non-existent folders are ignored, and inaccessible folders are reported in the scan results and tooltips.

## Routing Examples

To observe stereo inputs and outputs directly:

```text
MeasureLab Output L → DUT Input 1 → DUT Output 1 → Measurement Input L
MeasureLab Output R → DUT Input 2 → DUT Output 2 → Measurement Input R
```

To compare input and output with the Network Analyzer:

```text
MeasureLab Output L ─┬→ DUT Input 1 → DUT Output 1 → Measurement Input L (Measurement)
                     └─────────────────────────────→ Measurement Input R (Reference)
```

Set DUT Input 1 to "Output L", Measurement Input L to "DUT Output 1", and Measurement Input R to "Output L (reference)".
For stereo effects, select "Output L", "Output R", or "Silence" for DUT Input 2 depending on your purpose.
Ensure the measurement/reference channels on the instrument side match this routing.
If the output channel setting is mono, a single logical output is duplicated to both L/R in the routing.
If multiple signal generators are active, their mix becomes the stimulus signal for the DUT.

## Timing, Precision, and Compatibility

- Using the existing callback path of the virtual device, the DUT output and reference signal are passed to the instruments in the next block.
- Internal plugin states and the control panel are preserved when restarting the measurement stream with the same audio settings between blocks.
  Starting and stopping the signal generator does not cause the plugin to reload or the panel to reopen.
  Since the plugin's audio processing is also stopped while the measurement stream is stopped, internal states such as reverb or delay are carried over upon restart.
  Changing routing or bypass, or changing sample rate/block size resets the internal state. Parameter values are preserved.
- Samples buffered by the host at startup are padded with silence before the returned audio to maintain the timeline.
  The number of padded samples is displayed in the DUT dialog. Because this includes plugin-specific latency, calibrate for latency on the instrument side if necessary. This value alone does not represent the overall reported latency of the VST.
- Input and output to Pedalboard are float32. Even with MeasureLab's 64-bit setting, DUT processing operates at float32.
  Amplitude clipping, additional dither, and normalization are not applied.
- Compatible VST3 effects matching the OS and CPU architecture of the running Python on macOS/Windows/Linux are supported.
  VST2, MIDI instruments, sidechains, and multi-channel buses are not supported.
  Plugins that do not accept mono/stereo configurations will result in an error.
- Plugins are loaded in a separate process, with the main thread handling the native panel and a dedicated thread handling audio processing.
  Panel exit notifications and audio responses use separate communication paths. Loading times out at 30 seconds, and processing responses at 1 second.
  The panel can be displayed without time limits, and a 5-second timeout applies to the closing operation.
  When resetting a plugin due to changes in audio settings or routing, the panel is temporarily closed, processed in the main thread, and automatically redisplayed.
  If stops, crashes, or invalid outputs are detected, the entire measurement input is silenced, and a DUT error is displayed.
  It does not automatically revert to the normal loopback. Reloading is required to recover.
- The host is timer-driven and does not guarantee strict real-time operation or compatibility with any arbitrary plugin.
  Plugins with authentication screens or similar features that require GUI interaction may not be usable.

While a DUT is selected, the virtual mode demo generation for the Nonlinear Analyzer is not used, and the actual DUT output is measured instead.
No new analysis models or VST reproduction features have been added.

Please refer to the [Pedalboard official documentation](https://spotify.github.io/pedalboard/reference/pedalboard.html) for details on the host API and compatibility.
For Pedalboard's license, refer to their [official license information](https://spotify.github.io/pedalboard/license.html).

## Verification

Standard tests verify known gains, routing, reference signals, silencing, timeouts, and GUI operations.
Actual integration tests with VST3 are run in an environment where a desktop display is available, specifying the path to a compatible plugin for each OS.

```bash
MEASURELAB_TEST_VST3=/path/to/Effect.vst3 ./.venv/bin/python -m pytest -q tests/logic_verification/core/test_vst_dut.py
```

Integration tests assume an effect initially configured to pass audio, verifying native panel display/redisplay/closing, multiple rates/block sizes, and virtual audio paths.
