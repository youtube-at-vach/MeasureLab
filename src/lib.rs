//! Acquisition and waveform processing, independent of the desktop UI.
pub mod audio;
pub mod demo;
pub mod signal;
pub mod spectrum;

#[cfg(feature = "desktop")]
pub mod app;
#[cfg(feature = "desktop")]
pub mod gpu;
