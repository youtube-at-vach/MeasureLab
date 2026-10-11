use super::*;

impl ScopeApp {
    #[cfg(feature = "qa")]
    pub(super) fn check_stage3f(&mut self) -> Result<(), String> {
        self.poll_audio();
        self.source = Source::Software;
        self.core = Some(measurement::Worker::new(self.stft.take_feeder()));
        self.loopback_settings = loopback::Settings {
            frequency_hz: 750.0,
            ..Default::default()
        };
        self.lockin_settings = lockin::Settings {
            enabled: true,
            frequency_hz: 750.0,
            ..Default::default()
        };
        self.acquisition_mode = acquisition::Mode::Auto;
        self.spectrum_settings.size = 8192;
        self.spectrum_settings.averages = 1;
        self.spectrum_channel = 1;
        self.scope_channels = Pair([0, 1]);
        self.ms_per_div = 1.0;
        let replay = std::env::var_os("MEASURELAB_UI_SMOKE_REPLAY").is_some();
        if replay {
            self.reference = Some(Box::new(crate::results::load(std::path::Path::new(
                "dist/stage3f-results.json",
            ))?));
            self.reference_label = "Reference loaded after application restart".into();
            self.restore_settings(settings::load(std::path::Path::new(
                "dist/stage3f-settings.json",
            ))?)?;
            assert!(!self.running());
        }
        for run in 0..if replay { 1 } else { 2 } {
            self.start();
            let deadline = Instant::now() + Duration::from_secs(5);
            while self
                .core
                .as_ref()
                .unwrap()
                .metrics
                .input_frames
                .load(Ordering::Relaxed)
                < (run + 1) * 48000
            {
                if Instant::now() > deadline {
                    return Err("Software input timed out".into());
                }
                self.poll_measurement();
                std::thread::sleep(Duration::from_millis(5));
            }
            self.stop();
            let mut snapshot = self.pending_stop.take().unwrap().wait();
            self.accept_snapshot(&mut snapshot);
            let doc = self.capture_results()?;
            doc.validate()?;
            assert_eq!(self.lockin_result.state, lockin::State::Valid);
            assert!((self.lockin_result.amplitude_peak.unwrap() - 0.0625).abs() < 1e-8);
            assert!((self.lockin_result.phase_degrees.unwrap() - 30.0).abs() < 1e-6);
            assert!((self.analyzer.power()[128].sqrt() - 0.0625).abs() < 1e-10);
            if run == 0 && !replay {
                std::fs::create_dir_all("dist").map_err(|e| e.to_string())?;
                let settings = self.capture_settings()?;
                settings::save(
                    std::path::Path::new("dist/stage3f-settings.json"),
                    &settings,
                )?;
                export::save(std::path::Path::new("dist/stage3f-results.json"), &doc)?;
                crate::results::save_csv(std::path::Path::new("dist/stage3f-results.csv"), &doc)?;
                crate::result_image::save(std::path::Path::new("dist/stage3f-results.png"), &doc)?;
                self.reference = Some(Box::new(crate::results::load(std::path::Path::new(
                    "dist/stage3f-results.json",
                ))?));
                self.reference_label =
                    "Saved software measurement before restore / remeasure".into();
                let epoch = self.input_generation;
                self.spectrum_settings.size = 1024;
                self.scope_channels = Pair([15, 7]);
                self.restore_settings(settings::load(std::path::Path::new(
                    "dist/stage3f-settings.json",
                ))?)?;
                assert!(!self.running());
                assert_eq!(self.input_generation, epoch);
                assert_eq!(self.scope_channels, Pair([0, 1]));
                assert_eq!(*self.reference.as_ref().unwrap().as_ref(), doc);
            } else {
                let old = self.reference.as_ref().unwrap();
                if !replay {
                    assert_ne!(doc.input.generation, old.input.generation);
                }
                for (a, b) in old.scope.traces.iter().zip(&doc.scope.traces) {
                    assert_eq!(a.channel, b.channel);
                    assert!(
                        (a.raw_statistics.values.as_ref().unwrap().rms
                            - b.raw_statistics.values.as_ref().unwrap().rms)
                            .abs()
                            < 1e-10
                    );
                }
                assert!(
                    (old.spectrum.values.as_ref().unwrap()[128]
                        - doc.spectrum.values.as_ref().unwrap()[128])
                        .abs()
                        < 1e-10
                );
            }
        }
        // Single uses the same source but ends before the 512k FFT is filled.
        self.acquisition_mode = acquisition::Mode::Single;
        self.spectrum_settings.size = 524288;
        self.start();
        let deadline = Instant::now() + Duration::from_secs(5);
        while !self
            .core
            .as_ref()
            .unwrap()
            .metrics
            .single_complete
            .load(Ordering::Acquire)
        {
            if Instant::now() > deadline {
                return Err("Single trigger timed out".into());
            }
            std::thread::sleep(Duration::from_millis(2));
        }
        self.stop();
        let mut snapshot = self.pending_stop.take().unwrap().wait();
        self.accept_snapshot(&mut snapshot);
        assert_eq!(self.acquisition_state, acquisition::State::Complete);
        assert_eq!(self.scope_range.end - self.scope_range.start, 480);
        assert!(!self.analyzer.is_ready());
        assert_eq!(self.scope_missing, 0);
        self.capture_results()?.validate()?;
        self.visible = [true, true, false, false];
        self.sidebar.section = Some(SettingsSection::Scope);
        if std::env::var_os("MEASURELAB_UI_SMOKE_COMPARE").is_some() {
            self.compare_open = true;
        }
        println!(
            "Stage 3f virtual UI QA OK: software common input; settings/results JSON save-load-restore-remeasure; reference retains conditions; CSV/PNG; Single exact finite capture with unfilled 512k; experimental Lock-in amplitude/phase matches theory (physical use unverified)"
        );
        self.created = Instant::now();
        Ok(())
    }
    pub(super) fn software_controls(&mut self, ui: &mut egui::Ui) {
        setting_label(ui, "SOFTWARE LOOPBACK · CH 1 REF / CH 2 DUT");
        ui.label(RichText::new("Known sine → gain / phase / delay / noise DUT → common input. Conditions apply on Start.").small().color(MUTED));
        egui::ComboBox::from_id_salt("software_rate")
            .selected_text(format!(
                "{} Hz",
                self.requested_sample_rate.unwrap_or(48000)
            ))
            .show_ui(ui, |ui| {
                for rate in [44100, 48000, 96000, 192000] {
                    ui.selectable_value(
                        &mut self.requested_sample_rate,
                        Some(rate),
                        format!("{rate} Hz"),
                    );
                }
            });
        let s = &mut self.loopback_settings;
        ui.add(
            egui::DragValue::new(&mut s.frequency_hz)
                .range(10.0..=80000.0)
                .prefix("Frequency Hz "),
        );
        ui.add(
            egui::DragValue::new(&mut s.amplitude_peak)
                .range(0.0..=1.0)
                .speed(0.001)
                .prefix("Reference peak FS "),
        );
        ui.add(
            egui::DragValue::new(&mut s.gain)
                .range(-100.0..=100.0)
                .speed(0.01)
                .prefix("DUT gain "),
        );
        ui.add(
            egui::DragValue::new(&mut s.phase_degrees)
                .speed(1.0)
                .prefix("Phase lead ° "),
        );
        ui.add(
            egui::DragValue::new(&mut s.delay_samples)
                .range(0..=384000)
                .prefix("Delay samples "),
        );
        ui.add(
            egui::DragValue::new(&mut s.dc_offset)
                .speed(0.001)
                .prefix("DUT DC FS "),
        );
        ui.add(
            egui::DragValue::new(&mut s.noise_rms)
                .range(0.0..=1.0)
                .speed(0.00001)
                .prefix("Noise RMS FS "),
        );
        ui.add(
            egui::DragValue::new(&mut s.frequency_offset_hz)
                .speed(0.1)
                .prefix("DUT frequency offset Hz "),
        );
        ui.checkbox(&mut s.reference_enabled, "Reference present");
    }

