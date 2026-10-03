//! File boundary for comparing the candidate with immutable reference bytes.
use dsp_core::{Analysis, Analyzer, Window};
use realfft::FftNum;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::Path;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: u32,
    n: usize,
    dtype: String,
    window: String,
    rate_hz: f64,
    channel_ids: Vec<String>,
}

#[derive(Serialize)]
struct ArrayEntry {
    file: String,
    dtype: String,
    shape: Vec<usize>,
    complex: Option<&'static str>,
    byte_order: &'static str,
    layout: &'static str,
    origin: &'static str,
}

fn write_array(
    directory: &Path,
    name: &str,
    values: impl Iterator<Item = f64>,
    dtype: &str,
    shape: Vec<usize>,
    complex: bool,
) -> Result<ArrayEntry, Box<dyn std::error::Error>> {
    let file = format!("{name}.bin");
    let mut writer = BufWriter::new(
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(directory.join(&file))?,
    );
    for value in values {
        if dtype == "<f4" {
            writer.write_all(&(value as f32).to_le_bytes())?;
        } else {
            writer.write_all(&value.to_le_bytes())?;
        }
    }
    writer.flush()?;
    Ok(ArrayEntry {
        file,
        dtype: dtype.into(),
        shape,
        complex: complex.then_some("real-imag-last-axis"),
        byte_order: "little",
        layout: "C/frame-major",
        origin: "candidate",
    })
}

fn output<T: FftNum + realfft::num_traits::ToPrimitive>(
    directory: &Path,
    request: &Request,
    result: Analysis<T>,
) -> Result<(), Box<dyn std::error::Error>> {
    // Only create output after the entire request and calculation have succeeded.
    fs::create_dir(directory)?;
    let channels = result.channel_ids.len();
    let bins = request.n / 2 + 1;
    let mut arrays = BTreeMap::new();
    arrays.insert(
        "fft_over_n",
        write_array(
            directory,
            "fft_over_n",
            result.fft_over_n.iter().flat_map(|z| [z.re, z.im]),
            "<f8",
            vec![bins, channels, 2],
            true,
        )?,
    );
    arrays.insert(
        "inverse_windowed",
        write_array(
            directory,
            "inverse_windowed",
            result.inverse_windowed.iter().map(|v| v.to_f64().unwrap()),
            &request.dtype,
            vec![request.n, channels],
            false,
        )?,
    );
    for (name, values, shape) in [
        ("window", &result.window, vec![request.n]),
        ("frequency_hz", &result.frequency_hz, vec![bins]),
        ("peak_fs", &result.peak_fs, vec![bins, channels]),
        ("tone_rms_fs", &result.tone_rms_fs, vec![bins, channels]),
        ("psd_fs2_hz", &result.psd_fs2_hz, vec![bins, channels]),
        (
            "asd_fs_sqrt_hz",
            &result.asd_fs_sqrt_hz,
            vec![bins, channels],
        ),
        ("rms_fs", &result.rms_fs, vec![channels]),
        (
            "integrated_power_fs2",
            &result.integrated_power_fs2,
            vec![channels],
        ),
        (
            "time_window_power_fs2",
            &result.time_window_power_fs2,
            vec![channels],
        ),
    ] {
        arrays.insert(
            name,
            write_array(directory, name, values.iter().copied(), "<f8", shape, false)?,
        );
    }
    let manifest = serde_json::json!({
        "schema_version": 1,
        "request": request,
        "channel_ids": result.channel_ids,
        "backend": "realfft-3.5.0",
        "fft_precision": request.dtype,
        "reduction_precision": "<f8",
        "units": {
            "fft_over_n": "FS", "inverse_windowed": "FS", "frequency_hz": "Hz",
            "peak_fs": "FS peak", "tone_rms_fs": "FS RMS", "rms_fs": "FS RMS",
            "psd_fs2_hz": "FS^2/Hz", "asd_fs_sqrt_hz": "FS/sqrt(Hz)",
            "integrated_power_fs2": "FS^2", "time_window_power_fs2": "FS^2", "window": "1"
        },
        "arrays": arrays
    });
    let mut writer = BufWriter::new(File::create(directory.join("manifest.json"))?);
    serde_json::to_writer_pretty(&mut writer, &manifest)?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    Ok(())
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 3 {
        return Err("Usage: fft-candidate REQUEST.json INPUT.bin NEW_OUTPUT_DIRECTORY".into());
    }
    let request: Request = serde_json::from_slice(&fs::read(&args[0])?)?;
    // Bounds belong to this evaluation file adapter, not a device capability declaration.
    if request.schema_version != 1
        || !(3..=4_194_304).contains(&request.n)
        || !(1..=32).contains(&request.channel_ids.len())
    {
        return Err("Unsupported schema or evaluation dimensions".into());
    }
    let window = match request.window.as_str() {
        "boxcar" => Window::Boxcar,
        "hann" => Window::SymmetricHann,
        _ => return Err("Unsupported window".into()),
    };
    let size = match request.dtype.as_str() {
        "<f4" => 4,
        "<f8" => 8,
        _ => return Err("Unsupported dtype".into()),
    };
    let wanted = request
        .n
        .checked_mul(request.channel_ids.len())
        .and_then(|v| v.checked_mul(size));
    if wanted.map(|v| v as u64) != Some(fs::metadata(&args[1])?.len()) {
        return Err("Input byte count does not match dimensions/dtype".into());
    }
    let bytes = fs::read(&args[1])?;
    if request.dtype == "<f4" {
        let input: Vec<_> = bytes
            .as_chunks::<4>()
            .0
            .iter()
            .map(|v| f32::from_le_bytes(*v))
            .collect();
        let result = Analyzer::<f32>::new(request.n, request.rate_hz, window)?
            .analyze(&input, &request.channel_ids)?;
        output(Path::new(&args[2]), &request, result)?;
    } else {
        let input: Vec<_> = bytes
            .as_chunks::<8>()
            .0
            .iter()
            .map(|v| f64::from_le_bytes(*v))
            .collect();
        let result = Analyzer::<f64>::new(request.n, request.rate_hz, window)?
            .analyze(&input, &request.channel_ids)?;
        output(Path::new(&args[2]), &request, result)?;
    }
    println!(
        "FFT candidate OK: {} frames, {} channels, {}",
        request.n,
        request.channel_ids.len(),
        request.dtype
    );
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("FFT candidate failed: {error}");
        std::process::exit(1);
    }
}
