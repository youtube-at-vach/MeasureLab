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
                if let Some(error) = self.input_error.as_ref().or(self.error.as_ref()) {
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
                if let Some(error) = self.input_error.as_ref().or(self.error.as_ref()) {
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
        setting_label(ui, i18n::text("common.software_loopback_ch_ref_ch_dut"));
        ui.label(
            RichText::new(i18n::text(
                "common.known_sine_gain_phase_delay_noise_dut_common_input",
            ))
            .small()
            .color(MUTED),
        );
        if self.shell.separate_io_rates {
            egui::ComboBox::from_id_salt("software_rate")
                .selected_text(
                    i18n::format(
                        "common.hz_4",
                        &[(
                            "unwrap_or",
                            &(self.requested_sample_rate.unwrap_or(48000)).to_string(),
                        )],
                    )
                    .as_ref(),
                )
                .show_ui(ui, |ui| {
                    for rate in [44100, 48000, 96000, 192000] {
                        ui.selectable_value(
                            &mut self.requested_sample_rate,
                            Some(rate),
                            i18n::format("common.hz_3", &[("rate", &(rate).to_string())]).as_ref(),
                        );
                    }
                });
        }
        let s = &mut self.loopback_settings;
        ui.add(
            egui::DragValue::new(&mut s.frequency_hz)
                .range(10.0..=80000.0)
                .prefix(i18n::text("common.frequency_hz")),
        );
        ui.add(
            egui::DragValue::new(&mut s.amplitude_peak)
                .range(0.0..=1.0)
                .speed(0.001)
                .prefix(i18n::text("common.reference_peak_fs")),
        );
        ui.add(
            egui::DragValue::new(&mut s.gain)
                .range(-100.0..=100.0)
                .speed(0.01)
                .prefix(i18n::text("common.dut_gain")),
        );
        ui.add(
            egui::DragValue::new(&mut s.phase_degrees)
                .speed(1.0)
                .prefix(i18n::text("common.phase_lead")),
        );
        ui.add(
            egui::DragValue::new(&mut s.delay_samples)
                .range(0..=384000)
                .prefix(i18n::text("common.delay_samples")),
        );
        ui.add(
            egui::DragValue::new(&mut s.dc_offset)
                .speed(0.001)
                .prefix(i18n::text("common.dut_dc_fs")),
        );
        ui.add(
            egui::DragValue::new(&mut s.noise_rms)
                .range(0.0..=1.0)
                .speed(0.00001)
                .prefix(i18n::text("common.noise_rms_fs")),
        );
        ui.add(
            egui::DragValue::new(&mut s.frequency_offset_hz)
                .speed(0.1)
                .prefix(i18n::text("common.dut_frequency_offset_hz")),
        );
        ui.checkbox(
            &mut s.reference_enabled,
            i18n::text("common.reference_present"),
        );
    }

    pub(super) fn file_menu(&mut self, ui: &mut egui::Ui) {
        ui.menu_button(i18n::text("common.file"), |ui| {
            if ui.button(i18n::text("common.file_paths_status")).clicked() {
                self.shell.file_paths = true;
                ui.close();
            }
            ui.add_enabled_ui(!self.workspace_pending, |ui| {
                if ui.button(i18n::text("common.save_settings_2")).clicked() {
                    match self.capture_settings() {
                        Ok(doc) => {
                            self.submit_workspace(workspace_io::Task::SaveSettings(Box::new(doc)))
                        }
                        Err(e) => self.workspace_status = Some(e.into()),
                    }
                    ui.close();
                }
                if ui
                    .add_enabled(
                        self.can_restore_settings(),
                        egui::Button::new(i18n::text("common.restore_settings_2")),
                    )
                    .clicked()
                {
                    self.submit_workspace(workspace_io::Task::RestoreSettings);
                    ui.close();
                }
                ui.separator();
                if ui
                    .button(i18n::text("common.load_reference_result"))
                    .clicked()
                {
                    self.submit_workspace(workspace_io::Task::LoadResult);
                    ui.close();
                }
                if self.spectrum_history.linked {
                    ui.label(spectrum_history::export_reason());
                }
                if ui
                    .add_enabled(
                        self.can_export(),
                        egui::Button::new(i18n::text("common.keep_held_result_as_reference")),
                    )
                    .clicked()
                {
                    match self.capture_results() {
                        Ok(doc) => {
                            self.reference = Some(Box::new(doc));
                            self.reference_label = i18n::text("common.previous_held_result").into();
                            self.comparison_current = None;
                            self.compare_open = true;
                        }
                        Err(e) => self.workspace_status = Some(e.into()),
                    }
                    ui.close();
                }
                for (label, format) in [
                    (
                        i18n::text("common.save_held_result_json"),
                        workspace_io::Format::Json,
                    ),
                    (
                        i18n::text("common.export_held_result_csv"),
                        workspace_io::Format::Csv,
                    ),
                    (
                        i18n::text("common.export_annotated_png"),
                        workspace_io::Format::Png,
                    ),
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
                            Err(e) => self.workspace_status = Some(e.into()),
                        }
                        ui.close();
                    }
                }
                if self.spectrum_history.linked {
                    for (label, format) in [
                        (
                            i18n::text("common.save_held_scope_json"),
                            workspace_io::Format::Json,
                        ),
                        (
                            i18n::text("common.export_held_scope_csv"),
                            workspace_io::Format::Csv,
                        ),
                        (
                            i18n::text("common.export_held_scope_png"),
                            workspace_io::Format::Png,
                        ),
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
                                Err(e) => self.workspace_status = Some(e.into()),
                            }
                            ui.close();
                        }
                    }
                }
            });
            if ui
                .add_enabled(
                    self.reference.is_some(),
                    egui::Button::new(i18n::text("common.compare_saved_reference")),
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
                    egui::Button::new(i18n::text("common.clear_reference")),
                )
                .clicked()
            {
                self.reference = None;
                self.compare_open = false;
            }
            if let Some(status) = &self.workspace_status {
                ui.separator();
                ui.label(status.render().as_ref());
            }
        });
    }

    fn submit_workspace(&mut self, task: workspace_io::Task) {
        let restore = matches!(task, workspace_io::Task::RestoreSettings);
        match self.workspace_io.submit(task) {
            Ok(()) => {
                self.workspace_pending = true;
                self.workspace_restoring = restore;
                self.workspace_status = Some(UiStatus::SelectingFile);
            }
            Err(e) => self.workspace_status = Some(e.into()),
        }
    }
    pub(super) fn poll_workspace(&mut self) {
        while let Ok(event) = self.workspace_io.events.try_recv() {
            self.workspace_pending = false;
            self.workspace_restoring = false;
            self.workspace_status = Some(match event {
                workspace_io::Event::Saved(path) => UiStatus::Saved(path),
                workspace_io::Event::Cancelled => UiStatus::Cancelled,
                workspace_io::Event::Error(e) => e.into(),
                workspace_io::Event::Settings(doc) => match self.restore_settings(*doc) {
                    Ok(()) => UiStatus::Restored,
                    Err(e) => e.into(),
                },
                workspace_io::Event::Reference(doc, path) => {
                    self.reference = Some(doc);
                    self.reference_label = path.display().to_string();
                    self.comparison_current = None;
                    self.compare_open = true;
                    UiStatus::ReferenceLoaded
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
        egui::Window::new(i18n::text("common.reference_comparison")).id(egui::Id::new("Reference comparison")).open(&mut open).default_size(vec2(930.0,680.0)).show(ctx,|ui| {
            ui.label(RichText::new(&self.reference_label).small().color(MUTED));
            ui.label(i18n::text("common.one_reference_is_retained_recordings_use_independent_sample_clock"));
            egui::ScrollArea::vertical().show(ui,|ui| {
                if let Some(reference)=&self.reference {
                    ui.columns(2,|cols| {
                        cols[0].heading(i18n::text("common.reference"));result_summary(&mut cols[0],reference);
                        cols[1].heading(i18n::text("common.current_held_result"));
                        if let Some(current)=&current {result_summary(&mut cols[1],current);}else{cols[1].label(i18n::text("common.stop_input_to_compare_the_current_result"));}
                    });
                    if let Some(current)=&current {
                        ui.separator();
                        for (i,(a,b)) in reference.scope.traces.iter().zip(&current.scope.traces).enumerate() {
                            if a.channel==b.channel && a.calibrated_statistics.unit==b.calibrated_statistics.unit && crate::results::matching_excitation(reference, reference.scope.sample_range.clone(), current, current.scope.sample_range.clone()) {
                                if let (Some(a),Some(b))=(&a.calibrated_statistics.values,&b.calibrated_statistics.values) {
                                    ui.label(i18n::format("common.trace_current_reference_rms_each_result_s_own_interval", &[("i", &(i+1).to_string()), ("rms", &format!("{:.9e}", b.rms-a.rms))]).as_ref());
                                }
                            }else{ui.label(i18n::format("common.trace_differs_in_channel_unit_or_known_stationary_excitation", &[("i", &(i+1).to_string())]).as_ref());}
                        }
                        if reference.spectrum.settings!=current.spectrum.settings || reference.spectrum.mode!=current.spectrum.mode || reference.spectrum.unit!=current.spectrum.unit || reference.spectrum.channel!=current.spectrum.channel || reference.input.nominal_sample_rate_hz!=current.input.nominal_sample_rate_hz || !crate::results::matching_excitation(reference, reference.spectrum.average.as_ref().map_or(0..0, |a| a.contributing_envelope.clone()), current, current.spectrum.average.as_ref().map_or(0..0, |a| a.contributing_envelope.clone())) {
                            ui.label(i18n::text("common.spectrum_definitions_or_known_stationary_excitation_differ_inspect_each"));
                        }else if let (Some(a),Some(b))=(&reference.spectrum.band,&current.spectrum.band)
                            && a.inclusive_bins==b.inclusive_bins && a.power_unit==b.power_unit {
                            ui.label(i18n::format("common.psd_band_power_current_reference", &[("power", &format!("{:.9e}", b.power-a.power)), ("power_unit", &(b.power_unit).to_string())]).as_ref());
                        }
                        if let Some(d) = crate::results::lockin_difference(reference, current) {
                            let l = current.lockin.as_ref().unwrap();
                            ui.label(i18n::format("common.lock_in_current_reference_each_result_s_own_interval", &[("x", &format!("{:.9e}", d.x)), ("y", &format!("{:.9e}", d.y)), ("amplitude_peak", &format!("{:.9e}", d.amplitude_peak)), ("response_unit_peak", &(l.response_unit_peak).to_string()), ("phase_degrees", &format!("{:+.9}", d.phase_degrees)), ("gain", &format!("{:.9e}", d.gain)), ("gain_unit", &(l.gain_unit).to_string())]).as_ref());
                        } else if reference.lockin.is_some() || current.lockin.is_some() {
                            ui.label(i18n::text("common.lock_in_difference_requires_two_valid_settled_results_with"));
                        }
                        if reference.comparison.is_some() || current.comparison.is_some() {
                            let width=current.comparison.as_ref().map_or(1.0,|c|c.result.bin_width_hz());
                            let bin=(self.comparison_frequency_hz/width).round() as usize;
                            ui.label(i18n::format("common.synchronous_comparison_at_bin_hz", &[("bin", &(bin).to_string()), ("width", &format!("{:.3}", bin as f64*width))]).as_ref());
                            for (label,document) in [(i18n::text("common.reference"),reference.as_ref()),(i18n::text("common.current"),current.as_ref())] {
                                if let Some(c)=&document.comparison {
                                    ui.label(i18n::format("common.ref_ch_sig_ch_windows", &[("label", (label)), ("state", c.result.state.display_name()), ("reference_channel", &(c.result.settings.reference_channel+1).to_string()), ("response_channel", &(c.result.settings.response_channel+1).to_string()), ("start", &(c.result.sample_range.start).to_string()), ("end", &(c.result.sample_range.end).to_string()), ("averaged_windows", &(c.result.averaged_windows).to_string()), ("gain_unit", &(c.gain_unit).to_string())]).as_ref());
                                    if let Some(b)=c.result.bins.get(bin) {ui.label(i18n::format("common.gain_phase_coherence", &[("gain", &format!("{:?}", b.gain)), ("phase_lead_degrees", &format!("{:?}", b.phase_lead_degrees)), ("coherence", &format!("{:?}", b.coherence)), ("state", b.state.display_name())]).as_ref());}
                                }
                            }
                            if let Some(d)=crate::results::comparison_difference(reference,current,bin) {ui.label(i18n::format("common.current_reference_gain_phase_wrapped_delay_s", &[("gain", &format!("{:.9e}", d.gain)), ("phase_degrees", &format!("{:+.9}", d.phase_degrees)), ("phase_delay_seconds", &format!("{:?}", d.phase_delay_seconds))]).as_ref());}
                            else {ui.label(i18n::text("common.difference_requires_valid_matching_input_analysis_calibration_and_excitation"));}
                        }
                    }
                }
            });
        });
        self.compare_open = open;
    }
}

fn result_summary(ui: &mut egui::Ui, doc: &export::Document) {
    ui.label(
        i18n::format(
            "common.generation_nominal_hz_ch",
            &[
                ("generation", &(doc.input.generation).to_string()),
                (
                    "nominal_sample_rate_hz",
                    &(doc.input.nominal_sample_rate_hz).to_string(),
                ),
                ("channels", &(doc.input.channels).to_string()),
            ],
        )
        .as_ref(),
    );
    match &doc.input.source {
        export::Source::Generator => {
            ui.label(i18n::text(
                "common.generator_internal_loopback_actual_f64_output_shared_integer_sample",
            ));
            if let Some(timeline) = &doc.generator_output {
                ui.label(i18n::format("common.retained_output_condition_intervals_missing_evicted_intervals_are_unknown", &[("len", &(timeline.spans.len()).to_string())]).as_ref());
            }
        }
        export::Source::Audio {
            device_name,
            sample_format,
            ..
        } => {
            ui.label(
                i18n::format(
                    "common.input",
                    &[
                        ("device_name", &(device_name).to_string()),
                        ("sample_format", &(sample_format).to_string()),
                    ],
                )
                .as_ref(),
            );
        }
        export::Source::InternalQa { description } => {
            ui.label(description);
        }
        export::Source::SoftwareLoopback { settings: s } => {
            ui.label(
                i18n::format(
                    "common.software_loopback_hz_ref_fs_peak",
                    &[
                        ("frequency_hz", &format!("{:.6}", s.frequency_hz)),
                        ("amplitude_peak", &format!("{:.9e}", s.amplitude_peak)),
                    ],
                )
                .as_ref(),
            );
            ui.label(
                i18n::format(
                    "common.dut_gain_phase_delay_samples",
                    &[
                        ("gain", &(s.gain).to_string()),
                        ("phase_degrees", &(s.phase_degrees).to_string()),
                        ("delay_samples", &(s.delay_samples).to_string()),
                    ],
                )
                .as_ref(),
            );
            ui.label(
                i18n::format(
                    "common.dc_fs_noise_rms_fs_frequency_offset_hz_ref",
                    &[
                        ("dc_offset", &(s.dc_offset).to_string()),
                        ("noise_rms", &(s.noise_rms).to_string()),
                        ("frequency_offset_hz", &(s.frequency_offset_hz).to_string()),
                        (
                            "disabled",
                            (if s.reference_enabled {
                                i18n::text("common.enabled")
                            } else {
                                i18n::text("common.disabled")
                            }),
                        ),
                    ],
                )
                .as_ref(),
            );
        }
    }
    if let Some(l) = &doc.lockin {
        lockin_summary(ui, l);
    }
    if let Some(output) = &doc.external_output {
        ui.label(i18n::text(
            "common.external_generator_history_independent_uncalibrated_output_clock_input_window",
        ));
        ui.label(
            i18n::format(
                "common.observed_changes_evicted_lost_reports_output_notifications_since_output",
                &[
                    ("len", &(output.changes.len()).to_string()),
                    ("evicted_changes", &(output.evicted_changes).to_string()),
                    (
                        "lost_reports_since_output_worker_start",
                        &(output.lost_reports_since_output_worker_start).to_string(),
                    ),
                    (
                        "notifications_since_output_worker_start",
                        &(output.notifications_since_output_worker_start).to_string(),
                    ),
                ],
            )
            .as_ref(),
        );
        if let Some(o) = &output.latest {
            ui.label(
                i18n::format(
                    "common.last_observed_output_nominal_hz_generation_revision_next_output",
                    &[
                        ("label", (text::output_target(&o.target))),
                        (
                            "nominal_sample_rate",
                            &(o.status.nominal_sample_rate).to_string(),
                        ),
                        ("pcm_label", (o.target.pcm_label())),
                        ("state", &format!("{:?}", o.status.state)),
                        (
                            "output_generation",
                            &(o.status.output_generation).to_string(),
                        ),
                        ("revision", &(o.status.revision).to_string()),
                        ("next_sample", &(o.status.next_sample).to_string()),
                    ],
                )
                .as_ref(),
            );
        }
    }
    ui.label(
        i18n::format(
            "common.scope_trigger_ch_at_fs",
            &[
                ("start", &(doc.scope.sample_range.start).to_string()),
                ("end", &(doc.scope.sample_range.end).to_string()),
                (
                    "acquisition_mode",
                    doc.scope.acquisition_mode.display_name(),
                ),
                ("channel", &(doc.scope.trigger.channel + 1).to_string()),
                ("edge", doc.scope.trigger.edge.display_name()),
                ("level", &(doc.scope.trigger.level).to_string()),
            ],
        )
        .as_ref(),
    );
    for (i, t) in doc.scope.traces.iter().enumerate() {
        ui.label(
            i18n::format(
                "common.trace_ch",
                &[
                    ("i", &(i + 1).to_string()),
                    ("channel", &(t.channel + 1).to_string()),
                    ("state", t.state.display_name()),
                    ("unit", &(t.calibrated_statistics.unit).to_string()),
                ],
            )
            .as_ref(),
        );
        if let Some(v) = &t.calibrated_statistics.values {
            ui.monospace(
                i18n::format(
                    "common.rms_peak_p_p",
                    &[
                        ("rms", &format!("{:.9e}", v.rms)),
                        ("peak", &format!("{:.9e}", v.peak)),
                        ("peak_to_peak", &format!("{:.9e}", v.peak_to_peak)),
                    ],
                )
                .to_string(),
            );
        }
        ui.label(
            t.calibration
                .as_ref()
                .map_or(i18n::text("common.uncalibrated").into(), |c| {
                    i18n::format(
                        "common.calibration_rev_gain_offset_2",
                        &[
                            ("id", &(c.id).to_string()),
                            ("revision", &(c.revision).to_string()),
                            ("gain", &(c.gain).to_string()),
                            ("offset", &(c.offset).to_string()),
                            ("conditions", &(c.conditions).to_string()),
                        ],
                    )
                    .to_string()
                }),
        );
        if let Some(samples) = &t.raw_samples_fs {
            reference_plot(
                ui,
                samples.iter().copied(),
                samples.len(),
                false,
                i18n::text("common.raw_scope_fs_relative_sample_position"),
            );
        }
    }
    let s = &doc.spectrum;
    ui.label(
        i18n::format(
            "common.spectrum_ch_points_dc_removal",
            &[
                ("state", s.state.display_name()),
                (
                    "c",
                    &(s.channel
                        .map_or("unavailable".into(), |c| (c + 1).to_string()))
                    .to_string(),
                ),
                (
                    "end",
                    &(s.latest_window.as_ref().map_or(
                        i18n::text("common.no_complete_fft_window").into(),
                        |w| {
                            i18n::format(
                                "common.window",
                                &[
                                    ("start", &(w.start).to_string()),
                                    ("end", &(w.end).to_string()),
                                ],
                            )
                            .to_string()
                        },
                    ))
                    .to_string(),
                ),
                ("size", &(s.settings.size).to_string()),
                ("name", (s.settings.window.display_name())),
                ("mode", s.mode.display_name()),
                ("remove_dc", &(s.settings.remove_dc).to_string()),
                ("unit", &(s.unit).to_string()),
            ],
        )
        .as_ref(),
    );
    ui.label(
        i18n::format(
            "common.f_hz_rbw_hz",
            &[
                ("bin_width_hz", &format!("{:.9}", s.bin_width_hz)),
                ("rbw_hz", &format!("{:.9}", s.rbw_hz)),
            ],
        )
        .as_ref(),
    );
    if let Some(a) = &s.average {
        ui.label(
            i18n::format(
                "common.ema_windows_envelope",
                &[
                    ("alpha", &format!("{:.9}", a.alpha)),
                    ("processed_windows", &(a.processed_windows).to_string()),
                    ("start", &(a.contributing_envelope.start).to_string()),
                    ("end", &(a.contributing_envelope.end).to_string()),
                ],
            )
            .as_ref(),
        );
    }
    ui.label(
        s.calibration
            .as_ref()
            .map_or(i18n::text("common.uncalibrated").into(), |c| {
                i18n::format(
                    "common.calibration_rev_gain_offset",
                    &[
                        ("id", &(c.id).to_string()),
                        ("revision", &(c.revision).to_string()),
                        ("gain", &(c.gain).to_string()),
                        ("offset", &(c.offset).to_string()),
                        ("unit", &(c.unit).to_string()),
                        ("conditions", &(c.conditions).to_string()),
                    ],
                )
                .to_string()
            }),
    );
    if let Some(v) = &s.values {
        reference_plot(
            ui,
            v.iter().copied().map(Some),
            v.len(),
            true,
            i18n::text("common.spectrum_linear_values_bin_position"),
        );
    }
    if let Some(b) = &s.band {
        ui.label(
            i18n::format(
                "common.band_hz_power_rms",
                &[
                    ("bin_centres_hz", &format!("{:?}", b.bin_centres_hz)),
                    ("power", &format!("{:.9e}", b.power)),
                    ("power_unit", &(b.power_unit).to_string()),
                    ("rms", &format!("{:.9e}", b.rms)),
                    ("rms_unit", &(b.rms_unit).to_string()),
                ],
            )
            .as_ref(),
        );
    }
    ui.label(
        i18n::format(
            "common.loss_capture_scope_fft_input_fft_windows_missing_nonfinite",
            &[
                (
                    "capture_dropped_samples",
                    &(doc.loss.capture_dropped_samples).to_string(),
                ),
                (
                    "scope_missing_samples",
                    &(doc.loss.scope_missing_samples).to_string(),
                ),
                (
                    "missing_input_samples",
                    &(s.diagnostics.missing_input_samples).to_string(),
                ),
                (
                    "missing_windows",
                    &(s.diagnostics.missing_windows).to_string(),
                ),
                (
                    "nonfinite_windows",
                    &(s.diagnostics.nonfinite_windows).to_string(),
                ),
                (
                    "processed_windows_since_reset",
                    &(s.diagnostics.processed_windows_since_reset).to_string(),
                ),
                ("input_end", &(s.diagnostics.input_end).to_string()),
                (
                    "filled_samples",
                    &(s.diagnostics.filled_samples).to_string(),
                ),
                ("input_failed", &(doc.loss.input_failed).to_string()),
            ],
        )
        .as_ref(),
    );
}

fn lockin_summary(ui: &mut egui::Ui, l: &export::Lockin) {
    let r = &l.result;
    let number = |value: Option<f64>| value.map_or("—".into(), |v| format!("{v:.9e}"));
    ui.label(
        i18n::format(
            "common.lock_in_experimental_sig_ch_ref_ch_s_n",
            &[
                ("state", r.state.display_name()),
                (
                    "response_channel",
                    &(r.settings.response_channel + 1).to_string(),
                ),
                (
                    "reference_channel",
                    &(r.settings.reference_channel + 1).to_string(),
                ),
                (
                    "time_constant_seconds",
                    &(r.settings.time_constant_seconds).to_string(),
                ),
                (
                    "integration_samples",
                    &(r.settings.integration_samples).to_string(),
                ),
                ("frequency_hz", &(r.settings.frequency_hz).to_string()),
                (
                    "fixed_frequency",
                    (if r.settings.track_reference {
                        i18n::text("common.tracking")
                    } else {
                        i18n::text("common.fixed_frequency")
                    }),
                ),
                (
                    "reference_min_rms_fs",
                    &(r.settings.reference_min_rms_fs).to_string(),
                ),
            ],
        )
        .as_ref(),
    );
    ui.monospace(
        i18n::format(
            "common.x_y_r_leads_ref_gain",
            &[
                ("x", &(number(r.x)).to_string()),
                ("y", &(number(r.y)).to_string()),
                ("amplitude_peak", &(number(r.amplitude_peak)).to_string()),
                ("response_unit_peak", &(l.response_unit_peak).to_string()),
                ("phase_degrees", &(number(r.phase_degrees)).to_string()),
                ("gain", &(number(r.gain)).to_string()),
                ("gain_unit", &(l.gain_unit).to_string()),
            ],
        )
        .to_string(),
    );
    ui.label(
        i18n::format(
            "common.envelope_latest_complete_windows_missing_samples_ref_hz_ac",
            &[
                ("start", &(r.sample_range.start).to_string()),
                ("end", &(r.sample_range.end).to_string()),
                ("start_2", &(r.latest_window.start).to_string()),
                ("end_2", &(r.latest_window.end).to_string()),
                ("processed_windows", &(r.processed_windows).to_string()),
                ("missing_samples", &(r.missing_samples).to_string()),
                (
                    "reference_frequency_hz",
                    &(number(r.reference_frequency_hz)).to_string(),
                ),
                (
                    "reference_ac_rms_fs",
                    &(number(r.reference_ac_rms_fs)).to_string(),
                ),
                (
                    "reference_sinusoid_fraction",
                    &(number(r.reference_sinusoid_fraction)).to_string(),
                ),
            ],
        )
        .as_ref(),
    );
    for (label, calibration) in [
        (i18n::text("common.ref"), &l.reference_calibration),
        (i18n::text("common.sig"), &l.response_calibration),
    ] {
        ui.label(calibration.as_ref().map_or_else(
            || i18n::format("common.uncalibrated_fs_2", &[("label", (label))]).to_string(),
            |c| {
                i18n::format(
                    "common.rev_gain_offset",
                    &[
                        ("label", (label)),
                        ("id", &(c.id).to_string()),
                        ("revision", &(c.revision).to_string()),
                        ("gain", &(c.gain).to_string()),
                        ("offset", &(c.offset).to_string()),
                        ("unit", &(c.unit).to_string()),
                        ("conditions", &(c.conditions).to_string()),
                    ],
                )
                .to_string()
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
