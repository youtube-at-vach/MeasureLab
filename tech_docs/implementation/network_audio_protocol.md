# Remote Audio I/O Protocol

This document specifies the UDP protocol currently used by the `Remote Audio I/O` screen in MeasureLab. It describes the behavior implemented by the v2 protocol in `src/core/network_audio/`; it is not a general-purpose network-audio standard.

The protocol lets one MeasureLab instance act as a **provider** of its local audio devices, while exactly one other instance acts as a **client**. Audio capture always flows from provider to client. Playback from client to provider is available only when both sides permit duplex operation.

## 1. Transport and compatibility

- Transport is IPv4 UDP. A provider listens on one UDP port; the default UI value is `40100`.
- All protocol datagrams are at most 1,200 bytes. The implementation deliberately keeps each message within one UDP datagram; IP fragmentation is not used by the protocol.
- The first four bytes of every datagram are the ASCII magic value `MLAU` (`0x4d 0x4c 0x41 0x55`).
- Protocol version is currently `2`. A receiver rejects a datagram with a different magic value or version.
- Header integers use network byte order (big-endian). Audio samples use little-endian IEEE 754 binary32 (`<f4`).
- UDP does not guarantee delivery, ordering, or uniqueness. The receiver accepts useful out-of-order audio through its indexed jitter buffer and records missing, late, duplicate, and corrupt data as integrity incidents.

The wire format does not authenticate peers or encrypt control or audio traffic. It is intended only for a trusted LAN. In particular, device names and provider host names are sent in discovery and connection replies.

## 2. Datagram classes

Byte 5 (zero-based offset 5) distinguishes the two datagram classes after the common magic and version prefix:

- Values `1` and `2` are audio directions: capture and playback respectively.
- Values `16` through `29` are control packet types.

Control packet types are as follows.

| Value | Name | Normal direction |
| --- | --- | --- |
| 16 | `DISCOVER_QUERY` | client to LAN broadcast |
| 17 | `DISCOVER_REPLY` | provider to client |
| 18 | `CONNECT_REQUEST` | client to provider |
| 19 | `CONNECT_OFFER` | provider to client |
| 20 | `START` | client to provider |
| 21 | `START_ACK` | provider to client |
| 22 | `KEEPALIVE` | client to provider |
| 23 | `KEEPALIVE_ACK` | provider to client |
| 24 | `PLAYBACK_STATE` | client to provider |
| 25 | `CONTROL_ACK` | provider to client |
| 26 | `STOP` | client to provider |
| 27 | `STOPPED` | provider to client |
| 28 | `ERROR` | provider to client |
| 29 | `AUDIO_NACK` | receiver to audio sender |

## 3. Control datagram format

A control datagram is a 28-byte header followed by a UTF-8 JSON object. The JSON is serialized compactly; field order is not semantically significant.

| Offset | Size | Type | Field |
| ---: | ---: | --- | --- |
| 0 | 4 | bytes | magic: `MLAU` |
| 4 | 1 | unsigned 8-bit | protocol version: `2` |
| 5 | 1 | unsigned 8-bit | control packet type |
| 6 | 2 | unsigned 16-bit, big-endian | JSON payload length in bytes |
| 8 | 8 | unsigned 64-bit, big-endian | session ID (`0` before a session exists) |
| 16 | 8 | unsigned 64-bit, big-endian | message ID |
| 24 | 4 | unsigned 32-bit, big-endian | CRC-32 of the JSON payload |
| 28 | variable | bytes | UTF-8 JSON object |

The complete datagram must be no more than 1,200 bytes, and its actual JSON length must equal the header value. The CRC is the unsigned result of `zlib.crc32()` over the JSON bytes. The receiver rejects an invalid packet type, length mismatch, checksum failure, invalid UTF-8/JSON, or a JSON value other than an object.

Except for data emitted by a faulty peer, control message IDs are nonzero. Requests use a random positive 63-bit ID, and the response repeats that ID. The provider caches a response for the tuple `(sender address, request type, message ID)` for 10 seconds (up to 256 entries), so retrying the same request is idempotent during that period.

