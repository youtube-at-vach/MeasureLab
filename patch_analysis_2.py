import re

with open("src/core/analysis.py", "r") as f:
    content = f.read()

# Fix the `axis_info=0.0` issue and the unpack vs attribute usage issue
content = re.sub(
    r'axis_info: FreqAxisInfo = 0\.0\)',
    'axis_info: FreqAxisInfo)',
    content
)

content = re.sub(
    r'axis_info: FreqAxisInfo=0\.0\)',
    'axis_info: FreqAxisInfo)',
    content
)

content = re.sub(
    r'axis_info=0\.0',
    'axis_info',
    content
)

# And ensure we consistently unpack it at the top of methods
# This has been done mostly, but let's make sure `axis_info.is_linear_freqs` is not used in `_calculate_a_weighted_noise`
# _calculate_a_weighted_noise unpacks it:
# is_linear_freqs, is_log_freqs, freq_step, start_freq, stop_freq = axis_info
# Let's fix that specific method:
content = re.sub(
    r'if axis_info\.is_linear_freqs:',
    'if is_linear_freqs:',
    content
)
# Wait, let's verify if `is_linear_freqs` is defined locally in those scopes.
# In `calculate_noise_profile`:
# axis_info = AudioCalc._analyze_frequency_axis(freqs)
# if axis_info.is_linear_freqs: <-- this is correct and should not be replaced.
# Let's just do a safer replace using merge diffs.

with open("test_output3.py", "w") as f:
    f.write(content)
