use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU64, Ordering},
        mpsc,
    },
    thread,
    time::Duration,
};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use rtrb::{Consumer, Producer, RingBuffer};

#[derive(Clone, Copy, Debug)]
pub struct AudioFrame {
    pub samples: [f32; 2],
    pub sequence: u64,
}

#[derive(Default)]
pub struct Metrics {
    pub dropped: AtomicU64,
    pub callbacks: AtomicU64,
    pub failed: AtomicBool,
}

pub struct Capture {
    pub consumer: Consumer<AudioFrame>,
    pub sample_rate: u32,
    pub channels: u16,
    pub format: String,
    pub metrics: Arc<Metrics>,
}

#[derive(Clone, Debug)]
pub struct DeviceInfo {
    pub name: String,
    pub is_default: bool,
}

pub enum Command {
    Refresh,
    Start(usize),
    Stop,
    Shutdown,
}
pub enum Event {
    Devices(Vec<DeviceInfo>),
    Started(Capture),
    Stopped,
    Error(String),
}

/// Device discovery and stream creation stay off the UI thread. The actual
/// data callback only converts samples and writes into a bounded SPSC queue.
pub struct AudioWorker {
    commands: mpsc::Sender<Command>,
    pub events: mpsc::Receiver<Event>,
    handle: Option<thread::JoinHandle<()>>,
}

impl AudioWorker {
    pub fn new() -> Self {
        let (commands, requests) = mpsc::channel();
        let (events, receiver) = mpsc::channel();
        let handle = thread::spawn(move || {
            let host = cpal::default_host();
            let mut devices = Vec::new();
            let mut stream: Option<cpal::Stream> = None;
            while let Ok(command) = requests.recv() {
                match command {
                    Command::Refresh => {
                        let default = host.default_input_device();
                        match host.input_devices() {
                            Ok(found) => {
                                devices = found.collect();
                                let info = devices
                                    .iter()
                                    .map(|d| DeviceInfo {
                                        name: d.to_string(),
                                        is_default: default.as_ref() == Some(d),
                                    })
                                    .collect();
                                let _ = events.send(Event::Devices(info));
                            }
                            Err(error) => {
                                let _ = events.send(Event::Error(error.to_string()));
                            }
                        }
                    }
                    Command::Start(index) => {
                        // Release the old device before opening the new one.
                        stream.take();
                        let result = devices
                            .get(index)
                            .ok_or_else(|| {
                                "Input device is unavailable. Refresh the device list.".to_owned()
                            })
                            .and_then(start_device);
                        match result {
                            Ok((opened, capture)) => {
                                stream = Some(opened);
                                let _ = events.send(Event::Started(capture));
                            }
                            Err(error) => {
                                let _ = events.send(Event::Error(error));
                            }
                        }
                    }
                    Command::Stop => {
                        stream.take();
                        let _ = events.send(Event::Stopped);
                    }
                    Command::Shutdown => break,
                }
            }
        });
        let worker = Self {
            commands,
            events: receiver,
            handle: Some(handle),
        };
        worker.send(Command::Refresh);
        worker
    }

    pub fn send(&self, command: Command) {
        let _ = self.commands.send(command);
    }
}

impl Default for AudioWorker {
    fn default() -> Self {
        Self::new()
    }
}

impl Drop for AudioWorker {
    fn drop(&mut self) {
        let _ = self.commands.send(Command::Shutdown);
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }
}

pub fn start_device(device: &cpal::Device) -> Result<(cpal::Stream, Capture), String> {
    let supported = device.default_input_config().map_err(|e| e.to_string())?;
    let format = supported.sample_format();
    let config: cpal::StreamConfig = supported.into();
    if config.channels == 0 || config.sample_rate == 0 {
        return Err("Device returned an invalid audio configuration.".to_owned());
    }
    let (producer, consumer) =
        RingBuffer::new((config.sample_rate as usize / 2).clamp(1024, 262_144));
    let metrics = Arc::new(Metrics::default());
    macro_rules! build {
        ($ty:ty) => {
            build_stream::<$ty>(device, config.clone(), producer, metrics.clone())
        };
    }
    let stream = match format {
        cpal::SampleFormat::I8 => build!(i8),
        cpal::SampleFormat::I16 => build!(i16),
        cpal::SampleFormat::I24 => build!(cpal::I24),
        cpal::SampleFormat::I32 => build!(i32),
        cpal::SampleFormat::I64 => build!(i64),
        cpal::SampleFormat::U8 => build!(u8),
        cpal::SampleFormat::U16 => build!(u16),
        cpal::SampleFormat::U24 => build!(cpal::U24),
        cpal::SampleFormat::U32 => build!(u32),
        cpal::SampleFormat::U64 => build!(u64),
        cpal::SampleFormat::F32 => build!(f32),
        cpal::SampleFormat::F64 => build!(f64),
        other => return Err(format!("Unsupported audio format: {other}")),
    }
    .map_err(|e| e.to_string())?;
    stream.play().map_err(|e| e.to_string())?;
    Ok((
        stream,
        Capture {
            consumer,
            sample_rate: config.sample_rate,
            channels: config.channels,
            format: format.to_string(),
            metrics,
        },
    ))
}

