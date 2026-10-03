//! Input-only CPAL owner for the display evaluation. Construct/start/stop on the
//! analysis thread; callbacks only write the bounded queue and atomic counters.
use audio_core::backend::{Backend, InputBinding, SampleFormat};
use audio_core::{Consumer, IoFormat, MAX_CHANNELS};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use serde_json::{Value, json};
use std::path::Path;
use std::sync::{
    Arc,
    atomic::{AtomicU64, Ordering::Relaxed},
};
use std::time::{Duration, Instant};

/// Selected by the immutable request, never inferred from the default device.
pub enum BackendInput {
    Cpal(LiveInput),
    PortAudio(portaudio_input::PortAudioInput),
}
impl BackendInput {
    pub fn open(
        backend: Backend,
        library: Option<&Path>,
        name: &str,
        channels: usize,
        format: &IoFormat,
    ) -> Result<(Self, Consumer), String> {
        match (backend, library) {
            (Backend::Cpal, None) => {
                LiveInput::open(name, channels, format).map(|(s, rx)| (Self::Cpal(s), rx))
            }
            (Backend::PortAudio, Some(path)) => {
                portaudio_input::PortAudioInput::open(path, name, channels, format)
                    .map(|(s, rx)| (Self::PortAudio(s), rx))
            }
            _ => Err("live_backend_library_configuration".into()),
        }
    }
    pub fn start(&mut self) -> Result<(), String> {
        match self {
            Self::Cpal(s) => s.start(),
            Self::PortAudio(s) => s.start(),
        }
    }
    pub fn failed(&self) -> bool {
        match self {
            Self::Cpal(s) => s.failed(),
            Self::PortAudio(s) => s.failed(),
        }
    }
    pub fn stop(&mut self) -> Result<f64, String> {
        match self {
            Self::Cpal(s) => s.stop(),
            Self::PortAudio(s) => s.stop(),
        }
    }
    pub fn report(&self) -> Value {
        match self {
            Self::Cpal(s) => s.report(),
            Self::PortAudio(s) => s.report(),
        }
    }
}