Control scalar validation is strict: an integer field must be a JSON integer and a Boolean field must be a JSON Boolean. In particular, `true` is not accepted where an integer is expected.

## 4. Discovery

The client performs active discovery every two seconds. It opens an ephemeral UDP socket, enables broadcast, and sends `DISCOVER_QUERY` to every directed IPv4 broadcast address of its active non-loopback interfaces (falling back to `255.255.255.255`) on the selected provider port.

The discovery request uses session ID `0` and contains:

```json
{"protocol":2,"nonce":"<32-hex-character client nonce>"}
```

A discoverable provider replies by unicast to the sender's ephemeral port, preserving the request message ID and using session ID `0`:

```json
{
  "protocol": 2,
  "nonce": "<request nonce>",
  "instance_id": "<32-hex-character provider instance ID>",
  "service_port": 40100,
  "provider_name": "<provider host name>",
  "input_device_name": "<local input device name>",
  "output_device_name": "<local output device name>",
  "sample_rate": 48000,
  "block_size": 256,
  "input_channels": 2,
  "output_channels": 2,
  "duplex": true,
  "busy": false
}
```

The receiver accepts a reply only when its protocol version and nonce match the current query, the service port is in `1..65535`, the sample rate is in `1000..768000`, the block size is in `16..262144`, and both channel counts are either one or two. A discovered provider expires six seconds after its last valid reply. `busy` advertises that the provider already has a client; the UI does not offer connection to such an entry.

## 5. Session establishment and shutdown

Only one client can hold a provider session at a time. The provider allocates a random nonzero 63-bit session ID after accepting a connection request. The client connects its UDP socket to the provider address, so all subsequent normal traffic uses that source/destination pair.

```text
Client                                      Provider
  | -- CONNECT_REQUEST (session 0) --------> |
  | <-- CONNECT_OFFER (new session ID) ----- |
  | -- START (new session ID) -------------> |
  | <-- START_ACK (new session ID) --------- |
  | <========= capture audio =============== |
  | ========= playback audio =============== |  (only when duplex is active)
  | -- STOP (new session ID) --------------> |
  | <-- STOPPED (new session ID) ----------- |
```

### 5.1 Connection request and offer

`CONNECT_REQUEST` has session ID `0` and this payload:

```json
{"protocol":2,"client_nonce":"<32-hex-character client nonce>","duplex":true,"retransmission":true,"retransmit_window_ms":100}
```

`duplex` is the client's request to send playback to the provider. The provider rejects a request with an unsupported protocol version, an absent/invalid nonce, or when another client is already allocated. Rejection is an `ERROR` response with an `error` string.

`retransmission` is an optional request for deadline-limited audio packet retransmission. The provider only enables it when requested and echoes the resulting state in `CONNECT_OFFER`. A missing or false value preserves the original non-retransmitting behavior. `retransmit_window_ms` is limited to 20 through 250 ms and is derived from the client's selected network buffer. The provider may increase it to cover the client's effective two-block minimum jitter buffer after block alignment, but never above 250 ms.

On success, `CONNECT_OFFER` uses the allocated session ID in both its header and the `session_id` payload member:

```json
{
  "protocol": 2,
  "client_nonce": "<request client_nonce>",
  "session_id": 123456789,
  "sample_rate": 48000,
  "block_size": 256,
  "input_channels": 2,
  "output_channels": 2,
  "provider_name": "<provider host name>",
  "input_device_name": "<local input device name>",
  "output_device_name": "<local output device name>",
  "duplex": true,
  "retransmission": true,
  "retransmit_window_ms": 100
}
```

The client verifies the echoed nonce, matching session IDs, protocol version, and the same sample-rate, block-size, and channel-count ranges used by discovery. The effective duplex setting is the logical AND of the requested value and the offered value. The offer sets the provider's local sample rate, block size, and channel layout for the client; the client does not negotiate alternative values.

Retransmission is active only when the client requested it and the offer confirms it. This additive negotiation keeps protocol-v2 peers compatible: an older peer ignores the request field or omits the offer field, and no `AUDIO_NACK` packets are then sent.

