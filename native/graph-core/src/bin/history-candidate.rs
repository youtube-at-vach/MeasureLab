//! Headless MIG-006-C harness. Requests contain inputs only, never expected answers.
use graph_core::history::{History, HistoryLimits, TriggerEvent};
use graph_core::time::{ClockMapping, relation};
use graph_core::{
    Average, FftKey, Graph, Limits, Numeric, Precision, Presentation, Rational, Samples,
    SignalBlock, Source, Timebase, WindowSpec,
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{fs, path::Path, sync::Arc, time::Duration};

fn rational(v: &Value) -> Result<Rational, Box<dyn std::error::Error>> {
    Ok(Rational {
        numerator: v[0].as_i64().ok_or("rational numerator")?,
        denominator: v[1].as_u64().ok_or("rational denominator")?,
    })
}
fn timebase(v: &Value) -> Result<Timebase, Box<dyn std::error::Error>> {
    let optional = |v: &Value| {
        if v.is_null() {
            Ok(None)
        } else {
            rational(v).map(Some)
        }
    };
    Ok(Timebase {
        id: v["id"].as_str().ok_or("timebase id")?.into(),
        revision: 0,
        clock_domain: v["clock_domain"].as_str().ok_or("clock")?.into(),
        generation: v["generation"].as_u64().ok_or("generation")?,
        rate: rational(&v["rate"])?,
        nominal_rate: rational(&v["nominal_rate"])?,
        origin_sample: v["origin_sample"].as_u64().ok_or("origin sample")?,
        origin_seconds: optional(&v["origin_seconds"])?,
        origin_kind: v["origin_kind"].as_str().ok_or("origin kind")?.into(),
        uncertainty_seconds: optional(&v["uncertainty_seconds"])?,
    })
}
fn source(v: &Value) -> Result<Source, Box<dyn std::error::Error>> {
    let generation = v["generation"].as_u64().ok_or("generation")?;
    Ok(Source {
        stream_id: v["stream_id"].as_str().ok_or("stream")?.into(),
        generation,
        channel_ids: vec!["fixture.ramp".into()],
        precision: Precision::F64,
        timebase: Timebase {
            id: v["timebase_id"].as_str().ok_or("timebase")?.into(),
            revision: 0,
            clock_domain: "fixture.virtual".into(),
            generation,
            rate: Rational {
                numerator: 48000,
                denominator: 1,
            },
            nominal_rate: Rational {
                numerator: 48000,
                denominator: 1,
            },
            origin_sample: 0,
            origin_seconds: None,
            origin_kind: "virtual".into(),
            uncertainty_seconds: None,
        },
        route_revision: "none".into(),
        tap: graph_core::Tap::InputRaw,
        filter_state_revision: "none".into(),
        calibration_revision: "none".into(),
    })
}
fn history_case(v: &Value) -> Result<Value, Box<dyn std::error::Error>> {
    let source = source(v)?;
    let capacity = v["capacity"].as_u64().ok_or("capacity")? as usize;
    let mut history = History::new(source.clone(), HistoryLimits::frames(capacity))?;
    for interval in v["acquired_intervals"].as_array().ok_or("intervals")? {
        let mut start = interval[0].as_u64().ok_or("start")?;
        let end = interval[1]
            .as_u64()
            .ok_or("end")?
            .min(v["acquired_until"].as_u64().ok_or("high")?);
        while start < end {
            let stop = (start + 127).min(end);
            history.append(SignalBlock::new(
                source.clone(),
                start,
                Samples::F64((start..stop).map(|n| n as f64).collect()),
                Vec::new(),
            )?)?;
            start = stop;
        }
    }
    if history.acquired_until() != v["acquired_until"].as_u64().ok_or("high")? {
        return Err("Trace does not end at acquired_until".into());
    }
    let e = &v["event"];
    let event = TriggerEvent {
        id: e["id"].as_str().ok_or("event id")?.into(),
        stream_id: e["stream_id"].as_str().ok_or("stream")?.into(),
        generation: e["generation"].as_u64().ok_or("generation")?,
        timebase_id: e["timebase_id"].as_str().ok_or("timebase")?.into(),
        sample: rational(&e["sample"])?,
        source: e["source"].as_str().ok_or("source")?.into(),
        kind: e["kind"].as_str().ok_or("kind")?.into(),
        polarity: e["polarity"].as_str().ok_or("polarity")?.into(),
        condition_revision: e["condition_revision"].as_str().ok_or("revision")?.into(),
        validity: serde_json::from_value(e["validity"].clone())?,
        received_host_seconds: Some(Rational {
            numerator: v["notification_host_seconds"].as_i64().ok_or("host time")?,
            denominator: 1,
        }),
    };
    match history.query(
        &event,
        v["pre"].as_u64().ok_or("pre")?,
        v["post"].as_u64().ok_or("post")?,
    ) {
        Err(reason) => Ok(json!({"status":"rejected", "reason":reason, "event_id":event.id})),
        Ok(read) => {
            if let Some(block) = &read.snapshot {
                let Samples::F64(values) = block.samples() else {
                    return Err("Unexpected precision".into());
                };
                if values
                    .iter()
                    .enumerate()
                    .any(|(i, x)| *x != (block.interval().0 + i as u64) as f64)
                {
                    return Err("History sample position mismatch".into());
                }
            }
            let mut output = serde_json::to_value(&read.report)?;
            output["event_id"] = json!(event.id);
            output["fractional_residual"] = json!([
                read.fractional_residual.numerator,
                read.fractional_residual.denominator
            ]);
            Ok(output)
        }
    }
}
fn time_case(v: &Value) -> Result<Value, Box<dyn std::error::Error>> {
    let left = timebase(&v["left"])?;
    let right = timebase(&v["right"])?;
    let m = &v["mapping"];
    let mapping = if m.is_null() {
        None
    } else {
        Some(ClockMapping {
            from: serde_json::from_value(m["from"].clone())?,
            to: serde_json::from_value(m["to"].clone())?,
            offset: rational(&m["offset"])?,
            ratio: rational(&m["ratio"])?,
            valid_interval: serde_json::from_value(m["valid_interval"].clone())?,
            method: m["method"].as_str().ok_or("method")?.into(),
            uncertainty_samples: if m["uncertainty_samples"].is_null() {
                None
            } else {
                Some(rational(&m["uncertainty_samples"])?)
            },
        })
    };
    let result = relation(
        &left,
        &right,
        mapping.as_ref(),
        v["sample"].as_i64().ok_or("sample")?,
    )?;
    let mut output = json!({"value":result.value.as_ref().map(|r| json!([r.numerator,r.denominator])), "reason":result.reason});
    if result.mapping.is_some() {
        output["mapping"] = m.clone();
    } else if result.value.is_some() {
        output["uncertainty_seconds"] = result
            .uncertainty_seconds
            .map(|r| json!([r.numerator, r.denominator]))
            .unwrap_or(Value::Null);
    }
    Ok(output)
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    operation: String,
    input: Value,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: u64,
    cases: Vec<Case>,
}
fn cases(path: &Path, output: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let request: Request = serde_json::from_slice(&fs::read(path)?)?;
    if request.schema_version != 1 || request.cases.len() > 128 {
        return Err("Unsupported request".into());
    }
    let mut results = Vec::new();
    for case in request.cases {
        let observed = match case.operation.as_str() {
            "history" => history_case(&case.input)?,
            "time" => time_case(&case.input)?,
            _ => return Err("Unsupported operation".into()),
        };
        results.push(json!({"id":case.id, "observed":observed}));
    }
    // create_new preserves any existing output.
    use std::io::Write;
    fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(output)?
        .write_all(&serde_json::to_vec_pretty(&results)?)?;
    Ok(())
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CorpusRequest {
    schema_version: u64,
    source: Source,
    start: u64,
    n: usize,
    window: WindowSpec,
}
fn bytes(block: &SignalBlock) -> Vec<u8> {
    match block.samples() {
        Samples::F32(v) => v.iter().flat_map(|v| v.to_le_bytes()).collect(),
        Samples::F64(v) => v.iter().flat_map(|v| v.to_le_bytes()).collect(),
    }
}
fn corpus(request: &Path, input: &Path, output: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let request: CorpusRequest = serde_json::from_slice(&fs::read(request)?)?;
    if request.schema_version != 1 || request.n < 3 || request.n > 4_194_304 {
        return Err("Invalid corpus request".into());
    }
    let source = request.source.clone();
    let size = if source.precision == Precision::F32 {
        4
    } else {
        8
    };
    let count = request
        .n
        .checked_mul(source.channel_ids.len())
        .and_then(|n| n.checked_mul(size))
        .ok_or("Input size overflow")?;
    if fs::metadata(input)?.len() != count as u64 {
        return Err("Input byte count mismatch".into());
    }
    let raw = fs::read(input)?;
    let mut history = History::new(source.clone(), HistoryLimits::frames(2 * request.n))?;
    let mut at = 0;
    let chunks = [1, 127, 256, 17];
    let mut index = 0;
    while at < request.n {
        let stop = (at + chunks[index % chunks.len()]).min(request.n);
        let part =
            &raw[at * source.channel_ids.len() * size..stop * source.channel_ids.len() * size];
        let samples = if size == 4 {
            Samples::F32(
                part.as_chunks::<4>()
                    .0
                    .iter()
                    .map(|v| f32::from_le_bytes(*v))
                    .collect(),
            )
        } else {
            Samples::F64(
                part.as_chunks::<8>()
                    .0
                    .iter()
                    .map(|v| f64::from_le_bytes(*v))
                    .collect(),
            )
        };
        history.append(SignalBlock::new(
            source.clone(),
            request.start + at as u64,
            samples,
            Vec::new(),
        )?)?;
        at = stop;
        index += 1;
    }
    let mut first = history.reader(request.start as i64);
    let mut second = history.reader(request.start as i64);
    let read = history.read_next(&mut first, request.n)?;
    let held = Arc::clone(read.snapshot.as_ref().ok_or("Missing snapshot")?);
    let end = request.start + request.n as u64;
    // A later acquisition precedes the second notification; neither cursor nor input storage is shared.
    let zeros = |frames| {
        if size == 4 {
            Samples::F32(vec![0.0; frames * source.channel_ids.len()])
        } else {
            Samples::F64(vec![0.0; frames * source.channel_ids.len()])
        }
    };
    history.append(SignalBlock::new(source.clone(), end, zeros(1), Vec::new())?)?;
    let delayed = history
        .read_next(&mut second, request.n)?
        .snapshot
        .ok_or("Missing delayed snapshot")?;
    if bytes(&held) != raw || bytes(&delayed) != raw {
        return Err("History altered source bytes".into());
    }
    let graph = Graph::new(Limits::default())?;
    let key = FftKey {
        source: source.clone(),
        n: request.n,
        hop: request.n,
        alignment: request.start,
        window: request.window,
        remove_dc: false,
        input_gains: Vec::new(),
    };
    let p = || Presentation {
        color: "blue".into(),
        unit: "FS".into(),
    };
    let a = graph.subscribe(key.clone(), Average::None, p())?;
    let b = graph.subscribe(key, Average::CumulativePsd, p())?;
    let jobs = graph.schedule_history(&read)?;
    if jobs.len() != 1 {
        return Err("Expected one shared job".into());
    }
    for job in jobs {
        if !std::thread::spawn(move || job.run())
            .join()
            .map_err(|_| "Worker panicked")?
        {
            return Err("Publish failed".into());
        }
    }
    let a_result = a.take_latest().ok_or("No first result")?;
    let b_result = b.take_latest().ok_or("No second result")?;
    if !Arc::ptr_eq(a_result.raw(), b_result.raw()) {
        return Err("FFT result not shared".into());
    }
    let complex = match a_result.raw().numeric().ok_or("Invalid FFT")? {
        Numeric::F32(v) => &v.fft_over_n,
        Numeric::F64(v) => &v.fft_over_n,
    };
    let complex_bytes: Vec<u8> = complex
        .iter()
        .flat_map(|v| [v.re, v.im])
        .flat_map(|v| v.to_le_bytes())
        .collect();
    history.append(SignalBlock::new(
        request.source.clone(),
        end + 1,
        zeros(2 * request.n),
        Vec::new(),
    )?)?;
    if bytes(&held) != raw || bytes(&delayed) != raw {
        return Err("Held snapshots mutated after eviction".into());
    }
    let expired = history.read_interval(request.start as i64, end as i64)?;
    if expired.report.status != "gap" || graph.schedule_history(&expired).is_ok() {
        return Err("Expired history entered graph".into());
    }
    let before = graph.stats();
    drop(a);
    drop(b);
    graph.shutdown();
    if !graph.wait_idle(Duration::from_secs(1)) {
        return Err("Outstanding jobs".into());
    }
    fs::create_dir(output)?;
    fs::write(output.join("snapshot.bin"), bytes(&held))?;
    fs::write(output.join("delayed.bin"), bytes(&delayed))?;
    fs::write(output.join("fft_over_n.bin"), complex_bytes)?;
    fs::write(
        output.join("manifest.json"),
        serde_json::to_vec_pretty(&json!({"schema_version":1, "source":request.source,
        "interval":[request.start,end], "dtype":if size==4 {"<f4"} else {"<f8"}, "frames":request.n,
        "reader_positions":[first.position(),second.position()], "shared_allocation":true,
        "result_id":a_result.raw().id(), "second_result_id":b_result.raw().id(), "validity":a_result.raw().validity(),
        "before_release":before, "after_shutdown":graph.stats(), "expired":expired.report,
        "retained_frames":history.retained_frames(), "retained_numeric_bytes":history.retained_numeric_bytes()}))?,
    )?;
    Ok(())
}
fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    match args.as_slice() {
        [mode, request, output] if mode == "--cases" => cases(Path::new(request), Path::new(output)),
        [mode, request, input, output] if mode == "--corpus" => corpus(Path::new(request), Path::new(input), Path::new(output)),
        _ => Err("Usage: history-candidate --cases REQUEST NEW_OUTPUT | --corpus REQUEST INPUT NEW_OUTPUT_DIR".into()),
    }
}
fn main() {
    if let Err(e) = run() {
        eprintln!("History candidate failed: {e}");
        std::process::exit(1);
    }
}
