//! Input-only corpus harness; candidate receives original bytes and configuration, no oracle.
#![forbid(unsafe_code)]
use audio_core::{IoFormat, Producer, frame_queue, frame_queue_f64};
use graph_core::acquisition::{Acquisition, CaptureLimits, CaptureSample, FftSpec};
use graph_core::history::HistoryLimits;
use graph_core::{Average, Numeric, Precision, Presentation, Samples, SignalBlock, WindowSpec};
use serde::Deserialize;
use serde_json::json;
use std::{error::Error, fs, path::Path, sync::Arc};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: u64,
    format: IoFormat,
    precision: Precision,
    n: usize,
    window: WindowSpec,
}
fn bytes(block: &SignalBlock) -> Vec<u8> {
    match block.samples() {
        Samples::F32(v) => v.iter().flat_map(|v| v.to_le_bytes()).collect(),
        Samples::F64(v) => v.iter().flat_map(|v| v.to_le_bytes()).collect(),
    }
}
fn feed<T: CaptureSample>(
    tx: &mut Producer<T>,
    worker: &mut Acquisition<T>,
    values: &[T],
    channels: usize,
) -> Result<Vec<u8>, Box<dyn Error>> {
    let mut raw = Vec::new();
    let mut position = 0;
    for frames in [1, 127, 256, 17].into_iter().cycle() {
        if position == values.len() {
            break;
        }
        let end = (position + frames * channels).min(values.len());
        tx.write(&values[position..end], None, 0)?;
        loop {
            let report = worker.poll()?;
            if !report.gaps.is_empty()
                || report
                    .timestamps
                    .iter()
                    .any(|s| s.seconds.is_some() || s.backend_flags != 0)
            {
                return Err("Unexpected gap or timestamp in saved acquisition".into());
            }
            for block in &report.blocks {
                raw.extend(bytes(block));
            }
            if report.deliveries == 0 && report.windows.is_empty() {
                break;
            }
        }
        position = end;
    }
    Ok(raw)
}
fn run_corpus<T: CaptureSample>(
    request: Request,
    mut tx: Producer<T>,
    rx: audio_core::Consumer<T>,
    values: &[T],
    output: &Path,
) -> Result<(), Box<dyn Error>> {
    let channels = request.format.input_ids.len();
    let mut worker = Acquisition::new(
        rx,
        request.format.clone(),
        FftSpec {
            n: request.n,
            hop: request.n,
            alignment: 0,
            window: request.window,
        },
        CaptureLimits {
            history: HistoryLimits::frames(2 * request.n),
            frames_per_poll: 71,
            windows_per_poll: 2,
        },
    )?;
    let p = || Presentation {
        color: "blue".into(),
        unit: "FS".into(),
    };
    let a = worker.subscribe(Average::None, p())?;
    let b = worker.subscribe(Average::CumulativePsd, p())?;
    let save = worker.subscribe(Average::None, p())?;
    let raw = feed(&mut tx, &mut worker, values, channels)?;
    let first = a.take_latest().ok_or("No first result")?;
    let second = b.take_latest().ok_or("No second result")?;
    let saved = save.take_latest().ok_or("No save result")?;
    let shared = Arc::ptr_eq(first.raw(), second.raw()) && Arc::ptr_eq(first.raw(), saved.raw());
    if !shared {
        return Err("Unshared FFT".into());
    }
    let held = worker
        .history()
        .unwrap()
        .read_interval(0, request.n as i64)?
        .snapshot
        .ok_or("No retained snapshot")?;
    let complex = match first.raw().numeric().ok_or("Invalid FFT")? {
        Numeric::F32(v) => &v.fft_over_n,
        Numeric::F64(v) => &v.fft_over_n,
    };
    let complex_bytes: Vec<u8> = complex
        .iter()
        .flat_map(|v| [v.re, v.im])
        .flat_map(f64::to_le_bytes)
        .collect();
    let before = worker.graph().stats();
    drop(a);
    drop(b);
    feed(&mut tx, &mut worker, values, channels)?;
    let session = save.take_latest().ok_or("Save demand lost")?;
    let save_only = worker.graph().stats();
    drop(save);
    let after_release = worker.graph().stats();
    feed(&mut tx, &mut worker, values, channels)?;
    let expired = worker
        .history()
        .unwrap()
        .read_interval(0, request.n as i64)?
        .report;
    let source = worker.key().source.clone();
    let queue = worker.queue_stats().unwrap();
    worker.stop();
    worker.stop();
    let header = json!({"schema_version":1,"format":request.format,"source":source,
        "interval":[0,request.n],"shared_allocation":shared,"result_id":first.raw().id(),
        "second_result_id":second.raw().id(),"save_result_id":saved.raw().id(),
        "session_interval":session.raw().interval(),"expired":expired,"queue":queue,
        "before_release":before,"save_only":save_only,"after_release":after_release,
        "after_stop":worker.graph().stats(),"state":worker.state(),"history_released":worker.history().is_none()});
    fs::create_dir(output)?;
    fs::write(output.join("poll_raw.bin"), raw)?;
    fs::write(output.join("snapshot.bin"), bytes(&held))?;
    fs::write(output.join("held_after_stop.bin"), bytes(&held))?;
    fs::write(output.join("fft_over_n.bin"), complex_bytes)?;
    fs::write(
        output.join("manifest.json"),
        serde_json::to_vec_pretty(&header)?,
    )?;
    Ok(())
}
fn run() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 4 {
        return Err("usage: acquisition-candidate REQUEST.json INPUT.bin OUTPUT_DIRECTORY".into());
    }
    let request: Request = serde_json::from_slice(&fs::read(&args[1])?)?;
    let output = Path::new(&args[3]);
    let channels = request.format.input_ids.len();
    if request.schema_version != 1
        || !(3..=65536).contains(&request.n)
        || channels == 0
        || channels > 16
        || output.exists()
    {
        return Err("Invalid request or existing output".into());
    }
    let size = if request.precision == Precision::F32 {
        4
    } else {
        8
    };
    if fs::metadata(&args[2])?.len() != (request.n * channels * size) as u64 {
        return Err("Input byte count mismatch".into());
    }
    let raw = fs::read(&args[2])?;
    let rate = request.format.rate[0] as f64 / request.format.rate[1] as f64;
    match request.precision {
        Precision::F32 => {
            let (tx, rx) = frame_queue(1024, channels, rate)?;
            let values: Vec<_> = raw
                .as_chunks::<4>()
                .0
                .iter()
                .map(|v| f32::from_le_bytes(*v))
                .collect();
            run_corpus(request, tx, rx, &values, output)
        }
        Precision::F64 => {
            let (tx, rx) = frame_queue_f64(1024, channels, rate)?;
            let values: Vec<_> = raw
                .as_chunks::<8>()
                .0
                .iter()
                .map(|v| f64::from_le_bytes(*v))
                .collect();
            run_corpus(request, tx, rx, &values, output)
        }
    }
}
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
