# Glossary

Explanations of technical terms used in MeasureLab documentation.

## Audio Systems

### JACK (JACK Audio Connection Kit)

A sound server daemon for professional audio processing on Linux. It provides low latency connections and flexible routing between applications. Recommended for precise measurements requiring phase synchronization in MeasureLab.

### PipeWire

A new multimedia server for Linux. It aims to integrate and replace the functions of both traditional PulseAudio and JACK. It is becoming standard in modern Linux distributions and offers low latency and flexible routing similar to JACK.

## Application & Runtime

### AppImage

An application distribution format for Linux. It bundles necessary libraries and dependencies into a single file, so you can run it just by downloading the file and granting execution permissions, without installation.

### venv (Virtual Environment)

A standard Python feature that creates an independent execution environment for each project. It is used to install specific versions of libraries required for MeasureLab without affecting the system's Python environment.

## Others

### FFT Wisdom (Initial Optimization)

A mechanism used by the Fast Fourier Transform (FFT) library, FFTW, to explore and save the "fastest algorithm for that computer". This calculation is performed when MeasureLab is started for the first time, which may cause a delay of tens of seconds to several minutes, but from the second time onwards, it starts instantly using the saved "Wisdom".
