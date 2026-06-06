# Lock-in Amplifier: Measurement Principles & Limitations

This document describes the operating principles of the software Lock-in Amplifier (`src/gui/widgets/lock_in_amplifier.py`) and explains why a hardware reference loopback is strictly required for accurate phase measurements.

## 1. Measurement Principle

The Lock-in Amplifier extracts the amplitude and phase of a signal at a specific frequency by mixing the input signal with a reference sine wave (Local Oscillator) and integrating the result.

### Dual-Phase Demodulation

We use "Dual-Phase" demodulation to recover both magnitude and phase independent of the signal's alignment with the reference.

Given an input signal $V_{sig}(t) = A_{sig} \sin(\omega t + \phi_{sig})$ and a reference frequency $\omega$, we generate two orthogonal reference signals:

* **In-Phase Reference (I):** $\sin(\omega t + \phi_{ref})$
* **Quadrature Reference (Q):** $\cos(\omega t + \phi_{ref})$

The mixing process involves multiplying the signal by these references and applying a Low-Pass Filter (LPF) (or averaging over integer cycles):

$$ X = \text{Mean}( V_{sig}(t) \cdot \sin(\omega t + \phi_{ref}) ) \propto A_{sig} \cos(\phi_{sig} - \phi_{ref}) $$
$$ Y = \text{Mean}( V_{sig}(t) \cdot \cos(\omega t + \phi_{ref}) ) \propto A_{sig} \sin(\phi_{sig} - \phi_{ref}) $$

From $X$ and $Y$, we calculate:

* **Magnitude:** $R = \sqrt{X^2 + Y^2} \propto A_{sig}$
* **Phase:** $\theta = \arctan(Y / X) = \phi_{sig} - \phi_{ref}$

Ideally, if $\phi_{ref}$ is known and constant (e.g., $\phi_{ref} = 0$), then $\theta$ gives us $\phi_{sig}$.

## 2. The "Undefined Phase" Problem

In a standard PC audio environment, the Operating System and Audio Driver (ALSA/PulseAudio/WASAPI) manage the input and output streams. Crucially, **there is no guaranteed fixed phase relationship between the Output Buffer (DAC) and the Input Buffer (ADC).**

### Why this happens

1. **Buffered I/O:** Audio is processed in blocks. The exact time $t_{generate}$ when a sample is written to the output buffer is separated from the time $t_{capture}$ when a corresponding sample is read from the input buffer by a variable system latency $\Delta t_{latency}$.
2. **Undefined Latency:** $\Delta t_{latency}$ depends on buffer sizes, driver state, and OS scheduling. It varies every time the stream is started and potentially drifts or jitters during operation.

### Impact on Measurement

In "Internal Mode", the software generates the output sine wave mathematically:
$$ V_{out}(t) = \sin(\omega t_{software}) $$

And it demodulates the input using the same software timebase:
$$ Ref(t) = \sin(\omega t_{software}) $$

However, the physical signal arriving at the ADC is:
$$ V_{in}(t) = \sin(\omega (t_{software} - \Delta t_{latency}) + \phi_{DUT}) $$

The measured phase becomes:
$$ \theta_{measured} = \phi_{DUT} - \omega \cdot \Delta t_{latency} $$

Since $\Delta t_{latency}$ is unknown and undefined, **the measured phase is effectively random**. It will change every time you restart the measurement.

> **Note:** Magnitude accuracy is generally preserved because latency only affects the phase term $\omega \cdot \Delta t_{latency}$, not the amplitude $A_{sig}$, provided the sampling rates are locked (which they are on a single audio interface).

## 3. Solution: External Reference Loopback

To solve this, we must measure the **actual physical phase** of the excitation signal.

**Configuration:**

1. **Output (Ch 1):** Connect to DUT Input.
2. **Output (Ch 1) Split:** Connect also to **Reference Input (Ch 2)**.
3. **Input (Ch 1):** Connect to DUT Output.

The Lock-in Amplifier then analyzes the Reference Input (Ch 2) to establish the reference phasor.

* **Ref Input sees:** $A_{ref} \sin(\omega t + \phi_{latency})$
* **Sig Input sees:** $A_{sig} \sin(\omega t + \phi_{latency} + \phi_{DUT})$

By locking to the Ref Input (calculating $\phi_{ref} = \phi_{latency}$), the demodulation cancels out the latency:

$$ \theta_{result} = (\phi_{latency} + \phi_{DUT}) - \phi_{latency} = \phi_{DUT} $$

### Code Implementation Details

In `src/gui/widgets/lock_in_amplifier.py`:

* **Internal Mode (No Ref Loopback):**
    * The code detects low signal on the Reference channel.
    * This forces the reference phase to be 0 relative to the *current software buffer*.
    * **Result:** Magnitude is correct. Phase is unstable/undefined relative to the DUT.

* **External Mode (With Ref Loopback):**
    * The code calculates the fundamental phasor of the Reference channel.
    * `ref_unit = ref_c_fund / |ref_c_fund|`
    * The Signal is multiplied by the conjugate of this phasor (`sig_c * conj(ref_unit)`).
    * **Result:** Accurate Phase and Magnitude relative to the excitation signal.

## 4. Summary

* **Without REF Loopback:** You are measuring "Signal vs Software Timer". Phase includes arbitrary system latency. **Not suitable for Impedance or Phase measurements.**
* **With REF Loopback:** You are measuring "Signal vs Excitation". Latency cancels out. **Required for accurate measurement.**
