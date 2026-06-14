# Glossary

Explanations of technical terms used in MeasureLab documentation.

## Audio Systems

### JACK (JACK Audio Connection Kit)

A sound server daemon for professional audio processing on Linux. It provides low latency connections and flexible routing between applications. Recommended for precise measurements requiring phase synchronization in MeasureLab.

### PipeWire

A new multimedia server for Linux. It aims to integrate and replace the functions of both traditional PulseAudio and JACK. It is becoming standard in modern Linux distributions and offers low latency and flexible routing similar to JACK.

### LTC (Linear Timecode)

A standard for encoding timecode information (hours, minutes, seconds, frames) into an audio signal (a buzzing electronic tone) to record it on audio equipment or recording channels. It is widely used to synchronize the timing of multiple cameras and recorders, allowing automatic alignment during video editing.

### Loopback & Crosstalk

Loopback is a path where output signals are routed directly back into inputs, either via physical cables or internally through device or OS settings. Crosstalk is the unwanted leakage of signals between adjacent channels that should be independent.

## Acoustics & Measurement Basics

### Calibration

The process of measuring and adjusting the relationship between digital signal values (dBFS) and physical quantities (such as voltage or sound pressure) to guarantee the accuracy of the measurement instrument. This enables direct reading of waveforms in physical units like voltage (V) or sound pressure (dB SPL).

### dBFS (Decibels relative to Full Scale)

A relative unit of measurement for digital audio levels. The maximum possible digital level (clipping limit) is defined as 0 dBFS, and levels below this maximum are represented as negative values (e.g., -12 dBFS).

### dBV / dBu

Decibel units representing voltage magnitude. 0 dBV is referenced to 1.0 Vrms (commonly used in consumer audio equipment), while 0 dBu is referenced to 0.775 Vrms (standard in professional audio equipment, originating from old telephone line standards).

### dB SPL (Sound Pressure Level)

A unit representing the physical intensity of sound (magnitude of air pressure fluctuations). The threshold of human hearing (20 micropascals) is defined as 0 dB SPL, and it is commonly used to express environmental noise levels or speaker volumes.

### TrueRMS (True Root Mean Square)

A method to accurately measure the actual energy (effective value) of an alternating voltage or current. It provides precise measurements without errors, even for complex or distorted waveforms and noise, not just simple sine waves.

### PPM (Parts Per Million)

A unit representing one-millionth (1 PPM = 0.0001%). In MeasureLab, it is used to describe extremely small deviations or long-term drift (clock drift) in the audio interface's internal clock.

### Jitter

Minor fluctuations or variations in the time domain during the transmission or processing of digital signals. In audio, increased jitter can degrade high-frequency clarity or cause the sound to become muddy.

### ENOB (Effective Number of Bits)

A metric that represents the signal quality of digital audio (noise and distortion level) converted into a theoretical "bit depth" or resolution. For example, even in a circuit processing 24-bit audio, if noise and distortion are high, the device may be evaluated as having "an ENOB equivalent to 18 bits."

### Allan Deviation

A metric used to evaluate the "short-term frequency stability" of clocks, oscillators, and other timing devices. Unlike standard deviation, it can more accurately characterize the fluctuations (noise types) in frequency over time.

### Impedance & Reactance

Impedance is the opposition to alternating current (AC) in a circuit, measured in ohms (\(\Omega\)). It corresponds to "resistance" in direct current (DC) circuits but varies with frequency. Reactance is the component of impedance caused by coils (inductors) or capacitors, representing opposition that does not dissipate energy as heat.

### Q-factor (Quality Factor) & Dissipation Factor (D-factor)

Q-factor represents the sharpness of resonance or the energy efficiency of a component like an inductor. A higher Q-factor indicates lower energy loss. Dissipation Factor (D-factor) is the reciprocal of Q-factor (\(D = 1/Q\)), indicating the degree of energy loss in components like capacitors, where a smaller value means better performance.

### Linearity & Hysteresis

Linearity refers to the property where the output of a system is strictly proportional to its input. Hysteresis is a phenomenon where the state of a system depends on its history; in measurements, this refers to differences in values observed when decreasing the signal level (going path) versus increasing it (returning path).

### Equivalent Input Noise (EIN)

