# Boxcar Averager

![Boxcar Averager](../assets/widgets/boxcar_averager.png)

## Overview

This tool removes random noise and clearly brings out hidden minute waveforms by repeatedly superimposing and averaging periodic signals.
Also called a "boxcar integrator," it is used for measuring minute signals and high-precision observation of the impulse response and step response of systems.

This widget has both an "Internal mode," which outputs test signals itself to synchronize, and an "External mode," which synchronizes with external trigger signals.

## Operation

### Starting and Resetting Measurement

- **Start / Stop Button**: Switches between starting and stopping measurement (integration).
- **Reset Button**: Clears the integrated data up to now and restarts averaging from zero. Press this immediately after changing settings or moving the measurement target.

### Graph Display

- **Horizontal Axis (Time)**: Represents the time for one cycle.
- **Vertical Axis (Amplitude)**: The amplitude of the averaged signal.
- **N=...**: The current number of integrations (number of times averaged) is displayed in the title part. As the number of times increases, the noise decreases and the waveform becomes smoother.

## Setting Items

### Basic Settings (Controls)

- **Mode (Sync Mode)**
    - **Internal Pulse / Step / Impulse**: Generates test signals (pulse, step waveform, impulse) internally and synchronizes based on them. Signals are output from the output terminal.
    - **Internal PRBS/MLS**: Uses pseudo-random signals (for special measurements).
    - **External Reference**: Averaging the signal of another channel using an external reference signal (such as a square wave) as a trigger.

- **Period**
    - Specifies the length of time to perform one averaging in milliseconds (ms).
    - Set it to a length where the response of the measurement target is sufficiently contained. If it is too short, reverberation will overlap with the next cycle (aliasing).

- **Channel (Measurement Channel)**
    - Select the input channel you want to measure (Stereo / Left / Right).

### Gate Settings (Gate)

A function to limit the time range to be analyzed. Used when extracting only specific reflected sounds or reducing the processing load.

- **Gate Checkbox**: Turns the function ON/OFF.
- **Start**: Sets the delay time from the start point of the cycle (t=0) to the actual start of recording.
- **Width**: Sets the width (length) to be recorded.

### External Sync Settings (External Sync)

Displayed only when Mode is set to `External Reference`.

- **Ref (Reference Channel)**: Select the channel (Left or Right) to be used as a trigger. Usually, a clean synchronization signal is input here.
- **Edge**: Select whether to trigger on the **Rising** edge or the **Falling** edge.
- **Lvl (Level)**: Sets the voltage level (threshold) for trigger determination.

## Usage Examples

### Seeing the Step Response of Amplifiers and Effectors

Measure the followability (rise characteristics and damping) when a sudden signal change is given to audio equipment.

1. Connect the output of the audio interface to the input of the measurement target, and return the output to the input (loopback connection).
2. Set **Mode** to `Internal Step`.
3. Set **Period** to about `100 ms`.
4. Press **Start** and look at the graph.
5. You can observe the waveform, which was jagged with noise, becoming a clean staircase-like waveform as the number of integrations (N) increases.

### Detection of Minute Signals (Noise Reduction)

Observe small repetitive signals that are buried in noise and invisible with an oscilloscope.

1. Set **Mode** to `External Reference`.
2. Input the synchronization signal (trigger) from the measurement system into Ch2 (Right), and input a minute sensor signal, etc., into Ch1 (Left).
3. Set **Ref** to `Right` and adjust **Lvl** appropriately.
4. When you press **Start**, Ch1 is overwritten in accordance with the timing of the synchronization signal, and only random noise is canceled and disappears.