    pub(super) fn file_menu(&mut self, ui: &mut egui::Ui) {
        ui.menu_button("File", |ui| {
            ui.add_enabled_ui(!self.workspace_pending, |ui| {
                if ui.button("Save settings…").clicked() {
                    match self.capture_settings() {
                        Ok(doc) => {
                            self.submit_workspace(workspace_io::Task::SaveSettings(Box::new(doc)))
                        }
                        Err(e) => self.workspace_status = Some(e),
                    }
                    ui.close();
                }
                if ui
                    .add_enabled(
                        self.can_restore_settings(),
                        egui::Button::new("Restore settings…"),
                    )
                    .clicked()
                {
                    self.submit_workspace(workspace_io::Task::RestoreSettings);
                    ui.close();
                }
                ui.separator();
                if ui.button("Load reference result…").clicked() {
                    self.submit_workspace(workspace_io::Task::LoadResult);
                    ui.close();
                }
                if ui
                    .add_enabled(
                        self.can_export(),
                        egui::Button::new("Keep held result as reference"),
                    )
                    .clicked()
                {
                    match self.capture_results() {
                        Ok(doc) => {
                            self.reference = Some(Box::new(doc));
                            self.reference_label = "Previous held result".into();
                            self.comparison_current = None;
                            self.compare_open = true;
                        }
                        Err(e) => self.workspace_status = Some(e),
                    }
                    ui.close();
                }
                for (label, format) in [
                    ("Save held result JSON…", workspace_io::Format::Json),
                    ("Export held result CSV…", workspace_io::Format::Csv),
                    ("Export annotated PNG…", workspace_io::Format::Png),
                ] {
                    if ui
                        .add_enabled(self.can_export(), egui::Button::new(label))
                        .clicked()
                    {
                        match self.capture_results() {
                            Ok(doc) => self.submit_workspace(workspace_io::Task::SaveResult(
                                Box::new(doc),
                                format,
                            )),
                            Err(e) => self.workspace_status = Some(e),
                        }
                        ui.close();
                    }
                }
            });
            if ui
                .add_enabled(
                    self.reference.is_some(),
                    egui::Button::new("Compare reference"),
                )
                .clicked()
            {
                self.comparison_current = None;
                self.compare_open = true;
                ui.close();
            }
            if ui
                .add_enabled(
                    self.reference.is_some(),
                    egui::Button::new("Clear reference"),
                )
                .clicked()
            {
                self.reference = None;
                self.compare_open = false;
            }
            if let Some(status) = &self.workspace_status {
                ui.separator();
                ui.label(status);
            }
        });
    }

