# Routing and physical monitoring

Open **Routing** in the sidebar to inspect MeasureLab's connections and audition virtual measurements through a physical output.
Routing is an infrastructure page. Closing it or switching to an instrument does not stop an enabled monitor.

## Audition a DUT

1. Enable **Virtual Audio** in Settings and load a [VST3 DUT](../vst_dut.md) if needed.
2. Open Routing and select a Monitor Out source.
3. Explicitly select a physical output device.
4. Check the monitor volume and enable Monitor Out. The initial volume is −20 dB.
5. Start a generator or measurement. Enabling the monitor alone does not start audio processing.

The VST launcher's Monitor Out shortcut controls this same route. If no device is selected, it opens Routing.
Its Routing button also opens this page.

| Source | Signal |
| --- | --- |
| DUT output (default) | The DUT output before measurement return mapping; mono DUT output is duplicated to both sides |
| Measurement return | The two channels returned to instruments on the next block, including any dry reference |
| Output mix | The module output mix before the DUT and dithering; available without a loaded DUT |

For example, a measurement using wet audio on L and a dry reference on R can still monitor the DUT's stereo output independently.
Monitor volume ranges from −60 to 0 dB. Volume, float32 conversion and clipping affect only the monitor copy.
A stereo device receives its first two channels; a mono device receives their average.
The existing measurement output channel selection and dithering do not apply to this monitor.

## Inspect connections

The page shows the backend, clock, sample rate and devices or remote endpoint.
Rows describe Source → Processing → Destination and actual state. A source with several destinations appears on several rows.
Expand DUT routing details to inspect the individual DUT inputs and measurement return channels.

In physical and remote client modes, the output destination selector controls the same setting as the bottom-right menu.
Remote input-only connections show output as unavailable. Provider routes distinguish waiting, sharing and muted playback.
Device setup remains in Settings; connection management remains in Remote Audio I/O.

## Timing, state and limits

- Enabled and playing are separate states. An enabled monitor waits until measurement audio is available.
- Dropout indication remains until the monitor is re-enabled. Its tooltip reports dropped, missing and buffered frames.
- This is an audition path. The buffer targets approximately 100 ms, with at least two measurement blocks, plus the physical device latency.
- The virtual timer and device clocks may drift. Missing audio is zero-filled; excessive buffering discards old audio. The measurement producer never waits for playback.
- The device must accept the measurement sample rate. An unsupported rate fails only the monitor, without changing measurement settings. No application resampling is performed.
- Turn the monitor off before changing source or device. Volume and ON/OFF can change during measurement without restarting the DUT or measurement stream.
- Stopping measurement discards queued monitor audio. An enabled monitor follows a subsequent start with the same settings.
- Backend, format, DUT load/unload, routing and bypass changes turn the monitor off.
- A failed or disconnected monitor does not stop measurement. There is no fallback device or automatic error recovery. Resolve the problem and toggle OFF→ON to retry.
- DUT errors silence measurement returns and stop DUT-derived monitoring. The pre-DUT output mix remains available for audition.
- Preferences last only for this application session. Restarting restores OFF, −20 dB and no selected device.

The additional physical monitor is available only in virtual mode. Simultaneous remote sends, multiple monitor devices, free-form patching and low-latency instrument performance are outside this version's scope.
