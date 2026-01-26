
import sys
import numpy as np
import pytest
from unittest.mock import MagicMock

# Mock sounddevice
sd_mock = MagicMock()
sys.modules['sounddevice'] = sd_mock

from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer
from src.core.audio_engine import AudioEngine

@pytest.fixture
def analyzer():
    engine = MagicMock(spec=AudioEngine)
    engine.sample_rate = 48000
    engine.register_callback = MagicMock(return_value=1)
    sa = SpectrumAnalyzer(engine)
    sa.buffer_size = 100 # Small buffer for easier testing
    sa.start_analysis()
    return sa

def test_ring_buffer_logic(analyzer):
    callback = analyzer.audio_engine.register_callback.call_args[0][0]

    # 1. Fill buffer partially
    # Buffer size 100. Write 60.
    indata = np.ones((60, 2), dtype=np.float32) * 0.5
    outdata = np.zeros((60, 2), dtype=np.float32)

    callback(indata, outdata, 60, 0, 0)

    assert analyzer.write_head == 60
    # Check data content in buffer
    assert np.all(analyzer.input_data[0:60] == 0.5)

    # Check retrieved data (unrolled)
    # The analyzer logic for unrolling is in update_plot usually,
    # but we can simulate it:
    head = analyzer.write_head
    unrolled = np.concatenate((analyzer.input_data[head:], analyzer.input_data[:head]))

    # Since we filled 60, remaining 40 are 0 (initially).
    # head is 60.
    # [60:] (indices 60-99) are 0.
    # [:60] (indices 0-59) are 0.5.
    # Unrolled: [zeros(40), ones(60)*0.5]
    # This represents the sliding window history. Correct.
    assert np.all(unrolled[0:40] == 0.0)
    assert np.all(unrolled[40:100] == 0.5)

def test_ring_buffer_wrap(analyzer):
    callback = analyzer.audio_engine.register_callback.call_args[0][0]

    # Buffer 100.
    # Write 80.
    indata1 = np.ones((80, 2), dtype=np.float32) * 1.0
    outdata = np.zeros((80, 2), dtype=np.float32)
    callback(indata1, outdata, 80, 0, 0)

    assert analyzer.write_head == 80

    # Write 40. Should wrap.
    # 80 + 40 = 120. 20 wrapped.
    indata2 = np.ones((40, 2), dtype=np.float32) * 2.0
    callback(indata2, outdata, 40, 0, 0)

    assert analyzer.write_head == 20

    # Buffer state:
    # Indices 0-19: 2.0 (wrapped part of write 2)
    # Indices 20-79: 1.0 (remnant of write 1)
    # Indices 80-99: 2.0 (first part of write 2)

    assert np.all(analyzer.input_data[0:20] == 2.0)
    assert np.all(analyzer.input_data[20:80] == 1.0)
    assert np.all(analyzer.input_data[80:100] == 2.0)

    # Check unrolled
    head = analyzer.write_head # 20
    unrolled = np.concatenate((analyzer.input_data[head:], analyzer.input_data[:head]))
    # [20:] -> indices 20-99.
    #   20-79: 1.0 (60 samples)
    #   80-99: 2.0 (20 samples)
    # [:20] -> indices 0-19.
    #   0-19: 2.0 (20 samples)

    # Result: 60 samples of 1.0, followed by 40 samples of 2.0.
    # This correctly represents history: Oldest (1.0) -> Newest (2.0).
    assert np.all(unrolled[0:60] == 1.0)
    assert np.all(unrolled[60:100] == 2.0)

def test_allocation_check(analyzer):
    callback = analyzer.audio_engine.register_callback.call_args[0][0]
    initial_id = id(analyzer.input_data)

    indata = np.zeros((50, 2), dtype=np.float32)
    outdata = np.zeros((50, 2), dtype=np.float32)

    callback(indata, outdata, 50, 0, 0)

    new_id = id(analyzer.input_data)
    assert new_id == initial_id
