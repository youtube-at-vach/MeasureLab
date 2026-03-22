import collections

import numpy as np

from src.core.ltc import LTCDecoder, LTCEncoder


def test_ltc_encoder_init():
    """Test LTCEncoder initialization."""
    sample_rate = 48000
    fps = 30.0
    encoder = LTCEncoder(sample_rate, fps)

    assert encoder.sample_rate == sample_rate
    assert encoder.fps == fps
    assert encoder.samples_per_frame == sample_rate / fps
    assert encoder.total_frames == 0
    assert encoder.current_frame_samples == 0
    assert encoder.phase == 1.0


def test_ltc_encoder_set_fps():
    """Test LTCEncoder set_fps updates fps and samples_per_frame."""
    encoder = LTCEncoder(48000, 30.0)
    assert encoder.samples_per_frame == 1600.0

    encoder.set_fps(25.0)
    assert encoder.fps == 25.0
    assert encoder.samples_per_frame == 48000 / 25.0


def test_ltc_encoder_generate_frame():
    """Test LTCEncoder generate_frame creates valid output array."""
    sample_rate = 48000
    fps = 30.0
    encoder = LTCEncoder(sample_rate, fps)

    # 48000 / 30 = 1600 samples per frame
    samples = encoder.generate_frame(10, 15, 30, 12)

    assert isinstance(samples, np.ndarray)
    assert samples.dtype == np.float32
    # The output size might slightly vary depending on precise bit calculations
    # but it should be approximately samples_per_frame
    assert len(samples) >= 1599
    assert len(samples) <= 1602


def test_ltc_encoder_generate_frame_buffer():
    """Test LTCEncoder generate_frame with pre-allocated buffer."""
    sample_rate = 48000
    fps = 30.0
    encoder = LTCEncoder(sample_rate, fps)

    req_size = int(encoder.samples_per_frame) + 2
    buffer = np.zeros(req_size, dtype=np.float32)

    samples = encoder.generate_frame(10, 15, 30, 12, out_buffer=buffer)

    assert samples.base is buffer
    assert len(samples) <= req_size


def test_ltc_decoder_init():
    """Test LTCDecoder initialization."""
    sample_rate = 48000
    fps = 30.0
    decoder = LTCDecoder(sample_rate, fps)

    assert decoder.sample_rate == sample_rate
    assert decoder.fps == fps
    assert decoder.samples_since_last_zc == 0
    assert decoder._last_sign is None
    assert decoder.bit_stream == 0
    assert decoder.bits_count == 0
    assert decoder.current_bits == []
    assert decoder.last_bit_is_one is False
    assert decoder.pulse_avg == (sample_rate / fps) / 160.0
    assert isinstance(decoder.decoded_bits, collections.deque)
    assert decoder.decoded_bits.maxlen == 160
    assert decoder.sync_val == 0
    assert decoder.decoded_tc == "--:--:--:--"
    assert decoder.locked is False
    assert decoder.total_samples == 0
    assert decoder.last_frame_offset_in_chunk is None


def test_ltc_decoder_reset():
    """Test LTCDecoder reset method."""
    sample_rate = 48000
    fps = 30.0
    decoder = LTCDecoder(sample_rate, fps)

    decoder.samples_since_last_zc = 100
    decoder.locked = True
    decoder.decoded_tc = "10:10:10:10"
    decoder.decoded_bits.append(1)

    decoder.reset(44100, 25.0)

    assert decoder.sample_rate == 44100
    assert decoder.fps == 25.0
    assert decoder.samples_since_last_zc == 0
    assert decoder.locked is False
    assert decoder.decoded_tc == "--:--:--:--"
    assert len(decoder.decoded_bits) == 0


def test_ltc_decoder_process_samples_none_or_empty():
    """Test LTCDecoder process_samples with None or empty array."""
    decoder = LTCDecoder(48000, 30.0)

    assert decoder.process_samples(None) is False
    assert decoder.process_samples(np.array([])) is False
    assert decoder.process_samples(np.array([], dtype=np.float32)) is False


