use super::*;
use audio_probe::live::LiveInput;
use graph_core::Samples;
use std::time::Instant;

pub(super) fn run(
    owner: &Owner,
    notify: &impl Fn(u64) -> bool,
    request: &Request,
) -> Result<(), String> {
    let live = request.live.as_ref().ok_or("display_input_source")?;
    let (mut input, rx) = LiveInput::open(&live.device, live.device_channels, &request.format)?;
    let mut acquisition = Acquisition::new(
        rx,
        request.format.clone(),
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
    let mut subscriptions = BTreeMap::new();
    let mut evidence_written = false;
    let mut captured_frames = 0;
    let mut last_data = Instant::now();
    let result = (|| {
        if owner.stop.load(Ordering::Acquire)
            || !sync_demand(owner, &acquisition, &mut subscriptions)?
        {
            return Ok(());
        }
        input.start()?;
        while !owner.stop.load(Ordering::Acquire) {
            if !sync_demand(owner, &acquisition, &mut subscriptions)? {
                break;
            }
            if input.failed() {
                return Err("live_input_callback_failure".into());
            }
            let report = acquisition.poll()?;
            // This short correctness evaluation fails explicitly on discontinuity.
            // Recoverable XRUN/reconnect policy belongs to MIG-005-B.
            if !report.gaps.is_empty() {
                return Err("live_input_gap".into());
            }
            if report.deliveries > 0 {
                captured_frames += report.deliveries;
                last_data = Instant::now();
            } else if last_data.elapsed() > Duration::from_secs(3) {
                return Err("live_input_timeout".into());
            }
            if let Some(frame) = shared_frame(&subscriptions)? {
                if !evidence_written {
                    if let Some(path) = &request.evidence {
                        save_window(path, &acquisition, &frame)?;
                    }
                    evidence_written = true;
                }
                if !publish(owner, notify, &acquisition, frame) {
                    break;
                }
            }
            thread::sleep(Duration::from_millis(2));
        }
        Ok(())
    })();
    let stopped = input.stop();
    let queue = acquisition.queue_stats();
    let evaluations = acquisition.graph().stats().fft_evaluations;
    let reclaimed = reclaim(&mut acquisition);
    // Capture counters only after the callback/stream owner has been released.
    let metrics = json!({ "schema_version": 1, "generation": request.format.generation,
        "device": live.device, "format": request.format, "input": input.report(),
        "captured_frames": captured_frames, "fft_evaluations": evaluations, "queue": queue,
        "stop_ms": stopped.as_ref().ok(), "reclaimed": reclaimed.is_ok(),
        "error": result.as_ref().err().or(stopped.as_ref().err()).or(reclaimed.as_ref().err()) });
    if let Some(path) = &request.evidence {
        save_new(
            &path.join(format!("live-{}.json", request.format.generation)),
            serde_json::to_vec_pretty(&metrics).map_err(|e| e.to_string())?,
        )?;
    }
    result?;
    stopped?;
    reclaimed
}
fn save_new(path: &std::path::Path, bytes: Vec<u8>) -> Result<(), String> {
    use std::io::Write;
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|e| e.to_string())?;
    file.write_all(&bytes).map_err(|e| e.to_string())
}
fn save_window(
    path: &std::path::Path,
    acquisition: &Acquisition<f32>,
    frame: &Frame,
) -> Result<(), String> {
    let document = frame.result.to_value();
    let start = document["interval"][0]
        .as_i64()
        .ok_or("live_result_interval")?;
    let end = document["interval"][1]
        .as_i64()
        .ok_or("live_result_interval")?;
    let read = acquisition
        .history()
        .ok_or("live_history_missing")?
        .read_interval(start, end)?;
    let block = read.snapshot.ok_or("live_evidence_history_missing")?;
    let Samples::F32(values) = block.samples() else {
        return Err("live_evidence_precision".into());
    };
    let bytes = values.iter().flat_map(|v| v.to_le_bytes()).collect();
    let generation = acquisition.format().generation;
    save_new(&path.join(format!("input-{generation}.f32")), bytes)?;
    frame
        .result
        .save_new(
            &path.join(format!("generation-{generation}.json")),
            Format::Json,
        )
        .map_err(|e| e.to_string())?;
    Ok(())
}