### 5.2 Start, stop, and errors

The client sends `START` with an empty JSON object and the accepted session ID. The provider then registers its local audio callback, starts sending capture data, and replies `START_ACK` with an empty JSON object and the same message ID. A start failure returns `ERROR` with `{"error":"<bounded description>"}` and ends the allocated session.

The client terminates a connected session with `STOP` and an empty object; the provider replies `STOPPED` and releases the local callback. If the provider itself stops, it emits an unsolicited `STOPPED` with `{"reason":"provider stopped"}` before releasing the session. An unsolicited `ERROR` or `STOPPED` causes the client to treat the connection as failed unless it is already closing.

Before the start acknowledgement and for reliable post-start controls, the client retries the identical datagram with exponential waits starting at 0.2 seconds and capped at one second, until the operation timeout. The default connection timeout is five seconds; explicit control operations use three seconds (and shutdown uses 1.5 seconds).

## 6. Liveness and playback state

After the session starts, the client sends `KEEPALIVE` with an empty object once per second. The provider replies with `KEEPALIVE_ACK`, preserving the message ID. Both ends regard five seconds without received control traffic as a failed session; the provider ends the session and the client marks it as an error.

The audio stream is controlled separately from the session. Just before the client begins its callback stream, it requests:

```json
{"active":true,"next_sequence":1204}
```

in `PLAYBACK_STATE`. `next_sequence` is the unsigned 64-bit sequence number of the next playback audio datagram the client will transmit. It is required when retransmission was negotiated and `active` is true, so the provider can detect loss of the first playback packet. The current MeasureLab client includes the counter for both active and inactive state changes. A provider accepts its omission for compatibility with older protocol-v2 clients, but cannot request packets preceding the first sequence it observes in that case. When the callback stops, the client sends the same packet with `active` set to false. The provider replies with `CONTROL_ACK`:

```json
{"request_kind":24}
```

The provider only accepts playback audio while this state is active *and* duplex was negotiated and remains allowed locally. Disabling “Allow remote playback” on the provider immediately mutes and clears its playback buffer, even if the session had negotiated duplex. It continues tracking the highest playback sequence while muted so retransmission can resume from the correct sequence if playback is allowed again.

## 7. Audio datagram format

An audio datagram has a 40-byte header followed by interleaved samples.

| Offset | Size | Type | Field |
| ---: | ---: | --- | --- |
| 0 | 4 | bytes | magic: `MLAU` |
| 4 | 1 | unsigned 8-bit | protocol version: `2` |
| 5 | 1 | unsigned 8-bit | direction: `1` capture or `2` playback |
| 6 | 2 | unsigned 16-bit, big-endian | status flags |
| 8 | 8 | unsigned 64-bit, big-endian | session ID |
| 16 | 8 | unsigned 64-bit, big-endian | packet sequence number |
| 24 | 8 | unsigned 64-bit, big-endian | absolute first sample index |
| 32 | 2 | unsigned 16-bit, big-endian | frame count |
| 34 | 2 | unsigned 16-bit, big-endian | channel count |
| 36 | 4 | unsigned 32-bit, big-endian | CRC-32 of audio payload |
| 40 | variable | bytes | interleaved little-endian `float32` samples |

The valid frame count is `1..128`; the valid channel count is one or two. The audio payload length must be exactly `frames * channels * 4`, and its CRC-32 must match. A full two-channel 128-frame packet is 1,064 bytes, including its header. Larger callback blocks are split into 128-frame packets. The first fragment retains callback status flags, and later fragments set the flags to zero.

`sample_index` is the authoritative audio timeline. It is incremented by the actual frame count, starts at zero when the provider starts a session, and lets the receiving indexed buffer reorder packets and identify missing sample spans. `sequence` increments for each transmitted audio packet, but current loss accounting is based on absent sample ranges rather than assuming that sequence numbers arrive consecutively.

The flag bits are:

| Mask | Name | Meaning |
| ---: | --- | --- |
| `0x0001` | `INPUT_XRUN` | The provider's local callback observed input overflow or underflow. |
| `0x0002` | `OUTPUT_XRUN` | The provider's local callback observed output overflow or underflow. |