A metric indicating the noise performance of an amplifier or preamplifier, calculated by converting the device's self-noise into the equivalent noise level at the input terminal. This allows a fair comparison of noise levels between amplifiers with different gains.

### Trigger

A reference condition (such as a specific voltage level or direction of rising/falling) used to start the visual rendering of a waveform on an oscilloscope. Setting the trigger correctly allows fast-moving, repetitive waveforms to appear stationary and stable on the screen for detailed observation.

### Rise Time / Fall Time

The time required for a signal to transition from one state to another. Rise time is the time taken for a signal to rise from a low value (typically 10%) to a high value (typically 90%), while fall time is the reverse. They are used to evaluate the responsiveness and speed of amplifiers and filters.

### Vpp (Peak-to-Peak Voltage)

The difference between the maximum positive peak and the minimum negative peak of a voltage waveform. For a sine wave, the peak-to-peak voltage is approximately 2.82 times the Root Mean Square (Vrms) value, and exactly double the maximum zero-to-peak amplitude.

### Leq (Equivalent Continuous Sound Level)

A metric that represents the average sound energy of a fluctuating noise level over a specified period, expressed as a single steady decibel value. It is the most widely used metric for environmental noise assessments to represent the average perceived loudness over time.

### Time Weighting

A setting in sound level meters that defines the response speed (time constant) of the level measurement to mimic human perception. Standard settings include "FAST" (125ms time constant) for tracking general variations, "SLOW" (1s time constant) for averaging slow fluctuations, and "IMPULSE" for capturing transient impact sounds.

### Z-weighting

A frequency weighting setting in noise measurement that applies no correction (flat response) across the frequency spectrum. "Z" stands for zero-weighting, and it is used when you want to measure the actual physical sound pressure level exactly as it is, without filtering.

### FLL (Frequency Locked Loop)

A control system that detects changes in the frequency of an input signal and automatically adjusts the frequency of an internal oscillator (such as an NCO) to match and lock onto it. It is used to precisely monitor and track minor frequency drifts and fluctuations.

### EVM (Error Vector Magnitude)

A metric that represents the deviation between the ideal reference waveform and the actually measured waveform as a vector magnitude, expressed in percent (%). A smaller EVM percentage indicates that the waveform is less affected by noise or distortion, accurately reproducing the original signal.

### Sharpness & Roughness

Sharpness is a psychoacoustic metric (measured in acum) that represents the "sharpness" or "high-pitched piercing character" of a sound, with higher values indicating more high-frequency energy. Roughness is a metric (measured in asper) that represents the "roughness" or "harshness" of a sound, evaluating the unpleasant buzzing or grating sensation caused by rapid amplitude modulations (around 70 Hz).

### Tonality & Fluctuation Strength

Tonality is a metric (ranging from 0.0 to 1.0) indicating how close a sound's components are to a pure tone (a single distinct pitch), where noise-like sounds yield low values and sine-like sounds yield values close to 1.0. Fluctuation Strength is a metric (measured in vacil) that represents slower amplitude variations or modulations (below 20 Hz, particularly around 4 Hz to which the human ear is highly sensitive).

### Articulation Index (AI)

A metric ranging from 0.0 to 1.0 that evaluates speech intelligibility (how easy it is to understand spoken words) in the presence of background noise. A value closer to 1.0 indicates that speech can be heard clearly and without difficulty.

### DC Offset & Drift

DC Offset is a phenomenon where the entire signal is shifted in the positive or negative direction from the reference 0 V (zero volts), mixing a direct current component into the signal. Drift refers to the gradual, slow shift of measured values or clock frequencies over time or due to temperature changes.

### Gain Compression

A phenomenon where the gain (amplification factor) of an amplifier or system decreases as the input signal level increases beyond a certain point, causing the output level to saturate. It is related to measurements such as "P1dB (1dB Compression Point)," which indicates the limit where an amplifier begins to distort.

## Nonlinear Measurement & Modeling

### Nonlinearity / Nonlinear Measurement

The property of a system where the output is not proportional to the input. In audio equipment, this manifests as signal distortion (such as harmonic distortion) when the volume is increased. Precisely measuring and analyzing these distortion characteristics is called nonlinear measurement.

