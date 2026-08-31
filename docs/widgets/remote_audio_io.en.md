# Remote Audio I/O

## Overview

Remote Audio I/O uses an audio device attached to another MeasureLab computer on the same LAN as a measurement input or duplex input/output. It is an internal MeasureLab AudioEngine backend, not an operating-system virtual audio driver.

Sample position and measurement integrity take priority over concealment. Missing audio is not interpolated. A missing range is replaced by an equal-length zero range and reported visibly as data loss.

## Preparing the remote computer

1. In Settings, select the physical input/output devices, sample rate, buffer size, and channels used for remote measurement.
2. Open Remote Audio I/O.
3. Select **Provide Local I/O**.
4. Set the listen address and UDP port. Use `0.0.0.0` to listen on every IPv4 LAN interface.
5. Enable **Allow automatic discovery** to make the provider available in the connection list.
6. Enable **Allow remote playback** only when remote output is required.
7. Select **Start sharing**.

On Windows, allow inbound UDP connections to the selected port in Windows Defender Firewall before sharing (default: `40100`). An inbound TCP rule is not required. Because the main computer sends the UDP request first, it normally needs no additional inbound rule. Allow local-network access if macOS prompts for it. When a firewall is enabled on Linux, allow the same inbound UDP port on the provider.

While the provider is running, other measurement modules on the same computer cannot acquire the AudioEngine. This prevents unintended local output from contaminating a remote measurement.

## Connecting from the main computer

1. Open **Use Remote I/O** in Remote Audio I/O.
2. Select the remote computer under **Available MeasureLab computers**, then select **Connect selected**. No address or port entry is required.
3. If discovery is unavailable, enter an IPv4 address or host name and UDP port under **Manual connection**, then select **Connect by address**. Manual connections use the same UDP protocol as discovered connections.
4. Adjust the fixed network buffer when necessary. Start with 100 ms for a typical LAN.
5. Enable **Request remote output (duplex)** when output is required.
6. Start an ordinary measurement module after the connection is established.

Discovery sends an IPv4 broadcast query from the main computer to the selected UDP port and lists only providers that reply. Normally, use the default port `40100` on both computers. Discovery does not cross subnets and can be blocked by Wi-Fi client isolation, VPNs, or firewalls that filter broadcasts. Manual connection remains available when the provider address is otherwise reachable.

If the provider has not allowed remote playback, a duplex request is reduced to input-only operation.
Disabling **Allow remote playback** during a connection mutes output immediately. If an input-only session is already connected when the option is enabled, the permission takes effect on the next connection for safety.

Calibration profiles are not transferred over the network. For measurements in physical units, select a profile on the main computer that matches the remote audio interface, gain settings, and measurement chain.

## Data-integrity monitoring

Connection Integrity displays:

- Transmitted and received packet counts
- Missing frame count
- Late, duplicate, and corrupt packet counts
- Current buffered frame count

Do not treat a measurement interval showing `DATA LOSS DETECTED` as complete data. Increase the buffer or move to a wired LAN, then repeat the measurement.

## Transport and safety

- Protocol v2 carries discovery, connection control, keepalives, and uncompressed float32 PCM audio on one UDP port. It has no TCP listener.
- The main computer sends `DISCOVER_QUERY` and `CONNECT_REQUEST`; the provider returns responses and audio to the observed UDP source address. It does not trust a reply address declared in the payload.
- Session start, playback state, shutdown, and other control packets use acknowledgements and retries with the same message ID. Real-time audio is not retransmitted because doing so would increase latency.
- Keepalives prevent an unresponsive client from reserving the provider indefinitely.
- Audio packets include a session ID, sequence number, absolute sample position, and CRC.
- The remote audio device clock is the sample-time authority for the session.
- Playback uses a fixed look-ahead buffer. Its delay is not adjusted while streaming.
- The transport is not encrypted or authenticated. Enable the provider only on a trusted LAN.
- Protocol v2 supports IPv4, mono/stereo, and one client per provider.
- Wired Ethernet is recommended for stable measurements.

Stop active measurement modules before connecting or disconnecting. A failed network session never silently falls back to a local microphone or output.
