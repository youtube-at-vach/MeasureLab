//! Acquisition and waveform processing, independent of the desktop UI.
pub mod audio;
pub mod calibration;
pub mod channel;
pub mod cursor;
#[cfg(any(test, feature = "qa"))]
pub mod demo;
pub mod export;
mod file_io;
pub mod instance;
pub mod measurement;
pub mod settings;
pub mod signal;
pub mod spectrogram;
pub mod spectrum;
pub mod spectrum_worker;
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
