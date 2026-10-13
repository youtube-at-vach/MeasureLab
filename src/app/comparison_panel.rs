//! Captured synchronous results; display selection never schedules an FFT.
use super::*;

impl ScopeApp {
    #[cfg(feature = "qa")]
    pub(super) fn check_comparison_ui(&mut self, mode: &str) -> Result<(), String> {
        self.poll_audio();
        self.core = Some(measurement::Worker::new(self.stft.take_feeder()));
        self.source = Source::Software;
        self.demo_enabled = false;
        self.loopback_settings = loopback::Settings {
            frequency_hz: 750.0,
            ..Default::default()
        };
        self.comparison_settings = comparison::Settings {
            enabled: true,
            size: 4096,
            averages: 4,
            ..Default::default()
        };
        self.lockin_settings = lockin::Settings {
            enabled: true,
            frequency_hz: 750.0,
            ..Default::default()
        };
        self.spectrum_settings.size = 4096;
        self.spectrum_settings.window = Window::Rectangular;
        self.comparison_frequency_hz = 750.0;
        self.acquisition_mode = acquisition::Mode::Auto;
        self.start();
        let deadline = Instant::now() + Duration::from_secs(10);
        while self.comparison_result.state != comparison::State::Valid {
            self.poll_measurement();
            if Instant::now() > deadline {
                return Err("Comparison UI input timed out".into());
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        // A live pair change must clear the old average and invert the transfer.
        let before = self.comparison_settings;
        self.comparison_settings.reference_channel = 1;
        self.comparison_settings.response_channel = 0;
        self.apply_comparison_controls(before);
        let deadline = Instant::now() + Duration::from_secs(10);
        while self.comparison_result.settings != self.comparison_settings
            || self.comparison_result.state != comparison::State::Valid
        {
            self.poll_measurement();
            if Instant::now() > deadline {
                return Err("Live comparison routing timed out".into());
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        assert!((self.comparison_result.bins[64].gain.unwrap() - 2.0).abs() < 1e-9);
        assert!((self.comparison_result.bins[64].phase_lead_degrees.unwrap() + 30.0).abs() < 1e-7);
        self.comparison_settings = before;
        self.core.as_ref().unwrap().configure_comparison(before);
        let deadline = Instant::now() + Duration::from_secs(10);
        while self.comparison_result.settings != before
            || self.comparison_result.state != comparison::State::Valid
        {
            self.poll_measurement();
            if Instant::now() > deadline {
                return Err("Comparison original routing timed out".into());
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        self.stop();
        let mut snapshot = self
            .pending_stop
            .take()
            .ok_or("Missing comparison stop")?
            .wait();
        self.accept_snapshot(&mut snapshot);
        let held = self.comparison_result.clone();
        let b = &held.bins[64];
        assert!((b.gain.unwrap() - 0.5).abs() < 1e-9);
        assert!((b.phase_lead_degrees.unwrap() - 30.0).abs() < 1e-7);
        assert!(held.delay.is_none());
        self.select_view([mode == "pair", false, false, false]);
        self.comparison_visible = true;
        self.sidebar.visible = mode == "narrow";
        let settings = self.capture_settings()?;
        let doc = self.capture_results()?;
        doc.validate()?;
        std::fs::create_dir_all("dist/comparison-qa").map_err(|e| e.to_string())?;
        export::save(
            std::path::Path::new("dist/comparison-qa/ui-results.json"),
            &doc,
        )?;
        crate::results::save_csv(
            std::path::Path::new("dist/comparison-qa/ui-results.csv"),
            &doc,
        )?;
        let loaded =
            crate::results::load(std::path::Path::new("dist/comparison-qa/ui-results.json"))?;
        assert_eq!(loaded.comparison, doc.comparison);
        let before = self.comparison_settings;
        self.comparison_settings.response_channel = 0;
        self.comparison_settings.reference_channel = 1;
        self.apply_comparison_controls(before);
        assert_eq!(self.comparison_result, held);
        self.restore_settings(settings::Document::decode(&settings.encode()?)?)?;
        assert!(!self.running());
        self.start();
        let deadline = Instant::now() + Duration::from_secs(10);
        while self.comparison_result.state != comparison::State::Valid {
            self.poll_measurement();
            if Instant::now() > deadline {
                return Err("Comparison remeasurement timed out".into());
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        self.stop();
        let mut snapshot = self
            .pending_stop
            .take()
            .ok_or("Missing remeasurement stop")?
            .wait();
        self.accept_snapshot(&mut snapshot);
        let current = self.capture_results()?;
        let difference = crate::results::comparison_difference(&loaded, &current, 64)
            .ok_or("Comparison conditions differ after restore")?;
        assert!(difference.gain.abs() < 1e-9 && difference.phase_degrees.abs() < 1e-7);
        self.created = Instant::now();
        println!(
            "Comparison UI QA OK: {mode}; normal software input; finite stop; JSON/CSV; stopped edit; OFF restore and new-generation remeasurement; gain/phase match"
        );
        Ok(())
    }
    pub(super) fn comparison_controls(&mut self, ui: &mut egui::Ui) {
        if ui.button("Open comparison display").clicked() {
            self.select_view([false; 4]);
            self.comparison_visible = true;
        }
        let before = self.comparison_settings;
        let channels = self.lockin_channel_count();
        ui.add_enabled_ui(
            !self.busy && self.pending_stop.is_none() && !self.workspace_restoring,
            |ui| {
                comparison_controls(ui, &mut self.comparison_settings, channels);
            },
        );
        self.apply_comparison_controls(before);
        ui.label(RichText::new("AC comparison · positive phase leads REF; positive delay lags REF. Stopped edits apply on the next Start.").small().color(MUTED));
    }
    fn apply_comparison_controls(&mut self, before: comparison::Settings) {
        if before == self.comparison_settings {
            return;
        }
        if let Err(error) = self.comparison_settings.validate(self.sample_rate) {
            self.comparison_settings = before;
            self.error = Some(error);
        } else if self.running()
            && let Some(core) = &self.core
        {
            core.configure_comparison(self.comparison_settings);
        }
    }
    pub(super) fn comparison_panel(&mut self, ui: &mut egui::Ui) {
        egui::Frame::new().fill(Color32::from_rgb(17,27,35)).stroke(Stroke::new(1.0,BORDER))
            .inner_margin(8.0).show(ui, |ui| {
                ui.horizontal_wrapped(|ui| {
                    ui.label(RichText::new("SYNCHRONOUS COMPARISON").strong().color(BLUE));
                    ui.label(format!("{:?}{}",self.comparison_result.state, if self.running() {""} else {" · HELD"}));
                    ui.menu_button("Adjust", |ui| { self.comparison_controls(ui); });
                });
                let r = self.comparison_result.clone();
                let s = r.settings;
                ui.label(format!("REF CH {} / SIG CH {} · N {} × {} · Δf {:.3} Hz",s.reference_channel+1,s.response_channel+1,s.size,s.averages,r.bin_width_hz()));
                ui.horizontal_wrapped(|ui| {
                    ui.label("Read at");
                    ui.add(egui::DragValue::new(&mut self.comparison_frequency_hz).range(0.0..=r.nominal_sample_rate_hz as f64*0.5).speed(r.bin_width_hz()).suffix(" Hz"));
                    if let Some((k,b)) = r.bin_at(self.comparison_frequency_hz) {
                        let number = comparison_reading;
                        let ref_unit = self.calibration.captured.unit(s.reference_channel);
                        let sig_unit = self.calibration.captured.unit(s.response_channel);
                        let unit = if ref_unit==sig_unit {"ratio".into()} else {format!("{sig_unit}/{ref_unit}")};
                        ui.label(format!("Bin {k} ({:.3} Hz) · {:?}\nGain {} {} · phase {}° · coherence {}",k as f64*r.bin_width_hz(),b.state,number(b.gain),unit,number(b.phase_lead_degrees),number(b.coherence)));
                        ui.label(format!("Wrapped phase delay {} µs",number(b.phase_delay_seconds.map(|v|v*1e6))));
                    } else { ui.label("Waiting for a complete average; no valid reading"); }
                });
                if let Some(d) = &r.delay {
                    ui.label(format!("Linear phase slope: {:+.6} µs · {:.1}–{:.1} Hz · residual {:.6}° RMS",d.seconds*1e6,d.inclusive_bins[0] as f64*r.bin_width_hz(),d.inclusive_bins[1] as f64*r.bin_width_hz(),d.phase_residual_rms_degrees));
                } else { ui.label("Phase slope: — (needs ≥8 contiguous excited, coherent bins)"); }
                ui.label(RichText::new("Nominal Fs · CH phase/timing calibration unverified · phase delay wraps by 1/f").small().color(YELLOW));
                let h = ((ui.available_height()-42.0)/3.0).clamp(35.0,180.0);
                for plot in 0..3 { if let Some(hz) = comparison_plot(ui,&r,plot,h,self.comparison_frequency_hz) { self.comparison_frequency_hz=hz; } }
                ui.collapsing("Captured conditions", |ui| {
                    ui.label(format!("Input generation {} · analysis revision {} · {} Hz nominal · f64",r.generation,r.analysis_revision,r.nominal_sample_rate_hz));
                    ui.label(format!("Samples {}..{} · latest {}..{} · input end {}",r.sample_range.start,r.sample_range.end,r.latest_window.start,r.latest_window.end,r.input_end));
                    ui.label(format!("{} averaged windows · {} processed · {} missing · {} invalid samples",r.averaged_windows,r.processed_windows,r.missing_samples,r.invalid_samples));
                    ui.label(format!("{} · AC mean removed · disjoint arithmetic batches · REF floor {} FS²/Hz · coherence ≥{}",s.window.name(),s.reference_min_psd_fs2_hz,s.minimum_coherence));
                    ui.label("H1 = Pxy/Pxx. Scope, Spectrum and comparison each retain their own intervals. Slope fit assumes adjacent phase steps below π; periodic/wrapped data cannot determine absolute latency.");
                    for ch in [s.reference_channel,s.response_channel] { if let Some(c)=self.calibration.captured.get(ch) {ui.label(format!("CH {}: {} / revision {} · {} {} / FS",ch+1,c.id(),c.revision(),c.gain(),c.unit()));} }
                });
            });
    }
}
fn comparison_controls(ui: &mut egui::Ui, s: &mut comparison::Settings, channels: u16) {
    ui.checkbox(&mut s.enabled, "Analyze synchronous pair");
    ui.label("REFERENCE INPUT");
    channel_select(ui, "comparison_ref", &mut s.reference_channel, channels);
    ui.label("RESPONSE INPUT");
    channel_select(ui, "comparison_sig", &mut s.response_channel, channels);
    egui::ComboBox::from_id_salt("comparison_size")
        .selected_text(format!("{} samples", s.size))
        .show_ui(ui, |ui| {
            for n in comparison::SIZES {
                ui.selectable_value(&mut s.size, n, n.to_string());
            }
        });
    egui::ComboBox::from_id_salt("comparison_window")
        .selected_text(s.window.name())
        .show_ui(ui, |ui| {
            for w in [Window::Rectangular, Window::Hann, Window::BlackmanHarris] {
                ui.selectable_value(&mut s.window, w, w.name());
            }
        });
    ui.add(
        egui::DragValue::new(&mut s.averages)
            .range(2..=256)
            .prefix("Average windows "),
    );
    ui.add(
        egui::DragValue::new(&mut s.minimum_coherence)
            .range(0.0..=1.0)
            .speed(0.01)
            .prefix("Min coherence "),
    );
    ui.add(
        egui::DragValue::new(&mut s.reference_min_psd_fs2_hz)
            .range(1e-30..=1.0)
            .speed(1e-13)
            .max_decimals(20)
            .prefix("Min REF ")
            .suffix(" FS²/Hz"),
    );
    ui.add(
        egui::DragValue::new(&mut s.delay_band_hz[0])
            .range(0.0..=383999.0)
            .speed(10.0)
            .prefix("Slope from ")
            .suffix(" Hz"),
    );
    ui.add(
        egui::DragValue::new(&mut s.delay_band_hz[1])
            .range(1.0..=384000.0)
            .speed(10.0)
            .prefix("Slope to ")
            .suffix(" Hz"),
    );
}
fn comparison_plot(
    ui: &mut egui::Ui,
    r: &comparison::Result,
    plot: usize,
    height: f32,
    selected: f64,
) -> Option<f64> {
    let (rect, response) = ui.allocate_exact_size(
        vec2(ui.available_width(), height),
        egui::Sense::click_and_drag(),
    );
    let graph = egui::Rect::from_min_max(
        rect.left_top() + vec2(58.0, 18.0),
        rect.right_bottom() - vec2(8.0, 16.0),
    );
    if graph.width() <= 0.0 || graph.height() <= 0.0 {
        return None;
    }
    let painter = ui.painter().with_clip_rect(rect.intersect(ui.clip_rect()));
    let (title, min, max, color) = match plot {
        0 => ("Gain dB", -60.0, 20.0, GREEN),
        1 => ("Phase °", -180.0, 180.0, BLUE),
        _ => ("γ²", 0.0, 1.0, YELLOW),
    };
    painter.text(
        rect.left_top(),
        egui::Align2::LEFT_TOP,
        title,
        egui::FontId::monospace(10.0),
        color,
    );
    let font = egui::FontId::monospace(9.0);
    for i in 0..=4 {
        if (graph.height() < 60.0 && matches!(i, 1 | 3)) || (graph.height() < 30.0 && i == 2) {
            continue;
        }
        let y = graph.top() + graph.height() * i as f32 / 4.0;
        painter.line_segment(
            [pos2(graph.left(), y), pos2(graph.right(), y)],
            Stroke::new(1.0, BORDER),
        );
        painter.text(
            pos2(graph.left() - 3.0, y),
            egui::Align2::RIGHT_CENTER,
            if plot == 2 {
                format!("{:.2}", max - (max - min) * i as f64 / 4.0)
            } else {
                format!("{:.0}", max - (max - min) * i as f64 / 4.0)
            },
            font.clone(),
            MUTED,
        );
    }
    let rate = r.nominal_sample_rate_hz as f64;
    let project = |k: usize, v: f64| {
        pos2(
            graph.left() + graph.width() * k as f32 / (r.settings.size / 2) as f32,
            graph.bottom() - graph.height() * ((v - min) / (max - min)).clamp(0.0, 1.0) as f32,
        )
    };
    let mut previous: Option<(egui::Pos2, f64)> = None;
    for (k, b) in r.bins.iter().enumerate() {
        let value = match plot {
            0 => b.gain.filter(|v| *v > 0.0).map(|v| 20.0 * v.log10()),
            1 => b.phase_lead_degrees,
            _ => b.coherence,
        };
        if let Some(value) = value {
            let point = project(k, value);
            if let Some((old, old_value)) = previous
                && !(plot == 1 && (value - old_value).abs() > 180.0)
            {
                painter.line_segment([old, point], Stroke::new(1.5, color));
            }
            painter.circle_filled(point, 1.5, color);
            previous = Some((point, value));
        } else {
            previous = None;
        }
    }
    let x = graph.left() + graph.width() * (selected / (rate * 0.5)).clamp(0.0, 1.0) as f32;
    painter.line_segment(
        [pos2(x, graph.top()), pos2(x, graph.bottom())],
        Stroke::new(1.0, MUTED),
    );
    painter.text(
        pos2(graph.left(), rect.bottom()),
        egui::Align2::LEFT_BOTTOM,
        "0 Hz",
        font.clone(),
        MUTED,
    );
    painter.text(
        pos2(graph.right(), rect.bottom()),
        egui::Align2::RIGHT_BOTTOM,
        format!("{:.0} Hz", rate * 0.5),
        font,
        MUTED,
    );
    if (response.clicked() || response.dragged())
        && let Some(pos) = response.interact_pointer_pos()
    {
        return Some(((pos.x - graph.left()) / graph.width()).clamp(0.0, 1.0) as f64 * rate * 0.5);
    }
    None
}

fn comparison_reading(value: Option<f64>) -> String {
    value.filter(|v| v.is_finite()).map_or("—".into(), |v| {
        if v != 0.0 && !(1e-4..1e6).contains(&v.abs()) {
            format!("{v:.6e}")
        } else {
            format!("{v:.6}")
        }
    })
}
#[cfg(test)]
mod tests {
    #[test]
    fn comparison_readout_preserves_weak_values_and_invalid_state() {
        use super::comparison_reading as read;
        assert_eq!(read(Some(1e-12)), "1.000000e-12");
        assert_eq!(read(Some(-1e-7)), "-1.000000e-7");
        assert_eq!(read(Some(0.0)), "0.000000");
        assert_eq!(read(Some(0.5)), "0.500000");
        assert_eq!(read(None), "—");
        assert_eq!(read(Some(f64::NAN)), "—");
    }
}