fn build_stream<T>(
    device: &cpal::Device,
    config: cpal::StreamConfig,
    mut producer: Producer<AudioFrame>,
    metrics: Arc<Metrics>,
) -> Result<cpal::Stream, cpal::Error>
where
    T: cpal::SizedSample,
    f32: cpal::FromSample<T>,
{
    let channels = config.channels as usize;
    let failure = metrics.clone();
    let mut sequence = 0;
    device.build_input_stream(
        config,
        move |input: &[T], _| {
            let dropped = write_input(input, channels, &mut producer, &mut sequence);
            metrics.dropped.fetch_add(dropped, Ordering::Relaxed);
            metrics.callbacks.fetch_add(1, Ordering::Relaxed);
        },
        move |_| {
            failure.failed.store(true, Ordering::Relaxed);
        },
        Some(Duration::from_secs(2)),
    )
}

fn write_input<T: cpal::Sample>(
    input: &[T],
    channels: usize,
    producer: &mut Producer<AudioFrame>,
    sequence: &mut u64,
) -> u64
where
    f32: cpal::FromSample<T>,
{
    let mut dropped = 0;
    for frame in input.chunks_exact(channels) {
        let samples = [
            frame[0].to_sample::<f32>(),
            if channels >= 2 {
                frame[1].to_sample::<f32>()
            } else {
                0.0
            },
        ];
        if producer
            .push(AudioFrame {
                samples,
                sequence: *sequence,
            })
            .is_err()
        {
            dropped += 1;
        }
        *sequence += 1;
    }
    dropped
}

/// Explicit CLI hardware check; no audio is written to disk.
pub fn smoke_test() -> Result<(), String> {
    let host = cpal::default_host();
    let device = host
        .default_input_device()
        .ok_or("No default input device")?;
    let (_stream, mut capture) = start_device(&device)?;
    let deadline = std::time::Instant::now() + Duration::from_secs(2);
    let mut frames = 0;
    let mut peak = 0.0_f32;
    while std::time::Instant::now() < deadline {
        while let Ok(frame) = capture.consumer.pop() {
            frames += 1;
            peak = peak.max(frame.samples[0].abs());
        }
        thread::sleep(Duration::from_millis(5));
    }
    if capture.metrics.failed.load(Ordering::Relaxed) {
        return Err("Audio stream failed".into());
    }
    if frames == 0 {
        return Err(
            "No audio frames received. Check microphone permission and device availability.".into(),
        );
    }
    println!(
        "Audio OK: {} / {} Hz / {} channels / {} frames / peak {:.5} FS / dropped {}",
        device,
        capture.sample_rate,
        capture.channels,
        frames,
        peak,
        capture.metrics.dropped.load(Ordering::Relaxed)
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn signed_stereo_conversion_and_overflow_sequence_are_correct() {
        let (mut producer, mut consumer) = RingBuffer::new(1);
        let mut sequence = 0;
        assert_eq!(
            write_input(&[i16::MIN, 0, 100, 200], 2, &mut producer, &mut sequence),
            1
        );
        let first = consumer.pop().unwrap();
        assert_eq!(first.samples, [-1.0, 0.0]);
        assert_eq!(first.sequence, 0);
        write_input(&[0_i16, 0], 2, &mut producer, &mut sequence);
        assert_eq!(consumer.pop().unwrap().sequence, 2);
    }

    #[test]
    fn unsigned_mono_equilibrium_and_multichannel_mapping() {
        let (mut producer, mut consumer) = RingBuffer::new(4);
        let mut sequence = 0;
        write_input(&[32768_u16], 1, &mut producer, &mut sequence);
        assert_eq!(consumer.pop().unwrap().samples, [0.0, 0.0]);
        write_input(&[0.2_f32, -0.3, 0.9, 0.8], 4, &mut producer, &mut sequence);
        assert_eq!(consumer.pop().unwrap().samples, [0.2, -0.3]);
    }
}
