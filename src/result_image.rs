//! Annotated reports drawn from owned f64 results, independent of live UI/GPU.
use crate::export::Document;
use ab_glyph::{Font, FontArc, ScaleFont};
use std::path::Path;

const W: usize = 1600;
const H: usize = 1160;
struct Canvas {
    data: Vec<u8>,
    font: FontArc,
}
impl Canvas {
    fn new() -> Result<Self, String> {
        let fonts = eframe::egui::FontDefinitions::default();
        let font = fonts
            .font_data
            .get("Hack")
            .ok_or("Report font unavailable")?;
        Ok(Self {
            data: vec![17; W * H * 3],
            font: FontArc::try_from_vec(font.font.to_vec()).map_err(|e| e.to_string())?,
        })
    }
    fn pixel(&mut self, x: i32, y: i32, c: [u8; 3]) {
        if x >= 0 && y >= 0 && x < W as i32 && y < H as i32 {
            let i = (y as usize * W + x as usize) * 3;
            self.data[i..i + 3].copy_from_slice(&c);
        }
    }
    fn line(&mut self, a: (f64, f64), b: (f64, f64), color: [u8; 3]) {
        let steps = ((b.0 - a.0).abs().max((b.1 - a.1).abs())).ceil().max(1.0) as usize;
        for i in 0..=steps {
            let t = i as f64 / steps as f64;
            self.pixel(
                (a.0 + (b.0 - a.0) * t).round() as i32,
                (a.1 + (b.1 - a.1) * t).round() as i32,
                color,
            );
        }
    }
    fn text(&mut self, x: f32, y: f32, text: &str) {
        let font = self.font.clone();
        let scaled = font.as_scaled(19.0);
        let mut x = x;
        for c in text.chars() {
            let glyph = scaled.scaled_glyph(c);
            let advance = scaled.h_advance(glyph.id);
            let glyph = ab_glyph::Glyph {
                position: ab_glyph::point(x, y + scaled.ascent()),
                ..glyph
            };
            if let Some(outline) = font.outline_glyph(glyph) {
                let b = outline.px_bounds();
                outline.draw(|dx, dy, coverage| {
                    let v = (17.0 + 218.0 * coverage) as u8;
                    self.pixel(
                        b.min.x as i32 + dx as i32,
                        b.min.y as i32 + dy as i32,
                        [v; 3],
                    );
                });
            }
            x += advance;
            if x > W as f32 - 25.0 {
                break;
            }
        }
    }
    fn grid(&mut self, top: f64, bottom: f64) {
        for k in 0..=10 {
            let x = 90.0 + k as f64 * 143.0;
            self.line((x, top), (x, bottom), [48, 62, 70]);
        }
        for k in 0..=8 {
            let y = top + (bottom - top) * k as f64 / 8.0;
            self.line((90.0, y), (1520.0, y), [48, 62, 70]);
        }
    }
    /// Pixel extrema preserve narrow pulses/peaks; missing samples break paths.
    fn plot(
        &mut self,
        values: impl Iterator<Item = Option<f64>>,
        count: usize,
        [top, bottom]: [f64; 2],
        [min, max]: [f64; 2],
        color: [u8; 3],
    ) {
        if count == 0 || max <= min {
            return;
        }
        if count <= 1430 {
            let mut previous = None;
            for (i, value) in values.enumerate() {
                if let Some(value) = value {
                    let point = (
                        90.0 + i as f64 * 1430.0 / count as f64,
                        bottom - (value.clamp(min, max) - min) / (max - min) * (bottom - top),
                    );
                    self.line(previous.unwrap_or(point), point, color);
                    previous = Some(point);
                } else {
                    previous = None;
                }
            }
            return;
        }
        let mut column = None;
        let mut lo = f64::INFINITY;
        let mut hi = f64::NEG_INFINITY;
        for (i, value) in values.enumerate() {
            let x = 90 + (i * 1430 / count) as i32;
            if column != Some(x) || value.is_none() {
                if let Some(x) = column
                    && lo <= hi
                {
                    let y = |v: f64| bottom - (v - min) / (max - min) * (bottom - top);
                    self.line((x as f64, y(lo)), (x as f64, y(hi)), color);
                }
                lo = f64::INFINITY;
                hi = f64::NEG_INFINITY;
                column = Some(x);
            }
            if let Some(v) = value {
                lo = lo.min(v.clamp(min, max));
                hi = hi.max(v.clamp(min, max));
            }
        }
        if let Some(x) = column
            && lo <= hi
        {
            let y = |v: f64| bottom - (v - min) / (max - min) * (bottom - top);
            self.line((x as f64, y(lo)), (x as f64, y(hi)), color);
        }
    }
}