    fn submit_workspace(&mut self, task: workspace_io::Task) {
        let restore = matches!(task, workspace_io::Task::RestoreSettings);
        match self.workspace_io.submit(task) {
            Ok(()) => {
                self.workspace_pending = true;
                self.workspace_restoring = restore;
                self.workspace_status = Some("Selecting file…".into());
            }
            Err(e) => self.workspace_status = Some(e),
        }
    }
    pub(super) fn poll_workspace(&mut self) {
        while let Ok(event) = self.workspace_io.events.try_recv() {
            self.workspace_pending = false;
            self.workspace_restoring = false;
            self.workspace_status = Some(match event {
                workspace_io::Event::Saved(path) => format!("Saved {}", path.display()),
                workspace_io::Event::Cancelled => "File selection cancelled".into(),
                workspace_io::Event::Error(e) => e,
                workspace_io::Event::Settings(doc) => match self.restore_settings(*doc) {
                    Ok(()) => "Settings restored; input stopped".into(),
                    Err(e) => e,
                },
                workspace_io::Event::Reference(doc, path) => {
                    self.reference = Some(doc);
                    self.reference_label = path.display().to_string();
                    self.comparison_current = None;
                    self.compare_open = true;
                    "Reference loaded; captured input conditions preserved".into()
                }
            });
        }
    }

