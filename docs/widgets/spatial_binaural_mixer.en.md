# Spatial Binaural Mixer

## Overview

Place multiple audio files around a listener, render them through a stereo HRTF dataset,
and monitor or export the binaural mix. Processing is offline: position and gain changes
apply to the next render. Editing the mix stops the previous monitor playback.

The workspace combines a top-view azimuth map with numbered track cards. The map shows
direction only, not source distance or elevation. Both light and dark themes are supported.

## Load and position sources

1. Choose **Load SOFA** to load a stereo HRIR dataset (`.sofa` or `.nc`). The shared loader
   expects spherical source positions in degrees and impulse responses for two ears.
2. Choose **Add Audio Files** to import several files together, or **Add Track** to create
   an empty card and use **Load Audio** to choose or replace its source.
3. Select a numbered card, then click or drag in the map to change its azimuth. You can
   also enter an exact angle in the card. With the map focused, Left/Right changes the
   angle by 1°, Shift+Left/Right by 10°, and Home returns it to the front.
4. Set elevation and gain in the card. Hover over the filename to see its full path,
   duration, sample rate and channel count.

Angles follow the SOFA convention used by the loaded HRIRs:

| Parameter | Meaning |
| --- | --- |
| Azimuth 0° | Front |
| Azimuth +90° | Listener's left |
| Azimuth −90° | Listener's right |
| Azimuth ±180° | Rear |
| Elevation 0° | Horizontal plane |
| Elevation +90° / −90° | Above / below |

See the [SOFA coordinate specification](https://sofacoustics.org/mediawiki/index.php/SOFA_specifications).
The old guide reversed left and right; the renderer's angle convention is unchanged.

All files begin at the same time. Channels within each file are **averaged to mono**
before spatial rendering. Stereo width within the original file is therefore not retained,
and opposite-polarity channels can cancel. This is a source-positioning mixer, not a timeline editor.

**Solo** restricts the mix to loaded solo tracks; **Mute always excludes a track**, including
a solo track. An empty solo card does not silence loaded sources. Crossed-out map markers
identify excluded or unloaded sources. Number buttons let you select sources whose markers overlap.
Removing a card leaves the remaining source numbers unchanged.

## Preview range

**Preview Mode** processes the same time range in every included source. Set **Start** and
**Duration**, or use the previous/next segment buttons to move by one duration.
A source that has already ended contributes silence; its ending is never replayed.
If the range contains no source audio, the render reports an error.

The range label applies to **both monitoring and WAV export**. Disable Preview Mode to
export the complete mix. Convolution includes the filter tail, so the output may be longer
than the selected source segment. Each selected segment is convolved independently;
a preview does not include filter history from before its start time.

## Render, monitor and export

* **Render & Monitor** renders the current mix and starts playback through the active audio device.
* **Stop Monitor** stops playback and releases its audio callback. Playback completion does the same.
* **Render to WAV** asks for a destination, then renders and saves stereo 32-bit float WAV
  in the background. The sample rate captured at render start is used for the file header.
  The destination is replaced only after the complete file has been written successfully.
* Progress, cancellation and playback position appear within the workspace. Settings are
  locked while rendering. Cancellation takes effect after the current read, resampling,
  convolution or peak-analysis operation, or between output-writing blocks.
* Leaving or closing the widget stops monitoring and cancels a pending render. Cancelled
  renders do not start playback or replace the destination file.
* If the device sample rate changes, monitoring requires a new render rather than playing
  the previous buffer at the wrong rate. Export remains tied to the captured render rate.

The completed render shows its duration and the attenuation applied for peak headroom.

## Processing and output headroom

The renderer blends up to three measured HRIRs using inverse angular-distance weighting,
resamples sources and HRIRs as needed, and applies full FFT convolution. It accumulates the
mix in float64 and processes sources one at a time to avoid holding all decoded files at once.
The output and the current convolution still require memory proportional to their duration.
Interpolation quality depends on the dataset, its angular coverage and the measured HRIRs;
interpolation does not add missing acoustic information.

If the estimated true peak exceeds −1 dBTP, the whole mix is attenuated. This preserves
stereo balance without compression or upward normalization. Four-times interpolation and
the margin reduce inter-sample overload risk; they do not guarantee that every DAC
reconstruction filter remains unclipped.
