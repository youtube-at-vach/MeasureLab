use super::*;
#[cfg(feature = "qa")]
use crate::audio;

impl ScopeApp {
    #[cfg(feature = "qa")]
    pub(super) fn check_stage3f(&mut self) -> Result<(), String> {
        let restore = if let Some(name) = std::env::var("MEASURELAB_UI_SMOKE_BLACKHOLE")
            .ok()
            .or_else(|| std::env::var("MEASURELAB_UI_SMOKE_PHYSICAL").ok())
        {
            if !["BlackHole 2ch", "BlackHole 16ch", "ZOOM UAC-232"].contains(&name.as_str()) {
                return Err("Result reuse QA requires BlackHole 2ch/16ch or ZOOM UAC-232".into());
            }
            use cpal::traits::DeviceTrait;
            let device = audio::input_device(Some(&name))?;
            let rate = device
                .default_input_config()
                .map_err(|e| e.to_string())?
                .sample_rate();
            Some((device, rate))
        } else {
            None
        };
        let result = self.check_stage3f_results();
        if let Some((device, rate)) = restore {
            self.stop();
            if let Some(pending) = self.pending_stop.take() {
                let mut snapshot = pending.wait();
                self.accept_snapshot(&mut snapshot);
            }
            self.qa_wait_audio_idle()?;
            let (stream, _) = audio::start_device(&device, Some(rate))?;
            drop(stream);
            println!("Application QA nominal rate restored to {rate} Hz");
        }
        result
    }

