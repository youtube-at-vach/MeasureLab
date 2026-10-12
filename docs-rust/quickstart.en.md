# Quick start

## Build from source

Use a checkout containing the Rust edition and Rust 1.95 or later. Rust work targets `rewrite/rust` until the main transition. macOS needs Xcode Command Line Tools; Linux needs ALSA, X11 and Wayland development libraries; Windows needs MSVC and Visual Studio C++ Build Tools. See `guide/rust/SETUP.md` in the repository for details.

Run from the repository root:

```sh
cargo run --release --locked
```

With the local macOS/Linux setup, `./scripts/cargo.sh run --release --locked` also works. Normal startup leaves acquisition stopped.

## First measurement without hardware

1. Select **Software Loopback** under **Input source**. It is available in normal builds and does not drive a physical output.
2. Start acquisition using the top control, then select **Scope + Spectrum** under **View**.
3. Use **Adjust** beside each plot for time/amplitude scales and FFT/window/channel settings. Start with the default 8,192-point FFT.
4. Press **Stop** to hold results, then inspect cursors, RMS, peaks or PSD band values.
5. Use **File** to save settings and held results. JSON retains measurement conditions; CSV supports numerical reuse; PNG shares a view.
6. After restarting, restore settings while stopped, load the reference JSON, and compare a new measurement. Restoring settings does not start acquisition.

A complete 524,288-point window takes about 10.92 seconds at 48 kHz. Faster Live updates do not shorten that observation time. Continuous analyzes every N/4-hop window; Live/Latest observe recent windows and do not guarantee transient capture.

## Observe a Generator sine wave

1. Choose **View / Generator + Scope**. The two-channel internal output is available in normal builds.
2. Select **ON** and **OUT 1/2** for each GEN, then enter frequency (Hz), amplitude (dBFS peak) and phase (lead, degrees). Enter or leaving the field applies an edit; Esc cancels it. **Step** and the ± buttons also adjust values.
3. Select **Observe Generator**, then press **Start output** and **Start input** separately. The settings preview and measured waveform are separate views.
4. Switch to **Generator + Spectrum/Lock-in** to inspect analysis. Live edits transition amplitude and phase smoothly; Spectrum/Lock-in restart averaging and settling after the transition.
5. **Stop input** holds the measurement while output continues. **Stop output/Stop all outputs** stops generation; active input then receives new silent samples.

Select an output rate of 44.1, 48, 96 or 192 kHz while both input and output are stopped. Restoring settings also requires both to be stopped and leaves output OFF. Internal JSON/CSV results retain output conditions for the received intervals.

For audio-device output, select a destination and its supported sample rate, channel count and PCM while stopped, then assign the OUT channels. Unassigned outputs are silent. Choose the connected physical input under **Input source**, then press **Start output** and **Start input** separately. **Observe Generator** uses the internal connection. Output notifications or stalled callbacks latch ERROR; use **Reset output (stays OFF)** and an explicit Start to recover. Settings retain the output identity and format and restore with output OFF.

External input and output use separate clocks; output transitions are not automatically mapped to input analysis windows. Wait for input settling after edits and use two actual input channels for synchronous REF and response in Lock-in. External results do not include Generator output intervals. Output calibration and DAC/ADC latency remain unverified.

## Physical audio input

Select the input device and a supported sample rate, then press **Start input**. On macOS, allow microphone access for the application or terminal used to launch it. Channel count and available sample rates depend on the device. Scope waveform axes and triggers remain in FS even when numerical readouts use calibration.

Changes to input, analysis or calibration while stopped apply to the next Start. Held results keep their original conditions. Changing input or restarting acquisition begins a new history without mixing old generations.

## Experimental Lock-in

Use Software Loopback to supply REF and response, and select the REF/Signal channels in the Lock-in display. X/Y and R use peak units; positive phase means the response leads REF. Settling, lost REF and missing input are not valid measurements. Hardware validation remains incomplete.

After Stop finishes processing, use **File** to save Lock-in conditions, calibrations, state and f64 values as JSON or CSV. Invalid readings use JSON `null` or empty CSV cells. Reference comparison shows both results and their captured conditions; numerical differences require settled results with matching nominal sample rate, channels, REF/filter settings and calibrations. PNG displays Scope/Spectrum.

See the [overview](index.md) for verification limits and unimplemented features.
