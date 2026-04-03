import timeit

setup = """
class SignalParameters:
    def __init__(self):
        self.waveform = "pulse"
        self.pm_enabled = True
        self.pm_frequency = 10.0
        self.pm_deviation_deg = 5.0

params = SignalParameters()
PERIODIC_WAVEFORMS = {"sine", "square", "triangle", "sawtooth", "pulse", "tone_noise"}
"""

test_list = """
use_pm = bool(
    params.pm_enabled
    and params.pm_frequency > 0
    and params.pm_deviation_deg != 0
    and params.waveform in ["sine", "square", "triangle", "sawtooth", "pulse", "tone_noise"]
)
"""

test_set = """
use_pm = bool(
    params.pm_enabled
    and params.pm_frequency > 0
    and params.pm_deviation_deg != 0
    and params.waveform in PERIODIC_WAVEFORMS
)
"""

n_runs = 20_000_000
time_list = timeit.timeit(test_list, setup=setup, number=n_runs)
time_set = timeit.timeit(test_set, setup=setup, number=n_runs)

print(f"List lookup: {time_list:.4f} seconds")
print(f"Set lookup:  {time_set:.4f} seconds")
print(f"Improvement: {(time_list - time_set) / time_list * 100:.2f}%")