For capture packets, the client maps these conditions to its next network callback as input overflow and output underflow respectively. Missing capture samples are zero-filled and also reported as input overflow. For playback, a provider-side missing span after playback begins is rendered as silence, recorded as loss, and sets `OUTPUT_XRUN` on the capture packet emitted for that callback block.

## 8. Timing, buffering, and quality behavior

The client UI selects a fixed network buffer between 20 and 2,000 ms (100 ms by default). After receiving the offer, it is converted to an integral number of provider blocks and clamped to at least two blocks:

$$
J = \max\left(2B,\operatorname{round}\left(\frac{f_s t_J}{1000B}\right)B\right),
$$

where $J$ is jitter frames, $B$ is the offered block size, $f_s$ is the offered sample rate, and $t_J$ is the selected buffer in milliseconds. The client uses a playback scheduling delay of `max(2J, 4B)` frames. It begins its callback stream only after its capture buffer has enough audio at the requested jitter depth.

Both directions maintain bounded local queues/buffers sized to at least four seconds or sixteen blocks. A queue overflow drops that block and is recorded as lost frames. A late or duplicate packet is discarded and counted. Corrupt packets are discarded and counted; the client/provider continue running unless liveness or a transport failure ends the session. Once streaming has been primed, one capture read may wait at most one provider callback interval for its future jitter-buffer watermark. It then advances with silence/XRUN reporting instead of adding the previous fixed minimum wait of 250 ms. Reported stream latency uses the same sample timeline as callback timestamps: input latency is $J+B$, and output latency from callback time is $\max(0,D-J-B)$, where $D$ is the playback scheduling delay.

### 8.1 Optional audio retransmission

When negotiated, each audio sender retains recently transmitted datagrams for the negotiated retransmission window. The history entry capacity is derived from the sample rate, callback block size, packet size, and negotiated window, with one additional callback block retained at the count boundary. The receiver tracks bounded gaps in audio sequence numbers, waits briefly for normal packet reordering, and sends an `AUDIO_NACK` control message such as:

```json
{"direction":1,"sequences":[1204,1205,1206]}
```

`direction` is capture (`1`) or playback (`2`). A request contains at most 32 unique sequence numbers, and a receiver tracks at most 128 missing packets. The sender validates the session, peer address, direction, history lifetime, minimum resend interval, per-packet retry limit, and a global limit of 64 retransmissions per 100 ms before retransmitting the original audio datagram. The receiver waits 1 ms for ordinary reordering, then schedules up to eight NACK requests with RTT-aware exponential backoff compressed to fit the remaining window. The sender still retransmits each audio datagram at most three times. Socket wake-ups follow the next retry deadline instead of polling every 10 ms.

The client tracks capture gaps and the provider tracks playback gaps. Each gap also records the absolute sample position of its next received packet. A request expires at the earlier of the negotiated wall-clock window or that successor sample reaching playout, so retransmission can use all available time but cannot extend playout latency. A retransmitted packet is useful only while its absolute sample range remains in the indexed buffer; otherwise the existing late-packet and silence/XRUN behavior applies. Local callback XRUNs and local queue overflows never create retransmission requests because no recoverable network datagram exists for them. Status snapshots expose `deadline_recovery_rate` as recovered packets divided by recovered plus deadline-expired packets once at least one outcome is resolved.

## 9. Implementation scope

The protocol is implemented by the following source files:

- [`src/gui/widgets/remote_audio_io.py`](../../src/gui/widgets/remote_audio_io.py): user controls, endpoint configuration, and discovery presentation.
- [`src/core/network_audio/protocol.py`](../../src/core/network_audio/protocol.py): wire encoding, decoding, version constants, and limits.
- [`src/core/network_audio/discovery.py`](../../src/core/network_audio/discovery.py): active LAN discovery.
- [`src/core/network_audio/client.py`](../../src/core/network_audio/client.py): client handshake, streams, buffering, and liveness.
- [`src/core/network_audio/provider.py`](../../src/core/network_audio/provider.py): provider lifecycle, one-client policy, and local audio bridge.
