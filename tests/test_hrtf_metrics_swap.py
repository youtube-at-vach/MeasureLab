import numpy as np
from src.gui.widgets.hrtf_player import HRTFData

def test_hrtf_data_swap_metrics():
    # Mock data
    M = 10
    itd = np.array([10.0] * M)
    ild = np.array([3.0] * M)
    energy = np.array([-10.0] * M)
    delay = np.array([1.5] * M)

    # Dummy IR data (not used for this test of accessors, but required for dataclass)
    ir_data = np.zeros((M, 2, 100))
    pos = np.zeros((M, 3))

    data = HRTFData(
        source_positions=pos,
        ir_data=ir_data,
        sampling_rate=48000,
        itd=itd,
        ild=ild,
        energy_high=energy,
        group_delay_peak=delay
    )

    # Test Normal (swap_channels=False)
    assert np.allclose(data.get_itd(swap_channels=False), itd)
    assert np.allclose(data.get_ild(swap_channels=False), ild)
    assert np.allclose(data.get_energy_high(swap_channels=False), energy)
    assert np.allclose(data.get_group_delay_peak(swap_channels=False), delay)

    # Test Swapped (swap_channels=True)
    assert np.allclose(data.get_itd(swap_channels=True), -itd)
    assert np.allclose(data.get_ild(swap_channels=True), -ild)
    assert np.allclose(data.get_energy_high(swap_channels=True), energy)
    assert np.allclose(data.get_group_delay_peak(swap_channels=True), delay)
