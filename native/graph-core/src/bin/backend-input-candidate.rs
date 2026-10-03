//! Worker-side binary transport into the same typed input queue as CPAL callbacks.
//! PortAudio/device access stays in its adapter; this executable never opens a device.
#![forbid(unsafe_code)]
use audio_core::backend::{InputBinding, InputSample, InputWriter, SampleFormat};
use graph_core::acquisition::{Acquisition, CaptureLimits, CaptureSample, FftSpec};
use graph_core::history::HistoryLimits;
use graph_core::result::{Capture, Format, MeasurementResult};
use graph_core::{Average, FftResult, Numeric, Presentation, Samples, WindowSpec};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    error::Error,
    fs,
    io::{self, BufReader, Read},
    path::Path,
    sync::Arc,
};

const MAX_FRAMES: usize = 262144;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: u64,
    binding: InputBinding,
    n: usize,
    window: WindowSpec,
    queue_frames: usize,
    max_frames: usize,
}
trait WireSample: CaptureSample + InputSample {
    const WIDTH: usize;
    fn decode(bytes: &[u8]) -> Vec<Self>;
}
impl WireSample for f32 {
    const WIDTH: usize = 4;
    fn decode(bytes: &[u8]) -> Vec<Self> {
        bytes
            .as_chunks::<4>()
            .0
            .iter()
            .map(|v| f32::from_le_bytes(*v))
            .collect()
    }
}
impl WireSample for f64 {
    const WIDTH: usize = 8;
    fn decode(bytes: &[u8]) -> Vec<Self> {
        bytes
            .as_chunks::<8>()
            .0
            .iter()
            .map(|v| f64::from_le_bytes(*v))
            .collect()
    }
}
#[derive(Default)]
struct Evidence {
    raw: Vec<u8>,
    complex: Vec<u8>,
    windows: Vec<Value>,
    gaps: Vec<[u64; 2]>,
    stamps: usize,
    polls: usize,
    last: Option<Arc<FftResult>>,
}
fn drain<T: WireSample>(
    worker: &mut Acquisition<T>,
    a: &graph_core::Subscription,
    b: &graph_core::Subscription,
    evidence: &mut Evidence,
) -> Result<(), Box<dyn Error>> {
    loop {
        let report = worker.poll()?;
        evidence.polls += 1;
        evidence.stamps += report.timestamps.len();
        evidence.gaps.extend(report.gaps);
        for block in report.blocks {
            match block.samples() {
                Samples::F32(values) => evidence
                    .raw
                    .extend(values.iter().flat_map(|v| v.to_le_bytes())),
                Samples::F64(values) => evidence
                    .raw
                    .extend(values.iter().flat_map(|v| v.to_le_bytes())),
            }
        }
        for event in &report.windows {
            let first = a.take_latest();
            let second = b.take_latest();
            let shared = match (&first, &second) {
                (Some(a), Some(b)) => {
                    Arc::ptr_eq(a.raw(), b.raw()) && Some(a.raw().id()) == event.result_id
                }
                (None, None) => event.result_id.is_none(),
                _ => false,
            };
            if !shared {
                return Err("backend_input_unshared_fft".into());
            }
            let offset = evidence.complex.len();
            if let Some(first) = first {
                if let Some(numeric) = first.raw().numeric() {
                    let complex = match numeric {
                        Numeric::F32(v) => &v.fft_over_n,
                        Numeric::F64(v) => &v.fft_over_n,
                    };
                    evidence.complex.extend(
                        complex
                            .iter()
                            .flat_map(|v| [v.re, v.im])
                            .flat_map(f64::to_le_bytes),
                    );
                }
                evidence.last = Some(first.raw().clone());
            }
            evidence.windows.push(
                json!({"history": event.history, "result_id": event.result_id,
                "numeric": event.numeric, "shared_allocation": shared,
                "complex_offset": offset, "complex_bytes": evidence.complex.len() - offset}),
            );
        }
        if report.deliveries == 0 && report.windows.is_empty() {
            break;
        }
    }
    Ok(())
}
fn run_input<T: WireSample>(
    request: &Request,
    mut input: impl Read,
    output: &Path,
) -> Result<(), Box<dyn Error>> {
    let (mut writer, receiver): (InputWriter<T>, _) =
        request.binding.queue(request.queue_frames)?;
    let mut worker = Acquisition::new(
        receiver,
        request.binding.format.clone(),
        FftSpec {
            n: request.n,
            hop: request.n,
            alignment: 0,
            window: request.window,
        },
        CaptureLimits {
            history: HistoryLimits::frames(request.n * 2),
            frames_per_poll: 1024,
            windows_per_poll: 1,
        },
    )?;
    let presentation = || Presentation {
        color: "blue".into(),
        unit: "FS".into(),
    };
    let a = worker.subscribe(Average::None, presentation())?;
    let b = worker.subscribe(Average::CumulativePsd, presentation())?;
    let mut evidence = Evidence::default();
    let mut blocks = 0;
    loop {
        // 32-byte LE header: frames:u32, flags:u32, start:u64, generation:u64,
        // first_seconds:f64 (NaN = unknown). Explicit zero-frame terminal required.
        let mut header = [0; 32];
        input.read_exact(&mut header)?;
        let frames = u32::from_le_bytes(header[0..4].try_into()?) as usize;
        let flags = u32::from_le_bytes(header[4..8].try_into()?);
        let start = u64::from_le_bytes(header[8..16].try_into()?);
        let generation = u64::from_le_bytes(header[16..24].try_into()?);
        let seconds = f64::from_le_bytes(header[24..32].try_into()?);
        if generation != request.binding.format.generation || start != writer.next_sample() {
            return Err("backend_input_generation_or_position".into());
        }
        if frames == 0 {
            if flags != 0 || !seconds.is_nan() {
                return Err("backend_input_terminal".into());
            }
            let mut extra = [0; 1];
            if input.read(&mut extra)? != 0 {
                return Err("backend_input_trailing_bytes".into());
            }
            break;
        }
        if frames > audio_core::MAX_CALLBACK_FRAMES
            || writer.next_sample() + frames as u64 > request.max_frames as u64
            || seconds.is_infinite()
        {
            return Err("backend_input_transport_capacity_or_time".into());
        }
        let mut bytes = vec![0; frames * request.binding.device_channels * T::WIDTH];
        input.read_exact(&mut bytes)?;
        writer.write_at(
            generation,
            start,
            &T::decode(&bytes),
            (!seconds.is_nan()).then_some(seconds),
            flags,
        )?;
        blocks += 1;
        drain(&mut worker, &a, &b, &mut evidence)?;
    }
    let frames = writer.next_sample();
    let queue = worker.queue_stats().ok_or("backend_input_queue_missing")?;
    drop(writer); // no producer remains before EOF
    worker.finish_input()?;
    drain(&mut worker, &a, &b, &mut evidence)?;
    let before = worker.graph().stats();
    let snapshot = evidence
        .last
        .as_ref()
        .map(|raw| {
            MeasurementResult::from_fft(
                raw,
                Capture {
                    result_id: "backend-input.last".into(),
                    trigger_id: None,
                    acquired_host_seconds: None,
                    result_host_seconds: None,
                    trigger: None,
                    clock_mapping: None,
                },
                &BTreeMap::new(),
                1.,
            )
        })
        .transpose()?;
    drop(a);
    drop(b);
    worker.stop();
    worker.stop();
    let held_after_stop = snapshot.as_ref().map(MeasurementResult::to_value);
    let report = json!({"schema_version": 1, "binding": request.binding, "source": worker.key().source,
        "frames": frames, "blocks": blocks, "polls": evidence.polls, "stamps": evidence.stamps, "queue": queue,
        "gaps": evidence.gaps, "windows": evidence.windows, "before_release": before,
        "after_stop": worker.graph().stats(), "state": worker.state(),
        "history_released": worker.history().is_none(), "queue_released": worker.queue_stats().is_none(),
        "raw_bytes": evidence.raw.len(), "complex_bytes": evidence.complex.len(),
        "input_finished": true, "held_after_stop": held_after_stop});
    fs::create_dir(output)?;
    fs::write(output.join("input.bin"), evidence.raw)?;
    fs::write(output.join("complex.bin"), evidence.complex)?;
    if let Some(snapshot) = snapshot {
        for (file, format) in [("result.json", Format::Json), ("result.csv", Format::Csv)] {
            snapshot.save_new(&output.join(file), format)?;
            if MeasurementResult::load(&output.join(file), format)?.to_value()
                != snapshot.to_value()
            {
                return Err("backend_input_snapshot_roundtrip".into());
            }
        }
    }
    fs::write(
        output.join("manifest.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    Ok(())
}
fn run() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 4 {
        return Err(
            "usage: backend-input-candidate REQUEST.json WIRE.bin|- NEW_OUTPUT_DIRECTORY".into(),
        );
    }
    let request: Request = serde_json::from_slice(&fs::read(&args[1])?)?;
    request.binding.validate()?;
    let output = Path::new(&args[3]);
    if request.schema_version != 1
        || !(3..=4096).contains(&request.n)
        || request.queue_frames == 0
        || request.queue_frames > 8192
        || request.max_frames < request.n
        || request.max_frames > MAX_FRAMES
        || output.exists()
    {
        return Err("backend_input_request".into());
    }
    let input: Box<dyn Read> = if args[2] == "-" {
        Box::new(io::stdin())
    } else {
        Box::new(fs::File::open(&args[2])?)
    };
    match request.binding.sample_format {
        SampleFormat::F32 => run_input::<f32>(&request, BufReader::new(input), output),
        SampleFormat::F64 => run_input::<f64>(&request, BufReader::new(input), output),
    }
}
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
