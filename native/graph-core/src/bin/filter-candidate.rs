//! Saved-input-only harness: one graph transform state shared by two FFT consumers.
use graph_core::filter::{Filter, FilterConfig, FilterLimits, SosState, rate_ratio};
use graph_core::history::{History, HistoryLimits};
use graph_core::{
    Average, FftKey, Graph, InvalidSpan, Limits, Presentation, Rational, Samples, SignalBlock,
    Source, WindowSpec,
};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::{collections::BTreeMap, fs, path::Path, sync::Arc};
#[path = "filter-candidate/acquisition.rs"]
mod acquisition;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: u32,
    source: Source,
    output_stream: String,
    output_timebase: String,
    config: FilterConfig,
    frames: usize,
    gaps: Vec<[u64; 2]>,
    chunks: BTreeMap<String, Vec<usize>>,
    trigger: Rational,
    frequencies: Vec<f64>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Rates {
    schema_version: u32,
    rates: Vec<[i64; 2]>,
}
fn write_values(path: &Path, values: &[f64]) -> Result<(), Box<dyn std::error::Error>> {
    let bytes: Vec<_> = values.iter().flat_map(|v| v.to_le_bytes()).collect();
    fs::write(path, bytes)?;
    Ok(())
}
fn collect(
    block: Option<SignalBlock>,
    values: &mut Vec<f64>,
    validity: &mut Vec<InvalidSpan>,
    channels: usize,
) -> Result<(), Box<dyn std::error::Error>> {
    if let Some(block) = block {
        if block.interval().0 != (values.len() / channels) as u64 {
            return Err("output interval/phase mismatch".into());
        }
        let Samples::F64(v) = block.samples() else {
            return Err("output precision".into());
        };
        values.extend_from_slice(v);
        validity.extend_from_slice(block.validity());
    }
    Ok(())
}
#[derive(Serialize)]
struct WindowProof {
    interval: [u64; 2],
    result_id: graph_core::ResultId,
    second_result_id: graph_core::ResultId,
    shared_allocation: bool,
    validity: Vec<InvalidSpan>,
    numeric: bool,
    average_count: u64,
}
fn corpus(
    r: Request,
    raw: &[u8],
    output: &Path,
    through_queue: bool,
) -> Result<(), Box<dyn std::error::Error>> {
    if r.schema_version != 1
        || r.frames == 0
        || r.frames > 65536
        || r.chunks.is_empty()
        || r.chunks.len() > 8
        || r.chunks
            .values()
            .any(|p| p.is_empty() || p.len() > 16 || p.iter().any(|n| *n == 0 || *n > 65536))
        || raw.len() != r.frames * r.source.channel_ids.len() * 8
        || r.gaps.len() > 32
        || r.gaps
            .iter()
            .any(|g| g[0] >= g[1] || g[1] > r.frames as u64)
        || r.gaps.windows(2).any(|p| p[0][1] > p[1][0])
        || r.frequencies.len() > 32
    {
        return Err("invalid_request".into());
    }
    let values: Vec<_> = raw
        .as_chunks::<8>()
        .0
        .iter()
        .map(|b| f64::from_le_bytes(*b))
        .collect();
    if values.iter().any(|v| !v.is_finite()) {
        return Err("nonfinite input".into());
    }
    let template = Filter::new(
        r.source.clone(),
        r.output_stream.clone(),
        r.output_timebase.clone(),
        r.config.clone(),
        FilterLimits::default(),
    )?;
    let source = template.output_source().clone();
    let channels = source.channel_ids.len();
    let ratio = &template.metadata().rate_ratio;
    let count = (r.frames as u64 * ratio.numerator as u64).div_ceil(ratio.denominator) as usize;
    if count > 131072 {
        return Err("output capacity".into());
    }
    let mut runs = BTreeMap::new();
    let mut binaries = BTreeMap::new();
    // All validation and computation finish before creating a result directory.
    for (name, pattern) in &r.chunks {
        if name.is_empty() || !name.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-') {
            return Err("chunk name".into());
        }
        if through_queue {
            let (run, arrays) = acquisition::run(&r, pattern, &values)?;
            for (suffix, values) in arrays {
                binaries.insert(format!("{name}.{suffix}"), values);
            }
            runs.insert(name.clone(), run);
            continue;
        }
        let graph = Graph::new(Limits::default())?;
        let key = FftKey {
            source: source.clone(),
            n: 64,
            hop: 64,
            alignment: 0,
            window: WindowSpec::Boxcar,
            remove_dc: false,
            input_gains: Vec::new(),
        };
        let subscribe = || {
            graph.subscribe(
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
        graph.attach_filter(template.clone())?;
        let (mut observed, mut validity) = (Vec::new(), Vec::new());
        let (mut cursor, mut index) = (0u64, 0usize);
        while cursor < r.frames as u64 {
            if let Some(g) = r.gaps.iter().find(|g| g[0] <= cursor && cursor < g[1]) {
                cursor = g[1];
                continue;
            }
            let boundary = r
                .gaps
                .iter()
                .filter(|g| g[0] > cursor)
                .map(|g| g[0])
                .min()
                .unwrap_or(r.frames as u64);
            let end = (cursor + pattern[index % pattern.len()] as u64)
                .min(boundary)
                .min(r.frames as u64);
            let block = SignalBlock::new(
                r.source.clone(),
                cursor,
                Samples::F64(values[cursor as usize * channels..end as usize * channels].to_vec()),
                Vec::new(),
            )?;
            collect(
                graph.process_filter(&source, &block)?,
                &mut observed,
                &mut validity,
                channels,
            )?;
            cursor = end;
            index += 1;
        }
        collect(
            graph.finish_filter(&source, r.frames as u64)?,
            &mut observed,
            &mut validity,
            channels,
        )?;
        if observed.len() != count * channels {
            return Err("output length".into());
        }
        let state = graph.filter_state(&source);
        let mut history = History::new(source.clone(), HistoryLimits::frames(64))?;
        let mut proofs = Vec::new();
        let mut fft_sample = None;
        for start in (0..count / 64 * 64).step_by(64) {
            let spans = validity
                .iter()
                .filter(|v| v.start < (start + 64) as u64 && v.end > start as u64)
                .map(|v| InvalidSpan {
                    start: v.start.max(start as u64),
                    end: v.end.min((start + 64) as u64),
                    ..v.clone()
                })
                .collect();
            history.append(SignalBlock::new(
                source.clone(),
                start as u64,
                Samples::F64(observed[start * channels..(start + 64) * channels].to_vec()),
                spans,
            )?)?;
            let read = history.read_interval(start as i64, (start + 64) as i64)?;
            let jobs = graph.schedule_history(&read)?;
            if jobs.len() != 1 {
                return Err("shared FFT evaluated twice".into());
            }
            if !jobs.into_iter().next().unwrap().run() {
                return Err("FFT publication".into());
            }
            let x = a.take_latest().ok_or("first snapshot")?;
            let y = b.take_latest().ok_or("second snapshot")?;
            if !Arc::ptr_eq(x.raw(), y.raw()) || x.raw().id() != y.raw().id() {
                return Err("unshared result".into());
            }
            if fft_sample.is_none()
                && let Some(graph_core::Numeric::F64(numeric)) = x.raw().numeric()
            {
                fft_sample = Some(
                    numeric
                        .fft_over_n
                        .iter()
                        .flat_map(|z| [z.re, z.im])
                        .collect::<Vec<_>>(),
                );
            }
            let interval = x.raw().interval();
            proofs.push(WindowProof {
                interval: [interval.0, interval.1],
                result_id: x.raw().id(),
                second_result_id: y.raw().id(),
                shared_allocation: true,
                validity: x.raw().validity().to_vec(),
                numeric: x.raw().numeric().is_some(),
                average_count: x.average_count(),
            });
        }
        let before = graph.stats();
        let filters_before = graph.filter_count();
        drop(a);
        drop(b);
        let filters_released = graph.filter_count();
        let released = graph.stats();
        graph.shutdown();
        let after = graph.stats();
        binaries.insert(format!("{name}.output"), observed);
        if let Some(values) = fft_sample {
            binaries.insert(format!("{name}.fft_over_n"), values);
        }
        if let Some(state) = state {
            binaries.insert(format!("{name}.state"), state);
        }
        runs.insert(name.clone(),json!({"validity":validity,"windows":proofs,"before_release":before,"after_release":released,
            "after_shutdown":after,"filters_before":filters_before,"filters_released":filters_released,"filters_after":graph.filter_count()}));
    }
    if let FilterConfig::Sos { coefficients, .. } = &r.config {
        let sos = SosState::new(coefficients.clone(), channels)?;
        binaries.insert("offline.output".into(), sos.forward_backward(&values, 27)?);
        binaries.insert(
            "response".into(),
            sos.response(&r.frequencies, r.source.timebase.rate_hz())?,
        );
    }
    let header = json!({"schema_version":1,"metadata":template.metadata(),"trigger_output":template.metadata().map_position(&r.trigger)?,
        "output_interval":[0,count],"runs":runs,"arrays":binaries.iter().map(|(name,v)|(name.clone(),json!({"file":format!("{name}.bin"),"values":v.len(),"dtype":"<f8"}))).collect::<BTreeMap<_,_>>()});
    fs::create_dir(output)?;
    for (name, values) in binaries {
        write_values(&output.join(format!("{name}.bin")), &values)?;
    }
    fs::write(
        output.join("manifest.json"),
        serde_json::to_vec_pretty(&header)?,
    )?;
    Ok(())
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args: Vec<_> = std::env::args().collect();
    let through_queue = args.get(1).is_some_and(|a| a == "--acquisition");
    if through_queue {
        args.remove(1);
    }
    if args.len() == 4 && args[1] == "--rates" {
        let r: Rates = serde_json::from_slice(&fs::read(&args[2])?)?;
        if r.schema_version != 1 || r.rates.len() > 64 || Path::new(&args[3]).exists() {
            return Err("rate request".into());
        }
        let results: Vec<_> = r
            .rates
            .iter()
            .map(|[source, target]| {
                match rate_ratio(
                    &Rational {
                        numerator: *source,
                        denominator: 1,
                    },
                    &Rational {
                        numerator: *target,
                        denominator: 1,
                    },
                ) {
                    Ok(r) => json!({"status":"valid_rate_pair","ratio":r}),
                    Err(e) => json!({"status":e,"ratio":null}),
                }
            })
            .collect();
        fs::write(&args[3], serde_json::to_vec_pretty(&results)?)?;
        return Ok(());
    }
    if args.len() != 4 || Path::new(&args[3]).exists() {
        return Err("usage: filter-candidate request.json input.bin NEW_OUTPUT_DIR".into());
    }
    let r: Request = serde_json::from_slice(&fs::read(&args[1])?)?;
    corpus(r, &fs::read(&args[2])?, Path::new(&args[3]), through_queue)
}
