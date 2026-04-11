# Inverse Filter

![Inverse Filter](../assets/widgets/inverse_filter.png)

## Overview

A tool for creating and applying a filter to an audio file that "cancels out" a system's frequency response (such as the idiosyncrasies of speakers or microphones) obtained through measurement.

Imagine putting on a pair of blue-tinted sunglasses. Everything you see looks bluish, right? To restore the natural colors, you would need to wear another pair of glasses that adds the "opposite color of blue" (orange) over them.
The Inverse Filter is exactly this "opposite-color sunglasses" for sound. It measures the unique "quirks" (frequency response) of a microphone or speaker, and calculates the exact "reverse quirks" (inverse filter) needed to perfectly cancel them out. By applying this, you can synthesize audio that is remarkably close to an ideal, flat response, faithfully reproducing the original sound!

## Operations

### Load Calibration Data

First, you need to load the "medical record" (data) of the quirks you want to fix.

* **Reload from Memory**: Directly imports the latest measurement data that the app currently remembers, such as what you just measured with the `Network Analyzer`.
* **Load File**: Loads a previously saved calibration data file in `.json` format from your computer.

### Filter Design

Adjust the "strength" and "detail" of the correction filter based on the loaded data.

* **Max Gain (Regularization)**: The "maximum allowable limit" for boosting sound during correction.
* **FIR Taps**: The "resolution" or fineness of the filter. Think of it like the megapixels in a digital camera. A larger value (e.g., `8192` or `16384`) allows for highly precise correction of complex quirks, but it requires more computational power from your computer. Usually, around `8192` is recommended.
* **Smoothing**: Smooths out fine jaggedness (peaks and dips) in the characteristics, much like ironing a shirt. This helps prevent the sound from becoming unnatural due to overly sharp corrections.

### ☕ Coffee Break: Why is Max Gain (Regularization) necessary?

You might think, "If we're making an inverse filter, couldn't we just boost the missing sounds infinitely to make it perfectly flat?" However, reality isn't that simple.

If a speaker "cannot produce a specific frequency of sound at all (zero output)," the inverse filter will try its hardest by saying, "Let's multiply zero by infinity to make it flat!" But no matter what you multiply zero by, no sound will come out; instead, only the background "hissing" noise will be infinitely amplified into a loud roar.
**Max Gain** is the safety net that prevents this. For example, if set to "10dB," you are setting a rule that says, "Even if the original sound drops by 20dB, don't force it up; only boost it by a maximum of 10dB." This effectively prevents an explosion of noise.

### Audio Processing

* **Input**: Select the audio file (WAV format) you wish to cast the magic on (process).
* **Process & Save**: Saves a new, polished audio file with the filter applied.

## Settings

* **Normalize Output (RMS)**: Because correction boosts or cuts certain frequency ranges, the overall "perceived volume" might change. Checking this box automatically adjusts the volume (normalizes) so that the processed file has the same perceived loudness as the original file.

## Usage Examples

* **Microphone Correction**: If the frequency response (quirks) of your microphone is known, applying the inverse characteristic to a recorded voice can result in sound quality that is more faithful to the "true original voice."
* **Simple Room Acoustic Correction**: This can be utilized in acoustic research to bring recording results that include the specific reverberations of a room (reflections and standing waves) closer to a flat state.