### Hammerstein Model

A mathematical model used to describe nonlinear systems like audio amplifiers or speakers. It represents the system as a memoryless nonlinear block followed by a linear dynamic block (such as an EQ filter) in series.

### Wiener Kernels

Mathematical representations used to describe nonlinear systems in response to random noise inputs. They are used to evaluate the distortion characteristics of audio equipment at a specific signal level (RMS level), allowing a more practical understanding of the device's nonlinear behavior.

### Hermite Orthogonalization

A mathematical process used when converting from Hammerstein model measurement data to a Wiener model (Wiener kernels). It separates different orders of distortion components (e.g., 2nd, 3rd harmonics) so they do not interfere with each other.

### Feedforward Distortion Compensation

A technique to preemptively cancel out distortion in amplifiers or speakers. By generating a "predistorted" signal (adding inverse distortion based on the measured device characteristics) and feeding it to the device, the final acoustic output is made exceptionally clean.

### SDR (Signal-to-Distortion Ratio)

A metric indicating signal quality, representing the ratio of the desired linear signal component to the distortion and noise components, expressed in decibels (dB). A higher value indicates lower distortion and higher quality.

### P1dB (1dB Compression Point)

A metric showing the performance limit of amplifiers or speakers. As the input level increases, the output level initially increases proportionally, but eventually starts to saturate. P1dB is the point where the actual output deviates from the ideal linear output by 1dB, serving as a guideline for where distortion begins to become significant.

### Intermodulation Distortion (IMD)

A type of distortion that occurs when two or more signals of different frequencies are input simultaneously, where the nonlinearity of the system causes them to interfere and generate new frequencies (sum and difference tones) not present in the original signal. It affects the muddy sound quality when playing complex audio like actual music.

### SPDR (Spurious Free Dynamic Range)

The decibel (dB) difference between the level of the primary signal and the highest level of any other unwanted component (spurious or noise). A larger value indicates a cleaner signal that is less affected by unwanted noise.

### Synchronized Swept Sine (SSS)

A measurement method that plays a swept sine wave with a continuously and logarithmically changing frequency to a device under test (such as an amplifier or speaker) and extracts the linear (fundamental) and harmonic distortion components of each order (2nd, 3rd, etc.) with extreme precision from the response.

### THD Map (Total Harmonic Distortion Map)

A 2D contour or gradient map that visualizes the levels of Total Harmonic Distortion (THD) generated by a device, plotted with input amplitude (level) on the vertical axis and frequency on the horizontal axis, based on the measured nonlinear model.

## Signal Processing & Analysis

### FFT (Fast Fourier Transform)

An efficient computational method used to decompose a time-varying signal (like audio) into its constituent frequency components. This technology is essential for converting waveform displays (like in an oscilloscope) into frequency displays (like in a spectrum analyzer).

### PSD (Power Spectral Density)

The distribution of power (energy) of a signal over frequency. It is used to evaluate the characteristics of random noise signals (like white noise) uniformly and fairly, without being influenced by the frequency resolution (FFT size) settings.

### Window Function

A mathematical function applied to a segment of a waveform to smoothly fade out the edges before performing an FFT. It is used to prevent "spectral leakage" (computational noise) that occurs due to the sudden transition at the boundaries of the cut waveform. The Hanning window is a typical example.

### Spectral Leakage

An artifact in FFT analysis where energy from a signal "leaks" into adjacent frequencies due to the abrupt truncation of the analyzed waveform segment. It appears as a broad skirt around sharp frequency peaks.

### A-weighting / C-weighting

Frequency-dependent weighting curves that mimic the sensitivity of the human ear for noise and sound pressure measurements. A-weighting is standard for evaluating general environmental noise (quiet to moderate levels), while C-weighting is used for high-level sounds (such as loud live music or machinery noise).

### Noise Floor

The level of background noise present in a measurement system or environment when no input signal is applied. A lower noise floor allows smaller signals to be detected and measured.

### White Noise & Pink Noise

Typical test signals used in acoustic measurements. White noise has equal energy per hertz across all frequencies, sounding like a high-pitched "hiss" and appearing flat in PSD. Pink noise has energy that decreases with frequency, sounding like a deeper "shhh" and appearing flat to the human ear or in octave band analysis.

