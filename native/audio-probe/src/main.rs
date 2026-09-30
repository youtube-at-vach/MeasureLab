//! CPAL headless two-channel hardware diagnostic. File/JSON/Vec growth is on control thread.
#![forbid(unsafe_code)]
use audio_core::{Consumer, Delivery, IoFormat, MAX_CALLBACK_FRAMES, Route, frame_queue};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use serde_json::{Value, json};
use std::{
    error::Error,
    fs,
    io::Write,
    path::Path,
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering::Relaxed},
    },
    time::{Duration, Instant},
};

struct Stats {
    bins: [AtomicU64; 1001],
    count: AtomicU64,
    max_ns: AtomicU64,
    min_frames: AtomicU64,
    max_frames: AtomicU64,
}
impl Stats {
    fn new() -> Self {
        Self {
            bins: std::array::from_fn(|_| AtomicU64::new(0)),
            count: AtomicU64::new(0),
            max_ns: AtomicU64::new(0),
            min_frames: AtomicU64::new(u64::MAX),
            max_frames: AtomicU64::new(0),
        }
    }
    fn record(&self, started: Instant, frames: usize) {
        let ns = started.elapsed().as_nanos().min(u64::MAX as u128) as u64;
        self.bins[(ns / 10000).min(1000) as usize].fetch_add(1, Relaxed);
        self.count.fetch_add(1, Relaxed);
        self.max_ns.fetch_max(ns, Relaxed);
        self.min_frames.fetch_min(frames as u64, Relaxed);
        self.max_frames.fetch_max(frames as u64, Relaxed);
    }
    fn report(&self) -> Value {
        let count = self.count.load(Relaxed);
        let percentile = |p: f64| {
            let target = (count as f64 * p).ceil() as u64;
            let mut n = 0;
            for (index, bin) in self.bins.iter().enumerate() {
                n += bin.load(Relaxed);
                if count > 0 && n >= target {
                    return if index == 1000 {
                        None
                    } else {
                        Some((index + 1) as f64 / 100.)
                    };
                }
            }
            None
        };
        json!({"count":count,"p50_upper_ms":percentile(0.5),"p95_upper_ms":percentile(0.95),"p99_upper_ms":percentile(0.99),
            "max_ms":self.max_ns.load(Relaxed) as f64/1e6,"min_frames":if count>0{Some(self.min_frames.load(Relaxed))}else{None},"max_frames":self.max_frames.load(Relaxed)})
    }
}
struct Capture {
    values: Vec<f32>,
    samples: Vec<u64>,
    seconds: Vec<Option<f64>>,
    gaps: Vec<[u64; 2]>,
}
impl Capture {
    fn new() -> Self {
        Self {
            values: Vec::new(),
            samples: Vec::new(),
            seconds: Vec::new(),
            gaps: Vec::new(),
        }
    }
    fn drain(&mut self, rx: &mut Consumer) {
        while let Some(item) = rx.take() {
            match item {
                Delivery::Frame {
                    sample,
                    values,
                    seconds,
                    ..
                } => {
                    self.values.extend(values);
                    self.samples.push(sample);
                    self.seconds.push(seconds)
                }
                Delivery::Gap { interval } => self.gaps.push(interval),
            }
        }
    }
    fn save(&self, path: &Path) -> Result<Value, Box<dyn Error>> {
        let mut file = fs::File::create(path)?;
        for value in &self.values {
            file.write_all(&value.to_le_bytes())?
        }
        Ok(
            json!({"frames":self.samples.len(),"channels":2,"dtype":"<f4","samples":self.samples,"seconds":self.seconds,"gaps":self.gaps}),
        )
    }
}
fn selected_device(host: &cpal::Host, name: &str) -> Result<cpal::Device, Box<dyn Error>> {
    let devices: Vec<_> = host
        .devices()?
        .filter(|d| d.description().is_ok_and(|s| s.name() == name))
        .collect();
    if devices.len() != 1 {
        return Err("exact device name must resolve uniquely".into());
    }
    Ok(devices.into_iter().next().unwrap())
}
fn run() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() == 2 && args[1] == "--list" {
        let host = cpal::default_host();
        let mut devices = Vec::new();
        for d in host.devices()? {
            devices.push(json!({"name":d.description()?.name(),"input":d.default_input_config().ok().map(|c|format!("{c:?}")),"output":d.default_output_config().ok().map(|c|format!("{c:?}"))}));
        }
        println!("{}", serde_json::to_string(&devices)?);
        return Ok(());
    }
    if args.len() != 4 {
        return Err("usage: audio-probe REQUEST.json MIXED.f32 OUTPUT_DIRECTORY".into());
    }
    let request: Value = serde_json::from_slice(&fs::read(&args[1])?)?;
    if request["schema_version"] != 1 {
        return Err("unsupported schema".into());
    }
    let name = request["device"].as_str().ok_or("device")?;
    let duration = request["duration_seconds"].as_f64().ok_or("duration")?;
    if !duration.is_finite() || !(1.0..=60.0).contains(&duration) {
        return Err("duration must be in 1..60 seconds".into());
    }
    let output_path = Path::new(&args[3]);
    if output_path.exists() {
        return Err("output exists".into());
    }
    let bytes = fs::read(&args[2])?;
    if !bytes.len().is_multiple_of(4) {
        return Err("input shape".into());
    }
    let signal: Vec<_> = bytes
        .as_chunks::<4>()
        .0
        .iter()
        .map(|v| f32::from_le_bytes(*v))
        .collect();
    if signal.len() != (duration * 48000.) as usize
        || signal.iter().any(|v| !v.is_finite() || v.abs() > 0.05)
    {
        return Err("invalid signal length/amplitude".into());
    }
    let session = request["session_id"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or("session_id")?;
    let format = IoFormat {
        stream_id: format!("{session}.input"),
        generation: request["generation"].as_u64().ok_or("generation")?,
        timebase_id: format!("{session}.input.timebase"),
        clock_domain: format!("coreaudio.device:{name}"),
        rate: [48000, 1],
        input_ids: vec!["input.L".into(), "input.R".into()],
        input_ports: vec![0, 1],
        output_ids: vec!["output.L".into(), "output.R".into()],
        output_ports: vec![0, 1],
    };
    let host = cpal::default_host();
    let device = selected_device(&host, name)?;
    let supported = |input: bool| -> Result<bool, Box<dyn Error>> {
        let matches = |c: cpal::SupportedStreamConfigRange| {
            c.channels() == 2
                && c.sample_format() == cpal::SampleFormat::F32
                && c.min_sample_rate() <= 48000
                && 48000 <= c.max_sample_rate()
        };
        Ok(if input {
            device.supported_input_configs()?.any(matches)
        } else {
            device.supported_output_configs()?.any(matches)
        })
    };
    if !supported(true)? || !supported(false)? {
        return Err("explicit 2ch f32 48000 unsupported".into());
    }
    format.validate(2, 2)?;
    let config = cpal::StreamConfig {
        channels: 2,
        sample_rate: 48000,
        buffer_size: cpal::BufferSize::Fixed(256),
    };
    let (mut input_tx, mut input_rx) = frame_queue(8192, 2, 48000.)?;
    let (mut output_tx, mut output_rx) = frame_queue(8192, 2, 48000.)?;
    let errors = Arc::new(AtomicU64::new(0));
    let xruns = Arc::new(AtomicU64::new(0));
    let rejected = Arc::new(AtomicU64::new(0));
    let input_stats = Arc::new(Stats::new());
    let output_stats = Arc::new(Stats::new());
    let origin = Instant::now();
    let (err, xrun) = (errors.clone(), xruns.clone());
    let (stats, bad) = (input_stats.clone(), rejected.clone());
    let input = device.build_input_stream(
        config,
        move |data: &[f32], info: &cpal::InputCallbackInfo| {
            let started = Instant::now();
            let stamp = info.timestamp();
            let seconds = stamp
                .callback
                .checked_duration_since(stamp.capture)
                .map(|lag| origin.elapsed().as_secs_f64() - lag.as_secs_f64());
            if input_tx.write(data, seconds, 0).is_err() {
                bad.fetch_add(1, Relaxed);
            }
            stats.record(started, data.len() / 2);
        },
        move |e| {
            if e.kind() == cpal::ErrorKind::Xrun {
                xrun.fetch_add(1, Relaxed);
            } else {
                err.fetch_add(1, Relaxed);
            }
        },
        Some(Duration::from_secs(5)),
    )?;
    let route = Route {
        inputs: vec!["generator.L".into()],
        outputs: vec!["output.L".into(), "output.R".into()],
        gains: vec![vec![1.], vec![0.]],
        revision: "L-only.1".into(),
    }
    .compile(&["generator.L".into()])?;
    let mut scratch = vec![0f32; MAX_CALLBACK_FRAMES];
    let mut cursor = 0usize;
    let (err, xrun) = (errors.clone(), xruns.clone());
    let (stats, bad) = (output_stats.clone(), rejected.clone());
    let output = device.build_output_stream(
        config,
        move |data: &mut [f32], info: &cpal::OutputCallbackInfo| {
            let started = Instant::now();
            let frames = data.len() / 2;
            data.fill(0.);
            if frames > MAX_CALLBACK_FRAMES || !data.len().is_multiple_of(2) {
                bad.fetch_add(1, Relaxed);
                stats.record(started, frames);
                return;
            }
            for (offset, value) in scratch[..frames].iter_mut().enumerate() {
                *value = signal.get(cursor + offset).copied().unwrap_or(0.);
            }
            if route.process_into(&scratch[..frames], data).is_err() {
                bad.fetch_add(1, Relaxed);
            }
            // Mute preserves mixed source. Its independently recorded source file remains nonzero.
            for (offset, frame) in data.as_chunks_mut::<2>().0.iter_mut().enumerate() {
                if (108032..132096).contains(&(cursor + offset)) {
                    frame.fill(0.);
                }
            }
            let stamp = info.timestamp();
            let seconds = stamp
                .playback
                .checked_duration_since(stamp.callback)
                .map(|lag| origin.elapsed().as_secs_f64() + lag.as_secs_f64());
            if output_tx.write(data, seconds, 0).is_err() {
                bad.fetch_add(1, Relaxed);
            }
            cursor += frames;
            stats.record(started, frames);
        },
        move |e| {
            if e.kind() == cpal::ErrorKind::Xrun {
                xrun.fetch_add(1, Relaxed);
            } else {
                err.fetch_add(1, Relaxed);
            }
        },
        Some(Duration::from_secs(5)),
    )?;
    let cancel = request["cancel_preparing"].as_bool().unwrap_or(false);
    let mut captured = Capture::new();
    let mut submitted = Capture::new();
    let mut stop_ms = None;
    if !cancel {
        input.play()?;
        output.play()?;
        let until = Instant::now() + Duration::from_secs_f64(duration + 0.2);
        while Instant::now() < until {
            captured.drain(&mut input_rx);
            submitted.drain(&mut output_rx);
            std::thread::sleep(Duration::from_millis(2));
        }
        let stop = Instant::now();
        output.pause()?;
        input.pause()?;
        // Explicit duplicate stop (idempotence) before releasing on control thread.
        output.pause()?;
        input.pause()?;
        drop(output);
        drop(input);
        stop_ms = Some(stop.elapsed().as_secs_f64() * 1000.);
    } else {
        drop(output);
        drop(input);
    }
    captured.drain(&mut input_rx);
    submitted.drain(&mut output_rx);
    fs::create_dir(output_path)?;
    let capture = captured.save(&output_path.join("input.bin"))?;
    let submit = submitted.save(&output_path.join("output.bin"))?;
    let report = json!({"schema_version":1,"request":request,"backend":"CPAL 0.18.2","device":name,"format":format,
        "input":capture,"output":submit,
        "queues":{"input":input_rx.stats(),"output":output_rx.stats()},"input_callback":input_stats.report(),"output_callback":output_stats.report(),
        "errors":errors.load(Relaxed),"xruns":xruns.load(Relaxed),"callback_rejections":rejected.load(Relaxed),"stop_ms":stop_ms,
        "state":if cancel{"cancelled"}else{"stopped"},"timestamp_kind":"callback-host estimate using backend capture/playback offsets; cross-stream uncertainty unknown",
        "xrun_interval":"unknown"});
    fs::write(
        output_path.join("manifest.json"),
        serde_json::to_vec(&report)?,
    )?;
    println!(
        "{}",
        json!({"state":report["state"],"input_frames":captured.samples.len(),"output_frames":submitted.samples.len(),"errors":report["errors"],"xruns":report["xruns"]})
    );
    if !cancel
        && (captured.samples.is_empty()
            || submitted.samples.is_empty()
            || errors.load(Relaxed) > 0
            || rejected.load(Relaxed) > 0)
    {
        return Err("capture failed; report retained".into());
    }
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1)
    }
}
