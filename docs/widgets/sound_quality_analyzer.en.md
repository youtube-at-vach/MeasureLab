# Sound Quality Analyzer (Sound Quality Evaluation & Psychoacoustic Analysis)

![Sound Quality Analyzer](../assets/widgets/sound_quality_analyzer.png)

## Overview
This tool is used to quantify how sound is perceived by the human ear ("subjective quantity"). Instead of simply measuring voltage or sound pressure, it uses metrics based on psychoacoustics to objectively evaluate the pleasantness or unpleasantness of a sound.

This tool is for **offline analysis only**. It analyzes pre-recorded audio files (WAV, etc.).

## Metric Descriptions (Metrics)

*   **Integrated Loudness**: An average value of "sound volume" that takes into account the sensitivity characteristics of the human ear (K-weighting, which is similar to A-weighting). The unit is `LUFS`.
*   **Sharpness**: Represents the "sharpness" or "metallic" quality of a sound. Higher values indicate more high-frequency components. The unit is `acum`.
*   **Roughness**: Represents the "graininess" or "roughness" of a sound. It evaluates unpleasant modulations (around 70 Hz, for example) that cause a sensation of "roughness."
*   **Tonality**: Represents the extent to which the sound contains "sine-wave-like components." Sounds like white noise have low tonality, while sounds like a whistle or a pure sine wave have high tonality.

## Operation

1.  Click **Load File** to select an audio file.
2.  Press the **Analyze** button to start the analysis (long files may take some time).
3.  Once the analysis is complete, the **Summary Metrics** will display the average values for each channel.
4.  The graph below shows how each of these metrics "changed over time."

### Playback and Verification
*   **Playback Button (▶)**: Plays the analyzed audio file.
*   **Follow Cursor**: The yellow cursor on the graph moves in synchronization with the playback. You can listen to the sound at specific "high (or low) value locations."

## Use Cases
*   **Analysis of Unpleasant Noise**: Quantifies "why" fan or motor noise is annoying using metrics like roughness and sharpness.
*   **Sound Design Evaluation**: Verifies if product operation sounds or notification sounds match the intended image (e.g., gentle, sharp, powerful).