### Impulse Response

The output waveform of a system (such as an amplifier, speaker, or room) when presented with a brief, sharp impulse signal. This waveform contains all information about the system's frequency response and reverberation.

### Step Response

The output of a system when its input is suddenly changed from zero to a constant level. It is used to evaluate system stability and transient behavior, such as response speed, overshoot, and damping.

### Multitaper

An advanced spectral estimation method that combines multiple orthogonal window functions to reduce the variance (fluctuations) of noise in the spectrum, yielding a smoother and more reliable estimate, especially in noisy environments.

### Harmonics & Fundamental Frequency

The fundamental frequency is the lowest and primary frequency component in a complex signal. Harmonics are integer multiples of the fundamental frequency (such as 2nd or 3rd harmonics). While they define the timbre of instruments, in audio equipment, they appear as unwanted harmonic distortion.

### FIR Filter & FIR Taps

An FIR (Finite Impulse Response) filter is a digital filter that allows precise tone adjustments without altering phase characteristics (linear phase). FIR taps represent the "length" or resolution of the filter; higher taps allow more precise control over low frequencies or steep curves, at the cost of increased latency and computational load.

### Coherence

A metric ranging from 0.0 to 1.0 that represents the correlation (strength of connection) between the input and output signals. A value closer to 1.0 indicates that the input signal is transmitted to the output cleanly, without noise or unwanted distortion.

### Group Delay

The time delay (measured in seconds or milliseconds) introduced to each frequency component as a signal passes through a system. It is used to evaluate the temporal misalignment between low and high frequencies.

### 1/f Noise (Flicker Noise) & Hum Noise (Hum)

1/f Noise is a type of noise that is inversely proportional to frequency, becoming stronger at lower frequencies, often generated in semiconductor devices. Hum Noise is unwanted noise ("buzzing" or "humming") caused by the AC power line frequency (50 Hz or 60 Hz) and its harmonics leaking into the audio signal.

### Thermal Noise

The unavoidable electronic noise generated by the thermal agitation of charge carriers (usually electrons) inside an electrical conductor. It increases with temperature and resistance, setting the theoretical minimum noise limit (physical noise floor) of any electronic circuit.

### Formant

A prominent spectral peak (frequency band of concentrated energy) in the spectrum of a voice or musical instrument. In human speech, the locations of formants change depending on the shape of the vocal tract and mouth, which is how the brain distinguishes between different vowel sounds like "ah" or "ee".

### Mel Scale

A perceptual scale of pitches judged by listeners to be equal in distance from one another. Since human hearing is less sensitive to pitch changes at higher frequencies, the Mel scale stretches the representation of lower frequencies and compresses higher ones. It is widely used in speech recognition and voice analysis.

### Waterfall Display

A visualization method used in spectrograms and 3D plots where new spectral data is added continuously at one end, causing older data to scroll away like flowing water. This allows intuitive tracking of how frequency and amplitude components evolve over time.

### Wavelet Transform

A signal analysis method that decomposes a signal into both time and frequency components using brief wavelets. Unlike the Fourier Transform (FFT) which uses fixed window lengths, the Wavelet Transform dynamically adjusts resolution—providing high time resolution for high frequencies and high frequency resolution for low frequencies—making it ideal for analyzing transient, fast-changing signals.

### NCO (Numerically Controlled Oscillator)

A digital oscillator that generates extremely precise sine waves within software or digital signal processing. It is used in measurements as an ideal, highly accurate reference signal that is completely unaffected by physical circuit instability or external noise.

### Kalman Filter

An advanced algorithm used to statistically estimate the true state of a system from noisy and uncertain measurement data. In frequency counters and other devices, it is used to filter out random noise fluctuations and estimate precise, stable values along with their measurement uncertainty in real time.

### Multiplexed Parallel IQ Detection

A method where multiple lock-in detection channels (IQ detection) are executed simultaneously in parallel for the fundamental frequency and its integer harmonics. This technique allows pinpoint extraction and measurement of extremely low distortion components at specific frequencies, far exceeding the resolution limits of standard FFT (Fast Fourier Transform).

### Correlation Coefficient (r)

