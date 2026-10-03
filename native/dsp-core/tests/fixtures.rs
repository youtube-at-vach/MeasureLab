//! Compare the library directly with the original MIG-003 input/reference bytes.
use dsp_core::{Analysis, Analyzer, Window};
use realfft::FftNum;
use realfft::num_complex::Complex;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

fn read_array(directory: &Path, entry: &Value) -> Vec<f64> {
    let path = directory.join(entry["file"].as_str().unwrap());
    let bytes = fs::read(&path).unwrap();
    assert_eq!(
        format!("{:x}", Sha256::digest(&bytes)),
        entry["sha256"].as_str().unwrap(),
        "{}: fixture hash changed",
        path.display()
    );
    let width = match entry["dtype"].as_str().unwrap() {
        "<f4" => 4,
        "<f8" => 8,
        other => panic!("Unsupported fixture dtype: {other}"),
    };
    let count: usize = entry["shape"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_u64().unwrap() as usize)
        .product();
    assert_eq!(bytes.len(), count * width, "{}", path.display());
    bytes
        .chunks_exact(width)
        .map(|chunk| {
            let value = if width == 4 {
                f32::from_le_bytes(chunk.try_into().unwrap()) as f64
            } else {
                f64::from_le_bytes(chunk.try_into().unwrap())
            };
            assert!(value.is_finite(), "{}", path.display());
            value
        })
        .collect()
}

fn compare(actual: &[f64], expected: &[f64], atol: f64, rtol: f64, label: &str) {
    assert_eq!(actual.len(), expected.len(), "{label}: shape");
    for (i, (&a, &e)) in actual.iter().zip(expected).enumerate() {
        assert!(
            a.is_finite() && e.is_finite() && (a - e).abs() <= atol + rtol * e.abs(),
            "{label}[{i}]: {a} != {e}"
        );
    }
}

fn verify<T: FftNum + realfft::num_traits::ToPrimitive>(
    directory: &Path,
    case: &Value,
    atol: f64,
    rtol: f64,
) {
    let spec = &case["spec"];
    let arrays = &case["arrays"];
    let ids: Vec<String> = serde_json::from_value(case["metadata"]["channel_ids"].clone()).unwrap();
    let n = spec["n"].as_u64().unwrap() as usize;
    let window = match spec["window"].as_str().unwrap() {
        "boxcar" => Window::Boxcar,
        "hann" => Window::SymmetricHann,
        other => panic!("Unsupported fixture window: {other}"),
    };
    let input: Vec<T> = read_array(directory, &arrays["input"])
        .into_iter()
        .map(|v| T::from_f64(v).unwrap())
        .collect();
    let result: Analysis<T> = Analyzer::new(n, spec["rate_hz"].as_f64().unwrap(), window)
        .unwrap()
        .analyze(&input, &ids)
        .unwrap();
    assert_eq!(result.channel_ids, ids);
    let inverse: Vec<f64> = result
        .inverse_windowed
        .iter()
        .map(|v| v.to_f64().unwrap())
        .collect();
    let phase_atol = if spec["dtype"] == "<f4" { 1e-4 } else { 1e-7 };
    let phase_floor = if spec["dtype"] == "<f4" { 1e-4 } else { 1e-8 };
    let db_atol = if spec["dtype"] == "<f4" { 1e-3 } else { 1e-5 };
    let db_floor = if spec["dtype"] == "<f4" { 1e-4 } else { 1e-6 };
    for origin in ["theory", "current"] {
        for (name, actual) in [
            ("window", result.window.as_slice()),
            ("frequency_hz", &result.frequency_hz),
            ("inverse_windowed", &inverse),
            ("peak_fs", &result.peak_fs),
            ("psd_fs2_hz", &result.psd_fs2_hz),
            ("rms_fs", &result.rms_fs),
            ("integrated_power_fs2", &result.integrated_power_fs2),
            ("time_window_power_fs2", &result.time_window_power_fs2),
        ] {
            let expected = read_array(directory, &arrays[format!("{origin}.{name}")]);
            let (abs, rel) = if name == "window" {
                (1e-12, 1e-12)
            } else {
                (atol, rtol)
            };
            compare(
                actual,
                &expected,
                abs,
                rel,
                &format!("{}: {origin}.{name}", directory.display()),
            );
        }
        let fft = read_array(directory, &arrays[format!("{origin}.fft_over_n")]);
        assert_eq!(fft.len(), result.fft_over_n.len() * 2);
        let peaks = read_array(directory, &arrays[format!("{origin}.peak_fs")]);
        for (i, (actual, pair)) in result
            .fft_over_n
            .iter()
            .zip(fft.as_chunks::<2>().0)
            .enumerate()
        {
            let expected = Complex::new(pair[0], pair[1]);
            assert!(
                (*actual - expected).norm() <= atol + rtol * expected.norm(),
                "{}: {origin}.FFT[{i}]",
                directory.display()
            );
            if peaks[i] >= phase_floor {
                assert!(
                    (*actual * expected.conj()).arg().abs() <= phase_atol,
                    "{}: phase[{i}]",
                    directory.display()
                );
            }
            if peaks[i] >= db_floor {
                assert!(
                    (20.0 * (result.peak_fs[i] / peaks[i]).log10()).abs() <= db_atol,
                    "{}: dB[{i}]",
                    directory.display()
                );
            }
        }
        let expected_power = read_array(
            directory,
            &arrays[format!("{origin}.time_window_power_fs2")],
        );
        compare(
            &result.integrated_power_fs2,
            &expected_power,
            atol,
            rtol,
            "Parseval",
        );
        for (i, &peak) in peaks.iter().enumerate() {
            let bin = i / ids.len();
            let divisor = if bin == 0 || (n.is_multiple_of(2) && bin == n / 2) {
                1.0
            } else {
                2.0_f64.sqrt()
            };
            compare(
                &[result.tone_rms_fs[i]],
                &[peak / divisor],
                atol,
                rtol,
                "coherent bin RMS",
            );
            compare(
                &[result.asd_fs_sqrt_hz[i].powi(2)],
                &[result.psd_fs2_hz[i]],
                atol,
                rtol,
                "ASD squared",
            );
        }
    }
}

#[test]
fn original_fft_reference_bytes() {
    let fixtures = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../migration/fixtures");
    let mut count = 0;
    for (suite, cases_key, tolerances_key) in [
        ("fft-v1", "cases", "tolerances"),
        ("core-v1", "tones", "fft_tolerances"),
    ] {
        let directory = fixtures.join(suite);
        let manifest: Value =
            serde_json::from_slice(&fs::read(directory.join("manifest.json")).unwrap()).unwrap();
        assert_eq!(
            manifest["reference_commit"],
            "9fd79958f6a8bbae6808813d3704617612e6d26c"
        );
        assert_eq!(
            manifest[tolerances_key]["f32"],
            serde_json::json!({"atol": 2e-6, "rtol": 2e-5})
        );
        assert_eq!(
            manifest[tolerances_key]["f64"],
            serde_json::json!({"atol": 2e-11, "rtol": 1e-9})
        );
        for case in manifest[cases_key].as_array().unwrap() {
            let path = directory.join(case["spec"]["id"].as_str().unwrap());
            match case["spec"]["dtype"].as_str().unwrap() {
                "<f4" => verify::<f32>(&path, case, 2e-6, 2e-5),
                "<f8" => verify::<f64>(&path, case, 2e-11, 1e-9),
                other => panic!("Unsupported fixture precision: {other}"),
            }
            count += 1;
        }
    }
    assert_eq!(count, 18);
}
