//! Output-only discovery and exact config selection. Streams are opened by the
//! output manager; the callback owns the f64 engine and only writes PCM.
use super::*;
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};

#[derive(
    Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, serde::Serialize, serde::Deserialize,
)]
#[serde(rename_all = "lowercase")]
pub enum Pcm {
    F32,
    F64,
    I8,
    I16,
    I24,
    I32,
    I64,
    U8,
    U16,
    U24,
    U32,
    U64,
}
impl Pcm {
    fn from_format(format: cpal::SampleFormat) -> Option<Self> {
        use cpal::SampleFormat as F;
        Some(match format {
            F::F32 => Self::F32,
            F::F64 => Self::F64,
            F::I8 => Self::I8,
            F::I16 => Self::I16,
            F::I24 => Self::I24,
            F::I32 => Self::I32,
            F::I64 => Self::I64,
            F::U8 => Self::U8,
            F::U16 => Self::U16,
            F::U24 => Self::U24,
            F::U32 => Self::U32,
            F::U64 => Self::U64,
            _ => return None,
        })
    }
    pub fn label(self) -> &'static str {
        match self {
            Self::F32 => "f32",
            Self::F64 => "f64",
            Self::I8 => "i8",
            Self::I16 => "i16",
            Self::I24 => "i24",
            Self::I32 => "i32",
            Self::I64 => "i64",
            Self::U8 => "u8",
            Self::U16 => "u16",
            Self::U24 => "u24",
            Self::U32 => "u32",
            Self::U64 => "u64",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Config {
    pub rate: u32,
    pub channels: u16,
    pub pcm: Pcm,
}
#[derive(Clone, Debug)]
pub struct DeviceInfo {
    pub id: String,
    pub name: String,
    pub configs: Vec<Config>,
    pub preferred: Config,
}

/// Resolve a saved choice without relying on names or enumeration order.
pub fn resolve<'a>(
    devices: &'a [DeviceInfo],
    id: &str,
    requested: Config,
) -> Result<&'a DeviceInfo, String> {
    let mut matches = devices.iter().filter(|d| d.id == id);
    let device = matches
        .next()
        .ok_or("Saved output device is unavailable; refresh output devices")?;
    if matches.next().is_some() {
        return Err("Output device ID is ambiguous; refresh output devices".into());
    }
    if !device.configs.contains(&requested) {
        return Err("Saved output configuration is unavailable; refresh output devices".into());
    }
    Ok(device)
}

fn config(supported: cpal::SupportedStreamConfig) -> Option<Config> {
    let config = Config {
        rate: supported.sample_rate(),
        channels: supported.channels(),
        pcm: Pcm::from_format(supported.sample_format())?,
    };
    ((1..=crate::signal::MAX_CHANNELS as u16).contains(&config.channels)
        && crate::audio::validate_sample_rate(config.rate).is_ok())
    .then_some(config)
}

fn configs(
    default: Option<cpal::SupportedStreamConfig>,
    ranges: &[cpal::SupportedStreamConfigRange],
) -> Vec<Config> {
    const RATES: &[u32] = &[
        8_000, 11_025, 16_000, 22_050, 32_000, 44_100, 48_000, 88_200, 96_000, 176_400, 192_000,
        352_800, 384_000, 705_600, 768_000,
    ];
    let mut found: Vec<_> = default.and_then(config).into_iter().collect();
    for range in ranges {
        for rate in RATES
            .iter()
            .copied()
            .chain([range.min_sample_rate(), range.max_sample_rate()])
        {
            if let Some(c) = range.try_with_sample_rate(rate).and_then(config) {
                found.push(c);
            }
        }
    }
    found.sort_unstable();
    found.dedup();
    found
}

pub fn enumerate() -> Result<Vec<DeviceInfo>, String> {
    let devices = cpal::default_host()
        .output_devices()
        .map_err(|e| e.to_string())?;
    let mut found = Vec::new();
    for device in devices {
        let Ok(id) = device.id() else {
            continue;
        };
        let default = device.default_output_config().ok();
        let ranges: Vec<_> = device
            .supported_output_configs()
            .map(|r| r.collect())
            .unwrap_or_default();
        let configs = configs(default, &ranges);
        if let Some(preferred) = default
            .and_then(config)
            .or_else(|| configs.first().copied())
        {
            found.push(DeviceInfo {
                id: id.to_string(),
                name: device.to_string(),
                configs,
                preferred,
            });
        }
    }
    Ok(found)
}

fn select(
    default: Option<cpal::SupportedStreamConfig>,
    ranges: &[cpal::SupportedStreamConfigRange],
    requested: Config,
) -> Result<cpal::SupportedStreamConfig, String> {
    default
        .filter(|&c| config(c) == Some(requested))
        .or_else(|| {
            ranges
                .iter()
                .filter_map(|r| r.try_with_sample_rate(requested.rate))
                .find(|&c| config(c) == Some(requested))
        })
        .ok_or_else(|| {
            "Output device no longer supports the selected Fs, channels and PCM; refresh devices"
                .into()
        })
}

