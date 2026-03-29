import re

with open("src/core/analysis.py", "r") as f:
    content = f.read()

content = re.sub(
    r'def _calculate_hum_noise\(mag_sq, freqs, sampling_rate, bin_width, axis_info=0\.0\):',
    'def _calculate_hum_noise(mag_sq, freqs, sampling_rate, bin_width, axis_info: FreqAxisInfo):',
    content
)
content = re.sub(
    r'def _calculate_white_noise\(mag, freqs, axis_info=0\.0\):',
    'def _calculate_white_noise(mag, freqs, axis_info: FreqAxisInfo):',
    content
)
content = re.sub(
    r'def _calculate_1f_noise\(mag, freqs, hum_components, white_density, axis_info=0\.0\):',
    'def _calculate_1f_noise(mag, freqs, hum_components, white_density, axis_info: FreqAxisInfo):',
    content
)
content = re.sub(
    r'def _calculate_integrated_noise\(mag_sq, freqs, bin_width, axis_info=0\.0\):',
    'def _calculate_integrated_noise(mag_sq, freqs, bin_width, axis_info: FreqAxisInfo):',
    content
)
content = re.sub(
    r'def _calculate_peak_noise\(mag, freqs, axis_info=0\.0\):',
    'def _calculate_peak_noise(mag, freqs, axis_info: FreqAxisInfo):',
    content
)
content = re.sub(
    r'def _get_freq_index\(freqs, f, axis_info: FreqAxisInfo=0\.0, side="left"\):',
    'def _get_freq_index(freqs, f, axis_info: FreqAxisInfo, side="left"):',
    content
)

with open("src/core/analysis.py", "w") as f:
    f.write(content)
