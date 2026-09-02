---
title: "Remote Audio I/O"
---

## Overview

Remote Audio I/O uses an audio device attached to another MeasureLab computer on the same LAN as a measurement input or duplex input/output. It is an internal MeasureLab AudioEngine backend, not an operating-system virtual audio driver.

Sample position and measurement integrity take priority over concealment. Missing audio is not interpolated. A missing range is replaced by an equal-length zero range and reported visibly as data loss.

## Preparing the remote computer

1. In Settings, select the physical input/output devices, sample rate, buffer size, and channels used for remote measurement.
2. Open Remote Audio I/O.
3. Select **Share this computer's audio**.
4. Enable **Allow remote playback** only when remote output is required.
5. Select **Start sharing**. By default, MeasureLab listens on every IPv4 LAN interface and enables automatic discovery.
6. After sharing starts, open **Advanced** and check **Details**. **Connect from another computer** displays each usable LAN endpoint in `address:port` form, for example `192.168.1.10:40100`.
7. Change **Listen address**, **UDP port**, or **Allow automatic discovery** under **Advanced** before sharing when the defaults are unsuitable.

On Windows, allow inbound UDP connections to the selected port in Windows Defender Firewall before sharing (default: `40100`). An inbound TCP rule is not required. Because the main computer sends the UDP request first, it normally needs no additional inbound rule. Allow local-network access if macOS prompts for it. When a firewall is enabled on Linux, allow the same inbound UDP port on the provider.

If more than one endpoint is displayed, use the address on the LAN shared with the client. **Listening on 0.0.0.0:40100** means that the provider accepts connections on all IPv4 interfaces; `0.0.0.0` is not an address to enter on the client.

## Provider-only routing and local modules

While sharing is active, Remote Audio I/O displays **Provide Local I/O**, and the main window switches to a provider-only state:

- The status is **I/O Provider**, with **Mode: waiting**, **Mode: Input only**, or **Mode: Duplex**.
- **I/O Routing** is read-only because it reports the route owned by the provider rather than offering a local output choice.
- While waiting, it displays **Remote I/O provider — waiting for client**.
- For an input-only connection, it displays **Physical input → Remote client · Physical output muted**.
- For a duplex connection, it displays **Physical input → Remote client · Remote client → Physical output**.

Selecting **Start sharing** reserves the AudioEngine exclusively for the provider, including while it is waiting for a client. This keeps one owner in control of the physical audio stream, its device clock, sample order, and remote-output permission. Local measurement modules therefore cannot register their audio processing while sharing is active; allowing both paths to run could mix local output into the remote measurement or compromise its timing. Select **Stop sharing** before using local measurement modules again.

## Connecting from the main computer

1. Open **Connect to another computer** in Remote Audio I/O.
2. Select the remote computer under **Available MeasureLab computers**, then select **Connect selected**. No address or port entry is required.
3. If discovery is unavailable, check **Connect from another computer** in the provider's **Advanced** details. On the client, open **Advanced**, enter the endpoint's address part under **Remote host** and its port part under **UDP port**, then select **Connect by address**. For example, enter `192.168.1.10` and `40100` for `192.168.1.10:40100`. A reachable host name may be used instead of the displayed IPv4 address. Manual connections use the same UDP protocol as discovered connections.
4. The fixed network buffer and duplex request are also under **Advanced**. Start with 100 ms for a typical LAN.
5. Start an ordinary measurement module after the connection is established.

Discovery sends an IPv4 broadcast query from the main computer to the selected UDP port and lists only providers that reply. Normally, use the default port `40100` on both computers. Discovery does not cross subnets and can be blocked by Wi-Fi client isolation, VPNs, or firewalls that filter broadcasts. Manual connection remains available when the provider address is otherwise reachable.

If the provider has not allowed remote playback, a duplex request is reduced to input-only operation.
Disabling **Allow remote playback** during a connection mutes output immediately. If an input-only session is already connected when the option is enabled, the permission takes effect on the next connection for safety.

Calibration profiles are not transferred over the network. For measurements in physical units, select a profile on the main computer that matches the remote audio interface, gain settings, and measurement chain.

## Data-integrity monitoring

The **Connection quality** area at the top displays the following while connected:

- Missing frame count
- Event count combining missing packets, corrupt packets, and local queue overflows
- Whether data loss is still increasing or has stopped increasing

Open **Advanced** in the relevant tab to see the connected device and format, or the listening endpoints and connected client.

Do not treat a measurement interval showing **Data loss is increasing** as complete data. Increase the buffer or move to a wired LAN, then repeat the measurement.

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
