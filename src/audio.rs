use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU64, Ordering},
        mpsc,
    },
    thread,
    time::Duration,
};

use crate::signal::{MAX_CHANNELS, Samples};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use rtrb::{Consumer, Producer, RingBuffer};

pub const MAX_SAMPLE_RATE: u32 = 768_000;
const SAMPLE_RATES: &[u32] = &[
    8_000, 11_025, 16_000, 22_050, 32_000, 44_100, 48_000, 88_200, 96_000, 176_400, 192_000,
    352_800, 384_000, 705_600, 768_000,
];

/// Measurement I/O favors callback headroom over monitoring latency. CoreAudio
/// uses a device-wide buffer: request the same policy for input and output,
/// bounded by the reported capability, without changing Fs, PCM or channels.
pub(crate) fn measurement_stream_config(
    supported: cpal::SupportedStreamConfig,
) -> cpal::StreamConfig {
    let buffer_size = if cfg!(target_os = "macos") {
        measurement_buffer_size(supported.sample_rate(), supported.buffer_size())
    } else {
        cpal::BufferSize::Default
    };
    let mut config: cpal::StreamConfig = supported.into();
    config.buffer_size = buffer_size;
    config
}

fn measurement_buffer_size(rate: u32, limits: &cpal::SupportedBufferSize) -> cpal::BufferSize {
    let cpal::SupportedBufferSize::Range { min, max } = *limits else {
        return cpal::BufferSize::Default;
    };
    if min == 0 || min > max {
        return cpal::BufferSize::Default;
    }
    let frames = rate.div_ceil(50).max(1).next_power_of_two();
    cpal::BufferSize::Fixed(frames.clamp(min, max))
}

#[derive(Clone, Copy, Debug)]
pub struct AudioFrame {
    pub samples: Samples,
    pub sequence: u64,
    /// Host availability of this callback batch, not the ADC sampling time.
    #[cfg(feature = "qa")]
    pub available_at: Option<std::time::Instant>,
}

#[derive(Default)]
pub struct Metrics {
    pub dropped: AtomicU64,
    pub callbacks: AtomicU64,
    /// Exclusive source-frame endpoint of the last completed callback,
    /// including queue loss. Published after its frames and drop count.
    pub input_end: AtomicU64,
    pub failed: AtomicBool,
    #[cfg(feature = "qa")]
    pub profile: crate::callback_profile::Metrics,
    #[cfg(feature = "qa")]
    pub callback_min_frames: AtomicU64,
    #[cfg(feature = "qa")]
    pub callback_max_frames: AtomicU64,
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
    /// Backend-qualified stable identity; names and enumeration order are not IDs.
    pub id: Option<String>,
    pub name: String,
    pub channels: u16,
    pub default_sample_rate: u32,
    pub is_default: bool,
    pub sample_rates: Vec<u32>,
}

