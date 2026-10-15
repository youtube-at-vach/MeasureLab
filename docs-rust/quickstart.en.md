# Quick start

## Build from source

Use a checkout containing the Rust edition and Rust 1.95 or later. The Rust edition is on `main`. macOS needs Xcode Command Line Tools; Linux needs ALSA, X11 and Wayland development libraries; Windows needs MSVC and Visual Studio C++ Build Tools. See `guide/rust/SETUP.md` in the repository for details.

Run from the repository root:

```sh
cargo run --release --locked
```

With the local macOS/Linux setup, `./scripts/cargo.sh run --release --locked` also works. Normal startup leaves acquisition stopped.

## First measurement without hardware

1. Select **Software Loopback** under **I/O / Input**. It is available in normal builds and does not drive a physical output.
2. Use **Back to instruments**, open **Scope**, choose **Pair with… / Spectrum**, then press **Start input**.
3. Click a pane to select its details. CH, time/amplitude scales, Autoset and cursors stay in the instrument; FFT/window/averaging settings are in the selected details. Start with the default 8,192-point FFT.
4. Press **Stop input** to hold results, then inspect cursors, RMS, peaks or PSD band values.
5. Use **File** to save settings and held results. JSON retains measurement conditions; CSV supports numerical reuse; PNG shares a view.
6. After restarting, restore settings while stopped, load the reference JSON, and compare a new measurement. Restoring settings does not start acquisition.

A complete 524,288-point window takes about 10.92 seconds at 48 kHz. Faster Live updates do not shorten that observation time. Continuous analyzes every N/4-hop window; Live/Latest observe recent windows and do not guarantee transient capture.

Normal startup shows Scope alone, with input and output stopped. Selecting an instrument always opens its single view. **Measurement console / Add instrument…** retains up to seven instruments, using side-by-side, stacked, 2 × 2 or tabs. Narrow windows temporarily use tabs without changing the saved arrangement. **Open single** keeps the console for returning later. **Remove from view** leaves analysis and output running. The right details follow the selected pane; narrow windows use **Measurement / Details**. **Running…** shows hidden analysis and provides analysis stops; **Stop output** remains available on every screen. LIVE / HELD / WAITING / NOT ACQUIRED describe acquisition, separately from validity. Settings version 6 reads versions 1–5 and restores input/output stopped.

In Scope, select CH1–CH4 in the 40-point strip below the waveform, and use each checkbox to toggle its waveform independently. Selection and visibility are separate; CH3/CH4 show **No input** on a two-channel input. The right **Acquisition / Horizontal / Trigger / Channel** sections contain acquisition, time scale and position, trigger, and the selected channel's FS range and offset. The current time scale stays visible near the waveform. Use the wheel for time scale and Shift+wheel for the selected channel's vertical scale. **Channel / Input source** can assign any of the 1–16 input channels. Older settings preserve their two assignments and scales, with the added CH3/CH4 hidden.

Spectrum overlays up to four traces in one plot. The bottom channel bar selects a trace independently of its display toggle. The right details are ordered FFT → Frequency / Scale → Measurement → Averaging. Switch **Amplitude / PSD** at the top and set the shared FFT conditions and axes. Expand **Custom frequency range** for precise bounds or select **Manual** for level limits. Only CH1 is visible by default.

Select **Cursor A / B**, then click or drag on the plot to place two independent frequency cursors. They read the selected trace's nearest FFT bins and show Δf and ΔL; **Clear** removes them. **Average / Weight** near the bottom controls exponential averaging of linear power (EMA), with settling guidance. Processed-window counts are under **Advanced analysis / diagnostics**. Hidden traces stop FFT processing and start a fresh average when enabled. Peak/cursor readings and result exports follow the selected trace. For uncalibrated amplitude, a bin-centred 1 FS peak sine is 0 dBFS.

When additional measurement details exceed a console pane's height, scroll within that pane. The pane title and shared input/output status and stop controls remain outside the scroll area.

## Observe a Generator sine wave

1. Open **Generator**, then choose **Pair with… / Scope**. The two-channel internal output is available in normal builds.
2. Assign **OUT 1/2** under **I/O / Output**, enable **ON** on each central GEN card, then enter frequency (Hz), amplitude (dBFS peak) and phase (lead, degrees). Enter or leaving the field applies an edit; Esc cancels it. Use the selected Generator details under **EDIT STEP** to select a step for the ± buttons and arrow keys.
3. Select **I/O / Output / Observe Generator**, then press **Start output** and **Start input** separately. The settings preview and measured waveform are separate views.
4. Select **Generator**, then pair it with Spectrum/Lock-in to inspect analysis. Live edits transition amplitude and phase smoothly; Spectrum/Lock-in restart averaging and settling after the transition.
5. **Stop input** holds the measurement while output continues. **Stop output** stops generation; active input then receives new silent samples.