def test_ltc_decoder_process_samples_no_crossing():
    """Test LTCDecoder process_samples when no zero crossing occurs."""
    decoder = LTCDecoder(48000, 30.0)
    samples = np.ones(100, dtype=np.float32)

    assert decoder.process_samples(samples) is False
    assert decoder.samples_since_last_zc == 100
    assert decoder.total_samples == 100

    assert decoder.process_samples(samples) is False
    assert decoder.samples_since_last_zc == 200
    assert decoder.total_samples == 200


def test_ltc_decoder_process_pulse_long_short():
    """Test LTCDecoder _process_pulse logic for long and short pulses."""
    decoder = LTCDecoder(48000, 30.0)

    # 48000 / 30 = 1600 samples/frame, 80 bits/frame = 20 samples/bit
    # Long pulse ~ 20 samples (represents bit '0')
    # Short pulse ~ 10 samples (represents half of bit '1')
    decoder.pulse_avg = 10.0

    # Send a long pulse (> 15) -> decodes to 0
    decoded = decoder._process_pulse(20.0)
    assert not decoded
    assert decoder.decoded_bits[-1] == 0
    assert decoder.last_bit_is_one is False

    # Send a short pulse (< 15) -> waits for second short pulse
    decoded = decoder._process_pulse(10.0)
    assert not decoded
    assert decoder.last_bit_is_one is True

    # Send second short pulse (< 15) -> decodes to 1
    decoded = decoder._process_pulse(10.0)
    assert not decoded
    assert decoder.decoded_bits[-1] == 1
    assert decoder.last_bit_is_one is False


def test_ltc_decoder_check_sync_and_decode():
    """Test LTCDecoder _check_sync and _decode_frame_bits via direct bit injection."""
    decoder = LTCDecoder(48000, 30.0)

    # Timecode 12:34:56:12
    # BCD encoding
    # Frames: 12 (0010 0001)
    ff_bits = [0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0]  # 16 bits
    # Seconds: 56 (0110 0101)
    ss_bits = [0, 1, 1, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0]  # 16 bits
    # Minutes: 34 (0100 0011)
    mm_bits = [0, 0, 1, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0]  # 16 bits
    # Hours: 12 (0010 0001)
    hh_bits = [0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0]  # 16 bits
    # Sync Word: 0x3FFD (0011 1111 1111 1101) reversed as per bit order?
    # No, sync pattern in bit 64-79: 0011 1111 1111 1101 = 0x3FFD
    sync_bits = [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1]  # 16 bits

    all_bits = ff_bits + ss_bits + mm_bits + hh_bits + sync_bits

    # Inject bits and check sync
    for bit in all_bits:
        decoder._push_bit(bit)

    assert decoder._check_sync() is True
    assert decoder.locked is True
    assert decoder.decoded_tc == "12:34:56:12"


def test_ltc_encoder_decoder_roundtrip():
    """Test encoding a frame and successfully decoding it."""
    sample_rate = 48000
    fps = 30.0
    encoder = LTCEncoder(sample_rate, fps)
    decoder = LTCDecoder(sample_rate, fps)

    # We might need multiple frames because of boundary conditions and phase tracking
    frames = [encoder.generate_frame(10, 15, 30, ff) for ff in [11, 12, 13]]
    audio_stream = np.concatenate(frames)

    decoded_tcs = []

    # Process in chunks to simulate real-time buffering
    chunk_size = 512
    for i in range(0, len(audio_stream), chunk_size):
        chunk = audio_stream[i : i + chunk_size]
        if decoder.process_samples(chunk):
            decoded_tcs.append(decoder.decoded_tc)

    assert decoder.locked is True
    assert len(decoded_tcs) > 0
    assert "10:15:30:12" in decoded_tcs
