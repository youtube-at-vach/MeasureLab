//! Audio acquisition, signal generation and measurement, independent of the desktop UI.
pub mod acquisition;
mod activity;
pub mod audio;
pub mod calibration;
#[cfg(feature = "qa")]
pub mod callback_profile;
pub mod channel;
pub mod comparison;
pub mod comparison_worker;
pub mod cursor;
#[cfg(any(test, feature = "qa"))]
pub mod demo;
pub mod export;
mod file_io;
pub mod generator;
pub mod instance;
pub mod lockin;
pub mod lockin_worker;
pub mod loopback;
pub mod measurement;
pub mod output;
pub mod results;
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
pub mod result_image;
#[cfg(feature = "desktop")]
pub mod spectrogram_gpu;
#[cfg(feature = "desktop")]
pub mod workspace_io;
