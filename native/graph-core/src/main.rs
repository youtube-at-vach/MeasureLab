//! File harness: run the original fixture input on an analysis thread and share one owned result.
use graph_core::{
    Average, FftKey, Graph, Limits, Numeric, Precision, Presentation, Samples, SignalBlock,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: u32,
    key: KeyRequest,
    start: u64,
}
// Input gains are deliberately excluded from this immutable FFT corpus comparison.
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct KeyRequest {
    source: graph_core::Source,
    n: usize,
    hop: usize,
    alignment: u64,
    window: graph_core::WindowSpec,
    remove_dc: bool,
}
#[derive(Serialize)]
struct ArrayEntry {
    file: String,
    shape: Vec<usize>,
    dtype: &'static str,
}
fn write_array(
    directory: &Path,
    name: &str,
    values: impl Iterator<Item = f64>,
    shape: Vec<usize>,
    dtype: &'static str,
) -> Result<ArrayEntry, Box<dyn std::error::Error>> {
    let file = format!("{name}.bin");
    let mut out = BufWriter::new(
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(directory.join(&file))?,
    );
    for value in values {
        if dtype == "<f4" {
            out.write_all(&(value as f32).to_le_bytes())?;
        } else {
            out.write_all(&value.to_le_bytes())?;
        }
    }
    out.flush()?;
    Ok(ArrayEntry { file, shape, dtype })
}
fn arrays<T: Copy + Into<f64>>(
    directory: &Path,
    a: &dsp_core::Analysis<T>,
    n: usize,
    precision: Precision,
) -> Result<BTreeMap<&'static str, ArrayEntry>, Box<dyn std::error::Error>> {
    let channels = a.channel_ids.len();
    let bins = n / 2 + 1;
    let mut arrays = BTreeMap::new();
    arrays.insert(
        "fft_over_n",
        write_array(
            directory,
            "fft_over_n",
            a.fft_over_n.iter().flat_map(|z| [z.re, z.im]),
            vec![bins, channels, 2],
            "<f8",
        )?,
    );
    arrays.insert(
        "inverse_windowed",
        write_array(
            directory,
            "inverse_windowed",
            a.inverse_windowed.iter().map(|x| (*x).into()),
            vec![n, channels],
            if precision == Precision::F32 {
                "<f4"
            } else {
                "<f8"
            },
        )?,
    );
    for (name, values, shape) in [
        ("window", &a.window, vec![n]),
        ("frequency_hz", &a.frequency_hz, vec![bins]),
        ("peak_fs", &a.peak_fs, vec![bins, channels]),
        ("tone_rms_fs", &a.tone_rms_fs, vec![bins, channels]),
        ("psd_fs2_hz", &a.psd_fs2_hz, vec![bins, channels]),
        ("asd_fs_sqrt_hz", &a.asd_fs_sqrt_hz, vec![bins, channels]),
        ("rms_fs", &a.rms_fs, vec![channels]),
        (
            "integrated_power_fs2",
            &a.integrated_power_fs2,
            vec![channels],
        ),
        (
            "time_window_power_fs2",
            &a.time_window_power_fs2,
            vec![channels],
        ),
    ] {
        arrays.insert(
            name,
            write_array(directory, name, values.iter().copied(), shape, "<f8")?,
        );
    }
    Ok(arrays)
}
fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 3 {
        return Err("Usage: graph-core REQUEST.json INPUT.bin NEW_OUTPUT_DIRECTORY".into());
    }
    let request: Request = serde_json::from_slice(&fs::read(&args[0])?)?;
    if request.schema_version != 1 || request.key.remove_dc {
        return Err("Unsupported graph comparison request".into());
    }
    let key = FftKey {
        source: request.key.source.clone(),
        n: request.key.n,
        hop: request.key.hop,
        alignment: request.key.alignment,
        window: request.key.window,
        remove_dc: false,
        input_gains: Vec::new(),
    };
    let graph = Graph::new(Limits::default())?;
    let spectrum = graph.subscribe(
        key.clone(),
        Average::None,
        Presentation {
            color: "blue".into(),
            unit: "FS peak".into(),
        },
    )?;
    let spectrogram = graph.subscribe(
        key.clone(),
        Average::CumulativePsd,
        Presentation {
            color: "red".into(),
            unit: "dBFS".into(),
        },
    )?;
    let size = if key.source.precision == Precision::F32 {
        4
    } else {
        8
    };
    let count = key
        .n
        .checked_mul(key.source.channel_ids.len())
        .and_then(|v| v.checked_mul(size))
        .ok_or("Input size overflow")?;
    if fs::metadata(&args[1])?.len() != count as u64 {
        return Err("Input byte count mismatch".into());
    }
    let bytes = fs::read(&args[1])?;
    let samples = if size == 4 {
        Samples::F32(
            bytes
                .as_chunks::<4>()
                .0
                .iter()
                .map(|v| f32::from_le_bytes(*v))
                .collect(),
        )
    } else {
        Samples::F64(
            bytes
                .as_chunks::<8>()
                .0
                .iter()
                .map(|v| f64::from_le_bytes(*v))
                .collect(),
        )
    };
    let input = Arc::new(SignalBlock::new(
        key.source.clone(),
        request.start,
        samples,
        Vec::new(),
    )?);
    let mut jobs = graph.schedule(input)?;
    if jobs.len() != 1 {
        return Err("Expected one shared FFT job".into());
    }
    let job = jobs.pop().unwrap();
    if !std::thread::spawn(move || job.run())
        .join()
        .map_err(|_| "Analysis thread panicked")?
    {
        return Err("Result cancelled".into());
    }
    let a = spectrum.take_latest().ok_or("Missing spectrum result")?;
    let b = spectrogram
        .take_latest()
        .ok_or("Missing spectrogram result")?;
    let shared = Arc::ptr_eq(a.raw(), b.raw());
    let before = graph.stats();
    if !shared || before.fft_evaluations != 1 || b.average_count() != 1 {
        return Err("Graph sharing/average invariant failed".into());
    }
    let numeric = a.raw().numeric().ok_or("FFT result invalid")?;
    let directory = Path::new(&args[2]);
    fs::create_dir(directory)?;
    let arrays = match numeric {
        Numeric::F32(v) => arrays(directory, v, key.n, key.source.precision)?,
        Numeric::F64(v) => arrays(directory, v, key.n, key.source.precision)?,
    };
    drop(spectrum);
    drop(spectrogram);
    graph.shutdown();
    if !graph.wait_idle(Duration::from_secs(1)) {
        return Err("In-flight work retained on shutdown".into());
    }
    let after = graph.stats();
    if after.nodes != 0
        || after.subscriptions != 0
        || after.in_flight != 0
        || after.cache_results != 0
    {
        return Err("Graph resources retained on shutdown".into());
    }
    let manifest = serde_json::json!({ "schema_version": 1, "request": request, "key": a.raw().key(),
        "transform_revision": graph_core::TRANSFORM_REVISION, "result_id": a.raw().id(),
        "spectrum_result_id": a.raw().id(), "spectrogram_result_id": b.raw().id(),
        "interval": a.raw().interval(), "validity": a.raw().validity(), "error": a.raw().error(),
        "shared_allocation": shared, "average_count": b.average_count(), "before_release": before, "after_shutdown": after, "arrays": arrays });
    let mut out = BufWriter::new(
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(directory.join("manifest.json"))?,
    );
    serde_json::to_writer_pretty(&mut out, &manifest)?;
    out.write_all(b"\n")?;
    out.flush()?;
    println!(
        "Graph candidate OK: {} frames, {} channels; 1 FFT, 2 consumers, released",
        key.n,
        key.source.channel_ids.len()
    );
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("Graph candidate failed: {error}");
        std::process::exit(1);
    }
}
