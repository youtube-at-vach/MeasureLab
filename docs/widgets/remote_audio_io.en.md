# Remote Audio I/O

## Overview

Remote Audio I/O uses an audio device attached to another MeasureLab computer on the same LAN as a measurement input or duplex input/output. It is an internal MeasureLab AudioEngine backend, not an operating-system virtual audio driver.

Sample position and measurement integrity take priority over concealment. Missing audio is not interpolated. A missing range is replaced by an equal-length zero range and reported visibly as data loss.

## Preparing the remote computer

1. In Settings, select the physical input/output devices, sample rate, buffer size, and channels used for remote measurement.
2. Open Remote Audio I/O.
3. Select **Provide Local I/O**.
4. Set the listen address and control port. Use `0.0.0.0` to listen on every IPv4 LAN interface.
5. Enable **Allow remote playback** only when remote output is required.
6. Select **Start Provider**.

On Windows, receiving a connection from another computer requires Windows Firewall permission. MeasureLab checks the current permission when the Provider is first started and again after the executable location or port changes. When necessary, an explanation dialog is followed by Windows administrator approval. This check and approval are not performed during ordinary MeasureLab startup or when using Remote Audio Client.

The automatically created inbound rules are restricted to TCP and UDP on the selected port, the current `MeasureLab.exe`, Private or Domain networks, and sources on the local subnet. The rules do not apply to Public networks. On an organization-managed device that disables local rules, provide the displayed requirements to the administrator.

While the provider is running, other measurement modules on the same computer cannot acquire the AudioEngine. This prevents unintended local output from contaminating a remote measurement.

## Connecting from the main computer

1. Open **Use Remote I/O** in Remote Audio I/O.
2. Enter the remote computer's IPv4 address or host name and control port.
3. Set the fixed network buffer. Start with 100 ms for a typical LAN.
4. Enable **Request remote output (duplex)** when output is required.
5. Select **Connect**.
6. Start an ordinary measurement module after the connection is established.

If the provider has not allowed remote playback, a duplex request is reduced to input-only operation.
Disabling **Allow remote playback** during a connection mutes output immediately. If an input-only session is already connected when the option is enabled, the permission takes effect on the next connection for safety.

Calibration profiles are not transferred over the network. For measurements in physical units, select a profile on the main computer that matches the remote audio interface, gain settings, and measurement chain.

## Data-integrity monitoring

Connection Integrity displays:

- Transmitted and received packet counts
- Missing frame count
- Late, duplicate, and corrupt packet counts
- Current buffered frame count
- Direction, absolute sample position, frame count, and reason for each recent incident

Do not treat a measurement interval showing `DATA LOSS DETECTED` as complete data. Increase the buffer or move to a wired LAN, then repeat the measurement.

## Transport and safety

- TCP carries control messages and UDP carries uncompressed float32 PCM. Both use the same port number selected in the interface.
- The control channel uses an application heartbeat so an unresponsive client cannot reserve the provider indefinitely.
- UDP packets include a session ID, sequence number, absolute sample position, and CRC.
- The remote audio device clock is the sample-time authority for the session.
- Playback uses a fixed look-ahead buffer. Its delay is not adjusted while streaming.
- The transport is not encrypted or authenticated. Enable the provider only on a trusted LAN.
- The initial implementation supports IPv4, mono/stereo, and one client.
- Wired Ethernet is recommended for stable measurements.

Stop active measurement modules before connecting or disconnecting. A failed network session never silently falls back to a local microphone or output.
