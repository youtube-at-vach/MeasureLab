use super::*;
use audio_probe::live::BackendInput;
use graph_core::Samples;
use std::time::Instant;

pub(super) fn run(
    owner: &Owner,
    notify: &impl Fn(u64) -> bool,
    request: &Request,
) -> Result<(), String> {
    let mut request = request.clone();
    let request = &mut request;
    let live = request.live.clone().ok_or("display_input_source")?;
    let (mut input, rx) = BackendInput::open(
        live.backend,
        live.library.as_deref(),
        &live.device,
        live.device_channels,
        &request.format,
    )?;
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
            history: HistoryLimits::frames(request.n * 8),
            frames_per_poll: 1024,
            windows_per_poll: 1,
        },
    )?;
    let mut subscriptions = BTreeMap::new();
    let mut evidence_written = false;
    let mut pending_windows = Vec::new();
    let mut captured_frames = 0;
    let mut save_inputs = SaveInputs::default();
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
            calibration::process(owner, notify, request)?;
            trigger::process(owner, notify, request, &mut acquisition)?;
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
            if let Some(frame) = shared_frame(&subscriptions, request)? {
                if request.save_input_evidence {
                    save_inputs.push(&acquisition, &frame)?;
                }
                if !evidence_written {
                    if request.evidence.is_some() {
                        defer_window(&mut pending_windows, &acquisition, &frame, None)?;
                    }
                    evidence_written = true;
                }
                if let Some(revision) = calibration::evidence_revision(owner)
                    && request.evidence.is_some()
                {
                    defer_window(&mut pending_windows, &acquisition, &frame, Some(revision))?;
                }
                if !publish(owner, notify, &acquisition, frame) {
                    break;
                }
            }
            trigger::process(owner, notify, request, &mut acquisition)?;
            thread::sleep(Duration::from_millis(2));
        }
        Ok(())
    })();
    let stopped = input.stop();
    let queue = acquisition.queue_stats();
    let evaluations = acquisition.graph().stats().fft_evaluations;
    let reclaimed = reclaim(&mut acquisition);
    let triggers = trigger::finish_evidence(owner, request);
    // Keep only bounded immutable snapshots and raw bytes during acquisition.
    // Full normal-result JSON encoding/I/O now waits for stream/graph shutdown.
    let windows = request.evidence.as_ref().map_or(Ok(()), |path| {
        pending_windows
            .into_iter()
            .try_for_each(|window| save_window(path, window, request))
    });
    // CSV serialization can exceed the live queue's time budget. Defer only this
    // diagnostic exchange until no callback/graph remains; do not enlarge the queue.
    let exchange = calibration::finish_live_evidence(request);
    // Raw diagnostic windows never perform I/O while the stream is active.
    let save_evidence = if request.save_input_evidence {
        save_inputs.write(request)
    } else {
        Ok(())
    };
    // Capture counters only after the callback/stream owner has been released.
    let metrics = json!({ "schema_version": 1, "generation": request.format.generation,
        "device": live.device, "backend": live.backend, "format": request.format, "input": input.report(),
        "captured_frames": captured_frames, "fft_evaluations": evaluations, "queue": queue,
        "stop_ms": stopped.as_ref().ok(), "reclaimed": reclaimed.is_ok(),
        "error": result.as_ref().err().or(stopped.as_ref().err()).or(reclaimed.as_ref().err()).or(triggers.as_ref().err()).or(windows.as_ref().err()).or(exchange.as_ref().err()).or(save_evidence.as_ref().err()) });
    if let Some(path) = &request.evidence {
        save_new(
            &path.join(format!("live-{}.json", request.format.generation)),
            serde_json::to_vec_pretty(&metrics).map_err(|e| e.to_string())?,
        )?;
    }
    result?;
    stopped?;
    reclaimed?;
    triggers?;
    windows?;
    exchange?;
    save_evidence
}

