# Boxcar Averager

![Boxcar Averager](../assets/widgets/boxcar_averager.png)

## Overview

This tool removes random noise and clearly brings out hidden minute waveforms by repeatedly superimposing and averaging periodic signals.
Also called a "boxcar integrator," it is used for measuring minute signals and high-precision observation of the impulse response and step response of systems.

This widget has both an "Internal mode," which outputs test signals itself to synchronize, and an "External mode," which synchronizes with external trigger signals.

## ☕ Coffee Break: The Magic of "Averaging" to Erase Noise

Imagine you are in a noisy crowd, and someone is whispering an important message to you. If they say it only once, it will be drowned out by the surrounding noise, and you won't understand a thing.
But what if that person repeats the "same word" at the "same timing" 100 times?
The surrounding noise (chatter, car sounds, etc.) is random and different every time, but the shape of the whisper is exactly the same each time. If you "overlap and average" these 100 times, the random positive and negative noise cancels each other out approaching zero, and only the whisper, which has the same shape every time, emerges clearly as if by magic!
This is the mechanism behind the Boxcar Averager. It is an extremely powerful technique for rescuing minute signals sunken in a sea of noise.

## Operation

### Starting and Resetting Measurement

- **Start / Stop Button**: Switches between starting and stopping measurement (integration).
- **Reset Button**: Clears the integrated data up to now and restarts averaging from zero. Press this immediately after changing settings or moving the measurement target.
- **Export Button**: Saves the averaged result as an audio file such as WAV.
- **Int64 Accumulation Checkbox**: Performs accumulation using 64-bit integers. Useful when averaging a very large number of times or when extreme precision is required for minute signals (eliminates errors caused by floating-point precision).

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

- **Period / Block (spl)**
    - Specifies the length of time to perform one averaging in milliseconds (ms) or number of samples (spl).
    - Changing one automatically calculates the other.
    - Set it to a length where the response of the measurement target is sufficiently contained. If it is too short, reverberation will overlap with the next cycle (aliasing).

- **Channel (Measurement Channel)**
    - Select the input channel you want to measure (Stereo / Left / Right).

### Gate & Sync Settings

Settings for limiting the analysis range and synchronizing with external signals.

- **Gate**: A function to limit the time range to be analyzed. Used when extracting only specific reflected sounds or reducing the processing load.
    - **Enable**: Turns the function ON/OFF.
    - **Start**: Sets the delay time from the start point of the cycle (t=0) to the actual start of recording.
    - **Width**: Sets the width (length) to be recorded.

- **External Sync**: Displayed only when Mode is set to `External Reference`.
    - **Ref (Reference Channel)**: Select the channel (Left or Right) to be used as a trigger.
    - **Edge**: Select whether to trigger on the **Rising** edge, **Falling** edge, or **Free Run** (continuous capture without synchronization).
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
