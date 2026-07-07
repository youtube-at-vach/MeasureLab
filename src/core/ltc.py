from typing import Optional
import collections

import numpy as np


SYNC_WORD = 0xBFFC  # 1011 1111 1111 1100 (Reverse of 0011 1111 1111 1101 ?)


class LTCEncoder:
    """Generates LTC audio samples."""

    def __init__(self, sample_rate: int, fps: float):
        self.sample_rate = sample_rate
        self.fps = fps
        self.samples_per_frame = sample_rate / fps
        self.current_frame_samples = 0
        self.phase = 1.0  # -1.0 or 1.0

        # State
        self.total_frames = 0
        self.samples_generated = 0.0  # Accumulator to prevent drift

    def reset(self):
        """Resets the encoder state."""
        self.samples_generated = 0.0
        self.phase = 1.0
        self.total_frames = 0

    def set_fps(self, fps: float):
        self.fps = fps
        self.samples_per_frame = self.sample_rate / fps
        self.samples_generated = 0.0

    def generate_frame(
        self,
        hh: int,
        mm: int,
        ss: int,
        ff: int,
        user_bits: Optional[list] = None,
        out_buffer: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """Generates audio samples for one LTC frame."""
        bits = [0] * 80

        # Helper to set bits
        def set_b(idx, val):
            if 0 <= idx < 80:
                bits[idx] = 1 if val else 0

        # Timecode Data (BCD)
        # IMPORTANT: these are BCD digits, not binary values.

        # Frame
        ff_u = int(ff) % 10
        ff_t = int(ff) // 10
        set_b(0, ff_u & 1)
        set_b(1, ff_u & 2)
        set_b(2, ff_u & 4)
        set_b(3, ff_u & 8)
        set_b(8, ff_t & 1)
        set_b(9, ff_t & 2)

        # Seconds
        ss_u = int(ss) % 10
        ss_t = int(ss) // 10
        set_b(16, ss_u & 1)
        set_b(17, ss_u & 2)
        set_b(18, ss_u & 4)
        set_b(19, ss_u & 8)
        set_b(24, ss_t & 1)
        set_b(25, ss_t & 2)
        set_b(26, ss_t & 4)

        # Minutes
        mm_u = int(mm) % 10
        mm_t = int(mm) // 10
        set_b(32, mm_u & 1)
        set_b(33, mm_u & 2)
        set_b(34, mm_u & 4)
        set_b(35, mm_u & 8)
        set_b(40, mm_t & 1)
        set_b(41, mm_t & 2)
        set_b(42, mm_t & 4)

        # Hours
        hh_u = int(hh) % 10
        hh_t = int(hh) // 10
        set_b(48, hh_u & 1)
        set_b(49, hh_u & 2)
        set_b(50, hh_u & 4)
        set_b(51, hh_u & 8)
        set_b(56, hh_t & 1)
        set_b(57, hh_t & 2)

        # Sync Word (Bits 64-79): 0011 1111 1111 1101
        sync_pattern = [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1]
        for i, b in enumerate(sync_pattern):
            bits[64 + i] = b

        # Bi-phase Mark Encoding
        # Transition at start of every bit window.
        # If '1', transition also in middle.

        # Calculate exact start and end in global timeline
        start_abs = self.samples_generated
        end_abs = self.samples_generated + self.samples_per_frame

        # Calculate how many integer samples to output in this frame
        start_sample_idx = int(start_abs)
        end_sample_idx = int(end_abs)
        req_size = end_sample_idx - start_sample_idx

        if out_buffer is not None and len(out_buffer) >= req_size:
            samples = out_buffer
        else:
            samples = np.zeros(req_size, dtype=np.float32)

        current_level = self.phase

        # We generate samples with sub-sample precision reference to the absolute start
        for bit_idx, bit_val in enumerate(bits):
            # Calculate absolute bit boundaries
            bit_start_abs = start_abs + bit_idx * (self.samples_per_frame / 80.0)
            bit_end_abs = start_abs + (bit_idx + 1) * (self.samples_per_frame / 80.0)
            bit_mid_abs = start_abs + (bit_idx + 0.5) * (self.samples_per_frame / 80.0)

            # Map to frame-relative integer indices
            bit_start_rel = max(0, int(bit_start_abs) - start_sample_idx)
            bit_end_rel = min(req_size, int(bit_end_abs) - start_sample_idx)
            bit_mid_rel = max(0, min(req_size, int(bit_mid_abs) - start_sample_idx))

            current_level = -current_level  # Transition at start of bit

            if bit_val == 0:
                count = bit_end_rel - bit_start_rel
                if count > 0:
                    samples[bit_start_rel:bit_end_rel] = current_level
            else:
                # 1 -> Transition at mid
                count1 = bit_mid_rel - bit_start_rel
                if count1 > 0:
                    samples[bit_start_rel:bit_mid_rel] = current_level

                current_level = -current_level  # Mid transition

                count2 = bit_end_rel - bit_mid_rel
                if count2 > 0:
                    samples[bit_mid_rel:bit_end_rel] = current_level

        # Update phase and global accumulator for next frame
        self.phase = current_level
        self.samples_generated = end_abs
        self.total_frames += 1

        return samples[:req_size]


class LTCDecoder:
    """Decodes audio samples to Timecode."""

    def __init__(self, sample_rate: float, fps: float):
        self.sample_rate = sample_rate
        self.fps = fps
        self.samples_since_last_zc = 0
        self._last_sign: Optional[bool] = None
        self.bit_stream = 0
        self.bits_count = 0
        self.current_bits: list[int] = []
        self.last_bit_is_one = False

        # Pulse Width discrimination
        # Initial guess for half-bit (Short pulse)
        # 80 bits per frame.
        self.pulse_avg = (sample_rate / fps) / 160.0

        self.decoded_bits: collections.deque[int] = collections.deque(maxlen=160)
        self.sync_val = 0
        self.decoded_tc = "--:--:--:--"
        self.locked = False

        self.total_samples = 0
        self.last_frame_offset_in_chunk: Optional[int] = None

    def reset(self, sample_rate: float, fps: float):
        self.sample_rate = sample_rate
        self.fps = fps
        self.samples_since_last_zc = 0
        self._last_sign = None
        self.bit_stream = 0
        self.bits_count = 0
        self.current_bits = []
        self.last_bit_is_one = False

        # Pulse Width discrimination
        # Initial guess for half-bit (Short pulse)
        # 80 bits per frame.
        self.pulse_avg = (sample_rate / fps) / 160.0

        self.decoded_bits.clear()
        self.sync_val = 0
        self.decoded_tc = "--:--:--:--"
        self.locked = False

        self.total_samples = 0
        self.last_frame_offset_in_chunk = None

    def process_samples(self, samples: Optional[np.ndarray]):
        """Process a chunk of audio samples. Returns True if a new frame was decoded."""
        # Vectorized zero-crossing (sign change) detection.
        # IMPORTANT: we must not miss a transition that occurs exactly at the
        # buffer boundary. We therefore track the sign of the last sample from
        # the previous call and synthesize a crossing at position 0 if needed.
        if samples is None:
            return False

        samples = np.asarray(samples)
        frames_in_chunk = int(samples.shape[0])
        if frames_in_chunk <= 0:
            return False

        decoded_any = False
        chunk_base = int(self.total_samples)
        self.last_frame_offset_in_chunk = None

        signs = np.signbit(samples)
        if self._last_sign is None:
            self._last_sign = bool(signs[0])

        signs_with_last = np.empty(signs.size + 1, dtype=bool)
        signs_with_last[0] = self._last_sign
        signs_with_last[1:] = signs

        crossing_positions = np.nonzero(signs_with_last[1:] != signs_with_last[:-1])[0]

        if crossing_positions.size > 0:
            # Combine the first position with the samples from the previous chunk
            # and calculate consecutive differences between all other positions.
            diffs = np.diff(crossing_positions, prepend=-self.samples_since_last_zc)

            valid = diffs > 0
            for pos, d in zip(crossing_positions[valid].tolist(), diffs[valid].tolist(), strict=False):
                if self._process_pulse(float(d)):
                    self.last_frame_offset_in_chunk = int(pos)
                    decoded_any = True

            # Residual samples since the last crossing within this chunk.
            last_pos = crossing_positions[-1]
            self.samples_since_last_zc = frames_in_chunk - last_pos
        else:
            self.samples_since_last_zc += frames_in_chunk

        self._last_sign = bool(signs[-1])
        self.total_samples = int(chunk_base) + int(frames_in_chunk)
        return decoded_any

    def _process_pulse(self, d: float) -> bool:
        """Returns True if a frame completion was triggered."""
        # Adaptive discriminator
        # Long pulse ~ 2 * Short pulse

        # Initial guess or update
        if self.pulse_avg == 0:
            self.pulse_avg = d

        # Use simple IIR for average tracking
        # We assume we track the Short pulse duration

        threshold = self.pulse_avg * 1.5

        frame_decoded = False

        if d > threshold:
            # Long Pulse -> '0'
            self._push_bit(0)
            if self._check_sync():
                frame_decoded = True

            self.last_bit_is_one = False
            # Update average towards Long/2 -> Short
            self.pulse_avg = 0.95 * self.pulse_avg + 0.05 * (d / 2.0)
        else:
            # Short Pulse
            if self.last_bit_is_one:
                # Second short -> '1'
                self._push_bit(1)
                if self._check_sync():
                    frame_decoded = True
                self.last_bit_is_one = False
            else:
                self.last_bit_is_one = True

            self.pulse_avg = 0.95 * self.pulse_avg + 0.05 * d

        return frame_decoded

    def _push_bit(self, bit: int):
        self.decoded_bits.append(bit)
        self.sync_val = ((self.sync_val << 1) | bit) & 0xFFFF

    def _check_sync(self) -> bool:
        if len(self.decoded_bits) >= 16:
            # Check last 16 bits for Sync Word 0x3FFD (0011 1111 1111 1101)
            # bits are pushed 0 or 1.
            # We need to construct integer.

            # Optimization: could allow reverse play, but for now forward only

            if self.sync_val == 0x3FFD:
                if len(self.decoded_bits) >= 80:
                    frame_bits = list(self.decoded_bits)[-80:]
                    self._decode_frame_bits(frame_bits)
                    return True
        return False

    def _decode_frame_bits(self, bits):
        ff_ones = bits[0] | (bits[1] << 1) | (bits[2] << 2) | (bits[3] << 3)
        ff_tens = bits[8] | (bits[9] << 1)
        ff = ff_tens * 10 + ff_ones

        ss_ones = bits[16] | (bits[17] << 1) | (bits[18] << 2) | (bits[19] << 3)
        ss_tens = bits[24] | (bits[25] << 1) | (bits[26] << 2)
        ss = ss_tens * 10 + ss_ones

        mm_ones = bits[32] | (bits[33] << 1) | (bits[34] << 2) | (bits[35] << 3)
        mm_tens = bits[40] | (bits[41] << 1) | (bits[42] << 2)
        mm = mm_tens * 10 + mm_ones

        hh_ones = bits[48] | (bits[49] << 1) | (bits[50] << 2) | (bits[51] << 3)
        hh_tens = bits[56] | (bits[57] << 1)
        hh = hh_tens * 10 + hh_ones

        self.decoded_tc = f"{hh:02}:{mm:02}:{ss:02}:{ff:02}"
        self.locked = True
