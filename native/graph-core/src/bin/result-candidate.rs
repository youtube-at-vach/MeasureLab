//! Headless MIG-006-E harness: inputs only, saved bytes, three consumers and file roundtrips.
use graph_core::export::{SaveStatus, SaveWorker};
use graph_core::product::{self, ProductFormat};
use graph_core::result::{Capture, Format, MeasurementResult, Profile};
use graph_core::{
    Average, FftKey, Graph, Limits, Precision, Presentation, Rational, Samples, SignalBlock,
    Source, Tap, Timebase, WindowSpec,
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::time::Duration;
use std::{collections::BTreeMap, fs, path::Path, sync::Arc};
type Error = Box<dyn std::error::Error>;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct LegacyTimebase {
    id: String,
    clock_domain: String,
    generation: u64,
    rate: (i64, u64),
    nominal_rate: (i64, u64),
    origin_sample: u64,
    origin_seconds: Option<(i64, u64)>,
    origin_kind: String,
    uncertainty_seconds: Option<(i64, u64)>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Provenance {
    stream_id: String,
    generation: u64,
    interval: [u64; 2],
    timebase: LegacyTimebase,
    result_id: String,
    operation_revision: String,
    trigger_id: Option<String>,
    route_revision: String,
    tap: String,
    acquired_host_seconds: Option<(i64, u64)>,
    result_host_seconds: Option<(i64, u64)>,
    validity: Vec<graph_core::InvalidSpan>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ToneInput {
    channel_order: Vec<String>,
    frequency_correction: f64,
    frequency_hz: Vec<f64>,
    peak_fs: BTreeMap<String, f64>,
    profiles: BTreeMap<String, Profile>,
    provenance: Provenance,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ToneRequest {
    schema_version: u32,
    input: ToneInput,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Key {
    source: Source,
    n: usize,
    hop: usize,
    alignment: u64,
    window: WindowSpec,
    remove_dc: bool,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FftRequest {
    schema_version: u32,
    key: Key,
    start: u64,
    capture: Capture,
    profiles: BTreeMap<String, Profile>,
    frequency_correction: f64,
}
fn rational(pair: (i64, u64)) -> Rational {
    Rational {
        numerator: pair.0,
        denominator: pair.1,
    }
}
fn roundtrip(result: &MeasurementResult, directory: &Path) -> Result<(), Error> {
    for (name, format) in [("result.json", Format::Json), ("result.csv", Format::Csv)] {
        let path = directory.join(name);
        result.save_new(&path, format)?;
        if MeasurementResult::load(&path, format)?.to_value() != result.to_value() {
            return Err("roundtrip mismatch".into());
        }
        let bytes = fs::read(&path)?;
        if result.save_new(&path, format).is_ok() || bytes != fs::read(path)? {
            return Err("existing destination replaced".into());
        }
    }
    Ok(())
}
fn async_roundtrip(result: MeasurementResult, directory: &Path) -> Result<Value, Error> {
    let snapshot = Arc::new(result);
    let mut worker = SaveWorker::start(2)?;
    let mut receipts = Vec::new();
    let files = [("result.json", Format::Json), ("result.csv", Format::Csv)];
    let tickets = files
        .iter()
        .map(|(name, format)| worker.submit(Arc::clone(&snapshot), directory.join(name), *format))
        .collect::<Result<Vec<_>, _>>()?;
    for (ticket, (name, format)) in tickets.iter().zip(files) {
        let receipt = ticket.wait(Duration::from_secs(30));
        if receipt.status != SaveStatus::Saved
            || MeasurementResult::load(&directory.join(name), format)?.to_value()
                != snapshot.to_value()
        {
            return Err("async roundtrip did not complete exactly".into());
        }
        receipts.push(receipt);
    }
    for (name, format) in files {
        let path = directory.join(name);
        let bytes = fs::read(&path)?;
        let ticket = worker.submit(Arc::clone(&snapshot), path.clone(), format)?;
        let receipt = ticket.wait(Duration::from_secs(30));
        if !matches!(&receipt.status, SaveStatus::Failed { kind, .. } if kind == "AlreadyExists")
            || fs::read(path)? != bytes
        {
            return Err("async existing destination was not preserved".into());
        }
        receipts.push(receipt);
    }
    let failed = worker.submit(
        Arc::clone(&snapshot),
        directory.join("absent/result.json"),
        Format::Json,
    )?;
    let receipt = failed.wait(Duration::from_secs(30));
    if !matches!(&receipt.status, SaveStatus::Failed { kind, .. } if kind == "NotFound") {
        return Err("missing parent was not a save failure".into());
    }
    receipts.push(receipt);
    let recovered = worker.submit(
        Arc::clone(&snapshot),
        directory.join("recovered.json"),
        Format::Json,
    )?;
    let receipt = recovered.wait(Duration::from_secs(30));
    if receipt.status != SaveStatus::Saved {
        return Err("file worker did not recover after I/O failure".into());
    }
    receipts.push(receipt);
    worker.join()?;
    if Arc::strong_count(&snapshot) != 1 {
        return Err("file worker retained numeric snapshot".into());
    }
    Ok(json!({"capacity":2, "receipts":receipts, "snapshot_released_by_worker":true}))
}
fn product_roundtrip(result: MeasurementResult, directory: &Path) -> Result<Value, Error> {
    let snapshot = Arc::new(result);
    let mut worker = SaveWorker::start_product(2)?;
    let mut receipts = Vec::new();
    let files = [
        ("product.json", ProductFormat::ProductJson),
        ("product.csv", ProductFormat::ProductCsv),
    ];
    for (name, format) in files {
        let ticket = worker.submit(Arc::clone(&snapshot), directory.join(name), format)?;
        let receipt = ticket.wait(Duration::from_secs(30));
        if receipt.status != SaveStatus::Saved
            || product::load(&directory.join(name), format)?.to_value() != snapshot.to_value()
        {
            return Err("native product save did not complete exactly".into());
        }
        receipts.push(receipt);
    }
    for (name, format) in files {
        let path = directory.join(name);
        let before = fs::read(&path)?;
        let sidecar = matches!(format, ProductFormat::ProductCsv)
            .then(|| fs::read(product::sidecar_path(&path)))
            .transpose()?;
        let ticket = worker.submit(Arc::clone(&snapshot), path.clone(), format)?;
        let receipt = ticket.wait(Duration::from_secs(30));
        if !matches!(&receipt.status, SaveStatus::Failed { kind, .. } if kind == "AlreadyExists")
            || before != fs::read(&path)?
            || sidecar
                .is_some_and(|before| fs::read(product::sidecar_path(&path)).ok() != Some(before))
        {
            return Err("existing product file was not preserved".into());
        }
        receipts.push(receipt);
    }
    let failed = worker.submit(
        Arc::clone(&snapshot),
        directory.join("absent/product.json"),
        ProductFormat::ProductJson,
    )?;
    let receipt = failed.wait(Duration::from_secs(30));
    if !matches!(&receipt.status, SaveStatus::Failed { kind, .. } if kind == "NotFound") {
        return Err("missing parent not reported failed".into());
    }
    receipts.push(receipt);
    let orphan = directory.join("orphan.csv");
    fs::write(product::sidecar_path(&orphan), b"existing user sidecar")?;
    let partial = worker.submit(
        Arc::clone(&snapshot),
        orphan.clone(),
        ProductFormat::ProductCsv,
    )?;
    let receipt = partial.wait(Duration::from_secs(30));
    if !matches!(&receipt.status, SaveStatus::Failed { kind, .. } if kind == "AlreadyExists")
        || !orphan.exists()
        || fs::read(product::sidecar_path(&orphan))? != b"existing user sidecar"
        || product::load(&orphan, ProductFormat::ProductCsv).is_ok()
    {
        return Err("partial product pair was reported saved or restored".into());
    }
    receipts.push(receipt);
    for (name, format) in [
        ("recovered.json", ProductFormat::ProductJson),
        ("recovered.csv", ProductFormat::ProductCsv),
    ] {
        let ticket = worker.submit(Arc::clone(&snapshot), directory.join(name), format)?;
        let receipt = ticket.wait(Duration::from_secs(30));
        if receipt.status != SaveStatus::Saved
            || product::load(&directory.join(name), format)?.to_value() != snapshot.to_value()
        {
            return Err("product worker did not recover".into());
        }
        receipts.push(receipt);
    }
    worker.join()?;
    if Arc::strong_count(&snapshot) != 1
        || fs::read_dir(directory)?
            .any(|e| e.is_ok_and(|e| e.file_name().to_string_lossy().ends_with(".tmp")))
    {
        return Err("product worker retained snapshot or temporary files".into());
    }
    Ok(
        json!({"capacity":2,"receipts":receipts,"snapshot_released_by_worker":true,"partial_pair_rejected":true}),
    )
}
fn tone(request: &Path, output: &Path) -> Result<Value, Error> {
    let request: ToneRequest = serde_json::from_slice(&fs::read(request)?)?;
    if request.schema_version != 1 {
        return Err("unsupported schema".into());
    }
    let mut input = request.input;
    let p = input.provenance;
    if p.tap != "input.raw"
        || p.operation_revision != "rms-cosine-v1"
        || !p.validity.is_empty()
        || input.peak_fs.len() != input.channel_order.len()
    {
        return Err("unsupported tone provenance".into());
    }
    let source = Source {
        stream_id: p.stream_id,
        generation: p.generation,
        channel_ids: input.channel_order.clone(),
        precision: Precision::F64,
        timebase: Timebase {
            id: p.timebase.id,
            revision: 0,
            clock_domain: p.timebase.clock_domain,
            generation: p.timebase.generation,
            rate: rational(p.timebase.rate),
            nominal_rate: rational(p.timebase.nominal_rate),
            origin_sample: p.timebase.origin_sample,
            origin_seconds: p.timebase.origin_seconds.map(rational),
            origin_kind: p.timebase.origin_kind,
            uncertainty_seconds: p.timebase.uncertainty_seconds.map(rational),
        },
        route_revision: p.route_revision,
        tap: Tap::InputRaw,
        filter_state_revision: "none".into(),
        calibration_revision: "after-analysis".into(),
    };
    let capture = Capture {
        result_id: p.result_id,
        trigger_id: p.trigger_id,
        acquired_host_seconds: p.acquired_host_seconds.map(rational),
        result_host_seconds: p.result_host_seconds.map(rational),
        trigger: None,
        clock_mapping: None,
    };
    let peaks: Vec<_> = input
        .channel_order
        .iter()
        .map(|id| input.peak_fs.get(id).copied().ok_or("missing peak"))
        .collect::<Result<_, _>>()?;
    let result = MeasurementResult::coherent_tone(
        &source,
        p.interval,
        capture.clone(),
        &peaks,
        &input.profiles,
        input.frequency_hz.clone(),
        input.frequency_correction,
    )?;
    let before = result.encode(Format::Json)?;
    for profile in input.profiles.values_mut() {
        profile.revision = "profile.2".into();
        profile.v_per_fs *= 2.;
    }
    let new = MeasurementResult::coherent_tone(
        &source,
        p.interval,
        Capture {
            result_id: "new-profile-result".into(),
            ..capture
        },
        &peaks,
        &input.profiles,
        input.frequency_hz,
        1.0,
    )?;
    if before != result.encode(Format::Json)? || new.to_value() == result.to_value() {
        return Err("profile snapshot invariant".into());
    }
    fs::create_dir(output)?;
    roundtrip(&result, output)?;
    Ok(
        json!({"profile_change_kept_old_result":true, "roundtrips":2, "existing_destination_rejected":true}),
    )
}
fn fft(request: &Path, input: &Path, output: &Path) -> Result<Value, Error> {
    let request: FftRequest = serde_json::from_slice(&fs::read(request)?)?;
    if request.schema_version != 1 || request.key.remove_dc {
        return Err("unsupported request".into());
    }
    let key = FftKey {
        source: request.key.source,
        n: request.key.n,
        hop: request.key.hop,
        alignment: request.key.alignment,
        window: request.key.window,
        remove_dc: false,
        input_gains: vec![],
    };
    let graph = Graph::new(Limits::default())?;
    let subscribe = || {
        graph.subscribe(
            key.clone(),
            Average::None,
            Presentation {
                color: "blue".into(),
                unit: "FS".into(),
            },
        )
    };
    let a = subscribe()?;
    let b = subscribe()?;
    let session = subscribe()?;
    let bytes = fs::read(input)?;
    let width = if key.source.precision == Precision::F32 {
        4
    } else {
        8
    };
    if bytes.len()
        != key
            .n
            .checked_mul(key.source.channel_ids.len())
            .and_then(|v| v.checked_mul(width))
            .ok_or("shape overflow")?
    {
        return Err("input shape".into());
    }
    let samples = match key.source.precision {
        Precision::F32 => Samples::F32(
            bytes
                .as_chunks::<4>()
                .0
                .iter()
                .map(|v| f32::from_le_bytes(*v))
                .collect(),
        ),
        Precision::F64 => Samples::F64(
            bytes
                .as_chunks::<8>()
                .0
                .iter()
                .map(|v| f64::from_le_bytes(*v))
                .collect(),
        ),
    };
    let block = Arc::new(SignalBlock::new(
        key.source.clone(),
        request.start,
        samples,
        vec![],
    )?);
    for job in graph.schedule(block)? {
        if !job.run() {
            return Err("FFT did not publish".into());
        }
    }
    let one = a.take_latest().ok_or("view missing")?;
    let two = b.take_latest().ok_or("view missing")?;
    let save = session.take_latest().ok_or("session missing")?;
    if !Arc::ptr_eq(one.raw(), two.raw())
        || !Arc::ptr_eq(one.raw(), save.raw())
        || graph.stats().fft_evaluations != 1
    {
        return Err("result not shared".into());
    }
    let result = MeasurementResult::from_fft(
        save.raw(),
        request.capture,
        &request.profiles,
        request.frequency_correction,
    )?;
    drop(a);
    drop(b);
    drop(one);
    drop(two);
    let after_views = graph.stats();
    drop(session);
    drop(save);
    graph.shutdown();
    let after = graph.stats();
    if after.nodes != 0
        || after.subscriptions != 0
        || after.cache_results != 0
        || after.in_flight != 0
    {
        return Err("graph ownership retained".into());
    }
    fs::create_dir(output)?;
    roundtrip(&result, output)?;
    Ok(
        json!({"shared_allocation":true, "fft_evaluations":1, "roundtrips":2, "existing_destination_rejected":true, "after_views":after_views, "after_shutdown":after}),
    )
}
fn run() -> Result<(), Error> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    let audit = match args.as_slice() {
        [mode, input, output] if mode == "--product-import-json" || mode == "--product-import-csv" => {
            let imported = product::load_import(Path::new(input), if mode == "--product-import-json" { ProductFormat::ProductJson } else { ProductFormat::ProductCsv })?;
            fs::create_dir(Path::new(output))?;
            fs::write(Path::new(output).join("imported.json"), serde_json::to_vec(&imported.to_value())?)?;
            json!({"product_import_validated": true, "has_snapshot": imported.snapshot().is_some()})
        },
        [mode, input, specification, output] if mode == "--product-import-csv-spec" => {
            let imported = product::load_csv_with_spec(Path::new(input), Path::new(specification))?;
            fs::create_dir(Path::new(output))?;
            fs::write(Path::new(output).join("imported.json"), serde_json::to_vec(&imported.to_value())?)?;
            json!({"product_import_validated": true, "has_snapshot": imported.snapshot().is_some()})
        },
        [mode, input, output] if mode == "--product-save-json" || mode == "--product-save-csv" => {
            let result = MeasurementResult::load(Path::new(input), if mode == "--product-save-json" { Format::Json } else { Format::Csv })?;
            fs::create_dir(Path::new(output))?;
            product_roundtrip(result, Path::new(output))?
        },
        [mode, input, output] if mode == "--product-read-json" || mode == "--product-read-csv" => {
            let result = product::load(Path::new(input), if mode == "--product-read-json" { ProductFormat::ProductJson } else { ProductFormat::ProductCsv })?;
            fs::create_dir(Path::new(output))?;
            roundtrip(&result, Path::new(output))?;
            json!({"product_snapshot_validated":true,"roundtrips":2})
        },
        [mode, input, output] if mode == "--async-read-json" || mode == "--async-read-csv" => {
            let result = MeasurementResult::load(Path::new(input), if mode == "--async-read-json" { Format::Json } else { Format::Csv })?;
            fs::create_dir(Path::new(output))?;
            async_roundtrip(result, Path::new(output))?
        },
        [mode, input, output] if mode == "--read-json" || mode == "--read-csv" => {
            let result = MeasurementResult::load(Path::new(input), if mode == "--read-json" { Format::Json } else { Format::Csv })?;
            fs::create_dir(Path::new(output))?;
            roundtrip(&result, Path::new(output))?;
            json!({"roundtrips":2})
        },
        [mode, request, output] if mode == "--tone" => tone(Path::new(request),Path::new(output))?,
        [mode, request, input, output] if mode == "--fft" => fft(Path::new(request),Path::new(input),Path::new(output))?,
        _ => return Err("Usage: result-candidate --tone REQUEST NEW_DIRECTORY | --fft REQUEST INPUT.bin NEW_DIRECTORY".into()),
    };
    let output = Path::new(args.last().unwrap());
    fs::write(output.join("audit.json"), serde_json::to_vec(&audit)?)?;
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