pub enum Command {
    Refresh,
    Start {
        device: usize,
        sample_rate: Option<u32>,
    },
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
                                    .map(|d| {
                                        let config = d.default_input_config().ok();
                                        let ranges = d
                                            .supported_input_configs()
                                            .map(|configs| configs.collect::<Vec<_>>())
                                            .unwrap_or_default();
                                        DeviceInfo {
                                            id: d.id().ok().map(|id| id.to_string()),
                                            name: d.to_string(),
                                            channels: config.as_ref().map_or(0, |c| c.channels()),
                                            default_sample_rate: config
                                                .as_ref()
                                                .map_or(0, |c| c.sample_rate()),
                                            is_default: default.as_ref() == Some(d),
                                            sample_rates: available_sample_rates(
                                                config.as_ref(),
                                                &ranges,
                                            ),
                                        }
                                    })
                                    .collect();
                                let _ = events.send(Event::Devices(info));
                            }
                            Err(error) => {
                                let _ = events.send(Event::Error(error.to_string()));
                            }
                        }
                    }
                    Command::Start {
                        device,
                        sample_rate,
                    } => {
                        // Release the old device before opening the new one.
                        stream.take();
                        let result = devices
                            .get(device)
                            .ok_or_else(|| {
                                "Input device is unavailable. Refresh the device list.".to_owned()
                            })
                            .and_then(|device| start_device(device, sample_rate));
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

pub fn validate_sample_rate(sample_rate: u32) -> Result<(), String> {
    if (1..=MAX_SAMPLE_RATE).contains(&sample_rate) {
        Ok(())
    } else {
        Err(format!(
            "Sample rate must be between 1 and {MAX_SAMPLE_RATE} Hz."
        ))
    }
}

fn supported_pcm(format: cpal::SampleFormat) -> bool {
    matches!(
        format,
        cpal::SampleFormat::I8
            | cpal::SampleFormat::I16
            | cpal::SampleFormat::I24
            | cpal::SampleFormat::I32
            | cpal::SampleFormat::I64
            | cpal::SampleFormat::U8
            | cpal::SampleFormat::U16
            | cpal::SampleFormat::U24
            | cpal::SampleFormat::U32
            | cpal::SampleFormat::U64
            | cpal::SampleFormat::F32
            | cpal::SampleFormat::F64
    )
}

fn available_sample_rates(
    default: Option<&cpal::SupportedStreamConfig>,
    ranges: &[cpal::SupportedStreamConfigRange],
) -> Vec<u32> {
    let Some(default) = default else {
        return Vec::new();
    };
    if !(1..=MAX_CHANNELS as u16).contains(&default.channels()) {
        return Vec::new();
    }
    let mut rates = Vec::new();
    if supported_pcm(default.sample_format()) {
        rates.push(default.sample_rate());
    }
    for range in ranges
        .iter()
        .filter(|r| r.channels() == default.channels() && supported_pcm(r.sample_format()))
    {
        rates.extend(
            SAMPLE_RATES
                .iter()
                .copied()
                .filter(|&rate| range.try_with_sample_rate(rate).is_some()),
        );
        // Keep nonstandard device rates as well as the common audio presets.
        rates.extend([range.min_sample_rate(), range.max_sample_rate()]);
    }
    rates.retain(|&rate| validate_sample_rate(rate).is_ok());
    rates.sort_unstable();
    rates.dedup();
    rates
}

fn select_input_config(
    default: cpal::SupportedStreamConfig,
    ranges: &[cpal::SupportedStreamConfigRange],
    requested: Option<u32>,
) -> Result<cpal::SupportedStreamConfig, String> {
    if default.channels() == 0 {
        return Err("Device returned an invalid audio configuration.".into());
    }
    if default.channels() as usize > MAX_CHANNELS {
        return Err(format!(
            "Input has {} channels; at most {MAX_CHANNELS} are supported.",
            default.channels()
        ));
    }
    let rate = requested.unwrap_or(default.sample_rate());
    validate_sample_rate(rate)?;
    if rate == default.sample_rate() && supported_pcm(default.sample_format()) {
        return Ok(default);
    }
    if requested.is_none() {
        return Err(format!(
            "Unsupported audio format: {}",
            default.sample_format()
        ));
    }
    ranges.iter()
        // A rate change must not silently reduce the device's input channels.
        .filter(|r| r.channels() == default.channels() && supported_pcm(r.sample_format()))
        .filter_map(|r| r.try_with_sample_rate(rate))
        .max_by_key(|c| c.sample_format() == default.sample_format())
        .ok_or_else(|| format!(
            "Input device does not support {rate} Hz with {} channels. Refresh the device list.",
            default.channels()
        ))
}

pub fn start_device(
    device: &cpal::Device,
    sample_rate: Option<u32>,
) -> Result<(cpal::Stream, Capture), String> {
    let default = device.default_input_config().map_err(|e| e.to_string())?;
    let ranges = if sample_rate.is_some_and(|rate| rate != default.sample_rate()) {
        device
            .supported_input_configs()
            .map_err(|e| e.to_string())?
            .collect()
    } else {
        Vec::new()
    };
    let supported = select_input_config(default, &ranges, sample_rate)?;
    let format = supported.sample_format();
    let config = measurement_stream_config(supported);
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
    f64: cpal::FromSample<T>,
{
    let channels = config.channels as usize;
    #[cfg(feature = "qa")]
    let rate = config.sample_rate;
    let failure = metrics.clone();
    let mut sequence = 0;
    device.build_input_stream(
        config,
        move |input: &[T], _| {
            #[cfg(feature = "qa")]
            let started = std::time::Instant::now();
            write_callback(input, channels, &mut producer, &mut sequence, &metrics);
            #[cfg(feature = "qa")]
            metrics
                .profile
                .record(started.elapsed(), input.len() / channels, rate);
        },
        move |error| {
            #[cfg(feature = "qa")]
            failure.profile.notification(&error);
            #[cfg(not(feature = "qa"))]
            let _ = error;
            failure.failed.store(true, Ordering::Release);
        },
        Some(Duration::from_secs(2)),
    )
}

/// The CPAL data path, also exercised by device-independent transport tests.
/// No allocation, locks, waiting or analysis; callback size need not be fixed.
pub(crate) fn write_callback<T: cpal::Sample>(
    input: &[T],
    channels: usize,
    producer: &mut Producer<AudioFrame>,
    sequence: &mut u64,
    metrics: &Metrics,
) where
    f64: cpal::FromSample<T>,
{
    #[cfg(feature = "qa")]
    {
        let frames = (input.len() / channels) as u64;
        // Zero means no nonempty callback observed yet.
        if frames > 0 {
            let previous = metrics.callback_min_frames.load(Ordering::Relaxed);
            metrics.callback_min_frames.store(
                if previous == 0 {
                    frames
                } else {
                    previous.min(frames)
                },
                Ordering::Relaxed,
            );
            metrics
                .callback_max_frames
                .fetch_max(frames, Ordering::Relaxed);
        }
    }
    let dropped = write_input(input, channels, producer, sequence);
    metrics.dropped.fetch_add(dropped, Ordering::Relaxed);
    metrics.callbacks.fetch_add(1, Ordering::Relaxed);
    metrics.input_end.store(*sequence, Ordering::Release);
}

fn write_input<T: cpal::Sample>(
    input: &[T],
    channels: usize,
    producer: &mut Producer<AudioFrame>,
    sequence: &mut u64,
) -> u64
where
    f64: cpal::FromSample<T>,
{
    // One clock read per callback, before PCM conversion/queueing. No per-frame
    // clock access, allocation, locking or waiting in the real-time path.
    #[cfg(feature = "qa")]
    let available_at = Some(std::time::Instant::now());
    let mut dropped = 0;
    for frame in input.chunks_exact(channels) {
        let mut samples = [0.0; MAX_CHANNELS];
        for (target, &sample) in samples.iter_mut().zip(frame) {
            *target = sample.to_sample::<f64>();
        }
        if producer
            .push(AudioFrame {
                samples,
                sequence: *sequence,
                #[cfg(feature = "qa")]
                available_at,
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
pub fn input_device(name: Option<&str>) -> Result<cpal::Device, String> {
    let host = cpal::default_host();
    if let Some(name) = name {
        host.input_devices()
            .map_err(|e| e.to_string())?
            .find(|device| device.to_string() == name)
            .ok_or_else(|| format!("Input device not found: {name}"))
    } else {
        host.default_input_device()
            .ok_or_else(|| "No default input device".to_owned())
    }
}

pub fn smoke_test(name: Option<&str>, sample_rate: Option<u32>) -> Result<(), String> {
    let device = input_device(name)?;
    let (_stream, mut capture) = start_device(&device, sample_rate)?;
    let deadline = std::time::Instant::now() + Duration::from_secs(2);
    let mut frames = 0;
    let mut peaks = [0.0_f64; MAX_CHANNELS];
    while std::time::Instant::now() < deadline {
        while let Ok(frame) = capture.consumer.pop() {
            frames += 1;
            for (peak, sample) in peaks.iter_mut().zip(frame.samples) {
                *peak = peak.max(sample.abs());
            }
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
        "Audio OK: {} / {} Hz / {} channels / {} frames / dropped {} / channel peaks {:?} FS",
        device,
        capture.sample_rate,
        capture.channels,
        frames,
        capture.metrics.dropped.load(Ordering::Relaxed),
        &peaks[..capture.channels as usize]
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn measurement_buffer_headroom_scales_with_fs_and_respects_device_limits() {
        let limits = cpal::SupportedBufferSize::Range { min: 64, max: 4096 };
        for (rate, frames) in [
            (8000, 256),
            (44100, 1024),
            (48000, 1024),
            (96000, 2048),
            (192000, 4096),
        ] {
            assert_eq!(
                measurement_buffer_size(rate, &limits),
                cpal::BufferSize::Fixed(frames)
            );
        }
        assert_eq!(
            measurement_buffer_size(768000, &limits),
            cpal::BufferSize::Fixed(4096)
        );
        assert_eq!(
            measurement_buffer_size(
                48000,
                &cpal::SupportedBufferSize::Range { min: 64, max: 512 }
            ),
            cpal::BufferSize::Fixed(512)
        );
        assert_eq!(
            measurement_buffer_size(
                48000,
                &cpal::SupportedBufferSize::Range {
                    min: 2048,
                    max: 4096
                }
            ),
            cpal::BufferSize::Fixed(2048)
        );
        for limits in [
            cpal::SupportedBufferSize::Unknown,
            cpal::SupportedBufferSize::Range { min: 0, max: 0 },
            cpal::SupportedBufferSize::Range { min: 512, max: 64 },
        ] {
            assert_eq!(
                measurement_buffer_size(48000, &limits),
                cpal::BufferSize::Default
            );
        }
    }

    #[test]
    fn measurement_buffer_policy_preserves_selected_rate_and_topology() {
        let supported = cpal::SupportedStreamConfig::new(
            16,
            96000,
            cpal::SupportedBufferSize::Range { min: 64, max: 4096 },
            cpal::SampleFormat::F64,
        );
        let selected = measurement_stream_config(supported);
        assert_eq!(selected.sample_rate, 96000);
        assert_eq!(selected.channels, 16);
        assert_eq!(
            selected.buffer_size,
            if cfg!(target_os = "macos") {
                cpal::BufferSize::Fixed(2048)
            } else {
                cpal::BufferSize::Default
            }
        );
    }

    fn config(channels: u16, rate: u32, format: cpal::SampleFormat) -> cpal::SupportedStreamConfig {
        cpal::SupportedStreamConfig::new(channels, rate, cpal::SupportedBufferSize::Unknown, format)
    }

    fn range(
        channels: u16,
        min: u32,
        max: u32,
        format: cpal::SampleFormat,
    ) -> cpal::SupportedStreamConfigRange {
        cpal::SupportedStreamConfigRange::new(
            channels,
            min,
            max,
            cpal::SupportedBufferSize::Unknown,
            format,
        )
    }

    #[test]
    fn rate_choices_keep_device_rates_and_stop_at_768_khz() {
        let default = config(16, 96_000, cpal::SampleFormat::F32);
        let ranges = [
            range(16, 44_100, 1_536_000, cpal::SampleFormat::F32),
            range(16, 100_000, 100_000, cpal::SampleFormat::F64),
            range(2, 8_000, 192_000, cpal::SampleFormat::F32),
            range(16, 4_000, 4_000, cpal::SampleFormat::DsdU8),
        ];
        assert_eq!(
            available_sample_rates(Some(&default), &ranges),
            vec![
                44_100, 48_000, 88_200, 96_000, 100_000, 176_400, 192_000, 352_800, 384_000,
                705_600, 768_000,
            ]
        );
        assert_eq!(available_sample_rates(Some(&default), &[]), vec![96_000]);
        assert!(available_sample_rates(None, &ranges).is_empty());
        assert!(
            available_sample_rates(Some(&config(32, 96_000, cpal::SampleFormat::F32)), &ranges)
                .is_empty()
        );
    }

    #[test]
    fn requested_rates_preserve_channels_and_prefer_default_pcm_format() {
        for channels in [1, 2, 16] {
            let default = config(channels, 48_000, cpal::SampleFormat::F32);
            let ranges = [
                range(channels, 44_100, 768_000, cpal::SampleFormat::F32),
                range(channels, 44_100, 768_000, cpal::SampleFormat::I16),
            ];
            for rate in [44_100, 48_000, 96_000, 192_000, 768_000] {
                let selected = select_input_config(default, &ranges, Some(rate)).unwrap();
                assert_eq!(selected.sample_rate(), rate);
                assert_eq!(selected.channels(), channels);
                assert_eq!(selected.sample_format(), cpal::SampleFormat::F32);
            }
            let automatic = select_input_config(default, &[], None).unwrap();
            assert_eq!(automatic.sample_rate(), 48_000);
            // Default-rate input still works when the driver cannot enumerate ranges.
            assert_eq!(
                select_input_config(default, &[], Some(48_000))
                    .unwrap()
                    .sample_rate(),
                48_000
            );
        }
    }

    #[test]
    fn unsupported_rates_are_rejected_without_fallback_or_channel_reduction() {
        let default = config(16, 48_000, cpal::SampleFormat::F32);
        let ranges = [
            range(16, 48_000, 96_000, cpal::SampleFormat::F32),
            range(2, 192_000, 192_000, cpal::SampleFormat::F32),
            range(16, 192_000, 192_000, cpal::SampleFormat::DsdU8),
        ];
        for rate in [0, 44_100, 192_000, 768_001] {
            assert!(select_input_config(default, &ranges, Some(rate)).is_err());
        }
        assert!(
            select_input_config(config(0, 48_000, cpal::SampleFormat::F32), &ranges, None).is_err()
        );
        assert!(
            select_input_config(
                config(32, 48_000, cpal::SampleFormat::F32),
                &ranges,
                Some(96_000)
            )
            .is_err()
        );
        let alternate = [range(16, 192_000, 192_000, cpal::SampleFormat::F64)];
        assert_eq!(
            select_input_config(default, &alternate, Some(192_000))
                .unwrap()
                .sample_format(),
            cpal::SampleFormat::F64
        );
    }

    #[test]
    fn f64_device_input_is_not_quantized_to_f32() {
        let (mut producer, mut consumer) = RingBuffer::new(1);
        write_input(&[1.0_f64 + 1e-8], 1, &mut producer, &mut 0);
        assert_eq!(consumer.pop().unwrap().samples[0], 1.0 + 1e-8);
    }

    #[test]
    fn signed_stereo_conversion_and_overflow_sequence_are_correct() {
        let (mut producer, mut consumer) = RingBuffer::new(1);
        let mut sequence = 0;
        assert_eq!(
            write_input(&[i16::MIN, 0, 100, 200], 2, &mut producer, &mut sequence),
            1
        );
        let first = consumer.pop().unwrap();
        assert_eq!(&first.samples[..2], &[-1.0, 0.0]);
        assert_eq!(first.sequence, 0);
        write_input(&[0_i16, 0], 2, &mut producer, &mut sequence);
        assert_eq!(consumer.pop().unwrap().sequence, 2);
    }

    #[test]
    fn unsigned_mono_equilibrium_and_multichannel_mapping() {
        let (mut producer, mut consumer) = RingBuffer::new(4);
        let mut sequence = 0;
        write_input(&[32768_u16], 1, &mut producer, &mut sequence);
        assert_eq!(consumer.pop().unwrap().samples, [0.0; MAX_CHANNELS]);
        write_input(&[0.2_f32, -0.3, 0.9, 0.8], 4, &mut producer, &mut sequence);
        assert_eq!(
            &consumer.pop().unwrap().samples[..4],
            &[
                0.2_f32 as f64,
                -0.3_f32 as f64,
                0.9_f32 as f64,
                0.8_f32 as f64
            ]
        );
    }

    #[test]
    fn all_sixteen_channels_keep_the_same_frame_sequence() {
        let (mut producer, mut consumer) = RingBuffer::new(2);
        let mut sequence = 4000;
        let input: Vec<_> = (0..32).map(|i| i as f64 / 32.0).collect();
        assert_eq!(write_input(&input, 16, &mut producer, &mut sequence), 0);
        for frame_index in 0..2 {
            let frame = consumer.pop().unwrap();
            assert_eq!(frame.sequence, 4000 + frame_index as u64);
            assert_eq!(
                &frame.samples,
                &input[frame_index * 16..(frame_index + 1) * 16]
            );
        }
    }

    #[test]
    fn variable_callbacks_preserve_pcm_conversion_channel_order_and_source_clock() {
        fn check<T: cpal::Sample>(input: &[T], channels: usize)
        where
            f64: cpal::FromSample<T>,
        {
            let (mut producer, mut consumer) = RingBuffer::new(1025);
            let metrics = Metrics::default();
            let mut sequence = 0;
            let mut start = 0;
            for (index, count) in [0, 1, 17, 255, 512, 1025, 7, 0].into_iter().enumerate() {
                let end = start + count;
                write_callback(
                    &input[start * channels..end * channels],
                    channels,
                    &mut producer,
                    &mut sequence,
                    &metrics,
                );
                assert_eq!(sequence, end as u64);
                assert_eq!(metrics.input_end.load(Ordering::Acquire), end as u64);
                assert_eq!(metrics.callbacks.load(Ordering::Relaxed), index as u64 + 1);
                assert_eq!(metrics.dropped.load(Ordering::Relaxed), 0);
                for n in start..end {
                    let frame = consumer.pop().unwrap();
                    assert_eq!(frame.sequence, n as u64);
                    for ch in 0..channels {
                        assert_eq!(
                            frame.samples[ch],
                            input[n * channels + ch].to_sample::<f64>()
                        );
                    }
                    assert!(frame.samples[channels..].iter().all(|&v| v == 0.0));
                }
                assert!(consumer.is_empty());
                start = end;
            }
            #[cfg(feature = "qa")]
            {
                assert_eq!(metrics.callback_min_frames.load(Ordering::Relaxed), 1);
                assert_eq!(metrics.callback_max_frames.load(Ordering::Relaxed), 1025);
            }
        }
        for channels in [1, 2, 16] {
            let samples = 1817 * channels;
            check(
                &(0..samples)
                    .map(|n| n as f64 * 1e-8 + 0.25)
                    .collect::<Vec<_>>(),
                channels,
            );
            check(
                &(0..samples)
                    .map(|n| n as f32 * 1e-5 - 0.5)
                    .collect::<Vec<_>>(),
                channels,
            );
            check(
                &(0..samples).map(|n| n as i16 - 16384).collect::<Vec<_>>(),
                channels,
            );
            check(
                &(0..samples).map(|n| n as u16 + 32768).collect::<Vec<_>>(),
                channels,
            );
        }
    }

    #[test]
    fn callback_endpoint_includes_overflow_and_empty_callbacks_do_not_erase_it() {
        let (mut producer, mut consumer) = RingBuffer::new(8);
        let metrics = Metrics::default();
        let mut sequence = 0;
        for count in [2, 17, 0] {
            write_callback(
                &vec![0.125_f64; count * 2],
                2,
                &mut producer,
                &mut sequence,
                &metrics,
            );
        }
        assert_eq!(metrics.input_end.load(Ordering::Acquire), 19);
        assert_eq!(metrics.dropped.load(Ordering::Relaxed), 11);
        for n in 0..8 {
            assert_eq!(consumer.pop().unwrap().sequence, n);
        }
        write_callback(
            &[0.125_f64, 0.0625],
            2,
            &mut producer,
            &mut sequence,
            &metrics,
        );
        assert_eq!(consumer.pop().unwrap().sequence, 19);
        assert_eq!(metrics.input_end.load(Ordering::Acquire), 20);
        assert_eq!(metrics.dropped.load(Ordering::Relaxed), 11);
        #[cfg(feature = "qa")]
        {
            assert_eq!(metrics.callback_min_frames.load(Ordering::Relaxed), 1);
            assert_eq!(metrics.callback_max_frames.load(Ordering::Relaxed), 17);
        }
    }
}