#[derive(Default)]
struct Counters {
    callbacks: AtomicU64,
    frames: AtomicU64,
    rejected: AtomicU64,
    errors: AtomicU64,
    xruns: AtomicU64,
}
pub struct LiveInput {
    stream: Option<cpal::Stream>,
    counters: Arc<Counters>,
}
/// This evaluation uses a fixed f32/48 kHz/256-frame request. No default device
/// fallback, implicit port padding or inferred host/device clock mapping.
pub fn validate(name: &str, channels: usize, format: &IoFormat) -> Result<(), String> {
    if name.trim().is_empty()
        || !(1..=MAX_CHANNELS).contains(&channels)
        || format.rate != [48000, 1]
        || format.input_ids.is_empty()
        || !format.output_ids.is_empty()
        || format.clock_domain != format!("cpal.device:{name}")
    {
        return Err("live_input_configuration".into());
    }
    InputBinding {
        backend: Backend::Cpal,
        device: name.into(),
        device_channels: channels,
        sample_format: SampleFormat::F32,
        format: format.clone(),
    }
    .validate()
    .map_err(String::from)
}
impl LiveInput {
    pub fn open(
        name: &str,
        channels: usize,
        format: &IoFormat,
    ) -> Result<(Self, Consumer), String> {
        validate(name, channels, format)?;
        let host = cpal::default_host();
        let devices: Vec<_> = host
            .devices()
            .map_err(|e| e.to_string())?
            .filter(|d| d.description().is_ok_and(|s| s.name() == name))
            .collect();
        if devices.len() != 1 {
            return Err("live_exact_device_not_unique".into());
        }
        let device = devices.into_iter().next().unwrap();
        if !device
            .supported_input_configs()
            .map_err(|e| e.to_string())?
            .any(|c| {
                usize::from(c.channels()) == channels
                    && c.sample_format() == cpal::SampleFormat::F32
                    && c.min_sample_rate() <= 48000
                    && c.max_sample_rate() >= 48000
            })
        {
            return Err("live_explicit_format_unsupported".into());
        }
        let binding = InputBinding {
            backend: Backend::Cpal,
            device: name.into(),
            device_channels: channels,
            sample_format: SampleFormat::F32,
            format: format.clone(),
        };
        let (mut tx, rx) = binding.queue::<f32>(8192)?;
        let counters = Arc::new(Counters::default());
        let capture = counters.clone();
        let errors = counters.clone();
        let stream = device
            .build_input_stream(
                cpal::StreamConfig {
                    channels: channels as u16,
                    sample_rate: 48000,
                    buffer_size: cpal::BufferSize::Fixed(256),
                },
                move |data: &[f32], _: &cpal::InputCallbackInfo| {
                    // Backend timestamps are not a verified clock map. Preserve null.
                    if tx.write_next(data, None, 0).is_err() {
                        capture.rejected.fetch_add(1, Relaxed);
                    }
                    capture.callbacks.fetch_add(1, Relaxed);
                    capture
                        .frames
                        .fetch_add((data.len() / channels) as u64, Relaxed);
                },
                move |error| {
                    if error.kind() == cpal::ErrorKind::Xrun {
                        errors.xruns.fetch_add(1, Relaxed);
                    } else {
                        errors.errors.fetch_add(1, Relaxed);
                    }
                },
                Some(Duration::from_secs(5)),
            )
            .map_err(|e| e.to_string())?;
        Ok((
            Self {
                stream: Some(stream),
                counters,
            },
            rx,
        ))
    }
    pub fn start(&self) -> Result<(), String> {
        self.stream
            .as_ref()
            .ok_or("live_input_closed")?
            .play()
            .map_err(|e| e.to_string())
    }
    pub fn failed(&self) -> bool {
        self.counters.errors.load(Relaxed) != 0
            || self.counters.rejected.load(Relaxed) != 0
            || self.counters.xruns.load(Relaxed) != 0
    }
    pub fn stop(&mut self) -> Result<f64, String> {
        let started = Instant::now();
        if let Some(stream) = self.stream.take() {
            let paused = stream.pause().map_err(|e| e.to_string());
            drop(stream); // release before returning, including pause failure
            paused?;
        }
        Ok(started.elapsed().as_secs_f64() * 1000.)
    }
    pub fn report(&self) -> Value {
        json!({"callbacks": self.counters.callbacks.load(Relaxed),
            "frames": self.counters.frames.load(Relaxed),
            "rejected": self.counters.rejected.load(Relaxed),
            "errors": self.counters.errors.load(Relaxed),
            "xruns": self.counters.xruns.load(Relaxed), "closed": self.stream.is_none()})
    }
}
impl Drop for LiveInput {
    fn drop(&mut self) {
        let _ = self.stop();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn validates_explicit_ports_before_device_access() {
        let mut format = IoFormat {
            stream_id: "live".into(),
            generation: 1,
            timebase_id: "clock".into(),
            clock_domain: "cpal.device:BlackHole 16ch".into(),
            rate: [48000, 1],
            input_ids: vec!["left".into(), "right".into()],
            input_ports: vec![15, 3],
            output_ids: vec![],
            output_ports: vec![],
        };
        validate("BlackHole 16ch", 16, &format).unwrap();
        assert!(validate("BlackHole 16ch", 2, &format).is_err());
        assert!(validate("", 16, &format).is_err());
        format.input_ports = vec![3, 3];
        assert!(validate("BlackHole 16ch", 16, &format).is_err());
        format.input_ports = vec![15, 3];
        format.rate = [44100, 1];
        assert!(validate("BlackHole 16ch", 16, &format).is_err());
    }

    #[test]
    fn callback_errors_and_xruns_fail_the_correctness_stream() {
        for key in 0..3 {
            let counters = Arc::new(Counters::default());
            let input = LiveInput {
                stream: None,
                counters: counters.clone(),
            };
            assert!(!input.failed());
            match key {
                0 => &counters.errors,
                1 => &counters.rejected,
                _ => &counters.xruns,
            }
            .store(1, Relaxed);
            assert!(input.failed());
        }
    }
}