#[derive(Debug, Default)]
pub struct Metrics {
    pub callbacks: AtomicU64,
    pub failed: AtomicBool,
    pub notifications: AtomicU64,
    #[cfg(feature = "qa")]
    pub profile: crate::callback_profile::Metrics,
}

pub(super) fn open(
    id: &str,
    requested: Config,
    execution: control::Execution,
) -> Result<(cpal::Stream, Arc<Metrics>), String> {
    let mut matches = cpal::default_host()
        .output_devices()
        .map_err(|e| e.to_string())?
        .filter(|d| d.id().is_ok_and(|found| found.to_string() == id));
    let device = matches
        .next()
        .ok_or("Selected output device is unavailable; refresh devices")?;
    if matches.next().is_some() {
        return Err("Output device ID is ambiguous; refresh output devices".into());
    }
    let default = device.default_output_config().ok();
    let ranges: Vec<_> = device
        .supported_output_configs()
        .map(|r| r.collect())
        .unwrap_or_default();
    let supported = select(default, &ranges, requested)?;
    let config = crate::audio::measurement_stream_config(supported);
    let metrics = Arc::new(Metrics::default());
    macro_rules! build {
        ($t:ty) => {
            build::<$t>(&device, config, execution, metrics.clone())
        };
    }
    let stream = match requested.pcm {
        Pcm::F32 => build!(f32),
        Pcm::F64 => build!(f64),
        Pcm::I8 => build!(i8),
        Pcm::I16 => build!(i16),
        Pcm::I24 => build!(cpal::I24),
        Pcm::I32 => build!(i32),
        Pcm::I64 => build!(i64),
        Pcm::U8 => build!(u8),
        Pcm::U16 => build!(u16),
        Pcm::U24 => build!(cpal::U24),
        Pcm::U32 => build!(u32),
        Pcm::U64 => build!(u64),
    }
    .map_err(|e| e.to_string())?;
    stream.play().map_err(|e| e.to_string())?;
    Ok((stream, metrics))
}

/// Full-scale signed magnitude is 2^(bits-1). Integer conversion truncates
/// toward zero and saturates +1 FS to the positive endpoint. Unsigned PCM is
/// biased by its midpoint. This keeps error within 1 LSB, including 24-bit +1.
trait Sample: cpal::SizedSample {
    fn encode(sample: f64) -> Self;
}
macro_rules! primitive {
    ($($t:ty),*) => { $(impl Sample for $t {
        fn encode(sample: f64) -> Self { <Self as cpal::Sample>::from_sample(sample) }
    })* };
}
primitive!(f32, f64, i8, i16, i32, i64, u8, u16, u32, u64);
impl Sample for cpal::I24 {
    fn encode(sample: f64) -> Self {
        Self::new(((sample * 8_388_608.0) as i32).clamp(-8_388_608, 8_388_607)).unwrap()
    }
}
impl Sample for cpal::U24 {
    fn encode(sample: f64) -> Self {
        Self::new(cpal::I24::encode(sample).inner() + 8_388_608).unwrap()
    }
}

fn build<T: Sample>(
    device: &cpal::Device,
    config: cpal::StreamConfig,
    mut execution: control::Execution,
    metrics: Arc<Metrics>,
) -> Result<cpal::Stream, cpal::Error> {
    let channels = config.channels as usize;
    #[cfg(feature = "qa")]
    let rate = config.sample_rate;
    let failure = metrics.clone();
    device.build_output_stream(
        config,
        move |output: &mut [T], _| {
            #[cfg(feature = "qa")]
            let started = Instant::now();
            render(output, channels, &mut execution, &metrics);
            #[cfg(feature = "qa")]
            metrics
                .profile
                .record(started.elapsed(), output.len() / channels, rate);
        },
        move |error| {
            // Even connection-time notifications latch failure. Recovery is
            // explicit; no allocation, logging or locking on this path.
            failure.notifications.fetch_add(1, Ordering::Relaxed);
            #[cfg(feature = "qa")]
            failure.profile.notification(&error);
            #[cfg(not(feature = "qa"))]
            let _ = error;
            failure.failed.store(true, Ordering::Release);
        },
        Some(Duration::from_secs(2)),
    )
}

