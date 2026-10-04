//! Acquisition and waveform processing, independent of the desktop UI.
pub mod audio;
pub mod demo;
pub mod instance;
pub mod signal;
pub mod spectrum;
pub mod stft;

#[cfg(feature = "qa")]
pub mod qa;

#[cfg(feature = "desktop")]
pub mod app;
#[cfg(feature = "desktop")]
pub mod gpu;
