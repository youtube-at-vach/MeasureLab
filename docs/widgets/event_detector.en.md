# Event Detector

![Event Detector](../assets/widgets/event_detector.png)

Event Detector continuously measures how often an input signal crosses a configured threshold and reports the event rate. It is intended for rare phenomena such as popcorn noise, random telegraph noise (RTN) in JFETs or operational amplifiers, and intermittent contact clicks.

## Relationship to Other Time-Domain Widgets

| Widget | Primary purpose |
| :--- | :--- |
| Oscilloscope | Inspect the shape of a short waveform in detail. |
| Raw Time Series | Visually inspect a decimated, long-duration waveform. |
| Transient Analyzer | Capture a triggered waveform and analyze it with tools such as CWT. |
| Event Detector | Monitor every input sample and count rare threshold events. |

Event Detector intentionally has no waveform plot. Use Raw Time Series or Oscilloscope alongside it when waveform shape must be inspected.

## Detection Settings

### Input Channel

Select CH1 or CH2 as the detector input. CH1 is used as a fallback for mono input.

### Threshold

Sets the event-start threshold. The initial implementation uses full-scale (FS) units.

### Polarity

- `Positive`: Detect only positive threshold crossings.
- `Negative`: Detect only negative threshold crossings.
- `Both`: Detect both polarities.

### Hysteresis

Sets the return margin that prevents small fluctuations near the threshold from becoming multiple events.

For positive polarity, an event starts when the signal crosses `+Threshold` and ends when it returns to or below `Threshold - Hysteresis`. Negative polarity uses the sign-reversed conditions.

Hysteresis must be smaller than Threshold.

### Holdoff

Sets the time after an event ends during which new events are ignored. This suppresses recounting caused by ringing or contact bounce.

## Results

- `Detector State`: Shows stopped, armed, active-event, or holdoff state.
- `Event Count`: Number of event starts since Start or Reset.
- `Event Rate`: Events per minute over the measured time.
- `Measurement Time`: Elapsed time used to calculate Event Rate.

Event Rate is calculated as follows:

```text
Event Rate = Event Count × 60 / Measurement Time [seconds]
```

## Basic Measurement Procedure

1. Connect the DUT to the audio interface, using a low-noise preamplifier when required.
2. Use Raw Time Series or Oscilloscope to estimate normal noise and abnormal-event levels.
3. In Event Detector, set the input channel, Threshold, Polarity, Hysteresis, and Holdoff.
4. Press `Start` to begin measurement.
5. After the chosen duration, press `Stop` and record Event Count and Event Rate.
6. Replace the DUT and repeat with the same gain, threshold, sample rate, and measurement time.

Detection settings are locked while measurement is running. Stop the measurement before changing them. `Reset` clears the count, elapsed time, and warnings without stopping acquisition.

## Event-Decision Notes

- A signal already beyond the threshold when measurement starts is not counted. Detection begins with a new crossing after the signal returns to its release level.
- An event spanning multiple audio blocks is counted only once.
- A `CLIPPING` warning means the input reached full scale and its amplitude relationship may no longer be valid.
- An `I/O BUFFER ERROR` warning means input samples may have been lost, so Event Count may be lower than the true value.
- DC and very-low-frequency measurement capability depends on the input coupling of the audio interface.

## Current Limitations

The initial display focuses on Event Count and Event Rate. Peak amplitude, duration, and interval are recorded internally, while distributions and file export are reserved for later expansion.