A numerical value between -1.0 and 1.0 that represents how similar two sets of data (such as the audio waveforms of the L and R channels) are to each other. A value of 1.0 means they are identical (in-phase mono), 0 means no correlation, and -1.0 means they are completely inverted (out-of-phase), serving as a metric for assessing stereo imaging and phase alignment.

### PRBS (Pseudo-Random Binary Sequence)

A test signal that appears to be random noise but is actually a deterministic sequence whose cycle and values are mathematically predictable. By sending this signal through an audio circuit or digital transmission path and comparing the received signal with the predicted values, one can instantaneously and comprehensively measure data drops (bit errors), latency, and distortion.

### Digital Down-Conversion (DDC) & Downsampling

Digital Down-Conversion is a technique to translate a high-frequency digital signal down to a lower frequency band (baseband) using digital arithmetic. Combining this with downsampling, which reduces the sampling rate, focuses computational power on a specific narrow band, dramatically increasing the frequency resolution of the FFT.

### Exponential Moving Average (EMA)

An averaging method that calculates a weighted average of past measurement data, where weights decrease exponentially for older data. Because more recent measurements carry higher weight, it quickly tracks sudden changes in the signal while smoothing out fluctuations caused by noise.

### Resolution Bandwidth (RBW)

The narrowest frequency band (measured in Hz) that a spectrum analyzer or measurement instrument can distinguish between adjacent frequency components. A smaller RBW allows for a sharper separation and detailed observation of closely spaced peaks.

### Savitzky-Golay Filter (SG Filter)

A smoothing filter that applies local least-squares polynomial fitting to measured waveform data. Unlike standard moving average filters, it effectively reduces noise while preserving the height, width, and overall shape of sharp peaks in the waveform.

### Time Synchronized Averaging (TSA)

A process that averages multiple segments of a signal captured in perfect synchronization with the start timing of a repetitive test tone (such as a sweep wave). Since unsynchronized random background noise cancels itself out towards zero, it extracts only the target measurement signal with extreme clarity.

### Bode Plot

A standard graph used to visually represent the frequency response of a system. It plots frequency on a logarithmic horizontal axis, with magnitude (magnitude response) on the upper vertical axis and phase (phase response) on the lower vertical axis.

### Resampling

The process of changing the sampling rate of digital audio (e.g., between 44.1 kHz and 48 kHz) using digital interpolation arithmetic, without altering the pitch or overall duration of the sound.

### Gaussian Noise

A completely random noise signal whose amplitude probability density function follows a normal (Gaussian) distribution. It has properties very close to naturally occurring electrical thermal noise and environmental noise.

### Crest Factor

The ratio (expressed in decibels or as a linear ratio) of the peak amplitude of a signal to its Root Mean Square (RMS) value. A higher crest factor indicates that the waveform contains sharp, sudden peaks, making it more prone to clipping (distortion) when passed through an amplifier or speaker.

### Maximum Length Sequence (MLS)

A pseudo-random binary sequence that resembles white noise, generated using digital shift registers. By playing it to a system and applying correlation processing like the Fast Hadamard Transform to the response, it computes the system's impulse response quickly with high noise immunity.

### Golay Codes & Golay Complementary Sequences

A pair of complementary pseudo-random binary sequences whose autocorrelation functions sum to zero sidelobes (unwanted artifacts). By playing these two signals sequentially, measuring their responses, and summing their cross-correlations, it yields an extremely clean impulse response or transfer function, even cleaner than the MLS method.

### Nyquist Frequency & Cutoff Frequency

The Nyquist frequency is half of the sampling rate, representing the theoretical upper limit of frequencies that can be accurately digitized and reproduced. The cutoff frequency is the boundary frequency at which a filter circuit or program begins to attenuate signal components.

### Filter Poles & Filter Order

Metrics indicating the complexity of an analog or digital filter and the steepness of its attenuation curve beyond the cutoff frequency. Each additional pole (one order) increases the attenuation slope by 6 dB/octave. A higher order cuts unwanted frequencies more sharply but introduces more phase distortion and signal latency.

### Interpolation

A mathematical process of constructing new data points between discrete measured sampling points (using functions like spline or linear interpolation) to estimate values at unmeasured arbitrary locations.

### Transient Response