    pub(super) fn compare_window(&mut self, ctx: &egui::Context) {
        if !self.compare_open {
            return;
        }
        if self.comparison_current.is_none() {
            self.comparison_current = self.capture_results().ok().map(Box::new);
        }
        let current = &self.comparison_current;
        let mut open = self.compare_open;
        egui::Window::new("Reference comparison").open(&mut open).default_size(vec2(930.0,680.0)).show(ctx,|ui| {
            ui.label(RichText::new(&self.reference_label).small().color(MUTED));
            ui.label("One reference is retained. Recordings use independent sample-clock origins; plots are shown separately.");
            egui::ScrollArea::vertical().show(ui,|ui| {
                if let Some(reference)=&self.reference {
                    ui.columns(2,|cols| {
                        cols[0].heading("Reference");result_summary(&mut cols[0],reference);
                        cols[1].heading("Current held result");
                        if let Some(current)=&current {result_summary(&mut cols[1],current);}else{cols[1].label("Stop input to compare the current result.");}
                    });
                    if let Some(current)=&current {
                        ui.separator();
                        for (i,(a,b)) in reference.scope.traces.iter().zip(&current.scope.traces).enumerate() {
                            if a.channel==b.channel && a.calibrated_statistics.unit==b.calibrated_statistics.unit {
                                if let (Some(a),Some(b))=(&a.calibrated_statistics.values,&b.calibrated_statistics.values) {
                                    ui.label(format!("Trace {}: current − reference RMS {:.9e} (each result's own interval)",i+1,b.rms-a.rms));
                                }
                            }else{ui.label(format!("Trace {} differs in channel/unit; no numeric difference",i+1));}
                        }
                        if reference.spectrum.settings!=current.spectrum.settings || reference.spectrum.mode!=current.spectrum.mode || reference.spectrum.unit!=current.spectrum.unit || reference.spectrum.channel!=current.spectrum.channel || reference.input.nominal_sample_rate_hz!=current.input.nominal_sample_rate_hz {
                            ui.label("Spectrum definitions differ; inspect each result's bins and band independently.");
                        }else if let (Some(a),Some(b))=(&reference.spectrum.band,&current.spectrum.band)
                            && a.inclusive_bins==b.inclusive_bins && a.power_unit==b.power_unit {
                            ui.label(format!("PSD band power current − reference: {:.9e} {}",b.power-a.power,b.power_unit));
                        }
                    }
                }
            });
        });
        self.compare_open = open;
    }
}

