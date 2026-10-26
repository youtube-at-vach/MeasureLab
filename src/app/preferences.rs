use super::*;
use settings::preferences::{Event, Preferences, Worker};

const SAVE_INTERVAL: Duration = Duration::from_secs(2);

pub(super) struct State {
    worker: Option<Worker>,
    path: Option<std::path::PathBuf>,
    pub loading: bool,
    loaded: Option<Preferences>,
    last_snapshot: Option<Preferences>,
    writable: bool,
    retry_save: bool,
    last_check: Instant,
    error: Option<String>,
}

impl State {
    pub fn new(enabled: bool) -> Self {
        let path = enabled.then(settings::preferences::default_path);
        let error = path.as_ref().and_then(|p| p.as_ref().err()).cloned();
        let path = path.and_then(Result::ok);
        Self {
            worker: path.as_ref().map(|p| Worker::new(p.clone())),
            loading: path.is_some(),
            path,
            loaded: None,
            last_snapshot: None,
            writable: false,
            retry_save: false,
            last_check: Instant::now(),
            error,
        }
    }

    #[cfg(feature = "qa")]
    fn at(path: std::path::PathBuf) -> Self {
        Self {
            worker: Some(Worker::new(path.clone())),
            path: Some(path),
            loading: true,
            ..Self::new(false)
        }
    }
}

impl ScopeApp {
    pub(super) fn poll_preferences(&mut self, ctx: &egui::Context) {
        while let Some(event) = self
            .preferences
            .worker
            .as_ref()
            .and_then(|worker| worker.events.try_recv().ok())
        {
            match event {
                Event::Loaded(Ok(preferences)) => {
                    self.preferences.loaded = preferences.map(|p| *p);
                    self.preferences.writable = true;
                    if self.preferences.loaded.is_none() {
                        self.preferences.loading = false;
                    }
                }
                Event::Loaded(Err(error)) => {
                    // Preserve unreadable, damaged and future-version files.
                    // Defaults remain usable; only automatic writes are disabled.
                    self.preferences.error = Some(error);
                    self.preferences.loading = false;
                }
                Event::Saved(result) => {
                    self.preferences.error = result.err();
                    self.preferences.retry_save = self.preferences.error.is_some();
                }
            }
        }
        // Enumeration is asynchronous. Never replace a saved input with the
        // system default merely because its discovery reply arrived later.
        if self.preferences.loaded.is_some() && !self.busy && self.generator.stopped() {
            let preferences = self.preferences.loaded.take().unwrap();
            self.preferences.loading = false;
            let result = if let Some(measurement) = &preferences.measurement {
                self.restore_settings_with_policy(
                    settings::Document {
                        version: settings::VERSION,
                        measurement: measurement.clone(),
                        workspace: preferences.workspace.clone(),
                    },
                    true,
                )
            } else {
                self.apply_workspace(preferences.workspace.clone());
                Ok(())
            };
            match result {
                Ok(()) => {
                    self.shell.sidebar_compact = preferences.sidebar_compact;
                    self.shell.separate_io_rates = preferences.separate_io_rates;
                    i18n::set_locale(ctx, &preferences.locale);
                    self.preferences.last_snapshot = Some(preferences);
                }
                Err(error) => {
                    self.preferences.error = Some(error);
                    self.preferences.writable = false;
                }
            }
        }
        if self.preferences.worker.is_some() {
            if self.preferences.loading {
                ctx.request_repaint_after(Duration::from_millis(25));
            } else {
                if self.preferences.last_check.elapsed() >= SAVE_INTERVAL {
                    self.save_preferences();
                    self.preferences.last_check = Instant::now();
                }
                ctx.request_repaint_after(SAVE_INTERVAL);
            }
        }
    }

    pub(super) fn save_preferences(&mut self) {
        if !self.preferences.writable
            || self.preferences.loading
            || self.workspace_restoring
            || self.settings_task == Some(SettingsTask::Restore)
        {
            return;
        }
        // Pending/incomplete edits never replace the last valid measurement.
        // Display preferences can still be retained without any input device.
        let measurement = self
            .capture_settings_with_policy(true)
            .ok()
            .map(|document| document.measurement)
            .or_else(|| {
                self.preferences
                    .last_snapshot
                    .as_ref()
                    .and_then(|p| p.measurement.clone())
            });
        let snapshot = Preferences {
            version: settings::VERSION,
            measurement,
            workspace: self.capture_workspace(),
            sidebar_compact: self.shell.sidebar_compact,
            separate_io_rates: self.shell.separate_io_rates,
            locale: i18n::locale().id().into(),
        };
        if (self.preferences.retry_save
            || self.preferences.last_snapshot.as_ref() != Some(&snapshot))
            && let Some(worker) = &self.preferences.worker
        {
            worker.save(snapshot.clone());
            self.preferences.last_snapshot = Some(snapshot);
            self.preferences.retry_save = false;
        }
    }