The temporary response of a system to a sudden change in input (such as an attack or sudden cutoff) before it settles into a steady state. It directly affects the reproduction of sharp attack sounds and how resonances decay.

## 3D Audio & Spatial Localization

### ITD (Interaural Time Difference)

The difference in arrival time of a sound between the two ears. When a sound comes from the left, it reaches the left ear slightly earlier. It is one of the primary cues the brain uses to determine the horizontal direction (localization) of a sound.

### ILD (Interaural Level Difference)

The difference in volume (level) of a sound between the two ears, caused by the head shadowing effect. It is particularly prominent at high frequencies where wavelengths are short, and serves as a key cue for sound localization alongside ITD.

### HRTF (Head-Related Transfer Function)

A mathematical representation of how a sound is modified by the head, outer ears, and shoulders before reaching the eardrum. It enables the reproduction of 3D audio (spatial audio) over standard stereo headphones, making sounds appear to come from behind or above.

### SOFA File (Spatially Oriented Format for Acoustics)

A standardized file format (with the `.sofa` extension) used to store HRTF and other spatially oriented acoustic measurement data in research and development.

### Lissajous Curves

A graph produced by plotting two independent signals against each other on the vertical and horizontal axes. In MeasureLab's goniometer (phase scope), it is used to visualize the relationship between the stereo L and R channels to monitor stereo width and phase alignment.

### Phase Cancellation

An acoustic phenomenon where out-of-phase waves (with opposing peaks and troughs) cancel each other out when summed. It can cause specific instruments or vocals to disappear when stereo tracks are played on mono devices (like smartphone speakers).

### LUFS (Loudness Units Full Scale)

A standardized measurement of perceived loudness based on human hearing sensitivity. Television broadcasting and streaming platforms (like YouTube and Spotify) use LUFS to automatically normalize volume levels, resolving volume differences between different songs or programs.

### True Peak

An estimate of the absolute peak level of an analog signal after digital-to-analog conversion, detecting hidden peaks between digital samples. It is used to prevent clipping distortion that cannot be caught by standard digital peak meters.

### IDW (Inverse Distance Weighting)

A method of interpolating (estimating) values at any unmeasured location based on surrounding measured data points, giving more influence (weight) to closer points and less to farther ones. In spatial audio, it is used to fill in the gaps between the limited measurement points of a SOFA file to enable smooth panning and localization from any arbitrary angle.

## Application & Runtime

### AppImage

An application distribution format for Linux. It bundles necessary libraries and dependencies into a single file, so you can run it just by downloading the file and granting execution permissions, without installation.

### venv (Virtual Environment)

A standard Python feature that creates an independent execution environment for each project. It is used to install specific versions of libraries required for MeasureLab without affecting the system's Python environment.

## Others

### FFT Wisdom (Initial Optimization)

A mechanism used by the Fast Fourier Transform (FFT) library, FFTW, to explore and save the "fastest algorithm for that computer". This calculation is performed when MeasureLab is started for the first time, which may cause a delay of tens of seconds to several minutes, but from the second time onwards, it starts instantly using the saved "Wisdom".

### Self-Demodulation & Square Root Pre-distortion

Self-demodulation is a phenomenon where high-power ultrasound waves radiated into the air naturally reconstruct the modulated audible sound due to the non-linear physical properties of the air itself. Square root pre-distortion is a signal processing technique that applies a square root mathematical operation to the source signal prior to modulation in order to cancel out the distortion that inherently occurs during self-demodulation.

### Sonification

The process of translating numerical data or physical measurement values into audio signals (such as pitch and volume), allowing users to intuitively perceive patterns, fluctuations, or the presence of weak signals through hearing.

### Musical Scale & Equal Temperament / Just Intonation

A musical scale is a sequence of notes ordered by musical rules or frequency relationships. Equal Temperament is the modern standard tuning system that divides an octave into 12 equal logarithmic ratios. Just Intonation tunes notes to simple integer ratios (like 4:5:6), producing extremely pure chords without beating, but it results in harsh dissonance when modulating to other keys.

### Frames Per Second (FPS)

A metric indicating how many times a display screen updates or redraws the screen per second (measured in fps). A higher value makes graph movements look smoother, but increases the computational rendering load on the CPU and GPU.
