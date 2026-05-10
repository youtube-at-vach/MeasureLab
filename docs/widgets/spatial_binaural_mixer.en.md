# Spatial Binaural Mixer

The **Spatial Binaural Mixer** is a high-quality, offline 3D spatial audio rendering module designed for placing multiple independent source tracks in a virtual 3D space using Head-Related Transfer Functions (HRTF / SOFA files).

Unlike real-time HRTF players, this module is specifically engineered for multi-track stem rendering. It employs block-less FFT convolution and high-precision spatial interpolation, ensuring the absolute highest sound quality for mixing and exporting spatial audio.

## ☕ Coffee Break: The Magic of Spatial/Binaural Audio

When a mosquito comes buzzing in the dark, we immediately know, "Ah, it's behind me to the right!" even with our eyes closed. But humans only have two ears (microphones), one on the left and one on the right. How can we tell "behind" or "above/below" with just two microphones?

The secret lies in the "shape of our earlobes" and the "roundness of our head"!
When sound comes from behind versus when it comes from the front, the way it reflects off the earlobes changes slightly, causing complex changes in the "color (frequency response)" and "arrival timing" of the sound. The brain instantly calculates these changes to pinpoint the sound's location.
The "HRTF (Head-Related Transfer Function)" is a complete recording and digitization of this "pattern of changes that the head and ears apply to sound."

This Spatial Binaural Mixer is a tool that multiplies (convolves) ordinary sound with this HRTF data (SOFA files)—the "magic of the earlobe." By using this, just by listening with normal headphones, sounds will magically appear to come from a 3D space outside your head!

---

## 🌟 Key Features

* **Multitrack Support**: Load multiple audio files (WAV, FLAC, MP3, etc.) and independently control their spatial position (Azimuth, Elevation), volume (Gain), and mute/solo states.
* **IDW Spatial Interpolation**: Uses Inverse Distance Weighting interpolation between the nearest measured HRIR points from the SOFA file to smoothly synthesize any arbitrary angle, extending the precision beyond the original SOFA grid.
* **Offline Block-less FFT Convolution**: Bypasses real-time buffer overlap-add mechanisms, convolving the entire audio track perfectly at once (`scipy.signal.fftconvolve`) to prevent any windowing artifacts or zipper noise.
* **Float64 Processing**: Internal summing bus operates in 64-bit floating point precision, ensuring absolute headroom before final normalization and export.
* **Highest Quality Resampling**: Synchronizes mixed sample rates natively using Polyphase Sinc interpolation (`resample_poly`).

---

## 🎛️ Usage Guide

### 1. Spatial Settings (SOFA)

Choose the HRTF filter dataset you want to use for the acoustic space.

* Click **Load SOFA** and select a `.sofa` or `.nc` format file.

### 2. Track Setup

Add the individual sound sources (e.g., Vocals, Drums, Bass) you want to spatialize.

1. Click **Add Track**.
2. For each added track row:
   * **Load Audio**: Select the source audio file. Mono files are spatialized natively; stereo files will be summed to mono uniformly to act as a point source before dual channel convolution.
   * **Azimuth**: Horizontal angle in degrees.
     * `0°`: Dead center front.
     * `+90°`: Straight to the right ear.
     * `-90°`: Straight to the left ear.
     * `180° / -180°`: Dead center behind.
   * **Elevation**: Vertical angle in degrees.
     * `0°`: Eye level horizontal plane.
     * `+90°`: Directly above the head (Zenith).
     * `-90°`: Directly below the head (Nadir).
   * **Gain**: Control the relative volume of the track in the final mix.
   * **Mute/Solo**: Quickly isolate or ignore tracks during monitor testing.
   * **XButton**: Removes the track.

### 3. Preview Settings

Use these settings to render and monitor only a specific portion of the tracks.

* **Preview Mode**: Enable to process only a segment of the audio instead of the full tracks.
* **Start**: The starting point of the preview segment in seconds.
* **Duration**: The length of the preview segment to process in seconds.
* **◀ / ▶ Buttons**: Quickly shift the start time backward or forward by the set duration to navigate through the tracks.

### 4. Rendering and Exporting

Because the module is optimized for quality over real-time responsiveness, audio is processed completely before playback or saving.

* **▶ Render & Monitor**: Renders the complete mixed tracks directly into RAM, then plays it out through MeasureLab's active audio device. Rendering time depends on the number of tracks and the track length. Progress is shown in a popup, and the process can be cancelled at any time.
* **⏸ Stop Monitor**: Immediately halts playback of the rendered RAM buffer.
* **Render to WAV**: Processes the mix and opens a dialog to save the result directly to your disk as a 32-bit Float WAV file, locking the peak volume to standard maximum (`0.99 FS` to avoid clipping).

## 💡 Practical Examples

* **Stem Breakdown**: Import vocals, bass, keys and drums separately. Set vocals to Center (`Az 0, El 10`), Drums to bottom rear, and keys off to the wide sides. Render the mix for an immersive binaural song.
* **ASMR / Narrative**: Import multiple voice tracks and sound effects, spread them across the full 3D sphere to mimic a realistic story scene, and export the unified high-fidelity scene to WAV.