    pub(super) fn preferences_controls(&mut self, ui: &mut egui::Ui) {
        setting_label(ui, i18n::text("common.startup_preferences"));
        ui.label(i18n::text("common.startup_preferences_help"));
        if let Some(path) = &self.preferences.path {
            ui.label(
                RichText::new(path.display().to_string())
                    .small()
                    .color(MUTED),
            );
        }
        if let Some(error) = &self.preferences.error {
            ui.colored_label(YELLOW, error);
            if !self.preferences.writable {
                ui.label(i18n::text("common.startup_preferences_recovery"));
            }
        }
    }

    pub(super) fn preferences_status(&mut self, ui: &mut egui::Ui) {
        if let Some(error) = &self.preferences.error
            && ui
                .small_button(i18n::text("common.startup_preferences_error"))
                .on_hover_text(error)
                .clicked()
        {
            self.shell.file_paths = true;
        }
    }

    #[cfg(feature = "qa")]
    pub(super) fn check_startup_preferences(&mut self, ctx: &egui::Context) -> Result<(), String> {
        fn settled(app: &mut ScopeApp) -> Result<(), String> {
            let deadline = Instant::now() + Duration::from_secs(5);
            while app.preferences.loading || app.generator.pending {
                app.generator.poll();
                app.poll_preferences(&egui::Context::default());
                if Instant::now() > deadline {
                    return Err("Startup preferences QA timed out".into());
                }
                std::thread::sleep(Duration::from_millis(2));
            }
            Ok(())
        }
        self.check_settings_restore()?;
        settled(self)?;
        let original = self.capture_settings()?;
        let device = self.devices[self.selected].clone();
        let mut other = device.clone();
        other.id = Some("test:unrelated-default".into());
        other.name = device.name.clone(); // Names are deliberately identical.
        let mut device = device;
        device.is_default = false;
        let directory = std::path::PathBuf::from("dist/startup-preferences-qa");
        std::fs::create_dir_all(&directory).map_err(|e| e.to_string())?;
        let path = directory.join("preferences.json");
        let _ = std::fs::remove_file(&path);
        self.preferences = State::at(path.clone());
        settled(self)?;
        self.shell.separate_io_rates = true;
        self.shell.sidebar_compact = true;
        self.save_preferences();
        self.preferences = State::new(false); // Flush on close.
        self.accept_devices(vec![other.clone(), device.clone()]);
        self.requested_sample_rate = None;
        self.spectrum_settings.size = 8192;
        self.preferences = State::at(path.clone());
        self.busy = true; // A loaded file must wait for device discovery.
        let generation = self.input_generation;
        self.start();
        assert_eq!(self.input_generation, generation);
        assert!(!self.running());
        let deadline = Instant::now() + Duration::from_secs(5);
        while self.preferences.loaded.is_none() {
            self.poll_preferences(ctx);
            assert!(Instant::now() < deadline, "Preference load timed out");
            std::thread::sleep(Duration::from_millis(2));
        }
        assert!(self.preferences.loading);
        assert!(!self.input_transport_enabled());
        self.busy = false;
        settled(self)?;
        assert_eq!(self.selected, 1);
        assert_eq!(self.capture_settings()?, original);
        assert!(self.shell.separate_io_rates && self.shell.sidebar_compact);
        assert!(!self.running() && self.generator.stopped());

        self.preferences = State::new(false);
        self.devices = vec![other.clone()];
        self.preferences = State::at(path.clone());
        settled(self)?;
        assert_eq!(self.selected, usize::MAX);
        assert!(!self.input_transport_enabled());
        assert!(self.input_error.is_some());
        assert_eq!(self.capture_settings_with_policy(true)?, original);
        self.save_preferences();
        self.preferences = State::new(false);
        self.accept_devices(vec![device, other]);
        assert_eq!(self.selected, 0);
        assert!(self.input_error.is_none());
        assert_eq!(self.capture_settings()?, original);

        let mut missing_output = original.clone();
        let generator = missing_output.measurement.generator.as_mut().unwrap();
        generator.target = output::Target::Audio {
            device_id: "test:unavailable-output".into(),
            device_name: "Unavailable output".into(),
            channels: 2,
            pcm: output::device::Pcm::F32,
            dither: output::dither::Dither::default(),
        };
        self.restore_settings_with_policy(missing_output.clone(), true)?;
        settled(self)?;
        assert_eq!(self.capture_settings()?, missing_output);
        assert!(!self.running() && self.generator.stopped());
        assert!(self.restore_settings(missing_output).is_err());
        self.restore_settings(original)?;
        settled(self)?;

        std::fs::write(&path, b"damaged preferences").map_err(|e| e.to_string())?;
        self.preferences = State::at(path.clone());
        settled(self)?;
        assert!(!self.preferences.writable);
        self.save_preferences();
        self.preferences = State::new(false);
        assert_eq!(
            std::fs::read(&path).map_err(|e| e.to_string())?,
            b"damaged preferences"
        );
        std::fs::remove_file(&path).map_err(|e| e.to_string())?;
        self.preferences.path = Some(path);
        i18n::set_locale(ctx, "en-US");
        println!(
            "Startup preferences UI QA OK: restart, delayed/reordered discovery, exact device identity, unavailable input/output retained, safe refresh, stopped I/O, final flush and damaged-file preservation"
        );
        Ok(())
    }
}