fn result_summary(ui: &mut egui::Ui, doc: &export::Document) {
    ui.label(format!(
        "Generation {} | nominal {} Hz | {}ch",
        doc.input.generation, doc.input.nominal_sample_rate_hz, doc.input.channels
    ));
    match &doc.input.source {
        export::Source::Audio {
            device_name,
            sample_format,
            ..
        } => {
            ui.label(format!("Input {device_name} | {sample_format}"));
        }
        export::Source::InternalQa { description } => {
            ui.label(description);
        }
        export::Source::SoftwareLoopback { settings: s } => {
            ui.label(format!(
                "Software Loopback | {:.6} Hz | REF {:.9e} FS peak",
                s.frequency_hz, s.amplitude_peak
            ));
            ui.label(format!(
                "DUT gain {} | phase {}° | delay {} samples",
                s.gain, s.phase_degrees, s.delay_samples
            ));
            ui.label(format!(
                "DC {} FS | noise RMS {} FS | frequency offset {} Hz | REF {}",
                s.dc_offset,
                s.noise_rms,
                s.frequency_offset_hz,
                if s.reference_enabled {
                    "enabled"
                } else {
                    "disabled"
                }
            ));
        }
    }
    ui.label(format!(
        "Scope [{}, {}) | {:?} | trigger CH {} {:?} at {} FS",
        doc.scope.sample_range.start,
        doc.scope.sample_range.end,
        doc.scope.acquisition_mode,
        doc.scope.trigger.channel + 1,
        doc.scope.trigger.edge,
        doc.scope.trigger.level
    ));
    for (i, t) in doc.scope.traces.iter().enumerate() {
        ui.label(format!(
            "Trace {} CH {} {:?} | {}",
            i + 1,
            t.channel + 1,
            t.state,
            t.calibrated_statistics.unit
        ));
        if let Some(v) = &t.calibrated_statistics.values {
            ui.monospace(format!(
                "RMS {:.9e}\nPeak {:.9e}\nP-P {:.9e}",
                v.rms, v.peak, v.peak_to_peak
            ));
        }
        ui.label(t.calibration.as_ref().map_or("Uncalibrated".into(), |c| {
            format!(
                "Calibration {} rev {} | gain {} offset {} | {}",
                c.id, c.revision, c.gain, c.offset, c.conditions
            )
        }));
        if let Some(samples) = &t.raw_samples_fs {
            reference_plot(
                ui,
                samples.iter().copied(),
                samples.len(),
                false,
                "Raw Scope FS · relative sample position",
            );
        }
    }
    let s = &doc.spectrum;
    ui.label(format!(
        "Spectrum {:?} | CH {}\n{} | {} points | {}\n{:?} | DC removal {} | {}",
        s.state,
        s.channel
            .map_or("unavailable".into(), |c| (c + 1).to_string()),
        s.latest_window
            .as_ref()
            .map_or("No complete FFT window".into(), |w| format!(
                "Window [{}, {})",
                w.start, w.end
            )),
        s.settings.size,
        s.settings.window.name(),
        s.mode,
        s.settings.remove_dc,
        s.unit
    ));
    ui.label(format!(
        "Δf {:.9} Hz | RBW {:.9} Hz",
        s.bin_width_hz, s.rbw_hz
    ));
    if let Some(a) = &s.average {
        ui.label(format!(
            "EMA α {:.9} | {} windows | envelope [{}, {})",
            a.alpha,
            a.processed_windows,
            a.contributing_envelope.start,
            a.contributing_envelope.end
        ));
    }
    ui.label(s.calibration.as_ref().map_or("Uncalibrated".into(), |c| {
        format!(
            "Calibration {} rev {} | gain {} offset {} {} | {}",
            c.id, c.revision, c.gain, c.offset, c.unit, c.conditions
        )
    }));
    if let Some(v) = &s.values {
        reference_plot(
            ui,
            v.iter().copied().map(Some),
            v.len(),
            true,
            "Spectrum linear values · bin position",
        );
    }
    if let Some(b) = &s.band {
        ui.label(format!(
            "Band {:?} Hz | power {:.9e} {} | RMS {:.9e} {}",
            b.bin_centres_hz, b.power, b.power_unit, b.rms, b.rms_unit
        ));
    }
    ui.label(format!(
        "Loss: capture {} | Scope {} | FFT input {}\nFFT windows: missing {} | nonfinite {} | observed {}\nInput end {} | filled {} | input failed {}",
        doc.loss.capture_dropped_samples,doc.loss.scope_missing_samples,s.diagnostics.missing_input_samples,
        s.diagnostics.missing_windows,s.diagnostics.nonfinite_windows,s.diagnostics.processed_windows_since_reset,
        s.diagnostics.input_end,s.diagnostics.filled_samples,doc.loss.input_failed
    ));
}

fn reference_plot(
    ui: &mut egui::Ui,
    values: impl Iterator<Item = Option<f64>>,
    count: usize,
    positive: bool,
    title: &str,
) {
    ui.label(RichText::new(title).small());
    let (rect, _) = ui.allocate_exact_size(vec2(ui.available_width(), 100.0), egui::Sense::hover());
    ui.painter()
        .rect_filled(rect, 0.0, Color32::from_rgb(17, 27, 35));
    let width = rect.width().ceil().max(1.0) as usize;
    let mut buckets = vec![(f64::INFINITY, f64::NEG_INFINITY); width];
    let mut max = 1e-15_f64;
    for (i, v) in values.enumerate() {
        if let Some(v) = v {
            let b = &mut buckets[(i * width / count.max(1)).min(width - 1)];
            b.0 = b.0.min(v);
            b.1 = b.1.max(v);
            max = max.max(v.abs());
        }
    }
    let min = if positive { 0.0 } else { -max };
    for (i, (lo, hi)) in buckets.into_iter().enumerate() {
        if lo <= hi {
            let y = |v: f64| rect.bottom() - ((v - min) / (max - min)) as f32 * rect.height();
            let x = rect.left() + i as f32;
            ui.painter()
                .line_segment([pos2(x, y(lo)), pos2(x, y(hi))], Stroke::new(1.0, GREEN));
        }
    }
}
