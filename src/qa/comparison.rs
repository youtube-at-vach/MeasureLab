//! Independent direct DFT of the exact captured comparison batch, including real I/O.
use crate::{comparison, measurement};
use rustfft::num_complex::Complex;
use std::{f64::consts::TAU, path::Path};

pub fn validate(snapshot: &measurement::Snapshot, path: &Path) -> Result<(), String> {
    let r = &snapshot.comparison;
    let s = r.settings;
    if snapshot.failed
        || snapshot.input_dropped != 0
        || r.state != comparison::State::Valid
        || r.missing_samples != 0
        || r.invalid_samples != 0
        || r.generation != snapshot.generation
    {
        return Err("Comparison input, continuity or finite result invalid".into());
    }
    let k = (750.0 / r.bin_width_hz()).round() as usize;
    let b = r.bins.get(k).ok_or("Comparison missing 750 Hz bin")?;
    let mut p = [0.0; 4];
    let weights: Vec<_> = (0..s.size).map(|i| s.window.weight(i, s.size)).collect();
    let scale = 2.0 / (snapshot.sample_rate as f64 * weights.iter().map(|v| v * v).sum::<f64>());
    for j in 0..s.averages {
        let start = r.sample_range.start + (j * s.size) as u64;
        let mut means = [0.0; 2];
        for n in start..start + s.size as u64 {
            let frame = snapshot
                .history
                .get(n)
                .ok_or("Comparison batch outside retained raw input")?;
            means[0] += frame[s.reference_channel] / s.size as f64;
            means[1] += frame[s.response_channel] / s.size as f64;
        }
        let mut xy = [Complex::<f64>::default(); 2];
        for (i, &weight) in weights.iter().enumerate() {
            let frame = snapshot.history.get(start + i as u64).unwrap();
            for (ch, source) in [s.reference_channel, s.response_channel]
                .into_iter()
                .enumerate()
            {
                let gain = snapshot.calibrations.get(source).map_or(1.0, |c| c.gain());
                xy[ch] += Complex::from_polar(
                    (frame[source] - means[ch]) * gain * weight,
                    -TAU * k as f64 * i as f64 / s.size as f64,
                );
            }
        }
        let cross = xy[0].conj() * xy[1];
        for (i, value) in [xy[0].norm_sqr(), xy[1].norm_sqr(), cross.re, cross.im]
            .into_iter()
            .enumerate()
        {
            p[i] += value * scale / s.averages as f64;
        }
    }
    let close = |a: f64, b: f64| (a - b).abs() <= b.abs() * 1e-9 + 1e-16;
    if ![b.reference_psd, b.response_psd, b.cross_re, b.cross_im]
        .into_iter()
        .zip(p)
        .all(|(a, b)| close(a, b))
    {
        return Err("Comparison FFT disagrees with independent same-window direct DFT".into());
    }
    if b.state != comparison::BinState::Valid || b.coherence.is_none_or(|v| v < 0.99) {
        return Err("Comparison 750 Hz tone is incoherent or unavailable".into());
    }
    let transfer = Complex::new(p[2] / p[0], p[3] / p[0]);
    if !close(b.gain.unwrap(), transfer.norm())
        || !close(b.phase_lead_degrees.unwrap(), transfer.arg().to_degrees())
    {
        return Err("Comparison gain/phase disagrees with independent input".into());
    }
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    std::fs::write(path,serde_json::to_vec_pretty(&serde_json::json!({"generation":r.generation,
        "nominal_sample_rate_hz":r.nominal_sample_rate_hz,"sample_range":r.sample_range,
        "settings":s,"bin":k,"frequency_hz":k as f64*r.bin_width_hz(),"measured":b,
        "direct_dft_psd":p,"direct_dft_gain":transfer.norm(),"direct_dft_phase_degrees":transfer.arg().to_degrees(),
        "missing_samples":r.missing_samples,"invalid_samples":r.invalid_samples,
        "limitations":crate::export::COMPARISON_LIMITATIONS})).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
    println!(
        "Comparison independent input oracle OK: N {} × {} · bin {k} · gain {:.12} · phase {:+.9}° · coherence {:.12} · {}..{}",
        s.size,
        s.averages,
        b.gain.unwrap(),
        b.phase_lead_degrees.unwrap(),
        b.coherence.unwrap(),
        r.sample_range.start,
        r.sample_range.end
    );
    Ok(())
}
