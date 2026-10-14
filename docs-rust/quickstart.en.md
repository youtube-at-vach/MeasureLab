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
2. Start acquisition using the top control, then select **Scope + Spectrum** under **View**.
3. Use **Adjust** beside each plot for time/amplitude scales and FFT/window/channel settings. Start with the default 8,192-point FFT.
4. Press **Stop** to hold results, then inspect cursors, RMS, peaks or PSD band values.
5. Use **File** to save settings and held results. JSON retains measurement conditions; CSV supports numerical reuse; PNG shares a view.
6. After restarting, restore settings while stopped, load the reference JSON, and compare a new measurement. Restoring settings does not start acquisition.

A complete 524,288-point window takes about 10.92 seconds at 48 kHz. Faster Live updates do not shorten that observation time. Continuous analyzes every N/4-hop window; Live/Latest observe recent windows and do not guarantee transient capture.

## Observe a Generator sine wave

1. Choose **View / Generator + Scope**. The two-channel internal output is available in normal builds.
2. Assign **OUT 1/2** under **I/O / Output**, enable **ON** on each central GEN card, then enter frequency (Hz), amplitude (dBFS peak) and phase (lead, degrees). Enter or leaving the field applies an edit; Esc cancels it. Use **Adjust / Generator / EDIT STEP** to select a step for the ± buttons and arrow keys.
3. Select **I/O / Output / Observe Generator**, then press **Start output** and **Start input** separately. The settings preview and measured waveform are separate views.
4. Switch to **Generator + Spectrum/Lock-in** to inspect analysis. Live edits transition amplitude and phase smoothly; Spectrum/Lock-in restart averaging and settling after the transition.
5. **Stop input** holds the measurement while output continues. **Stop output/Stop all outputs** stops generation; active input then receives new silent samples.

The central panel keeps compact numerical controls and settings previews. Wide windows show both channels side by side; narrow windows use tabs with both output states visible. **Adjust** opens phase alignment and applied output details.

Under **I/O / Output**, select an output rate of 44.1, 48, 96 or 192 kHz while both input and output are stopped. Restoring settings also requires both to be stopped and leaves output OFF. Internal JSON/CSV results retain output conditions for the received intervals.

For audio-device output, select a destination under **I/O / Output** and its supported sample rate, channel count and PCM while stopped, then assign the OUT channels. Unassigned outputs are silent. Choose the connected physical input under **I/O / Input**, then press **Start output** and **Start input** separately. **Observe Generator** uses the internal connection. Output notifications or stalled callbacks latch ERROR; use **Reset output (stays OFF)** and an explicit Start to recover. Settings retain the output identity and format and restore with output OFF.

External input and output use separate clocks; output transitions are not automatically mapped to input analysis windows. Wait for input settling after edits and use two actual input channels for synchronous REF and response in Lock-in. JSON/CSV results that observe an external Generator retain applied settings, output state, failures and up to 128 observed changes. Input Stop, Single completion or input failure freezes this evidence; later edits cannot change it. Input-window correspondence remains uncalibrated, so reference comparisons omit numerical differences. Host observation times are not DAC/ADC timestamps, and lost or evicted history is not reconstructed. Result format version 4 also reads versions 1–3. Output calibration and DAC/ADC latency remain unverified.

## Physical audio input

Select the input device and a supported sample rate, then press **Start input**. On macOS, allow microphone access for the application or terminal used to launch it. Channel count and available sample rates depend on the device. Scope waveform axes and triggers remain in FS even when numerical readouts use calibration.

On macOS, physical input and output request an audio buffer of about 20 ms within the device's supported range to leave room for stream initialization and scheduling. When supported, 48 kHz uses 1,024 frames, about 21.3 ms. Output edit and Stop response also depend on this buffer length. The selected sample rate, channel count, PCM and measurement units are preserved.

Changes to input, analysis or calibration while stopped apply to the next Start. Held results keep their original conditions. Changing input or restarting acquisition begins a new history without mixing old generations.

## Experimental Lock-in

Use Software Loopback to supply REF and response, and select the REF/Signal channels in the Lock-in display. X/Y and R use peak units; positive phase means the response leads REF. Settling, lost REF and missing input are not valid measurements. Hardware validation remains incomplete.

After Stop finishes processing, use **File** to save Lock-in conditions, calibrations, state and f64 values as JSON or CSV. Invalid readings use JSON `null` or empty CSV cells. Reference comparison shows both results and their captured conditions; numerical differences require settled results with matching nominal sample rate, channels, REF/filter settings and calibrations. PNG displays Scope/Spectrum.

## Compare synchronous gain, phase and delay

1. Supply two synchronous channels with Software Loopback or a real input, then choose **View / Comparison only**.
2. In **Adjust**, enable **Analyze synchronous pair** and select different REF/response channels. The default 4,096 samples × 8 windows needs about 0.683 seconds at 48 kHz.
3. Use **Read at** or click a graph to select a frequency bin. Positive phase leads REF; positive delay lags REF. Low reference, low coherence and missing data suppress readings.
4. Stop, save JSON/CSV, restore settings while stopped and remeasure. Restoration starts neither input nor output. Reference differences require matching valid input, analysis, calibration and excitation conditions.

This f64 AC comparison removes each window's mean, averages auto/cross PSD over finite nonoverlapping windows, then computes H1 and coherence. Phase delay is ambiguous by 1/f. A slope fit requires at least eight contiguous sufficiently excited, coherent bins; a single sine does not establish broadband delay. The input clock is nominal; interchannel phase/timing calibration and absolute DAC/ADC latency remain unverified. PNG displays Scope/Spectrum.

See the [overview](index.md) for verification limits and unimplemented features.
