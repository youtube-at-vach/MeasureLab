//! Acquisition and waveform processing, independent of the desktop UI.
pub mod audio;
pub mod cursor;
pub mod demo;
pub mod instance;
pub mod measurement;
pub mod signal;
pub mod spectrogram;
pub mod spectrum;
pub mod stft;
pub mod xy;

#[cfg(feature = "qa")]
pub mod qa;

#[cfg(feature = "desktop")]
pub mod app;
#[cfg(feature = "desktop")]
pub mod gpu;
#[cfg(feature = "desktop")]
pub mod spectrogram_gpu;