const SAVE_INPUT_MAX_BYTES: usize = 8 * 1024 * 1024;
const SAVE_INPUT_MAX_WINDOWS: usize = 256;
#[derive(Default)]
struct SaveInputs {
    bytes: Vec<u8>,
    end: u64,
    windows: usize,
}
impl SaveInputs {
    fn push(&mut self, acquisition: &Acquisition<f32>, frame: &Frame) -> Result<(), String> {
        let [start, end] = frame.result.interval();
        if start != self.end || end <= start {
            return Err("live_save_evidence_interval".into());
        }
        let read = acquisition
            .history()
            .ok_or("live_history_missing")?
            .read_interval(
                i64::try_from(start).map_err(|_| "live_result_interval")?,
                i64::try_from(end).map_err(|_| "live_result_interval")?,
            )?;
        let block = read.snapshot.ok_or("live_save_evidence_history_missing")?;
        let Samples::F32(values) = block.samples() else {
            return Err("live_evidence_precision".into());
        };
        if self.windows == SAVE_INPUT_MAX_WINDOWS
            || values.len() * 4 > SAVE_INPUT_MAX_BYTES - self.bytes.len()
        {
            return Err("live_save_evidence_capacity".into());
        }
        self.bytes
            .extend(values.iter().flat_map(|v| v.to_le_bytes()));
        self.end = end;
        self.windows += 1;
        Ok(())
    }
    fn write(self, request: &Request) -> Result<(), String> {
        let directory = request
            .evidence
            .as_ref()
            .ok_or("live_save_evidence_directory")?;
        let stem = directory.join(format!("save-input-{}", request.format.generation));
        let metadata = json!({"schema_version": 1, "format": request.format,
            "precision": "F32", "n": request.n, "interval": [0, self.end],
            "windows": self.windows, "byte_count": self.bytes.len(),
            "max_bytes": SAVE_INPUT_MAX_BYTES, "max_windows": SAVE_INPUT_MAX_WINDOWS});
        save_new(&stem.with_extension("f32"), self.bytes)?;
        save_new(
            &stem.with_extension("json"),
            serde_json::to_vec_pretty(&metadata).map_err(|e| e.to_string())?,
        )
    }
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
struct PendingWindow {
    generation: u64,
    revision: Option<u64>,
    result: Arc<MeasurementResult>,
    bytes: Vec<u8>,
}
fn defer_window(
    pending: &mut Vec<PendingWindow>,
    acquisition: &Acquisition<f32>,
    frame: &Frame,
    revision: Option<u64>,
) -> Result<(), String> {
    if pending.len() == 8 {
        return Err("live_evidence_capacity".into());
    }
    let [start, end] = frame.result.interval();
    let start = i64::try_from(start).map_err(|_| "live_result_interval")?;
    let end = i64::try_from(end).map_err(|_| "live_result_interval")?;
    let read = acquisition
        .history()
        .ok_or("live_history_missing")?
        .read_interval(start, end)?;
    let block = read.snapshot.ok_or("live_evidence_history_missing")?;
    let Samples::F32(values) = block.samples() else {
        return Err("live_evidence_precision".into());
    };
    pending.push(PendingWindow {
        generation: acquisition.format().generation,
        revision,
        result: frame.result.clone(),
        bytes: values.iter().flat_map(|v| v.to_le_bytes()).collect(),
    });
    Ok(())
}
fn save_window(
    path: &std::path::Path,
    window: PendingWindow,
    request: &Request,
) -> Result<(), String> {
    let PendingWindow {
        generation,
        revision,
        result,
        bytes,
    } = window;
    let stem = revision.map(|r| format!("calibration-{generation}-{r}"));
    let input_path = stem.as_ref().map_or_else(
        || path.join(format!("input-{generation}.f32")),
        |s| path.join(format!("{s}.f32")),
    );
    let result_path = stem.as_ref().map_or_else(
        || path.join(format!("generation-{generation}.json")),
        |s| path.join(format!("{s}.result.json")),
    );
    save_new(&input_path, bytes)?;
    calibration::save_result(&result, &result_path, request)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn save_raw_archive_keeps_all_intervals_and_refuses_capacity_without_truncation() {
        let mut request = crate::tests::request(Precision::F32, 4, false);
        let input = request.input.take().unwrap();
        let bytes = std::fs::read(&input).unwrap();
        let values: Vec<_> = bytes
            .as_chunks::<4>()
            .0
            .iter()
            .map(|v| f32::from_le_bytes(*v))
            .collect();
        let (mut tx, rx) = frame_queue(2048, 4, 48000.).unwrap();
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
                history: HistoryLimits::frames(request.n * 8),
                frames_per_poll: 1024,
                windows_per_poll: 1,
            },
        )
        .unwrap();
        let subscription = acquisition
            .subscribe(
                Average::None,
                Presentation {
                    color: "cyan".into(),
                    unit: "FS_peak".into(),
                },
            )
            .unwrap();
        let mut inputs = SaveInputs::default();
        for _ in 0..SAVE_INPUT_MAX_WINDOWS {
            tx.write(&values, None, 0).unwrap();
            acquisition.poll().unwrap();
            let frame = project(subscription.take_latest().unwrap().raw()).unwrap();
            inputs.push(&acquisition, &frame).unwrap();
            assert_eq!(
                inputs.push(&acquisition, &frame).unwrap_err(),
                "live_save_evidence_interval"
            );
        }
        let expected = bytes.repeat(SAVE_INPUT_MAX_WINDOWS);
        assert_eq!(inputs.bytes, expected);
        tx.write(&values, None, 0).unwrap();
        acquisition.poll().unwrap();
        let frame = project(subscription.take_latest().unwrap().raw()).unwrap();
        assert_eq!(
            inputs.push(&acquisition, &frame).unwrap_err(),
            "live_save_evidence_capacity"
        );
        assert_eq!(inputs.bytes, expected);
        let mut byte_limit = SaveInputs {
            bytes: vec![0; SAVE_INPUT_MAX_BYTES],
            end: inputs.end,
            windows: 0,
        };
        assert_eq!(
            byte_limit.push(&acquisition, &frame).unwrap_err(),
            "live_save_evidence_capacity"
        );
        drop(subscription);
        reclaim(&mut acquisition).unwrap();
        drop(acquisition);
        let directory = input.with_extension("save-raw");
        std::fs::create_dir(&directory).unwrap();
        request.evidence = Some(directory.clone());
        inputs.write(&request).unwrap();
        assert_eq!(
            std::fs::read(directory.join("save-input-1.f32")).unwrap(),
            expected
        );
        let metadata: serde_json::Value =
            serde_json::from_slice(&std::fs::read(directory.join("save-input-1.json")).unwrap())
                .unwrap();
        assert_eq!(
            metadata["interval"],
            json!([0, request.n * SAVE_INPUT_MAX_WINDOWS])
        );
        assert_eq!(metadata["windows"], SAVE_INPUT_MAX_WINDOWS);
        std::fs::remove_file(input).unwrap();
        std::fs::remove_dir_all(directory).unwrap();
    }
    #[test]
    fn deferred_windows_keep_bytes_profiles_and_capacity_after_graph_shutdown() {
        let mut request = crate::tests::request(Precision::F32, 4, false);
        let input = request.input.clone().unwrap();
        request.calibration = vec![ChannelCalibration {
            channel_id: request.format.input_ids[0].clone(),
            revision: "held.profile".into(),
            device_binding: graph_core::result::DeviceBinding {
                device: request.calibration_device(),
                port: 0,
            },
            is_calibrated: true,
            v_per_fs: 2.,
        }];
        let bytes = std::fs::read(&input).unwrap();
        let values: Vec<_> = bytes
            .as_chunks::<4>()
            .0
            .iter()
            .map(|v| f32::from_le_bytes(*v))
            .collect();
        let (mut tx, rx) = frame_queue(2048, 4, 48000.).unwrap();
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
                history: HistoryLimits::frames(request.n * 8),
                frames_per_poll: 1024,
                windows_per_poll: 1,
            },
        )
        .unwrap();
        let subscription = acquisition
            .subscribe(
                Average::None,
                Presentation {
                    color: "cyan".into(),
                    unit: "FS_peak".into(),
                },
            )
            .unwrap();
        tx.write(&values, None, 0).unwrap();
        acquisition.poll().unwrap();
        let spectrum = subscription.take_latest().unwrap();
        let capture = Capture {
            result_id: "deferred.normal".into(),
            trigger_id: None,
            acquired_host_seconds: None,
            result_host_seconds: None,
            trigger: None,
            clock_mapping: None,
        };
        let result =
            Arc::new(calibration::calibrated_result(spectrum.raw(), capture, &request).unwrap());
        let expected = result.to_value();
        let frame = project_result(result).unwrap();
        let mut pending = Vec::new();
        for revision in 1..=8 {
            defer_window(&mut pending, &acquisition, &frame, Some(revision)).unwrap();
        }
        assert!(defer_window(&mut pending, &acquisition, &frame, Some(9)).is_err());
        assert_eq!(pending.len(), 8);
        let window = pending.remove(0);
        assert_eq!(window.bytes, bytes);
        drop(subscription);
        reclaim(&mut acquisition).unwrap();
        drop(acquisition);
        let directory = input.with_extension("deferred");
        std::fs::create_dir(&directory).unwrap();
        request.evidence = Some(directory.clone());
        request.live = Some(LiveRequest {
            backend: Backend::Cpal,
            library: None,
            device: "diagnostic".into(),
            device_channels: 4,
        });
        request.calibration.clear();
        save_window(&directory, window, &request).unwrap();
        calibration::finish_live_evidence(&request).unwrap();
        let stem = directory.join("calibration-1-1");
        assert_eq!(std::fs::read(stem.with_extension("f32")).unwrap(), bytes);
        for (suffix, format) in [("result.json", Format::Json), ("result.csv", Format::Csv)] {
            assert_eq!(
                MeasurementResult::load(&stem.with_extension(suffix), format)
                    .unwrap()
                    .to_value(),
                expected
            );
        }
        assert!(
            save_window(
                &directory,
                PendingWindow {
                    generation: 1,
                    revision: Some(1),
                    result: frame.result,
                    bytes: bytes.clone()
                },
                &request
            )
            .is_err()
        );
        assert_eq!(std::fs::read(stem.with_extension("f32")).unwrap(), bytes);
        std::fs::remove_dir_all(directory).unwrap();
        std::fs::remove_file(input).unwrap();
    }
}
