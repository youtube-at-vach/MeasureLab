//! Saved inputs only: acquisition queue -> retained trigger windows -> immutable results.
#![forbid(unsafe_code)]
use audio_core::{IoFormat, Producer, frame_queue, frame_queue_f64};
use graph_core::acquisition::{
    Acquisition, CaptureLimits, CaptureSample, FftSpec, TriggerRead, TriggerRequest,
};
use graph_core::history::{HistoryLimits, TriggerEvent};
use graph_core::result::Format;
use graph_core::{Average, Precision, Presentation, Rational, Samples, SignalBlock, WindowSpec};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{error::Error, fs, io::Read, path::Path, sync::Arc};

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
) -> Result<(), Box<dyn Error>> {
    let mut position = 0;
    for frames in [1, 127, 256, 17].into_iter().cycle() {
        if position == values.len() {
            break;
        }
        let end = (position + frames * channels).min(values.len());
        tx.write(&values[position..end], None, 0)?;
        loop {
            let report = worker.poll()?;
            if !report.gaps.is_empty() {
                return Err("saved_capture_gap".into());
            }
            if report.deliveries == 0 && report.windows.is_empty() {
                break;
            }
        }
        position = end;
    }
    Ok(())
}
fn summary(read: &TriggerRead) -> Value {
    json!({"request_id": read.request_id, "history": read.history.report,
        "event": read.history.trigger, "residual": read.history.fractional_residual,
        "fft_origin": read.fft_origin, "raw_result_id": read.raw.as_ref().map(|r| r.id()),
        "has_snapshot": read.history.snapshot.is_some(), "has_result": read.result.is_some(),
        "result_id": read.result.as_ref().map(|r| r.to_value()["capture"]["result_id"].clone())})
}
fn trigger(request: &Request, shifted: bool) -> TriggerRequest {
    TriggerRequest {
        request_id: if shifted { "shifted" } else { "aligned" }.into(),
        pre: (request.n / 2) as u64,
        post: (request.n - request.n / 2) as u64,
        event: TriggerEvent {
            id: if shifted {
                "virtual.shifted"
            } else {
                "virtual.aligned"
            }
            .into(),
            stream_id: request.format.stream_id.clone(),
            generation: request.format.generation,
            timebase_id: request.format.timebase_id.clone(),
            sample: Rational {
                numerator: (2 * (request.n / 2 + usize::from(shifted)) + 1) as i64,
                denominator: 2,
            },
            source: "fixture.virtual".into(),
            kind: "edge".into(),
            polarity: "rising".into(),
            condition_revision: "fixture.trigger.v1".into(),
            validity: Vec::new(),
            received_host_seconds: Some(Rational {
                numerator: 99999,
                denominator: 1,
            }),
        },
    }
}
fn run_corpus<T: FreshQueue>(
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
        color: "cyan".into(),
        unit: "FS".into(),
    };
    let line = worker.subscribe(Average::None, p())?;
    let map = worker.subscribe(Average::CumulativePsd, p())?;
    let aligned_request = trigger(&request, false);
    let pending = worker.capture_trigger(&aligned_request)?;
    feed(&mut tx, &mut worker, values, channels)?;
    let aligned = worker.capture_trigger(&aligned_request)?;
    let initial = line.take_latest().ok_or("line_result_missing")?;
    let initial_map = map.take_latest().ok_or("map_result_missing")?;
    let shared_continuous = Arc::ptr_eq(
        initial.raw(),
        aligned.raw.as_ref().ok_or("aligned_missing")?,
    ) && Arc::ptr_eq(initial.raw(), initial_map.raw());
    feed(&mut tx, &mut worker, values, channels)?;
    let before = worker.graph().stats();
    let mut delayed_request = aligned_request.clone();
    delayed_request.request_id = "delayed".into();
    delayed_request.event.received_host_seconds = Some(Rational {
        numerator: 111111,
        denominator: 1,
    });
    let delayed = worker.capture_trigger(&delayed_request)?;
    let shifted_request = trigger(&request, true);
    let shifted = worker.capture_trigger(&shifted_request)?;
    let mut repeated_request = shifted_request.clone();
    repeated_request.request_id = "repeated".into();
    repeated_request.event.id = "virtual.repeated".into();
    repeated_request.event.received_host_seconds = None;
    let repeated = worker.capture_trigger(&repeated_request)?;
    let after = worker.graph().stats();
    let latest = line.take_latest().ok_or("line_latest_missing")?;
    let latest_map = map.take_latest().ok_or("map_latest_missing")?;
    let shared_trigger = Arc::ptr_eq(
        shifted.raw.as_ref().ok_or("shift_missing")?,
        repeated.raw.as_ref().ok_or("repeat_missing")?,
    );
    feed(&mut tx, &mut worker, values, channels)?;
    let expired = worker.capture_trigger(&aligned_request)?;
    let expired_shifted = worker.capture_trigger(&shifted_request)?;
    let mut new_format = request.format.clone();
    new_format.generation += 1;
    // Retire this generation using a fresh queue. The callback queue is never reused.
    let fresh_rx = new_queue::<T>(channels, &new_format)?;
    worker.restart(fresh_rx, new_format)?;
    let stale_error = worker
        .capture_trigger(&aligned_request)
        .err()
        .ok_or("old_event_accepted")?;
    drop(line);
    drop(map);
    worker.stop();
    worker.stop();
    let stopped_error = worker
        .capture_trigger(&aligned_request)
        .err()
        .ok_or("stopped_event_accepted")?;
    let header = json!({"schema_version":1,"format":request.format,"source":initial.raw().key().source,
        "reads": {"pending":summary(&pending),"aligned":summary(&aligned),"delayed":summary(&delayed),
            "shifted":summary(&shifted),"repeated":summary(&repeated),"expired":summary(&expired),"expired_shifted":summary(&expired_shifted)},
        "shared_continuous":shared_continuous,"shared_trigger":shared_trigger,
        "continuous_before":before,"continuous_after":after,"latest_interval":latest.raw().interval(),
        "latest_map_interval":latest_map.raw().interval(),"latest_average_count":latest_map.average_count(),
        "trigger_evaluations":worker.trigger_evaluations(),"stale_error":stale_error,"stopped_error":stopped_error,
        "history_released":worker.history().is_none(),"after_stop":worker.graph().stats()});
    fs::create_dir(output)?;
    for (name, read) in [
        ("aligned", &aligned),
        ("delayed", &delayed),
        ("shifted", &shifted),
        ("repeated", &repeated),
    ] {
        fs::write(
            output.join(format!("{name}.bin")),
            bytes(
                read.history
                    .snapshot
                    .as_ref()
                    .ok_or("held_snapshot_missing")?,
            ),
        )?;
        read.result
            .as_ref()
            .ok_or("held_result_missing")?
            .save_new(&output.join(format!("{name}.json")), Format::Json)?;
    }
    fs::write(
        output.join("manifest.json"),
        serde_json::to_vec_pretty(&header)?,
    )?;
    Ok(())
}
// The type is sealed to f32/f64 by CaptureSample; use a type-specific queue constructor.
trait FreshQueue: CaptureSample {
    fn queue(channels: usize, rate: f64) -> Result<audio_core::Consumer<Self>, String>;
}
impl FreshQueue for f32 {
    fn queue(channels: usize, rate: f64) -> Result<audio_core::Consumer<Self>, String> {
        frame_queue(1024, channels, rate)
            .map(|(_, rx)| rx)
            .map_err(String::from)
    }
}
impl FreshQueue for f64 {
    fn queue(channels: usize, rate: f64) -> Result<audio_core::Consumer<Self>, String> {
        frame_queue_f64(1024, channels, rate)
            .map(|(_, rx)| rx)
            .map_err(String::from)
    }
}
fn new_queue<T: FreshQueue>(
    channels: usize,
    format: &IoFormat,
) -> Result<audio_core::Consumer<T>, String> {
    T::queue(channels, format.rate[0] as f64 / format.rate[1] as f64)
}
fn run() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 4 {
        return Err("usage: trigger-candidate REQUEST.json INPUT.bin OUTPUT_DIRECTORY".into());
    }
    let mut encoded = Vec::new();
    fs::File::open(&args[1])?
        .take(65537)
        .read_to_end(&mut encoded)?;
    if encoded.len() > 65536 {
        return Err("request_capacity".into());
    }
    let request: Request = serde_json::from_slice(&encoded)?;
    let output = Path::new(&args[3]);
    let channels = request.format.input_ids.len();
    if request.schema_version != 1
        || !(3..=4096).contains(&request.n)
        || channels == 0
        || channels > 16
        || output.exists()
    {
        return Err("invalid_request_or_existing_output".into());
    }
    let size = if request.precision == Precision::F32 {
        4
    } else {
        8
    };
    let expected = request.n * channels * size;
    let mut raw = Vec::new();
    fs::File::open(&args[2])?
        .take((expected + 1) as u64)
        .read_to_end(&mut raw)?;
    if raw.len() != expected {
        return Err("input_shape".into());
    }
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