fn render<T: Sample>(
    output: &mut [T],
    channels: usize,
    execution: &mut control::Execution,
    metrics: &Metrics,
) {
    output.fill(T::EQUILIBRIUM);
    execution.begin_block();
    if metrics.failed.load(Ordering::Acquire) {
        execution.fail(generator::Error::OutputStream);
    }
    if channels == 0 || !output.len().is_multiple_of(channels) {
        execution.fail(generator::Error::ChannelCount);
        metrics.failed.store(true, Ordering::Release);
    } else {
        for pcm in output.chunks_exact_mut(channels) {
            // An asynchronous failure silences every subsequent frame.
            if metrics.failed.load(Ordering::Acquire) {
                execution.fail(generator::Error::OutputStream);
                break;
            }
            match execution.next_frame() {
                Ok(frame) => {
                    for (sample, &value) in pcm.iter_mut().zip(&frame.samples) {
                        *sample = T::encode(value);
                    }
                }
                Err(_) => break,
            }
        }
    }
    execution.end_block();
    metrics.callbacks.fetch_add(1, Ordering::Release);
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn saved_output_requires_unique_identity_and_exact_configuration() {
        let requested = Config {
            rate: 48_000,
            channels: 2,
            pcm: Pcm::F32,
        };
        let device = DeviceInfo {
            id: "stable-id".into(),
            name: "Output".into(),
            configs: vec![requested],
            preferred: requested,
        };
        let devices = [device.clone()];
        assert_eq!(
            resolve(&devices, "stable-id", requested).unwrap().id,
            "stable-id"
        );
        assert!(resolve(&devices, "missing", requested).is_err());
        assert!(
            resolve(
                &devices,
                "stable-id",
                Config {
                    pcm: Pcm::I16,
                    ..requested
                }
            )
            .is_err()
        );
        assert!(resolve(&[device.clone(), device], "stable-id", requested).is_err());
    }
    fn check<T: Sample>(lsb: f64)
    where
        f64: cpal::FromSample<T>,
    {
        for n in 0..=10000 {
            let x = n as f64 / 5000.0 - 1.0;
            assert!((T::encode(x).to_sample::<f64>() - x).abs() <= lsb + 2e-16);
        }
        assert_eq!(T::encode(0.0).to_sample::<f64>(), 0.0);
    }
    #[test]
    fn pcm_error_and_full_scale_endpoints() {
        check::<f64>(0.0);
        check::<f32>(3e-8);
        check::<i8>(2f64.powi(-7));
        check::<u8>(2f64.powi(-7));
        check::<i16>(2f64.powi(-15));
        check::<u16>(2f64.powi(-15));
        check::<cpal::I24>(2f64.powi(-23));
        check::<cpal::U24>(2f64.powi(-23));
        check::<i32>(2f64.powi(-31));
        check::<u32>(2f64.powi(-31));
        check::<i64>(2f64.powi(-63));
        check::<u64>(2f64.powi(-63));
        assert_eq!(cpal::I24::encode(1.0).inner(), 8_388_607);
        assert_eq!(cpal::U24::encode(1.0).inner(), 16_777_215);
    }
    #[test]
    fn variable_callbacks_match_f64_core_and_stop_survives_unconsumed_reports() {
        for channels in [1, 2, 16] {
            let mut settings = Settings::for_channels(channels);
            settings.signals[0].enabled = true;
            settings.signals[0].output_channel = Some(channels - 1);
            settings.signals[1].output_channel = None;
            let (mut controller, mut execution) =
                control::new(48000, channels, settings, 1 << 54).unwrap();
            let mut reference = Engine::new(48000, channels, settings, 1 << 54).unwrap();
            controller.start(settings).unwrap();
            reference.start(settings, 1).unwrap();
            let metrics = Metrics::default();
            for count in [1, 511, 17, 1024, 3, 4096] {
                let mut pcm = vec![42f32; count * channels];
                render(&mut pcm, channels, &mut execution, &metrics);
                for frame in pcm.chunks_exact(channels) {
                    let expected = reference.next_frame().unwrap();
                    for (ch, &value) in frame.iter().enumerate() {
                        assert!((value as f64 - expected.samples[ch]).abs() < 3e-8);
                    }
                }
            }
            let epoch = controller.stop().unwrap();
            reference.stop().unwrap();
            let mut pcm = vec![42f32; 1024 * channels];
            render(&mut pcm, channels, &mut execution, &metrics);
            for _ in 0..1024 {
                reference.next_frame().unwrap();
            }
            assert_eq!(execution.status().state, State::Stopped);
            assert!(pcm[480 * channels..].iter().all(|&v| v == 0.0));
            assert_eq!(execution.status().stopped_at, reference.status().stopped_at);
            let mut pcm = vec![42u16; 4 * channels];
            metrics.failed.store(true, Ordering::Release);
            render(&mut pcm, channels, &mut execution, &metrics);
            assert!(pcm.iter().all(|&x| x == 32768));
            assert_eq!(
                execution.status().state,
                State::Error(generator::Error::OutputStream)
            );
            assert!(controller.poll().is_some());
            assert_eq!(epoch, 1);
        }
    }
    #[test]
    fn configs_reject_fallbacks_and_keep_output_channel_variants() {
        let ranges = [cpal::SupportedStreamConfigRange::new(
            16,
            44100,
            192000,
            cpal::SupportedBufferSize::Unknown,
            cpal::SampleFormat::F32,
        )];
        let requested = Config {
            rate: 96000,
            channels: 16,
            pcm: Pcm::F32,
        };
        assert!(configs(None, &ranges).contains(&requested));
        assert!(select(None, &ranges, requested).is_ok());
        assert!(
            select(
                None,
                &ranges,
                Config {
                    channels: 2,
                    ..requested
                }
            )
            .is_err()
        );
        assert!(
            select(
                None,
                &ranges,
                Config {
                    pcm: Pcm::I16,
                    ..requested
                }
            )
            .is_err()
        );
        assert!(
            select(
                None,
                &ranges,
                Config {
                    rate: 384000,
                    ..requested
                }
            )
            .is_err()
        );
    }
}
