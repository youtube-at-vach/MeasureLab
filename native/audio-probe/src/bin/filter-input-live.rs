//! Short native callback -> explicit widening -> f64 FIR/history/shared FFT diagnostic.
//! All serialization and file I/O wait until the stream has closed.
#![forbid(unsafe_code)]
use audio_core::backend::{InputBinding, SampleFormat};
use audio_probe::live::BackendInput;
use graph_core::acquisition::{Acquisition, CaptureLimits, FftSpec};
use graph_core::filter::{Filter, FilterConfig, FilterLimits, InputConversion};
use graph_core::history::HistoryLimits;
use graph_core::{Average, FftKey, Numeric, Presentation, Rational, Samples, WindowSpec};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    error::Error,
    fs,
    path::PathBuf,
    sync::Arc,
    thread,
    time::{Duration, Instant},
};

fn run(request: Value, output: PathBuf) -> Result<(), Box<dyn Error>> {
    let fields = request.as_object().ok_or("request fields")?;
    if fields.len() != 5
        || fields.keys().any(|k| {
            ![
                "schema_version",
                "binding",
                "library",
                "input_conversion",
                "frames",
            ]
            .contains(&k.as_str())
        })
    {
        // Five fields are deliberately required; unknown configuration is rejected.
        return Err("request fields".into());
    }
    let binding: InputBinding = serde_json::from_value(request["binding"].clone())?;
    binding.validate()?;
    let library: Option<PathBuf> = serde_json::from_value(request["library"].clone())?;
    let conversion: InputConversion = serde_json::from_value(request["input_conversion"].clone())?;
    let frames = request["frames"].as_u64().ok_or("frames")?;
    if request["schema_version"] != 1
        || binding.sample_format != SampleFormat::F32
        || binding.format.rate != [48000, 1]
        || !(1024..=16384).contains(&frames)
        || frames % 128 != 0
    {
        return Err("configuration".into());
    }
    let (mut input, rx) = BackendInput::open(
        binding.backend,
        library.as_deref(),
        &binding.device,
        binding.device_channels,
        &binding.format,
    )?;
    let spec = FftSpec {
        n: 64,
        hop: 64,
        alignment: 0,
        window: WindowSpec::Boxcar,
    };
    let mut worker = Acquisition::new(
        rx,
        binding.format.clone(),
        spec.clone(),
        CaptureLimits {
            history: HistoryLimits::frames(256),
            frames_per_poll: 1024,
            windows_per_poll: 1,
        },
    )?;
    let filter = Filter::new_with_conversion(
        worker.key().source.clone(),
        format!("{}.fir", binding.format.stream_id),
        format!("{}.fir", binding.format.timebase_id),
        FilterConfig::Fir {
            coefficients: vec![0.25, 0.5, 0.25],
            target_rate: Rational {
                numerator: 24000,
                denominator: 1,
            },
            centered: false,
            revision: "causal-3tap-v1".into(),
        },
        FilterLimits::default(),
        Some(conversion),
    )?;
    let metadata = filter.metadata().clone();
    let key = FftKey {
        source: filter.output_source().clone(),
        n: 64,
        hop: 64,
        alignment: 0,
        window: WindowSpec::Boxcar,
        remove_dc: false,
        input_gains: vec![],
    };
    let subscribe = || {
        worker.graph().subscribe(
            key.clone(),
            Average::CumulativePsd,
            Presentation {
                color: "blue".into(),
                unit: "FS".into(),
            },
        )
    };
    let a = subscribe()?;
    let b = subscribe()?;
    worker.attach_filter(filter, spec, HistoryLimits::frames(512))?;
    let channels = binding.format.input_ids.len();
    let (mut raw, mut filtered, mut validity, mut windows, mut fft) =
        (Vec::new(), Vec::new(), Vec::new(), Vec::new(), None);
    let (mut max_deliveries, mut max_raw_windows, mut max_filtered_windows) = (0, 0, 0);
    let started = Instant::now();
    let result: Result<(), String> = (|| {
        input.start()?;
        while raw.len() / channels < frames as usize {
            if input.failed() {
                return Err("live callback failure".into());
            }
            if started.elapsed() > Duration::from_secs(5) {
                return Err("live timeout".into());
            }
            let report = worker.poll()?;
            if !report.gaps.is_empty() {
                return Err("live gap".into());
            }
            max_deliveries = max_deliveries.max(report.deliveries);
            max_raw_windows = max_raw_windows.max(report.windows.len());
            max_filtered_windows = max_filtered_windows.max(report.filtered_windows.len());
            for block in report.blocks {
                if block.interval().0 != (raw.len() / channels) as u64
                    || !block.validity().is_empty()
                {
                    return Err("raw interval or validity".into());
                }
                let Samples::F32(values) = block.samples() else {
                    return Err("raw precision".into());
                };
                raw.extend_from_slice(values);
            }
            for block in report.filtered_blocks {
                if block.interval().0 != (filtered.len() / channels) as u64 {
                    return Err("filtered interval".into());
                }
                let Samples::F64(values) = block.samples() else {
                    return Err("filtered precision".into());
                };
                filtered.extend_from_slice(values);
                validity.extend_from_slice(block.validity());
            }
            for event in report.filtered_windows {
                let x = a.take_latest().ok_or("first result")?;
                let y = b.take_latest().ok_or("second result")?;
                if !Arc::ptr_eq(x.raw(), y.raw()) || event.result_id != Some(x.raw().id()) {
                    return Err("unshared result".into());
                }
                if fft.is_none()
                    && let Some(Numeric::F64(numeric)) = x.raw().numeric()
                {
                    fft = Some(
                        numeric
                            .fft_over_n
                            .iter()
                            .flat_map(|z| [z.re, z.im])
                            .collect::<Vec<_>>(),
                    );
                }
                let (start, end) = x.raw().interval();
                windows.push(json!({"interval": [start,end], "result_id": x.raw().id(), "second_result_id": y.raw().id(), "shared_allocation": true,
                    "validity": x.raw().validity(), "numeric": x.raw().numeric().is_some(), "average_count": x.average_count()}));
            }
            thread::sleep(Duration::from_millis(1));
        }
        if raw.len() / channels != frames as usize {
            return Err("live frame boundary".into());
        }
        Ok(())
    })();
    let stopped = input.stop();
    let failed = input.failed();
    let queue = worker.queue_stats();
    let before = worker.graph().stats();
    let filters_before = worker.graph().filter_count();
    drop(a);
    drop(b);
    let released = worker.graph().stats();
    let filters_released = worker.graph().filter_count();
    let retired = worker.poll();
    let history_released = worker.filtered_history().is_none();
    worker.stop();
    let after = worker.graph().stats();
    let metrics = json!({"schema_version": 1, "binding": binding, "input": input.report(), "queue": queue, "stop_ms": stopped.as_ref().ok(),
        "error": result.as_ref().err().or(stopped.as_ref().err()), "failed": failed});
    fs::create_dir(&output)?;
    fs::write(
        output.join("live.json"),
        serde_json::to_vec_pretty(&metrics)?,
    )?;
    result?;
    stopped?;
    retired?;
    if failed {
        return Err("callback failure at close".into());
    }
    let mut arrays = BTreeMap::from([
        ("live.output", filtered),
        (
            "live.raw_f32_as_f64",
            raw.iter().copied().map(f64::from).collect(),
        ),
        ("live.fft_over_n", fft.ok_or("no numeric FFT")?),
    ]);
    let header = json!({"schema_version": 1, "metadata": metadata, "trigger_output": metadata.map_position(&Rational { numerator: 1024, denominator: 1 })?,
        "output_interval": [0,frames/2], "runs": {"live": {"validity": validity, "windows": windows, "before_release": before, "after_release": released, "after_shutdown": after,
            "filters_before": filters_before, "filters_released": filters_released, "filters_after": worker.graph().filter_count(),
            "acquisition": {"acquired_frames": raw.len()/channels, "gaps": [], "max_deliveries": max_deliveries, "max_raw_windows": max_raw_windows,
                "max_filtered_windows": max_filtered_windows, "history_released": history_released, "state": worker.state(), "queue_released": worker.queue_stats().is_none()}}},
        "arrays": arrays.iter().map(|(name,v)| (name, json!({"file": format!("{name}.bin"), "values": v.len(), "dtype": "<f8"}))).collect::<BTreeMap<_,_>>()});
    fs::write(
        output.join("input.f32.bin"),
        raw.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>(),
    )?;
    for (name, values) in &mut arrays {
        fs::write(
            output.join(format!("{name}.bin")),
            values
                .iter()
                .flat_map(|v| v.to_le_bytes())
                .collect::<Vec<_>>(),
        )?;
    }
    fs::write(
        output.join("manifest.json"),
        serde_json::to_vec_pretty(&header)?,
    )?;
    Ok(())
}
fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 || PathBuf::from(&args[2]).exists() {
        return Err("usage: filter-input-live request.json NEW_OUTPUT_DIR".into());
    }
    run(
        serde_json::from_slice(&fs::read(&args[1])?)?,
        PathBuf::from(&args[2]),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn invalid_precision_rate_frames_clock_and_policy_never_open_a_device() {
        let valid = json!({"schema_version": 1, "library": null, "input_conversion": "F32ToF64Exact", "frames": 8192,
            "binding": {"backend": "Cpal", "device": "BlackHole 2ch", "device_channels": 2, "sample_format": "F32",
                "format": {"stream_id": "input", "generation": 1, "timebase_id": "clock", "clock_domain": "cpal.device:BlackHole 2ch",
                    "rate": [48000,1], "input_ids": ["left","right"], "input_ports": [1,0], "output_ids": [], "output_ports": []}}});
        let unused = PathBuf::from("must-not-create-filter-live-test-output");
        for fault in 0..8 {
            let mut request = valid.clone();
            match fault {
                0 => {
                    request.as_object_mut().unwrap().remove("input_conversion");
                }
                1 => request["input_conversion"] = json!("implicit"),
                2 => request["binding"]["sample_format"] = json!("F64"),
                3 => request["binding"]["format"]["clock_domain"] = json!("wrong"),
                4 => request["binding"]["format"]["rate"] = json!([44100, 1]),
                5 => request["frames"] = json!(0),
                6 => request["frames"] = json!(8193),
                _ => request["library"] = json!("/unexpected/cpal/library"),
            }
            assert!(run(request, unused.clone()).is_err());
            assert!(!unused.exists());
        }
    }
}
