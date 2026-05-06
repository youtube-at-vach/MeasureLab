# Glossary

Explanations of technical terms used in MeasureLab documentation.

## Audio Systems

### JACK (JACK Audio Connection Kit)

A sound server daemon for professional audio processing on Linux. It provides low latency connections and flexible routing between applications. Recommended for precise measurements requiring phase synchronization in MeasureLab.

💡 **Knowledge Boost:**
Think of JACK as a "giant professional switchboard" found in TV stations or studios. It flawlessly handles complex connections like "send this app's sound to both that app and the speakers simultaneously" without any audio delay.

### PipeWire

A new multimedia server for Linux. It aims to integrate and replace the functions of both traditional PulseAudio and JACK. It is becoming standard in modern Linux distributions and offers low latency and flexible routing similar to JACK.

💡 **Knowledge Boost:**
PipeWire is like a "next-generation smart traffic controller" that takes the best parts of the old system and the professional system (JACK). It combines everyday ease of use with professional-grade accuracy.

## Application & Runtime

### AppImage

An application distribution format for Linux. It bundles necessary libraries and dependencies into a single file, so you can run it just by downloading the file and granting execution permissions, without installation.

💡 **Knowledge Boost:**
An AppImage is like an "all-in-one bento box"! Normally, apps require you to gather things separately ("install rice here, side dishes there"). But with an AppImage, you just place this one box down, and you can immediately enjoy all its delicious features.

### venv (Virtual Environment)

A standard Python feature that creates an independent execution environment for each project. It is used to install specific versions of libraries required for MeasureLab without affecting the system's Python environment.

💡 **Knowledge Boost:**
Think of venv as a "temporary, dedicated workbench" built inside your computer. No matter how messy you make it here (by installing various parts), it won't affect your other desks (the entire system), so you can work with peace of mind. And when you're done, throwing the whole desk away is easy!

## Others

### FFT Wisdom (Initial Optimization)

A mechanism used by the Fast Fourier Transform (FFT) library, FFTW, to explore and save the "fastest algorithm for that computer". This calculation is performed when MeasureLab is started for the first time, which may cause a delay of tens of seconds to several minutes, but from the second time onwards, it starts instantly using the saved "Wisdom".

#### ☕ Coffee Break: What exactly is this "Wisdom"?

Imagine your first day commuting to a new workplace or school. On the first day, you look at your map app, wondering "Is this route faster? Is that street less crowded?", through trial and error, which takes time.
But after commuting for a few days, you find your very own **"fastest commute route (Wisdom)"**, and from then on, you can get there via the quickest path without hesitation.

FFTW (the calculation engine) is doing the exact same thing! On the first day, it works hard to find the "calculation shortcuts" that best suit your PC's CPU, and jots them down in a file named "Wisdom". So, please give it a little patience just for that very first startup!