pub fn render(doc: &Document) -> Result<(u32, u32, Vec<u8>), String> {
    doc.validate()?;
    let mut c = Canvas::new()?;
    c.text(
        30.0,
        20.0,
        "MeasureLab | Held Scope / Spectrum | JSON is the numeric master",
    );
    let source = match &doc.input.source {
        crate::export::Source::Generator => "Generator internal loopback",
        crate::export::Source::Audio { device_name, .. } => device_name.as_str(),
        crate::export::Source::InternalQa { description } => description.as_str(),
        crate::export::Source::SoftwareLoopback { .. } => "Software Loopback",
    };
    c.text(
        30.0,
        50.0,
        &format!(
            "Input: {source} | generation {} | nominal {} Hz | {} channels",
            doc.input.generation, doc.input.nominal_sample_rate_hz, doc.input.channels
        ),
    );
    c.text(
        30.0,
        80.0,
        &format!(
            "Scope [{}, {}) | {:?} | trigger CH {} {:?} {:.6} FS | missing {}",
            doc.scope.sample_range.start,
            doc.scope.sample_range.end,
            doc.scope.acquisition_mode,
            doc.scope.trigger.channel + 1,
            doc.scope.trigger.edge,
            doc.scope.trigger.level,
            doc.loss.scope_missing_samples
        ),
    );
    for (i, t) in doc.scope.traces.iter().enumerate() {
        let cal = t.calibration.as_ref().map_or("uncalibrated".into(), |c| {
            format!("{} rev {}", c.id, c.revision)
        });
        let stats = t.calibrated_statistics.values.as_ref().map_or(
            format!("{:?}", t.calibrated_statistics.state),
            |s| {
                format!(
                    "RMS {:.9e} | peak {:.9e} | P-P {:.9e} {}",
                    s.rms, s.peak, s.peak_to_peak, t.calibrated_statistics.unit
                )
            },
        );
        c.text(
            30.0,
            110.0 + i as f32 * 30.0,
            &format!("Trace {} CH {} | {stats} | {cal}", i + 1, t.channel + 1),
        );
    }
    let peak = doc
        .scope
        .traces
        .iter()
        .flat_map(|t| t.raw_samples_fs.iter().flatten().flatten())
        .fold(0.0_f64, |m, x| m.max(x.abs()))
        .max(1e-9)
        * 1.1;
    c.grid(230.0, 490.0);
    c.text(30.0,190.0,&format!("Scope raw FS | vertical [{:.6e}, {:.6e}] | horizontal sample offset from interval start",-peak,peak));
    for (i, t) in doc.scope.traces.iter().enumerate() {
        if let Some(s) = &t.raw_samples_fs {
            c.plot(
                s.iter().copied(),
                s.len(),
                [230.0, 490.0],
                [-peak, peak],
                if i == 0 {
                    [56, 242, 173]
                } else {
                    [87, 166, 255]
                },
            );
        }
    }
    c.text(90.0, 505.0, "0 samples");
    c.text(
        1280.0,
        505.0,
        &format!(
            "{} samples",
            doc.scope.sample_range.end - doc.scope.sample_range.start
        ),
    );
    let s = &doc.spectrum;
    c.text(
        30.0,
        550.0,
        &format!(
            "Spectrum CH {} | {:?} | {} points | {} | {:?} | unit {}",
            s.channel
                .map_or("unavailable".into(), |c| (c + 1).to_string()),
            s.state,
            s.settings.size,
            s.settings.window.name(),
            s.mode,
            s.unit
        ),
    );
    c.text(
        30.0,
        580.0,
        &format!(
            "{} | bin {:.9} Hz | RBW {:.9} Hz | remove DC {}",
            s.latest_window
                .as_ref()
                .map_or("No complete FFT window".into(), |w| format!(
                    "Window [{}, {})",
                    w.start, w.end
                )),
            s.bin_width_hz,
            s.rbw_hz,
            s.settings.remove_dc
        ),
    );
    let average = s.average.as_ref().map_or("unavailable".into(), |a| {
        format!(
            "EMA alpha {:.9} | {} windows | envelope {:?}",
            a.alpha, a.processed_windows, a.contributing_envelope
        )
    });
    let cal = s.calibration.as_ref().map_or("uncalibrated".into(), |c| {
        format!("{} rev {}", c.id, c.revision)
    });
    c.text(30.0, 610.0, &format!("{average} | calibration {cal}"));
    if let Some(b) = &s.band {
        c.text(
            30.0,
            640.0,
            &format!(
                "Band {:?} Hz | power {:.9e} {} | RMS {:.9e} {}",
                b.bin_centres_hz, b.power, b.power_unit, b.rms, b.rms_unit
            ),
        );
    }
    c.grid(725.0, 985.0);
    let factor = if s.settings.quantity == crate::spectrum::Quantity::Amplitude {
        20.0
    } else {
        10.0
    };
    let db = |v: f64| if v > 0.0 { factor * v.log10() } else { -180.0 };
    let ceiling = s
        .values
        .as_ref()
        .map_or(0.0, |v| v.iter().fold(-180.0_f64, |m, &v| m.max(db(v))))
        .max(-174.0)
        + 6.0;
    c.text(
        30.0,
        685.0,
        &format!(
            "Spectrum dB re 1 {} | display [{:.1}, {:.1}] dB | floor is display only",
            s.unit,
            ceiling - 180.0,
            ceiling
        ),
    );
    if let Some(v) = &s.values {
        c.plot(
            v.iter().map(|&v| Some(db(v))),
            v.len(),
            [725.0, 985.0],
            [ceiling - 180.0, ceiling],
            [255, 211, 66],
        );
    }
    c.text(90.0, 1000.0, "0 Hz");
    c.text(
        1260.0,
        1000.0,
        &format!("{} Hz", doc.input.nominal_sample_rate_hz / 2),
    );
    c.text(30.0,1040.0,&format!("Loss: capture {} | FFT input {} | missing windows {} | nonfinite windows {} | failed {}",doc.loss.capture_dropped_samples,s.diagnostics.missing_input_samples,s.diagnostics.missing_windows,s.diagnostics.nonfinite_windows,doc.loss.input_failed));
    c.text(30.0,1070.0,"Scope and FFT intervals differ. Independent recordings have no shared sample-clock origin.");
    Ok((W as u32, H as u32, c.data))
}

pub fn save(path: &Path, doc: &Document) -> Result<(), String> {
    let (w, h, data) = render(doc)?;
    crate::file_io::atomic_write(path, |file| {
        let mut encoder = png::Encoder::new(file, w, h);
        encoder.set_color(png::ColorType::Rgb);
        encoder.set_depth(png::BitDepth::Eight);
        let mut metadata = doc.clone();
        for t in &mut metadata.scope.traces {
            t.raw_samples_fs = None;
        }
        metadata.spectrum.values = None;
        metadata.spectrum.peak_hold = None;
        encoder
            .add_itxt_chunk(
                "measurelab_conditions".into(),
                serde_json::to_string(&metadata).map_err(std::io::Error::other)?,
            )
            .map_err(std::io::Error::other)?;
        encoder
            .write_header()
            .map_err(std::io::Error::other)?
            .write_image_data(&data)
            .map_err(std::io::Error::other)
    })
}
