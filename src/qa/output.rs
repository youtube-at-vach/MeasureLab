//! Explicit QA output with a bounded, timestamped attachment interval.
use crate::audio;
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use std::{
    f64::consts::TAU,
    sync::{
        Arc, OnceLock,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    time::{Duration, Instant},
};

const WARMUP: Duration = Duration::from_millis(500);

#[derive(Default)]
struct Status {
    started: OnceLock<Instant>,
    warmup_until_nanos: AtomicU64,
    startup: AtomicU64,
    measured: AtomicU64,
    failed: AtomicBool,
}

impl Status {
    fn notify(&self, now: Instant) -> bool {
        let startup = self.started.get().is_some_and(|start| {
            now.checked_duration_since(*start).is_some_and(|d| {
                d.as_nanos() < self.warmup_until_nanos.load(Ordering::Acquire) as u128
            })
        });
        if startup {
            self.startup.fetch_add(1, Ordering::Relaxed);
        } else {
            self.measured.fetch_add(1, Ordering::Relaxed);
            self.failed.store(true, Ordering::Release);
        }
        startup
    }
}

pub struct Fixture {
    stream: Option<cpal::Stream>,
    device: cpal::Device,
    original_rate: u32,
    status: Arc<Status>,
    pub physical: bool,
}

impl Fixture {
    pub fn new(name: &str, rate: Option<u32>, physical: bool) -> Result<Self, String> {
        if (physical && name != "ZOOM UAC-232")
            || (!physical && !["BlackHole 2ch", "BlackHole 16ch"].contains(&name))
        {
            return Err(
                "QA output requires BlackHole, or explicit ZOOM UAC-232 physical mode".into(),
            );
        }
        let device = audio::input_device(Some(name))?;
        let original_rate = device
            .default_input_config()
            .map_err(|e| e.to_string())?
            .sample_rate();
        let output = cpal::default_host()
            .output_devices()
            .map_err(|e| e.to_string())?
            .find(|d| d.to_string() == name)
            .ok_or("QA output device not found")?;
        let rate = rate.unwrap_or(original_rate);
        let supported = output
            .supported_output_configs()
            .map_err(|e| e.to_string())?
            .filter(|c| c.sample_format() == cpal::SampleFormat::F32)
            .find_map(|c| c.try_with_sample_rate(rate))
            .ok_or("QA output rate is unsupported")?;
        let channels = supported.channels() as usize;
        if (physical && channels != 2) || (!physical && ![2, 16].contains(&channels)) {
            return Err("Unexpected QA output channel count".into());
        }
        let period = if physical { rate as usize } else { 8192 };
        let cycle: Vec<f32> = (0..period)
            .flat_map(|n| {
                (0..channels).map(move |ch| {
                    let (peak, hz) = if physical {
                        (0.1, 1000.0)
                    } else {
                        (0.125, (32 + ch * 7) as f64 * rate as f64 / 8192.0)
                    };
                    (peak * (TAU * hz * n as f64 / rate as f64).sin()) as f32
                })
            })
            .collect();
        let status = Arc::new(Status::default());
        let errors = status.clone();
        let mut head = 0;
        let stream = output
            .build_output_stream(
                supported.into(),
                move |data: &mut [f32], _| {
                    let mut offset = 0;
                    while offset < data.len() {
                        let count = (cycle.len() - head).min(data.len() - offset);
                        data[offset..offset + count].copy_from_slice(&cycle[head..head + count]);
                        offset += count;
                        head = (head + count) % cycle.len();
                    }
                },
                move |error| {
                    let now = Instant::now();
                    let startup = errors.notify(now);
                    let seconds = errors
                        .started
                        .get()
                        .map(|s| now.duration_since(*s).as_secs_f64());
                    eprintln!(
                        "QA output notification at {seconds:?} s, attachment={startup}: {error}"
                    );
                },
                Some(Duration::from_secs(2)),
            )
            .map_err(|e| e.to_string())?;
        Ok(Self {
            stream: Some(stream),
            device,
            original_rate,
            status,
            physical,
        })
    }

    pub fn start(&self) -> Result<(), String> {
        let now = Instant::now();
        let first = self.status.started.set(now).is_ok();
        let end = now.duration_since(*self.status.started.get().unwrap()) + WARMUP;
        self.status
            .warmup_until_nanos
            .store(end.as_nanos() as u64, Ordering::Release);
        if first {
            self.stream
                .as_ref()
                .unwrap()
                .play()
                .map_err(|e| e.to_string())?;
        }
        println!(
            "QA output started: explicit 0.5 s attachment interval; physical={}",
            self.physical
        );
        Ok(())
    }

    pub fn check(&self) -> Result<(), String> {
        println!(
            "QA output audit: attachment notifications {}, measured notifications {}",
            self.status.startup.load(Ordering::Relaxed),
            self.status.measured.load(Ordering::Relaxed)
        );
        if self.status.failed.load(Ordering::Acquire) {
            Err("QA output failed outside the attachment interval".into())
        } else {
            Ok(())
        }
    }

    pub fn restore(&mut self) -> Result<(), String> {
        if self.stream.take().is_some() {
            let (stream, _) = audio::start_device(&self.device, Some(self.original_rate))?;
            drop(stream);
            println!(
                "QA output nominal rate restored to {} Hz",
                self.original_rate
            );
            // Dropping the stream fixes the last notification endpoint. Audit
            // again so a notification during input teardown cannot be missed.
            self.check()?;
        }
        Ok(())
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        if let Err(error) = self.restore() {
            eprintln!("QA rate restoration failed: {error}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn attachment_boundary_preserves_measurement_failures() {
        let start = Instant::now();
        let status = Status::default();
        status.started.set(start).unwrap();
        status
            .warmup_until_nanos
            .store(WARMUP.as_nanos() as u64, Ordering::Release);
        assert!(status.notify(start + WARMUP - Duration::from_nanos(1)));
        assert!(!status.failed.load(Ordering::Acquire));
        assert!(!status.notify(start + WARMUP));
        assert!(status.failed.load(Ordering::Acquire));
        assert_eq!(status.startup.load(Ordering::Relaxed), 1);
        assert_eq!(status.measured.load(Ordering::Relaxed), 1);
        status
            .warmup_until_nanos
            .store((WARMUP * 2).as_nanos() as u64, Ordering::Release);
        assert!(status.notify(start + WARMUP + Duration::from_nanos(1)));
        assert!(
            status.failed.load(Ordering::Acquire),
            "reattachment must not erase a prior failure"
        );
        assert!(!Status::default().notify(start));
    }
}
