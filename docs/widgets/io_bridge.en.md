# I/O Bridge

## Overview

I/O Bridge is a persistent, one-action audio handoff for measurement work. It is owned by the AudioEngine and starts **OFF** on every application launch. The panel remembers only the selected route and send level.

The bridge never changes the configured devices implicitly. It uses the current logical analysis input for local monitoring, or the saved local input configuration for sending to a connected Remote Audio I/O provider.

## Routes

| Route | Input | Output | Availability |
| --- | --- | --- | --- |
| Physical | Offline VST3 analysis input, or Remote Audio I/O input | Configured local physical output | Offline + loaded VST3 DUT, or connected Remote Audio I/O with loopback disabled |
| Remote Output | Configured local physical input | Connected Remote Audio I/O output | Connected duplex provider with loopback disabled |

The route selector is disabled while the bridge is running. Remote input is not sent back to Remote Output, and an active output-producing measurement callback prevents the Local Input → Remote route from starting.

## Operation

1. Configure the required devices and format in Settings. Connect Remote Audio I/O first when using a remote route.
2. Open **I/O Bridge** from the sidebar or add it to the Measurement Console.
3. Select **Physical** or **Remote Output** while the bridge is OFF.
4. Set **Gain** between −60 and 0 dB. The default is −20 dB; this is a bridge-only relative level and does not change measurement calibration.
5. Press **ON** once. The status text reports OFF, STARTING, ON, STOPPING, or ERROR; press the same button to turn it OFF.

Unavailable routes show a reason and a short indication of the setting or connection that must be corrected. A bridge error stops only the bridge; measurement callbacks remain owned by the AudioEngine.

## Timing and safety

The bridge uses bounded producer/consumer buffers and a stateful linear sample-rate converter. Audio callbacks copy into the buffer without waiting; conversion and channel mapping run on a worker. Missing or overrun data is replaced with silence or the newest available data and is counted in the status snapshot.

NaN and infinite samples are converted to silence, output is clipped immediately before delivery, and ON/OFF and gain changes use a short ramp. The existing AudioEngine mute applies to the bridge output. Stop the bridge before changing devices, format, backend, DUT, or Remote Audio I/O connection; these transitions also stop it automatically.

The bridge does not detect acoustic feedback through speakers and microphones. Start at the default −20 dB, verify the physical wiring, and keep the visible OFF control available during testing.