The central panel keeps compact numerical controls and settings previews. Wide windows show both channels side by side; narrow windows use tabs with both output states visible. Selecting the Generator pane exposes phase alignment and applied output details. Use **Hide signal controls** to collapse the editors and give the measurement graphs more room.

Under **I/O / Output**, select an output rate of 44.1, 48, 96 or 192 kHz while both input and output are stopped. Restoring settings also requires both to be stopped and leaves output OFF. Internal JSON/CSV results retain output conditions for the received intervals.

For audio-device output, select a destination under **I/O / Output** and its supported sample rate, channel count and PCM while stopped, then assign the OUT channels. Unassigned outputs are silent. Choose the connected physical input under **I/O / Input**, then press **Start output** and **Start input** separately. **Observe Generator** uses the internal connection. Output notifications or stalled callbacks latch ERROR; use **Reset output (stays OFF)** and an explicit Start to recover. Settings retain the output identity and format and restore with output OFF.

External input and output use separate clocks; output transitions are not automatically mapped to input analysis windows. Wait for input settling after edits and use two actual input channels for synchronous REF and response in Lock-in. JSON/CSV results that observe an external Generator retain applied settings, output state, failures and up to 128 observed changes. Input Stop, Single completion or input failure freezes this evidence; later edits cannot change it. Input-window correspondence remains uncalibrated, so reference comparisons omit numerical differences. Host observation times are not DAC/ADC timestamps, and lost or evicted history is not reconstructed. Result format version 4 also reads versions 1–3. Output calibration and DAC/ADC latency remain unverified.

## Physical audio input

Select the input device and a supported sample rate, then press **Start input**. On macOS, allow microphone access for the application or terminal used to launch it. Channel count and available sample rates depend on the device. Scope waveform axes and triggers remain in FS even when numerical readouts use calibration.

On macOS, physical input and output request an audio buffer of about 20 ms within the device's supported range to leave room for stream initialization and scheduling. When supported, 48 kHz uses 1,024 frames, about 21.3 ms. Output edit and Stop response also depend on this buffer length. The selected sample rate, channel count, PCM and measurement units are preserved.

Changes to input, analysis or calibration while stopped apply to the next Start. Held results keep their original conditions. Changing input or restarting acquisition begins a new history without mixing old generations.

## Experimental Lock-in

Select **Lock-in**, supply REF and response with Software Loopback, set SIG/REF channels in the instrument, then press **Start analysis** and **Start input** separately. Set REF and filter conditions in the selected details. X/Y and R use peak units; positive phase means the response leads REF. Settling, lost REF and missing input are not valid measurements. Hardware validation remains incomplete.

After Stop finishes processing, use **File** to save Lock-in conditions, calibrations, state and f64 values as JSON or CSV. Invalid readings use JSON `null` or empty CSV cells. Reference comparison shows both results and their captured conditions; numerical differences require settled results with matching nominal sample rate, channels, REF/filter settings and calibrations. PNG displays Scope/Spectrum.

## Compare synchronous gain, phase and delay

1. Supply two synchronous channels with Software Loopback or a real input, then select **Synchronous 2ch**.
2. Select different REF/SIG channels in the instrument, then press **Start analysis** and **Start input** separately. Set window and averaging in the selected details. The default 4,096 samples × 8 windows needs about 0.683 seconds at 48 kHz.
3. Use **Read at** or click a graph to select a frequency bin. Positive phase leads REF; positive delay lags REF. Low reference, low coherence and missing data suppress readings.
4. Stop, save JSON/CSV, restore settings while stopped and remeasure. Restoration starts neither input nor output. Reference differences require matching valid input, analysis, calibration and excitation conditions.

**Display range** offers the selected point neighborhood (default), the valid band, the full Nyquist range or a custom range, with linear or logarithmic frequency axes. These controls affect display only. Primary readings are shown separately; hover details and JSON/CSV retain f64 precision.

This f64 AC comparison removes each window's mean, averages auto/cross PSD over finite nonoverlapping windows, then computes H1 and coherence. Phase delay is ambiguous by 1/f. A slope fit requires at least eight contiguous sufficiently excited, coherent bins; a single sine does not establish broadband delay. The input clock is nominal; interchannel phase/timing calibration and absolute DAC/ADC latency remain unverified. PNG displays Scope/Spectrum.

See the [overview](index.md) for verification limits and unimplemented features.