    #[cfg(feature = "qa")]
    fn check_stage3f_results(&mut self) -> Result<(), String> {
        self.poll_audio();
        let blackhole = std::env::var("MEASURELAB_UI_SMOKE_BLACKHOLE").ok();
        let physical = std::env::var("MEASURELAB_UI_SMOKE_PHYSICAL").ok();
        if physical.as_deref().is_some_and(|n| n != "ZOOM UAC-232") {
            return Err("Physical application QA requires ZOOM UAC-232".into());
        }
        if physical.is_some() && blackhole.is_some() {
            return Err("Choose one application QA input".into());
        }
        let external = blackhole.as_ref().or(physical.as_ref());
        let deadline = Instant::now() + Duration::from_secs(5);
        while external.is_some() && self.devices.is_empty() {
            if Instant::now() > deadline {
                return Err("BlackHole device enumeration timed out".into());
            }
            self.poll_audio();
            std::thread::sleep(Duration::from_millis(5));
        }
        let fixture = blackhole
            .as_ref()
            .map(|name| crate::qa::lockin::Fixture::new(name, 48000))
            .transpose()?;
        let physical_fixture = physical
            .as_ref()
            .map(|name| crate::qa::output::Fixture::new(name, Some(48000), true))
            .transpose()?;
        self.source = if external.is_some() {
            Source::Live
        } else {
            Source::Software
        };
        let response_channel = if let Some(name) = external {
            self.selected = self
                .devices
                .iter()
                .position(|d| &d.name == name)
                .ok_or("BlackHole device was not found")?;
            self.requested_sample_rate = Some(48000);
            if physical.is_some() {
                0
            } else {
                self.devices[self.selected].channels as usize - 1
            }
        } else {
            1
        };
        let expected_phase = if blackhole.is_some() { 13.125 } else { 30.0 };
        let phase_tolerance = if blackhole.is_some() { 1e-4 } else { 1e-6 };
        let fft_tolerance = if blackhole.is_some() { 1e-8 } else { 1e-10 };
        let stem = if physical.is_some() {
            "dist/stage4b-physical".to_string()
        } else if blackhole.is_some() {
            format!("dist/stage4b-{}ch", response_channel + 1)
        } else {
            "dist/stage3f".to_string()
        };
        self.core = Some(measurement::Worker::new(self.stft.take_feeder()));
        self.loopback_settings = loopback::Settings {
            frequency_hz: 750.0,
            ..Default::default()
        };
        self.lockin_settings = lockin::Settings {
            enabled: true,
            frequency_hz: if physical.is_some() { 1000.0 } else { 750.0 },
            reference_channel: usize::from(physical.is_some()),
            response_channel,
            ..Default::default()
        };
        self.acquisition_mode = acquisition::Mode::Auto;
        self.spectrum_settings.size = 8192;
        self.spectrum_settings.averages = 1;
        self.spectrum_channel = response_channel;
        self.scope_channels =
            Pair([self.lockin_settings.reference_channel, response_channel]).scope();
        self.ms_per_div = 1.0;
        let replay = std::env::var_os("MEASURELAB_UI_SMOKE_REPLAY").is_some();
        if replay {
            self.reference = Some(Box::new(crate::results::load(std::path::Path::new(
                &format!("{stem}-results.json"),
            ))?));
            self.reference_label = "Reference loaded after application restart".into();
            self.restore_settings(settings::load(std::path::Path::new(&format!(
                "{stem}-settings.json"
            )))?)?;
            assert!(!self.running());
        }
        for run in 0..if replay { 1 } else { 2 } {
            if let Some(f) = &physical_fixture {
                f.start()?;
            }
            self.start();
            if fixture.is_some() || physical_fixture.is_some() {
                // Poll stream creation before the bounded attachment warm-up.
                self.qa_wait_audio_idle()?;
                std::thread::sleep(Duration::from_millis(500));
                if let Some(fixture) = &fixture {
                    fixture.end_warmup("application Start");
                }
                self.core
                    .as_ref()
                    .unwrap()
                    .configure_lockin(self.lockin_settings);
            }
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
                self.poll_audio();
                if let Some(error) = &self.error {
                    return Err(error.clone());
                }
                if Instant::now() > deadline {
                    return Err("QA input timed out".into());
                }
                self.poll_measurement();
                std::thread::sleep(Duration::from_millis(5));
            }
            self.stop();
            let mut snapshot = self.pending_stop.take().unwrap().wait();
            if physical.is_some() {
                crate::qa::physical_lockin::validate_gui(&snapshot)?;
            }
            self.accept_snapshot(&mut snapshot);
            self.qa_wait_audio_idle()?;
            let doc = self.capture_results()?;
            doc.validate()?;
            assert_eq!(doc.lockin.as_ref().unwrap().result, self.lockin_result);
            assert_eq!(self.lockin_result.state, lockin::State::Valid);
            if physical.is_none() {
                assert!((self.lockin_result.amplitude_peak.unwrap() - 0.0625).abs() < 1e-8);
                assert!(
                    (self.lockin_result.phase_degrees.unwrap() - expected_phase).abs()
                        < phase_tolerance
                );
                assert!((self.analyzer.power()[128].sqrt() - 0.0625).abs() < fft_tolerance);
            }
            if let Some(f) = &physical_fixture {
                f.check()?;
            }
            if let Some(fixture) = &fixture
                && fixture.failed.load(Ordering::Relaxed)
            {
                return Err("BlackHole output error during application capture".into());
            }
            assert_eq!(doc.loss.capture_dropped_samples, 0);
            assert!(!doc.loss.input_failed);
            if run == 0 && !replay {
                std::fs::create_dir_all("dist").map_err(|e| e.to_string())?;
                let settings = self.capture_settings()?;
                settings::save(
                    std::path::Path::new(&format!("{stem}-settings.json")),
                    &settings,
                )?;
                export::save(std::path::Path::new(&format!("{stem}-results.json")), &doc)?;
                crate::results::save_csv(
                    std::path::Path::new(&format!("{stem}-results.csv")),
                    &doc,
                )?;
                crate::result_image::save(
                    std::path::Path::new(&format!("{stem}-results.png")),
                    &doc,
                )?;
                self.reference = Some(Box::new(crate::results::load(std::path::Path::new(
                    &format!("{stem}-results.json"),
                ))?));
                self.reference_label = if physical.is_some() {
                    "Saved physical measurement before restore / remeasure"
                } else if blackhole.is_some() {
                    "Saved BlackHole measurement before restore / remeasure"
                } else {
                    "Saved software measurement before restore / remeasure"
                }
                .into();
                let epoch = self.input_generation;
                self.spectrum_settings.size = 1024;
                self.scope_channels = Pair([15, 7]).scope();
                self.lockin_settings.time_constant_seconds = 0.1;
                self.lockin_settings.reference_channel = 1;
                self.requested_sample_rate = Some(96000);
                self.calibration.pending = self
                    .calibration
                    .pending
                    .clone()
                    .with(
                        response_channel,
                        Some(
                            calibration::Calibration::new(
                                "next-start-qa".into(),
                                2,
                                4.0,
                                0.5,
                                "V".into(),
                                "Pending condition must not relabel held results".into(),
                            )
                            .unwrap(),
                        ),
                    )
                    .unwrap();
                let after_edit = self.capture_results()?;
                assert_eq!(after_edit.input, doc.input);
                assert_eq!(after_edit.lockin, doc.lockin);
                self.restore_settings(settings::load(std::path::Path::new(&format!(
                    "{stem}-settings.json"
                )))?)?;
                assert!(!self.running());
                assert_eq!(self.input_generation, epoch);
                assert_eq!(
                    self.scope_channels,
                    Pair([self.lockin_settings.reference_channel, response_channel]).scope()
                );
                assert_eq!(
                    self.lockin_settings,
                    doc.lockin.as_ref().unwrap().result.settings
                );
                assert_eq!(self.capture_results()?.lockin, doc.lockin);
                assert_eq!(*self.reference.as_ref().unwrap().as_ref(), doc);
            } else {
                let old = self.reference.as_ref().unwrap();
                if !replay {
                    assert_ne!(doc.input.generation, old.input.generation);
                }
                for (a, b) in old.scope.traces.iter().zip(&doc.scope.traces) {
                    assert_eq!(a.channel, b.channel);
                    if a.channel >= doc.input.channels {
                        assert_eq!(a.state, export::State::Unavailable);
                        assert_eq!(b.state, export::State::Unavailable);
                        assert!(a.raw_statistics.values.is_none());
                        assert!(b.raw_statistics.values.is_none());
                        assert!(a.raw_samples_fs.is_none());
                        assert!(b.raw_samples_fs.is_none());
                        continue;
                    }
                    assert!(
                        (a.raw_statistics.values.as_ref().unwrap().rms
                            - b.raw_statistics.values.as_ref().unwrap().rms)
                            .abs()
                            < if external.is_some() { 0.01 } else { 1e-10 }
                    );
                }
                if physical.is_none() {
                    assert!(
                        (old.spectrum.values.as_ref().unwrap()[128]
                            - doc.spectrum.values.as_ref().unwrap()[128])
                            .abs()
                            < fft_tolerance
                    );
                }
                let difference = crate::results::lockin_difference(old, &doc)
                    .ok_or("Remeasured Lock-in conditions no longer match saved reference")?;
                if physical.is_some() {
                    assert!(
                        difference.amplitude_peak.abs()
                            < old.lockin.as_ref().unwrap().result.amplitude_peak.unwrap() * 0.01
                                + 2e-6
                    );
                    assert!(difference.phase_degrees.abs() < 0.1);
                } else {
                    assert!(difference.x.abs() < 1e-8);
                    assert!(difference.y.abs() < 1e-8);
                    assert!(difference.amplitude_peak.abs() < 1e-8);
                    assert!(difference.phase_degrees.abs() < phase_tolerance);
                    assert!(difference.gain.abs() < 1e-7);
                }
                self.comparison_current = Some(Box::new(doc));
            }
        }
        // External Single checks raw finite capture, not detector settling.
        if external.is_none() || std::env::var_os("MEASURELAB_UI_SMOKE_EXTERNAL_SINGLE").is_some() {
            // Physical/virtual I/O is armed on an already healthy stream. A
            // new device connection can itself contain a real transient.
            self.acquisition_mode = if external.is_some() {
                acquisition::Mode::Auto
            } else {
                acquisition::Mode::Single
            };
            self.spectrum_settings.size = 524288;
            if external.is_some() {
                self.lockin_settings.time_constant_seconds = 1.0;
            }
            if let Some(f) = &physical_fixture {
                f.start()?;
            }
            if let Some(f) = &fixture {
                f.end_warmup("before Single attachment");
            }
            self.start();
            if external.is_some() {
                self.qa_wait_audio_idle()?;
                std::thread::sleep(Duration::from_millis(500));
                self.poll_measurement();
                if let Some(error) = &self.error {
                    return Err(error.clone());
                }
                if let Some(f) = &fixture {
                    f.end_warmup("Auto before Single arm");
                }
                self.acquisition_mode = acquisition::Mode::Single;
                let mut snapshot = self.core.as_ref().unwrap().scope(self.core_config().scope);
                self.accept_snapshot(&mut snapshot);
            }
            let deadline = Instant::now() + Duration::from_secs(5);
            while !self
                .core
                .as_ref()
                .unwrap()
                .metrics
                .single_complete
                .load(Ordering::Acquire)
            {
                self.poll_audio();
                if Instant::now() > deadline {
                    return Err("Single trigger timed out".into());
                }
                std::thread::sleep(Duration::from_millis(2));
            }
            self.stop();
            let mut snapshot = self.pending_stop.take().unwrap().wait();
            if external.is_some() {
                let document = crate::qa::lockin::document(
                    &snapshot,
                    self.held_input.clone().unwrap(),
                    self.core.as_ref().unwrap(),
                )?;
                export::save(
                    std::path::Path::new(&format!("{stem}-single.json")),
                    &document,
                )?;
                crate::qa::physical_lockin::validate_single(
                    &snapshot,
                    self.reference.as_ref().unwrap(),
                )?;
            }
            self.accept_snapshot(&mut snapshot);
            self.qa_wait_audio_idle()?;
            assert_eq!(self.acquisition_state, acquisition::State::Complete);
            assert_eq!(self.scope_range.end - self.scope_range.start, 480);
            assert!(!self.analyzer.is_ready());
            assert_eq!(self.scope_missing, 0);
            let single = self.capture_results()?;
            single.validate()?;
            assert_eq!(
                single.lockin.as_ref().unwrap().result.state,
                lockin::State::Settling
            );
            if external.is_none() {
                assert!(single.lockin.as_ref().unwrap().result.x.is_none());
            }
            export::save(
                std::path::Path::new(&format!("{stem}-single.json")),
                &single,
            )?;
        }
        self.select_view([true, true, false, false]);
        self.presentation.details_visible = true;
        if std::env::var_os("MEASURELAB_UI_SMOKE_COMPARE").is_some() {
            self.compare_open = true;
        }
        if let Some(mut fixture) = physical_fixture {
            fixture.check()?;
            fixture.restore()?;
            self.select_lockin_view(true);
            self.lockin_display = settings::LockinDisplay::All;
            println!(
                "Stage 4b physical UI QA OK: settings/results, held edits, restore/reference, restart/recapture comparison, independent raw-window oracle, CSV/PNG; uncalibrated nominal Fs"
            );
        } else if let Some(fixture) = fixture {
            if fixture.failed.load(Ordering::Relaxed) {
                return Err("BlackHole fixture output failed".into());
            }
            drop(fixture);
            self.select_lockin_view(true);
            self.lockin_display = settings::LockinDisplay::All;
            println!(
                "Stage 4b external UI QA OK: {blackhole:?}; settings/result save, held edits, restore/reference, recapture/restart comparison, CSV/PNG; Single, when requested, armed on healthy Auto input"
            );
        } else {
            println!(
                "Stage 4a virtual UI QA OK: software common input; settings/results JSON save-load-restore-remeasure; Lock-in values/conditions survive held edits and restart; matching settled reference comparison; CSV/PNG; Single exact finite capture with unfilled 512k/Lock-in; experimental Lock-in amplitude/phase matches theory (physical use unverified)"
            );
        }
        self.created = Instant::now();
        Ok(())
    }
    #[cfg(feature = "qa")]
    pub(super) fn qa_wait_audio_idle(&mut self) -> Result<(), String> {
        let deadline = Instant::now() + Duration::from_secs(5);
        while self.busy {
            self.poll_audio();
            if Instant::now() > deadline {
                return Err("Audio device operation timed out".into());
            }
            std::thread::sleep(Duration::from_millis(5));
        }
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
            if ui.button("File paths & status…").clicked() {
                self.shell.file_paths = true;
                ui.close();
            }
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
                if self.spectrum_history.linked {
                    ui.label(spectrum_history::EXPORT_REASON);
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
                if self.spectrum_history.linked {
                    for (label, format) in [
                        ("Save held Scope JSON…", workspace_io::Format::Json),
                        ("Export held Scope CSV…", workspace_io::Format::Csv),
                        ("Export held Scope PNG…", workspace_io::Format::Png),
                    ] {
                        if ui
                            .add_enabled(self.can_export_scope(), egui::Button::new(label))
                            .clicked()
                        {
                            match self.capture_scope_results() {
                                Ok(doc) => self.submit_workspace(workspace_io::Task::SaveResult(
                                    Box::new(doc),
                                    format,
                                )),
                                Err(e) => self.workspace_status = Some(e),
                            }
                            ui.close();
                        }
                    }
                }
            });
            if ui
                .add_enabled(
                    self.reference.is_some(),
                    egui::Button::new("Compare saved reference"),
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
                            if a.channel==b.channel && a.calibrated_statistics.unit==b.calibrated_statistics.unit && crate::results::matching_excitation(reference, reference.scope.sample_range.clone(), current, current.scope.sample_range.clone()) {
                                if let (Some(a),Some(b))=(&a.calibrated_statistics.values,&b.calibrated_statistics.values) {
                                    ui.label(format!("Trace {}: current − reference RMS {:.9e} (each result's own interval)",i+1,b.rms-a.rms));
                                }
                            }else{ui.label(format!("Trace {} differs in channel, unit or known stationary excitation; no numeric difference",i+1));}
                        }
                        if reference.spectrum.settings!=current.spectrum.settings || reference.spectrum.mode!=current.spectrum.mode || reference.spectrum.unit!=current.spectrum.unit || reference.spectrum.channel!=current.spectrum.channel || reference.input.nominal_sample_rate_hz!=current.input.nominal_sample_rate_hz || !crate::results::matching_excitation(reference, reference.spectrum.average.as_ref().map_or(0..0, |a| a.contributing_envelope.clone()), current, current.spectrum.average.as_ref().map_or(0..0, |a| a.contributing_envelope.clone())) {
                            ui.label("Spectrum definitions or known stationary excitation differ; inspect each result's bins and band independently.");
                        }else if let (Some(a),Some(b))=(&reference.spectrum.band,&current.spectrum.band)
                            && a.inclusive_bins==b.inclusive_bins && a.power_unit==b.power_unit {
                            ui.label(format!("PSD band power current − reference: {:.9e} {}",b.power-a.power,b.power_unit));
                        }
                        if let Some(d) = crate::results::lockin_difference(reference, current) {
                            let l = current.lockin.as_ref().unwrap();
                            ui.label(format!("Lock-in current − reference (each result's own interval):\nΔX {:.9e} · ΔY {:.9e} · ΔR {:.9e} {}\nΔθ {:+.9}° (wrapped to ±180°) · ΔGain {:.9e} {}",
                                d.x, d.y, d.amplitude_peak, l.response_unit_peak, d.phase_degrees, d.gain, l.gain_unit));
                        } else if reference.lockin.is_some() || current.lockin.is_some() {
                            ui.label("Lock-in difference requires two valid, settled results with matching nominal Fs, channels, REF/filter settings and calibrations, no input failure, and known matching stationary excitation for Generator input.");
                        }
                        if reference.comparison.is_some() || current.comparison.is_some() {
                            let width=current.comparison.as_ref().map_or(1.0,|c|c.result.bin_width_hz());
                            let bin=(self.comparison_frequency_hz/width).round() as usize;
                            ui.label(format!("Synchronous comparison at bin {bin} ({:.3} Hz)",bin as f64*width));
                            for (label,document) in [("Reference",reference.as_ref()),("Current",current.as_ref())] {
                                if let Some(c)=&document.comparison {
                                    ui.label(format!("{label}: {:?} · REF CH {} / SIG CH {} · {}..{} · {} windows · {}",c.result.state,c.result.settings.reference_channel+1,c.result.settings.response_channel+1,c.result.sample_range.start,c.result.sample_range.end,c.result.averaged_windows,c.gain_unit));
                                    if let Some(b)=c.result.bins.get(bin) {ui.label(format!("Gain {:?} · phase {:?}° · coherence {:?} · {:?}",b.gain,b.phase_lead_degrees,b.coherence,b.state));}
                                }
                            }
                            if let Some(d)=crate::results::comparison_difference(reference,current,bin) {ui.label(format!("Current − reference: gain {:.9e} · phase {:+.9}° · wrapped delay {:?} s",d.gain,d.phase_degrees,d.phase_delay_seconds));}
                            else {ui.label("Difference requires valid matching input, analysis, calibration and excitation conditions without loss. Independent external output history does not establish matching excitation at input samples.");}
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
        export::Source::Generator => {
            ui.label(
                "Generator internal loopback · actual f64 output · shared integer sample clock",
            );
            if let Some(timeline) = &doc.generator_output {
                ui.label(format!(
                    "{} retained output condition intervals; missing/evicted intervals are unknown",
                    timeline.spans.len()
                ));
            }
        }
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
    if let Some(l) = &doc.lockin {
        lockin_summary(ui, l);
    }
    if let Some(output) = &doc.external_output {
        ui.label("External Generator history: independent, uncalibrated output clock; input-window correspondence unknown.");
        ui.label(format!(
            "{} observed changes | {} evicted | {} lost reports | {} output notifications since output worker start",
            output.changes.len(), output.evicted_changes,
            output.lost_reports_since_output_worker_start,
            output.notifications_since_output_worker_start
        ));
        if let Some(o) = &output.latest {
            ui.label(format!("Last observed output: {} | nominal {} Hz | {} | {:?} | generation {} revision {} | next output sample {}",
                o.target.label(), o.status.nominal_sample_rate, o.target.pcm_label(), o.status.state,
                o.status.output_generation, o.status.revision, o.status.next_sample));
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

fn lockin_summary(ui: &mut egui::Ui, l: &export::Lockin) {
    let r = &l.result;
    let number = |value: Option<f64>| value.map_or("—".into(), |v| format!("{v:.9e}"));
    ui.label(format!(
        "Lock-in {:?} · experimental | SIG CH {} / REF CH {}\nτ {} s · N {} · hint {} Hz · {} · REF min {} FS RMS",
        r.state, r.settings.response_channel + 1, r.settings.reference_channel + 1,
        r.settings.time_constant_seconds, r.settings.integration_samples, r.settings.frequency_hz,
        if r.settings.track_reference { "tracking ±10%" } else { "fixed frequency" },
        r.settings.reference_min_rms_fs
    ));
    ui.monospace(format!(
        "X {} · Y {} · R {} {}\nθ {}° (leads REF) · Gain {} {}",
        number(r.x),
        number(r.y),
        number(r.amplitude_peak),
        l.response_unit_peak,
        number(r.phase_degrees),
        number(r.gain),
        l.gain_unit
    ));
    ui.label(format!(
        "Envelope [{}, {}) · latest [{}, {})\n{} complete windows · {} missing samples\nREF {} Hz · AC RMS {} FS · sinusoid fit {}",
        r.sample_range.start, r.sample_range.end, r.latest_window.start, r.latest_window.end,
        r.processed_windows, r.missing_samples, number(r.reference_frequency_hz),
        number(r.reference_ac_rms_fs), number(r.reference_sinusoid_fraction)
    ));
    for (label, calibration) in [
        ("REF", &l.reference_calibration),
        ("SIG", &l.response_calibration),
    ] {
        ui.label(calibration.as_ref().map_or_else(
            || format!("{label}: uncalibrated · FS"),
            |c| {
                format!(
                    "{label}: {} rev {} · gain {} offset {} {} · {}",
                    c.id, c.revision, c.gain, c.offset, c.unit, c.conditions
                )
            },
        ));
    }
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
