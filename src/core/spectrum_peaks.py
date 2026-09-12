"""Bounded peak selection for the analyzer's optional GUI overlay."""

import numpy as np
from scipy.ndimage import minimum_filter1d
from scipy.signal import find_peaks, peak_prominences

MAX_PEAK_MARKERS = 5
PROMINENCE_WINDOW = 2049


def detect_spectrum_peaks(
    freqs, levels, prominence=6.0, spacing_hz=100.0, noise_floor=-90.0, *, frequency_range=None, level_range=None
):
    """Return up to five (Hz, level) pairs, strongest first.

    Prominence is local to at most 2049 source points. Spacing is in Hz,
    independent of FFT size or logarithmic display scale. Invalid points break
    the spectrum; neither they nor peaks bordering them are eligible.
    Duplicate display-envelope frequencies are collapsed to their maxima.
    """
    freqs = np.asarray(freqs)
    levels = np.asarray(levels)
    if freqs.ndim != 1 or levels.ndim != 1 or len(freqs) != len(levels) or len(freqs) < 3:
        return []
    if not np.all(np.isfinite([prominence, spacing_hz, noise_floor])) or prominence < 0 or spacing_hz < 0:
        return []
    differences = np.diff(freqs)
    if not np.all(np.isfinite(freqs)) or np.any(freqs < 0) or np.any(differences < 0):
        return []
    if np.any(differences == 0):
        starts = np.r_[0, np.flatnonzero(differences) + 1]
        levels = np.maximum.reduceat(levels, starts)
        freqs = freqs[starts]
    valid = np.isfinite(levels)
    safe = np.where(valid, levels, -np.inf)
    indices, _ = find_peaks(safe, height=noise_floor)
    indices = indices[valid[indices - 1] & valid[indices + 1] & (freqs[indices] > 0)]
    # Apply viewport eligibility before ranking so off-screen peaks cannot
    # consume the finite marker budget or suppress visible neighbors.
    for values, bounds in [(freqs, frequency_range), (levels, level_range)]:
        if bounds is not None:
            if len(bounds) != 2 or not np.all(np.isfinite(bounds)) or bounds[0] > bounds[1]:
                return []
            indices = indices[(values[indices] >= bounds[0]) & (values[indices] <= bounds[1])]
    # Usually only five prominence evaluations are needed, even for a dense comb.
    # If a stronger candidate fails, filter the remaining candidates in one batch;
    # this prevents an unbounded series of argmax scans on rejected candidates.
    candidates = safe[indices].copy()
    candidate_freqs = freqs[indices]
    selected = []
    prominence_checked = False
    while len(selected) < MAX_PEAK_MARKERS and len(indices):
        best = int(np.argmax(candidates))
        if not np.isfinite(candidates[best]):
            break
        index = indices[best]
        if not prominence_checked:
            local = peak_prominences(safe, [index], wlen=PROMINENCE_WINDOW)[0][0]
            if not np.isfinite(local) or local < prominence:
                eligible = np.flatnonzero(np.isfinite(candidates))
                if len(eligible) > 256:
                    # An absolute span bound cheaply rejects impossible thresholds.
                    candidates[candidates - np.min(safe) < prominence] = -np.inf
                    eligible = np.flatnonzero(np.isfinite(candidates))
                if len(eligible) > 256:
                    # Sliding minima give an upper bound on local prominence in O(N).
                    # Skip this full-array pass for sparse spectra. On dense combs,
                    # it avoids O(N * window) work when all candidates fail.
                    half = PROMINENCE_WINDOW // 2
                    left = minimum_filter1d(safe, size=half + 1, origin=half // 2, mode="nearest")
                    right = minimum_filter1d(safe, size=half + 1, origin=-half // 2, mode="nearest")
                    possible = safe[indices] - np.maximum(left[indices], right[indices])
                    eligible = np.flatnonzero((possible >= prominence) & np.isfinite(candidates))
                    candidates[possible < prominence] = -np.inf
                actual = peak_prominences(safe, indices[eligible], wlen=PROMINENCE_WINDOW)[0]
                candidates[eligible[(actual < prominence) | ~np.isfinite(actual)]] = -np.inf
                prominence_checked = True
                continue
        selected.append((float(freqs[index]), float(levels[index])))
        start = np.searchsorted(candidate_freqs, freqs[index] - spacing_hz, side="right")
        end = np.searchsorted(candidate_freqs, freqs[index] + spacing_hz, side="left")
        candidates[start:end] = -np.inf
        candidates[best] = -np.inf
    return selected
