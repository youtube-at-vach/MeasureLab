//! Generator controls and a static settings preview. Measured samples are
//! supplied separately by output::Worker through the shared measurement path.
use super::*;
use crate::{generator, output};

pub(super) struct GeneratorUi {
    pub worker: output::Worker,
    pub settings: generator::Settings,
    pub rate: u32,
    pub target: output::Target,
    pub devices: Vec<output::device::DeviceInfo>,
    pub status: generator::Status,
    pub controls_expanded: bool,
    pub pending: bool,
    pub starting: bool,
    pub stopping: bool,
    pub error: Option<String>,
    requested_id: u64,
    stop_epoch: u64,
    texts: [[String; 3]; generator::SIGNALS],
    edited: [[bool; 3]; generator::SIGNALS],
    selected: usize,
    step: f64,
    #[cfg(feature = "qa")]
    edit_latencies: Vec<f64>,
    #[cfg(feature = "qa")]
    edit_pending: Option<Instant>,
    #[cfg(feature = "qa")]
    profile_input_started: bool,
    #[cfg(feature = "qa")]
    profile_output_started: bool,
    #[cfg(feature = "qa")]
    device_metrics: Option<Arc<output::device::Metrics>>,
    #[cfg(feature = "qa")]
    disconnect: Option<DisconnectQa>,
}
#[cfg(feature = "qa")]
struct DisconnectQa {
    stage: u8,
    since: Instant,
    refreshed: Instant,
    error_status: Option<generator::Status>,
    notifications: u64,
}
#[cfg(feature = "qa")]
impl Default for DisconnectQa {
    fn default() -> Self {
        Self {
            stage: 0,
            since: Instant::now(),
            refreshed: Instant::now(),
            error_status: None,
            notifications: 0,
        }
    }
}
impl Default for GeneratorUi {
    fn default() -> Self {
        let settings = generator::Settings::default();
        Self {
            worker: {
                let worker = output::Worker::new();
                let _ = worker.refresh();
                worker
            },
            settings,
            rate: 48_000,
            target: output::Target::Internal,
            devices: Vec::new(),
            status: generator::Engine::new(48_000, 2, settings, 0)
                .unwrap()
                .status(),
            controls_expanded: true,
            pending: false,
            starting: false,
            stopping: false,
            error: None,
            requested_id: 0,
            stop_epoch: 0,
            texts: std::array::from_fn(|_| std::array::from_fn(|_| String::new())),
            edited: [[false; 3]; generator::SIGNALS],
            selected: 0,
            step: 1.0,
            #[cfg(feature = "qa")]
            edit_latencies: Vec::with_capacity(100),
            #[cfg(feature = "qa")]
            edit_pending: None,
            #[cfg(feature = "qa")]
            profile_input_started: false,
            #[cfg(feature = "qa")]
            profile_output_started: false,
            #[cfg(feature = "qa")]
            device_metrics: None,
            #[cfg(feature = "qa")]
            disconnect: Some(DisconnectQa::default()),
        }
    }
}
impl GeneratorUi {
    #[cfg(feature = "qa")]
    pub(super) fn command_marker(&self) -> (u64, u64) {
        (self.requested_id, self.stop_epoch)
    }
    #[cfg(feature = "qa")]
    pub(super) fn profile_stall_frames(&self) -> Option<u64> {
        if self.starting
            || self.pending
            || self.error.is_some()
            || self.status.state != generator::State::Running
            || self.status.transitioning()
        {
            return None;
        }
        self.device_metrics
            .as_ref()
            .map(|m| m.profile.frames())
            .filter(|&frames| frames >= self.rate as u64)
    }

    pub fn stopped(&self) -> bool {
        self.status.state == generator::State::Stopped
            && !self.starting
            && !self.stopping
            && !self.pending
    }
    pub fn poll(&mut self) {
        if let Some(update) = self.worker.poll() {
            #[cfg(feature = "qa")]
            {
                self.device_metrics = update.device_metrics;
            }
            self.status = update.status;
            let acknowledged = update.acknowledged_request >= self.requested_id;
            if acknowledged && update.error.is_none() && (self.pending || self.starting) {
                self.error = None;
            }
            if let Some(error) = update.error
                && acknowledged
                && (self.pending || self.starting || self.error.is_none())
            {
                self.error = Some(error.to_string());
                self.pending = false;
                self.starting = false;
            }
            if acknowledged {
                self.pending = false;
                self.starting = false;
                self.target = update.target;
                self.rate = update.status.nominal_sample_rate;
                if update.error.is_some() {
                    self.settings = update.status.settings;
                    self.selected = self
                        .selected
                        .min(self.settings.signals.len().saturating_sub(1));
                    self.edited = [[false; 3]; generator::SIGNALS];
                }
            }
            if update.stop_epoch >= self.stop_epoch
                && matches!(
                    self.status.state,
                    generator::State::Stopped | generator::State::Error(_)
                )
            {
                self.stopping = false;
            }
        }
        while let Ok(event) = self.worker.events.try_recv() {
            match event {
                output::Event::Devices(devices) => self.devices = devices,
                output::Event::Error(error) => self.error = Some(error),
            }
        }
    }
    pub(super) fn select(
        &mut self,
        target: output::Target,
        rate: u32,
        settings: generator::Settings,
    ) -> Result<(), String> {
        self.requested_id = self.worker.select(target.clone(), rate, settings)?;
        self.target = target;
        self.rate = rate;
        self.settings = settings;
        self.selected = self.selected.min(settings.signals.len().saturating_sub(1));
        self.texts = std::array::from_fn(|_| std::array::from_fn(|_| String::new()));
        self.edited = [[false; 3]; generator::SIGNALS];
        self.pending = true;
        self.error = None;
        Ok(())
    }
    pub(super) fn configure(&mut self, settings: generator::Settings) {
        match settings
            .validate(self.rate, self.target.channels())
            .map_err(|e| e.to_string())
            .and_then(|()| self.worker.configure(settings))
        {
            Ok(id) => {
                if self
                    .settings
                    .signals
                    .iter()
                    .map(|s| s.id)
                    .ne(settings.signals.iter().map(|s| s.id))
                {
                    self.texts = std::array::from_fn(|_| std::array::from_fn(|_| String::new()));
                    self.edited = [[false; 3]; generator::SIGNALS];
                }
                self.selected = self.selected.min(settings.signals.len().saturating_sub(1));
                self.requested_id = id;
                self.settings = settings;
                self.pending = true;
                self.error = None;
            }
            Err(e) => {
                self.selected = self
                    .selected
                    .min(self.settings.signals.len().saturating_sub(1));
                self.error = Some(e);
            }
        }
    }
    pub fn start(&mut self) {
        match self
            .settings
            .validate(self.rate, self.target.channels())
            .map_err(|e| e.to_string())
            .and_then(|()| self.worker.start(self.settings))
        {
            Ok(id) => {
                self.requested_id = id;
                self.starting = true;
                self.error = None;
            }
            Err(e) => self.error = Some(e),
        }
    }
    pub fn stop(&mut self) {
        self.stop_epoch = self.worker.stop();
        self.pending = false;
        self.stopping = true;
        self.starting = false;
    }
    pub(super) fn label(&self) -> &'static str {
        if self.stopping {
            return "STOPPING";
        }
        if self.starting {
            return "STARTING · pending";
        }
        match self.status.state {
            generator::State::Stopped => "STOPPED",
            generator::State::Starting => "STARTING",
            generator::State::Running => "RUNNING",
            generator::State::Stopping => "STOPPING",
            generator::State::Error(_) => "ERROR",
        }
    }
    pub(super) fn step_label(&self) -> String {
        self.step.to_string()
    }
    fn state_color(&self) -> Color32 {
        match self.status.state {
            generator::State::Error(_) => TRIGGER,
            _ if self.starting || self.stopping => YELLOW,
            generator::State::Starting | generator::State::Stopping => YELLOW,
            generator::State::Stopped => MUTED,
            _ => GREEN,
        }
    }
    fn application_label(&self) -> &'static str {
        if self.pending || self.starting {
            "PENDING"
        } else if matches!(self.status.state, generator::State::Error(_)) {
            "ERROR"
        } else if self.status.transitioning() {
            "TRANSITION"
        } else {
            "APPLIED"
        }
    }
    fn application_color(&self) -> Color32 {
        match self.application_label() {
            "ERROR" => TRIGGER,
            "PENDING" | "TRANSITION" => YELLOW,
            _ => MUTED,
        }
    }
    pub fn restore(&mut self, saved: output::Saved) -> Result<(), String> {
        saved.validate()?;
        // Resolve the exact saved identity/configuration before mutating UI.
        if let output::Target::Audio {
            device_id,
            channels,
            pcm,
            ..
        } = &saved.target
        {
            let config = output::device::Config {
                rate: saved.nominal_sample_rate,
                channels: *channels,
                pcm: *pcm,
            };
            output::device::resolve(&self.devices, device_id, config)?;
        }
        self.select(saved.target, saved.nominal_sample_rate, saved.signals)?;
        Ok(())
    }
}

impl ScopeApp {
    #[cfg(feature = "qa")]
    pub(super) fn check_generator_disconnect(&mut self, ctx: &egui::Context) -> Result<(), String> {
        let mut qa = self.generator.disconnect.take().unwrap();
        if qa.since.elapsed() > Duration::from_secs(180) {
            return Err("Physical disconnect/reconnect QA timed out".into());
        }
        match qa.stage {
            0 => {
                self.check_generator_edits();
                if self.generator.status.state == generator::State::Running
                    && !self.generator.status.transitioning()
                    && self
                        .generator
                        .device_metrics
                        .as_ref()
                        .is_some_and(|m| m.profile.frames() >= self.generator.rate as u64 * 2)
                {
                    qa.stage = 1;
                    qa.since = Instant::now();
                    println!(
                        "Disconnect QA READY: normal GUI input/output RUNNING; unplug UAC-232 USB, leave it disconnected until ERROR is reported."
                    );
                }
            }
            1 => {
                if matches!(self.generator.status.state, generator::State::Error(_)) {
                    qa.error_status = Some(self.generator.status);
                    qa.notifications = self
                        .generator
                        .device_metrics
                        .as_ref()
                        .map_or(0, |m| m.notifications.load(Ordering::Acquire));
                    self.stop();
                    self.generator.devices.clear();
                    self.generator.worker.refresh()?;
                    qa.stage = 2;
                    qa.since = Instant::now();
                    qa.refreshed = Instant::now();
                    self.screenshot_requested = true;
                    self.screenshot_received = false;
                    ctx.send_viewport_cmd(egui::ViewportCommand::Screenshot(Default::default()));
                    println!(
                        "Disconnect QA ERROR latched: {:?}; output notifications {}; reconnect USB now. No Start will be issued.",
                        self.generator.status.state, qa.notifications
                    );
                }
            }
            2 => {
                if !matches!(self.generator.status.state, generator::State::Error(_))
                    || self.generator.starting
                {
                    return Err(
                        "Output resumed or cleared ERROR without explicit reset after disconnect"
                            .into(),
                    );
                }
                if self.pending_stop.is_none()
                    && qa.since.elapsed() > Duration::from_secs(1)
                    && self
                        .generator
                        .devices
                        .iter()
                        .any(|d| d.name == "ZOOM UAC-232")
                {
                    self.generator.restore(output::Saved {
                        target: self.generator.target.clone(),
                        nominal_sample_rate: self.generator.rate,
                        signals: self.generator.settings,
                        use_as_input: false,
                    })?;
                    qa.stage = 3;
                    qa.since = Instant::now();
                    println!(
                        "Disconnect QA reconnected; explicit saved-output restore requested, stays OFF."
                    );
                } else if qa.refreshed.elapsed() > Duration::from_secs(1) {
                    self.generator.worker.refresh()?;
                    qa.refreshed = Instant::now();
                }
            }
            3 => {
                if self.generator.pending {
                } else if !self.generator.stopped() {
                    return Err("Output restoration did not remain OFF".into());
                } else if qa.since.elapsed() > Duration::from_secs(1) {
                    let path = std::path::Path::new("dist/generator-qa/disconnect.json");
                    std::fs::create_dir_all(path.parent().unwrap()).map_err(|e| e.to_string())?;
                    std::fs::write(path,serde_json::to_vec_pretty(&serde_json::json!({"physical_usb_disconnect":true,
                        "error_status":qa.error_status,"notifications_after_stream_release":qa.notifications,
                        "restored_status":self.generator.status,"restored_target":self.generator.target,
                        "input_stopped":!self.running(),"automatic_output_restart":false})).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
                    qa.stage = 4;
                    qa.since = Instant::now();
                    self.screenshot_requested = true;
                    self.screenshot_received = false;
                    ctx.send_viewport_cmd(egui::ViewportCommand::Screenshot(Default::default()));
                    println!(
                        "Disconnect QA OK: real USB failure latched ERROR; stream released; reconnect did not restart; exact saved destination restored OFF; input held."
                    );
                }
            }
            _ => {
                if qa.since.elapsed() > Duration::from_secs(2) {
                    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                }
            }
        }
        self.generator.disconnect = Some(qa);
        ctx.request_repaint_after(Duration::from_millis(16));
        Ok(())
    }
    #[cfg(feature = "qa")]
    pub(super) fn start_generator_profile_input(&mut self) {
        let internal = std::env::var_os("MEASURELAB_PROFILE_GENERATOR_INTERNAL").is_some();
        if (!internal && std::env::var_os("MEASURELAB_PROFILE_GENERATOR_DEVICE").is_none())
            || self.generator.profile_input_started
            || self.created.elapsed() < Duration::from_secs(2)
            || (!internal && self.devices.is_empty())
            || self.generator.starting
            || self.generator.pending
        {
            return;
        }
        if internal && self.generator.stopped() {
            self.generator.start();
            return;
        }
        // Exercise Start after the first GUI frames, as a user would. Any
        // notification after opening input remains a failure; none is ignored.
        assert!(
            self.generator.error.is_none(),
            "Generator output failed: {:?}",
            self.generator.error
        );
        self.generator.profile_input_started = true;
        self.start();
    }

    #[cfg(feature = "qa")]
    pub(super) fn check_generator_edits(&mut self) {
        if std::env::var_os("MEASURELAB_PROFILE_GENERATOR_DEVICE").is_none() {
            return;
        }
        if self.error.is_some() || self.generator.error.is_some() {
            // Preserve diagnostics before the existing strict failure. Reading
            // and serializing telemetry happens on the QA/UI side only.
            if let Err(error) = self.generator_callback_report(false, false) {
                eprintln!("Generator callback report failed: {error}");
            }
        }
        assert!(
            self.error.is_none(),
            "Generator profile input failed: {:?}",
            self.error
        );
        if !self.running() {
            return;
        }
        if !self.generator.profile_output_started {
            if self
                .core
                .as_ref()
                .unwrap()
                .metrics
                .input_frames
                .load(Ordering::Relaxed)
                >= self.sample_rate as u64 / 2
            {
                self.generator.start();
                self.generator.profile_output_started = true;
            }
            return;
        }
        let g = &mut self.generator;
        assert!(g.error.is_none(), "Generator output failed: {:?}", g.error);
        if std::env::var_os("MEASURELAB_PROFILE_GENERATOR_EDITS").is_none()
            || g.starting
            || g.pending
            || g.status.state != generator::State::Running
        {
            return;
        }
        if let Some(sent) = g.edit_pending
            && !g.pending
        {
            g.edit_latencies.push(sent.elapsed().as_secs_f64() * 1000.0);
            g.edit_pending = None;
        }
        let count = g.edit_latencies.len();
        if count < 100
            && g.edit_pending.is_none()
            && self.created.elapsed().as_secs_f64() >= 2.0 * (count + 1) as f64
        {
            let mut settings = g.settings;
            settings.signals[1].phase_degrees = if count == 99 {
                30.0
            } else if count.is_multiple_of(2) {
                20.0
            } else {
                40.0
            };
            g.configure(settings);
            g.edit_pending = Some(Instant::now());
        }
    }

    #[cfg(feature = "qa")]
    pub(super) fn finish_generator_profile(
        &mut self,
        snapshot: &measurement::Snapshot,
    ) -> Result<(), String> {
        let result = self.audit_generator_profile(snapshot);
        // Join releases the stream and its listeners before the notification
        // audit, retaining the counters independently of device ownership.
        self.generator.worker.finish_device_profile();
        self.generator.poll();
        let report = self.generator_callback_report(true, result.is_ok());
        result.and(report)
    }

    #[cfg(feature = "qa")]
    fn generator_callback_report(
        &self,
        streams_released: bool,
        measurement_audit_passed: bool,
    ) -> Result<(), String> {
        let input = self
            .input_callback_metrics
            .as_ref()
            .map(|m| m.profile.report());
        let output = self
            .generator
            .device_metrics
            .as_ref()
            .map(|m| m.profile.report());
        for (label, report) in [("input", &input), ("output", &output)] {
            if let Some(r) = report {
                println!(
                    "Generator {label} callback: {} calls, {} frames, block {:?}..{} frames, elapsed p95 upper {:?} ms, max {:.3} ms, budget p95 upper {:?}%, max {:?}%, over budget {}, notifications {}, xruns {}",
                    r.callbacks,
                    r.frames,
                    r.min_nonempty_frames,
                    r.max_frames,
                    r.processing_p95_upper_ns.map(|n| n as f64 / 1e6),
                    r.processing_max_ns as f64 / 1e6,
                    r.budget_fraction_p95_upper.map(|n| n * 100.0),
                    r.budget_fraction_max.map(|n| n * 100.0),
                    r.over_budget_callbacks,
                    r.notifications,
                    r.xruns,
                );
            }
        }
        let path = std::env::var_os("MEASURELAB_PROFILE_GENERATOR_CALLBACK_REPORT")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|| "dist/generator-qa/callback-profile.json".into());
        if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let document = serde_json::json!({
            "streams_released": streams_released,
            "measurement_audit_passed": measurement_audit_passed,
            "ui_stall_checked": self.ui_stall_checked,
            "timing_basis": "application callback host elapsed time, including preemption; excludes backend wrapper, device latency and scanout",
            "time_bucket_ns": 10000,
            "budget_bucket_fraction": 0.001,
            "nominal_sample_rate_hz": self.sample_rate,
            "input_channels": self.channels,
            "output_target": self.generator.target,
            "output_state": format!("{:?}", self.generator.status.state),
            "output_settings": self.generator.status.settings,
            "output_generation": self.generator.status.output_generation,
            "output_revision": self.generator.status.revision,
            "output_stop_sample": self.generator.status.stop_sample,
            "output_terminal_zero_endpoint": self.generator.status.stopped_at,
            "input": input,
            "output": output,
        });
        std::fs::write(
            &path,
            serde_json::to_vec_pretty(&document).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        println!(
            "Generator callback report: {} (streams released: {streams_released})",
            path.display()
        );
        if streams_released {
            let input = input.ok_or("Missing input callback profile")?;
            let output = output.ok_or("Missing output callback profile")?;
            if self.generator.error.is_some()
                || self.generator.status.state != generator::State::Stopped
            {
                return Err("Generator output failed before stream release completed".into());
            }
            if input.notifications != 0 || output.notifications != 0 {
                return Err("Generator callback audit found stream notifications".into());
            }
            if output.budget_fraction_p95_upper.is_none_or(|n| n > 0.25) {
                return Err(
                    "Generator output callback elapsed p95 exceeded 25% of block duration".into(),
                );
            }
        }
        Ok(())
    }

    #[cfg(feature = "qa")]
    fn audit_generator_profile(&mut self, snapshot: &measurement::Snapshot) -> Result<(), String> {
        if std::env::var_os("MEASURELAB_PROFILE_UI_STALL").is_some() && !self.ui_stall_checked {
            return Err("Generator profile did not exercise the running-output UI stall".into());
        }
        crate::qa::physical_lockin::validate_generator(
            snapshot,
            std::path::Path::new("dist/generator-qa/profile-oracle.json"),
        )?;
        if std::env::var_os("MEASURELAB_PROFILE_COMPARISON").is_some() {
            crate::qa::comparison::validate(
                snapshot,
                std::path::Path::new("dist/comparison-qa/device-oracle.json"),
            )?;
            let document = crate::qa::lockin::document(
                snapshot,
                self.held_input
                    .clone()
                    .ok_or("Missing profile input conditions")?,
                self.core.as_ref().unwrap(),
            )?;
            document.validate()?;
            export::save(
                std::path::Path::new("dist/comparison-qa/device-results.json"),
                &document,
            )?;
            crate::results::save_csv(
                std::path::Path::new("dist/comparison-qa/device-results.csv"),
                &document,
            )?;
            assert_eq!(
                crate::results::load(std::path::Path::new(
                    "dist/comparison-qa/device-results.json"
                ))?
                .comparison,
                document.comparison
            );
        }
        if std::env::var_os("MEASURELAB_PROFILE_GENERATOR_EDITS").is_some() {
            if self.generator.edit_latencies.len() != 100 {
                return Err("Generator edit trial did not complete 100 acknowledgements".into());
            }
            let mut values = self.generator.edit_latencies.clone();
            values.sort_by(f64::total_cmp);
            println!(
                "Generator edits: {} acknowledgements, p95 {:.3} ms, maximum {:.3} ms",
                values.len(),
                values[94],
                values[99]
            );
            std::fs::write(
                "dist/generator-qa/edit-latencies.json",
                serde_json::to_vec_pretty(&values).map_err(|e| e.to_string())?,
            )
            .map_err(|e| e.to_string())?;
            if values[94] >= 100.0 {
                return Err("Generator edit acknowledgement exceeded p95 100 ms".into());
            }
        }
        self.generator.stop();
        let deadline = Instant::now() + Duration::from_secs(3);
        while !self.generator.stopped() {
            self.generator.poll();
            if let Some(error) = &self.generator.error {
                return Err(error.clone());
            }
            if Instant::now() > deadline {
                return Err("Generator finite Stop timed out".into());
            }
            std::thread::sleep(Duration::from_millis(2));
        }
        println!(
            "Generator output finite Stop: generation {}, stop sample {:?}, terminal zero endpoint {:?}, next output frame {}",
            self.generator.status.output_generation,
            self.generator.status.stop_sample,
            self.generator.status.stopped_at,
            self.generator.status.next_sample
        );
        Ok(())
    }

    #[cfg(feature = "qa")]
    pub(super) fn setup_generator_device(
        &mut self,
        name: &str,
        rate: u32,
        start: bool,
    ) -> Result<(), String> {
        if !["ZOOM UAC-232", "BlackHole 2ch", "BlackHole 16ch"].contains(&name) {
            return Err(
                "Generator output QA requires explicit UAC-232 or BlackHole selection".into(),
            );
        }
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            self.generator.poll();
            if !self.generator.devices.is_empty() {
                break;
            }
            if Instant::now() > deadline {
                return Err("Output discovery timed out".into());
            }
            std::thread::sleep(Duration::from_millis(2));
        }
        let device = self
            .generator
            .devices
            .iter()
            .find(|d| d.name == name)
            .ok_or("QA output device unavailable")?;
        let config = device
            .configs
            .iter()
            .find(|c| c.rate == rate && c.pcm == output::device::Pcm::F32)
            .ok_or("QA output config unavailable")?;
        let target = output::Target::Audio {
            device_id: device.id.clone(),
            device_name: device.name.clone(),
            channels: config.channels,
            pcm: config.pcm,
        };
        let mut settings = generator::Settings::default();
        for (i, s) in settings.signals.iter_mut().enumerate() {
            s.enabled = true;
            s.frequency_hz = 750.0;
            s.amplitude_dbfs = 20.0 * (0.1 / (i + 1) as f64).log10();
        }
        settings.signals[1].phase_degrees = 30.0;
        let response = config.channels as usize - 1;
        settings.signals[1].output_channel = Some(response);
        self.scope_channels = Pair([0, response]).scope();
        self.xy_settings.channels = Pair([0, response]);
        self.spectrum_channel = response;
        self.spectrogram_channel = response;
        self.lockin_settings.response_channel = response;
        self.generator.select(target, rate, settings)?;
        while self.generator.pending {
            self.generator.poll();
            if Instant::now() > deadline {
                return Err("Output selection timed out".into());
            }
            std::thread::sleep(Duration::from_millis(2));
        }
        if let Some(error) = &self.generator.error {
            return Err(error.clone());
        }
        self.qa_show(Instrument::Generator);
        if start {
            self.generator.start();
        }
        Ok(())
    }

    #[cfg(feature = "qa")]
    pub(super) fn check_generator_ui(&mut self, mode: &str) -> Result<(), String> {
        self.poll_audio();
        self.core = Some(measurement::Worker::new(self.stft.take_feeder()));
        self.source = Source::Generator;
        self.demo_enabled = false;
        self.presentation.details_visible = matches!(mode, "narrow" | "workspace");
        if mode == "narrow" {
            self.generator.selected = 1;
        }
        self.select_view([
            matches!(mode, "scope" | "narrow" | "workspace"),
            matches!(mode, "spectrum" | "workspace"),
            mode == "workspace",
            mode == "workspace",
        ]);
        self.qa_show(Instrument::Generator);
        if mode == "lockin" {
            self.qa_show(Instrument::Lockin);
        }
        self.lockin_settings = lockin::Settings {
            enabled: true,
            frequency_hz: 750.0,
            time_constant_seconds: 0.005,
            ..Default::default()
        };
        self.comparison_settings = comparison::Settings {
            enabled: true,
            size: 4096,
            averages: 4,
            ..Default::default()
        };
        self.spectrum_channel = 1;
        self.spectrum_settings.size = 8192;
        self.spectrum_settings.averages = 1;
        self.spectrum_settings.window = Window::Rectangular;
        self.spectrum_mode = SpectrumMode::Continuous;
        self.ms_per_div = 512.0 / 480.0;
        self.scope_vertical.fill(Vertical {
            fs_per_div: 0.05,
            offset: 0.0,
        });
        self.acquisition_mode = acquisition::Mode::Auto;
        let mut settings = crate::generator::Settings::default();
        for (i, s) in settings.signals.iter_mut().enumerate() {
            s.enabled = true;
            s.frequency_hz = 750.0;
            s.amplitude_dbfs = 20.0 * (0.125 / (i + 1) as f64).log10();
        }
        settings.signals[1].phase_degrees = 30.0;
        let audio_device = std::env::var("MEASURELAB_UI_SMOKE_GENERATOR_DEVICE").ok();
        if let Some(name) = &audio_device {
            self.setup_generator_device(name, 48000, true)?;
            self.source = Source::Live;
            let deadline = Instant::now() + Duration::from_secs(5);
            while self.devices.is_empty() {
                self.poll_audio();
                if Instant::now() > deadline {
                    return Err("Input discovery timed out".into());
                }
                std::thread::sleep(Duration::from_millis(2));
            }
            self.selected = self
                .devices
                .iter()
                .position(|d| &d.name == name)
                .ok_or("QA input device unavailable")?;
            self.requested_sample_rate = Some(48000);
        } else {
            self.generator.configure(settings);
        }
        let deadline = Instant::now() + Duration::from_secs(5);
        while self.generator.pending {
            self.generator.poll();
            if Instant::now() > deadline {
                return Err("Generator configuration timed out".into());
            }
            std::thread::sleep(Duration::from_millis(2));
        }
        if audio_device.is_none() {
            assert!(self.generator.stopped());
            self.generator.start();
        }
        self.comparison_settings.response_channel = self.lockin_settings.response_channel;
        self.start();
        let deadline = Instant::now() + Duration::from_secs(5);
        while self
            .core
            .as_ref()
            .unwrap()
            .metrics
            .input_frames
            .load(Ordering::Relaxed)
            < 48_000
        {
            self.generator.poll();
            self.poll_audio();
            self.poll_measurement();
            if Instant::now() > deadline {
                return Err("Generator measurement timed out".into());
            }
            if let Some(e) = &self.error {
                return Err(e.clone());
            }
            if let Some(e) = &self.generator.error {
                return Err(e.clone());
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        // No UI result/feedback consumption for a full second. Both execution
        // and the common input/analysis workers must continue independently.
        let count = self
            .core
            .as_ref()
            .unwrap()
            .metrics
            .input_frames
            .load(Ordering::Relaxed);
        std::thread::sleep(Duration::from_secs(1));
        assert!(
            self.core
                .as_ref()
                .unwrap()
                .metrics
                .input_frames
                .load(Ordering::Relaxed)
                > count + 24_000
        );
        self.stop();
        let mut snapshot = self.pending_stop.take().unwrap().wait();
        if audio_device.is_some() {
            crate::qa::physical_lockin::validate_generator(
                &snapshot,
                std::path::Path::new("dist/generator-qa/device-oracle.json"),
            )?;
            if audio_device
                .as_ref()
                .is_some_and(|name| name.starts_with("BlackHole"))
            {
                let result = &snapshot.lockin;
                assert!((result.amplitude_peak.unwrap() - 0.05).abs() < 3e-8);
                assert!((result.phase_degrees.unwrap() - 30.0).abs() < 1e-6);
                assert!((result.reference_frequency_hz.unwrap() - 750.0).abs() < 1e-7);
                assert!((snapshot.measurements[1].rms - 0.05 / 2f64.sqrt()).abs() < 3e-8);
                assert!((snapshot.spectrum.power()[128].sqrt() - 0.05).abs() < 3e-8);
                let last = snapshot.history.channels() - 1;
                for n in result.latest_window.clone() {
                    for &sample in &snapshot.history.get(n).unwrap()[1..last] {
                        assert_eq!(sample, 0.0);
                    }
                }
            }
        }
        crate::qa::comparison::validate(
            &snapshot,
            std::path::Path::new("dist/comparison-qa/generator-ui-oracle.json"),
        )?;
        self.accept_snapshot(&mut snapshot);
        if audio_device.is_some() {
            self.qa_wait_audio_idle()?;
        }
        self.generator.poll();
        assert_eq!(
            self.generator.status.state,
            crate::generator::State::Running
        );
        let document = self.capture_results()?;
        document.validate()?;
        assert_eq!(document.loss.capture_dropped_samples, 0);
        assert!(!document.loss.input_failed);
        if audio_device.is_none() {
            assert!(document.external_output.is_none());
            assert!((self.lockin_result.amplitude_peak.unwrap() - 0.0625).abs() < 1e-8);
            assert!((self.lockin_result.phase_degrees.unwrap() - 30.0).abs() < 1e-6);
            assert!((self.lockin_result.reference_frequency_hz.unwrap() - 750.0).abs() < 1e-7);
            assert!((self.analyzer.power()[128].sqrt() - 0.0625).abs() < 1e-8);
            assert!((self.measurements[1].rms - 0.0625 / 2.0_f64.sqrt()).abs() < 1e-8);
            assert!(
                document
                    .generator_output
                    .as_ref()
                    .unwrap()
                    .stationary(self.lockin_result.sample_range.clone())
                    .is_some()
            );
        } else {
            let history = document
                .external_output
                .as_ref()
                .ok_or("Missing external Generator history")?;
            let observed = history
                .latest
                .as_ref()
                .ok_or("Missing observed output endpoint")?;
            assert_eq!(history.input_generation, document.input.generation);
            assert_eq!(observed.target, self.generator.target);
            assert_eq!(observed.status.nominal_sample_rate, 48_000);
            assert_eq!(observed.status.settings, self.generator.status.settings);
            assert_eq!(
                observed.status.output_generation,
                self.generator.status.output_generation
            );
            assert!(!crate::results::matching_excitation(
                &document,
                document.scope.sample_range.clone(),
                &document,
                document.scope.sample_range.clone(),
            ));
            assert!(
                (self.generator.status.settings.signals[0].amplitude_peak() - 0.1).abs() < 1e-12
            );
            assert_eq!(self.generator.status.nominal_sample_rate, 48000);
            let state = self.generator.status;
            std::fs::write("dist/generator-qa/device-output.json", serde_json::to_vec_pretty(&serde_json::json!({
                "target":self.generator.target, "applied_settings":state.settings,
                "nominal_output_rate":state.nominal_sample_rate, "generation":state.output_generation,
                "revision":state.revision, "applied_sample":state.applied_sample, "output_endpoint":state.next_sample,
                "clock_relation":"Input and output sample positions are independent; no DAC/ADC latency calibration"
            })).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
        }
        std::fs::create_dir_all("dist/generator-qa").map_err(|e| e.to_string())?;
        let saved = self.capture_settings()?;
        settings::save(
            std::path::Path::new("dist/generator-qa/settings.json"),
            &saved,
        )?;
        export::save(
            std::path::Path::new("dist/generator-qa/results.json"),
            &document,
        )?;
        crate::results::save_csv(
            std::path::Path::new("dist/generator-qa/results.csv"),
            &document,
        )?;
        let loaded = crate::results::load(std::path::Path::new("dist/generator-qa/results.json"))?;
        assert_eq!(loaded, document);
        self.generator.stop();
        if audio_device.is_some() {
            self.qa_wait_audio_idle()?;
        }
        let deadline = Instant::now() + Duration::from_secs(5);
        while !self.generator.stopped() {
            self.generator.poll();
            if Instant::now() > deadline {
                return Err("Generator Stop timed out".into());
            }
            std::thread::sleep(Duration::from_millis(2));
        }
        self.restore_settings(settings::load(std::path::Path::new(
            "dist/generator-qa/settings.json",
        ))?)?;
        while self.generator.pending {
            self.generator.poll();
            if Instant::now() > deadline {
                return Err("Generator restore timed out".into());
            }
            std::thread::sleep(Duration::from_millis(2));
        }
        assert!(self.generator.stopped());
        assert!(!self.running());
        assert_eq!(
            self.capture_results()?.generator_output,
            document.generator_output
        );
        assert_eq!(
            self.capture_results()?.external_output,
            document.external_output
        );
        // Leave a live Generator alongside held measurements for the screenshot.
        self.generator.start();
        println!(
            "Generator UI OK: {:?}, Scope/Spectrum/Lock-in, 1 s UI stall, independent input/output Stop, JSON/CSV roundtrip, OFF restore",
            self.generator.target
        );
        Ok(())
    }
    pub(super) fn generator_transport(&mut self, ui: &mut egui::Ui) {
        let g = &mut self.generator;
        ui.label(
            RichText::new(format!("OUTPUT · {}", g.label()))
                .small()
                .monospace()
                .color(g.state_color()),
        )
        .on_hover_text(format!(
            "{} · {} Hz · {}ch. Input Stop holds the measurement; output continues.",
            g.target.label(),
            g.rate,
            g.target.channels()
        ));
        if ui.button("Stop output").clicked() {
            g.stop();
        }
    }

    pub(super) fn generator_controls(&mut self, ui: &mut egui::Ui) {
        let restoring =
            self.workspace_restoring || self.settings_task == Some(SettingsTask::Restore);
        let g = &mut self.generator;
        setting_label(ui, "EDIT STEP");
        egui::ComboBox::from_id_salt("generator_step")
            .width(ui.available_width())
            .selected_text(g.step_label())
            .show_ui(ui, |ui| {
                for value in [0.01, 0.1, 1.0, 10.0, 100.0] {
                    ui.selectable_value(&mut g.step, value, format!("{value}"));
                }
            });
        ui.label(
            RichText::new(
                "± buttons / Up / Down use this step in Hz, dBFS or degrees. Enter / focus applies; Esc cancels.",
            )
            .small()
            .color(MUTED),
        );
        let mut settings = g.settings;
        if let Some(signal) = settings.signals.get_mut(g.selected) {
            setting_label(
                ui,
                &format!("GEN {} · {}", signal.id, signal.waveform.label()),
            );
            ui.add_enabled_ui(g.stopped() && !restoring, |ui| {
                match signal.waveform {
                    generator::Waveform::Noise => {
                        ui.label("White noise · uniform · peak bounded");
                        ui.horizontal(|ui| {
                            ui.label("Seed");
                            ui.add(egui::DragValue::new(&mut signal.noise_seed).range(1..=u64::MAX));
                        });
                        ui.label("Start replays the seed. Frequency and phase do not affect noise.");
                    }
                    generator::Waveform::Square | generator::Waveform::Triangle => {
                        ui.label("Up to 16 odd harmonics below 0.45 Fs. Peak level is the full-scale ceiling; RMS depends on frequency.");
                    }
                    generator::Waveform::Sine => {}
                }
            });
        } else {
            ui.label("Add a signal in the Generator panel.");
        }
        if settings != g.settings {
            g.configure(settings);
        }
        setting_label(ui, "APPLIED OUTPUT");
        ui.label(RichText::new(g.label()).monospace().color(g.state_color()));
        ui.label(format!(
            "{} Hz · {}ch · {} · nominal Fs",
            g.status.nominal_sample_rate,
            g.target.channels(),
            g.target.pcm_label()
        ));
        ui.label(
            RichText::new(g.application_label())
                .monospace()
                .color(g.application_color()),
        );
        for (i, s) in g
            .status
            .settings
            .signals
            .iter()
            .enumerate()
            .filter(|(_, s)| {
                g.settings
                    .signals
                    .get(g.selected)
                    .is_some_and(|selected| selected.id == s.id)
            })
        {
            ui.label(
                RichText::new(format!(
                    "GEN {} · {} · {} · {}",
                    s.id,
                    s.waveform.label(),
                    output_channel_label(*s),
                    if s.enabled { "ON" } else { "OFF" }
                ))
                .color(if i == 0 { GREEN } else { BLUE }),
            );
            ui.label(
                RichText::new(format!(
                    "{:.3} Hz · {:.3} dBFS peak · {:.3}° lead",
                    s.frequency_hz, s.amplitude_dbfs, s.phase_degrees
                ))
                .small(),
            )
            .on_hover_text(format!(
                "Applied: {} Hz · {} dBFS peak · {}° lead",
                s.frequency_hz, s.amplitude_dbfs, s.phase_degrees
            ));
            if s.waveform == generator::Waveform::Noise {
                ui.label(format!("Applied seed {}", s.noise_seed));
            }
        }
        ui.collapsing("Output details", |ui| {
            ui.label(format!(
                "Generation {} · revision {}",
                g.status.output_generation, g.status.revision
            ));
            ui.label(format!("Applied sample {}", g.status.applied_sample));
            ui.label(format!(
                "Selected transition ends {}",
                g.settings
                    .signals
                    .get(g.selected)
                    .and_then(|selected| g
                        .status
                        .settings
                        .signals
                        .iter()
                        .position(|s| s.id == selected.id))
                    .map_or(0, |i| g.status.transition_end[i])
            ));
        });
        self.generator_reset(ui);
    }

    pub(super) fn generator_reset(&mut self, ui: &mut egui::Ui) {
        let enabled = !self.running()
            && self.pending_stop.is_none()
            && !self.workspace_restoring
            && self.settings_task != Some(SettingsTask::Restore);
        let g = &mut self.generator;
        if let Some(error) = &g.error {
            ui.colored_label(TRIGGER, error);
        }
        if matches!(g.status.state, generator::State::Error(_))
            && ui
                .add_enabled(enabled, egui::Button::new("Reset output (stays OFF)"))
                .clicked()
        {
            match g.worker.select(g.target.clone(), g.rate, g.settings) {
                Ok(id) => {
                    g.pending = true;
                    g.requested_id = id;
                }
                Err(e) => g.error = Some(e),
            }
        }
    }

    pub(super) fn generator_panel(&mut self, ui: &mut egui::Ui) {
        let restoring =
            self.workspace_restoring || self.settings_task == Some(SettingsTask::Restore);
        egui::Frame::new().fill(Color32::from_rgb(15, 22, 29))
            .stroke(Stroke::new(1.0, BORDER)).corner_radius(5.0).inner_margin(8.0)
            .show(ui, |ui| {
                ui.spacing_mut().item_spacing = vec2(6.0, 4.0);
                ui.horizontal_wrapped(|ui| {
                    ui.label(RichText::new("Generator").strong().color(GREEN));
                    let g = &mut self.generator;
                    ui.label(RichText::new(g.application_label()).small().monospace().color(g.application_color()))
                        .on_hover_text(format!("Applied Fs: {} Hz (nominal). Settings preview uses FS peak; measured samples are shown in Scope.", g.status.nominal_sample_rate));
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if ui.add_enabled(!g.stopping && !restoring, egui::Button::new(
                            RichText::new(if g.stopped() { "▶ Start output" } else { "■ Stop output" })
                                .color(if g.stopped() { GREEN } else { TRIGGER }))).clicked() {
                            if g.stopped() { g.start(); } else { g.stop(); }
                        }
                    });
                });
                if ui.small_button(if self.generator.controls_expanded { "Hide signal controls" } else { "Show signal controls" }).clicked() {
                    self.generator.controls_expanded = !self.generator.controls_expanded;
                }
                self.generator_reset(ui);
                let g = &mut self.generator;
                let mut settings = g.settings;
                let editable = !g.stopping && !restoring
                    && !matches!(g.status.state, generator::State::Stopping | generator::State::Error(_));
                ui.add_enabled_ui(editable, |ui| {
                    generator_cards(ui, g, &mut settings);
                });
                if settings != g.settings { g.configure(settings); }
            });
    }
}

pub(super) fn output_channel_label(s: generator::Signal) -> String {
    s.output_channel
        .map_or("Unassigned".into(), |c| format!("OUT {}", c + 1))
}

#[derive(Clone, Copy)]
enum CardAction {
    Add,
    Duplicate(usize),
    Remove(usize),
    Move(usize, usize),
}

fn apply_card_action(g: &mut GeneratorUi, settings: &mut generator::Settings, action: CardAction) {
    match action {
        CardAction::Add | CardAction::Duplicate(_) => {
            let source = match action {
                CardAction::Duplicate(i) => Some(i),
                _ => None,
            };
            match settings.add(source, g.target.channels()) {
                Ok(index) => g.selected = index,
                Err(error) => g.error = Some(error.to_string()),
            }
        }
        CardAction::Remove(i) => {
            let selected_id = settings.signals.get(g.selected).map(|s| s.id);
            settings.signals.remove(i);
            g.selected = settings
                .signals
                .iter()
                .position(|s| Some(s.id) == selected_id)
                .unwrap_or(i.min(settings.signals.len().saturating_sub(1)));
        }
        CardAction::Move(from, to) => {
            let id = settings.signals[g.selected].id;
            settings.signals.swap(from, to);
            g.selected = settings.signals.iter().position(|s| s.id == id).unwrap();
        }
    }
}

fn generator_cards(ui: &mut egui::Ui, g: &mut GeneratorUi, settings: &mut generator::Settings) {
    let mut action = None;
    if ui
        .add_enabled(
            g.stopped() && settings.signals.len() < generator::SIGNALS,
            egui::Button::new("+ Add signal"),
        )
        .clicked()
    {
        action = Some(CardAction::Add);
    }
    if !g.stopped() {
        ui.label(
            RichText::new(
                "Stop output to add, remove, duplicate, reorder or change waveform / routing.",
            )
            .small()
            .color(MUTED),
        );
    }
    egui::ScrollArea::vertical()
        .id_salt("generator_cards")
        .show(ui, |ui| {
            if !g.controls_expanded {
                for (index, signal) in settings.signals.iter().enumerate() {
                    if ui
                        .selectable_label(
                            g.selected == index,
                            format!(
                                "GEN {} · {} · {} · {} · {} Hz · {} dBFS peak · {}°",
                                signal.id,
                                signal.waveform.label(),
                                output_channel_label(*signal),
                                if signal.enabled { "ON" } else { "OFF" },
                                display::number(Some(signal.frequency_hz)),
                                display::number(Some(signal.amplitude_dbfs)),
                                display::number(Some(signal.phase_degrees))
                            ),
                        )
                        .clicked()
                    {
                        g.selected = index;
                    }
                }
            } else if ui.available_width() >= 760.0 {
                for row in 0..settings.signals.len().div_ceil(2) {
                    ui.columns(2, |cols| {
                        for (col, column) in cols.iter_mut().enumerate() {
                            let index = row * 2 + col;
                            if index < settings.signals.len() {
                                generator_card(column, g, settings, index, &mut action);
                            }
                        }
                    });
                    ui.add_space(6.0);
                }
            } else {
                ui.horizontal_wrapped(|ui| {
                    for (i, s) in settings.signals.iter().enumerate() {
                        ui.selectable_value(
                            &mut g.selected,
                            i,
                            format!(
                                "GEN {} · {} · {}",
                                s.id,
                                output_channel_label(*s),
                                if s.enabled { "ON" } else { "OFF" }
                            ),
                        );
                    }
                });
                if !settings.signals.is_empty() {
                    generator_card(ui, g, settings, g.selected, &mut action);
                }
            }
            if settings.signals.is_empty() {
                ui.label("No signals. Add a signal to choose its waveform and output.");
            }
        });
    if let Some(action) = action {
        apply_card_action(g, settings, action);
    }
}

pub(super) fn routing_selector(
    ui: &mut egui::Ui,
    settings: &mut generator::Settings,
    index: usize,
    channels: usize,
) {
    let occupied: [bool; 16] = std::array::from_fn(|ch| {
        settings
            .signals
            .iter()
            .enumerate()
            .any(|(i, s)| i != index && s.output_channel == Some(ch))
    });
    let signal = &mut settings.signals[index];
    egui::ComboBox::from_id_salt(("generator_channel", signal.id))
        .width(110.0)
        .selected_text(output_channel_label(*signal))
        .show_ui(ui, |ui| {
            if ui
                .selectable_value(&mut signal.output_channel, None, "Unassigned")
                .changed()
            {
                signal.enabled = false;
            }
            for (ch, &used) in occupied.iter().enumerate().take(channels) {
                ui.add_enabled_ui(!used, |ui| {
                    ui.selectable_value(
                        &mut signal.output_channel,
                        Some(ch),
                        format!("OUT {}{}", ch + 1, if used { " · in use" } else { "" }),
                    );
                });
            }
        });
}

fn generator_card(
    ui: &mut egui::Ui,
    g: &mut GeneratorUi,
    settings: &mut generator::Settings,
    index: usize,
    action: &mut Option<CardAction>,
) -> egui::Response {
    let color = if g.selected == index { GREEN } else { BLUE };
    let len = settings.signals.len();
    egui::Frame::new()
        .fill(Color32::from_rgb(7, 14, 19))
        .stroke(Stroke::new(1.0, color.gamma_multiply(0.45)))
        .corner_radius(4.0)
        .inner_margin(8.0)
        .show(ui, |ui| {
            ui.set_min_width(ui.available_width());
            ui.spacing_mut().item_spacing = vec2(5.0, 4.0);
            ui.horizontal(|ui| {
                if ui
                    .selectable_label(
                        g.selected == index,
                        RichText::new(format!("GEN {}", settings.signals[index].id))
                            .strong()
                            .color(color),
                    )
                    .clicked()
                {
                    g.selected = index;
                }
                ui.add_enabled_ui(g.stopped(), |ui| {
                    routing_selector(ui, settings, index, g.target.channels());
                });
                let s = &mut settings.signals[index];
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    ui.add_enabled_ui(s.output_channel.is_some(), |ui| {
                        ui.checkbox(&mut s.enabled, "ON");
                    });
                });
            });
            ui.horizontal(|ui| {
                ui.add_sized(
                    vec2(72.0, 26.0),
                    egui::Label::new(RichText::new("Waveform").small().color(MUTED))
                        .halign(egui::Align::Min),
                );
                let s = &mut settings.signals[index];
                ui.add_enabled_ui(g.stopped(), |ui| {
                    egui::ComboBox::from_id_salt(("generator_waveform", s.id))
                        .width(130.0)
                        .selected_text(s.waveform.label())
                        .show_ui(ui, |ui| {
                            for waveform in generator::Waveform::ALL {
                                ui.selectable_value(&mut s.waveform, waveform, waveform.label());
                            }
                        });
                });
            });
            let s = &mut settings.signals[index];
            ui.separator();
            for (field, (title, unit, value)) in [
                ("Frequency", "Hz", &mut s.frequency_hz),
                ("Peak level", "dBFS", &mut s.amplitude_dbfs),
                ("Phase lead", "°", &mut s.phase_degrees),
            ]
            .into_iter()
            .enumerate()
            {
                ui.horizontal(|ui| {
                    ui.add_sized(
                        vec2(72.0, 26.0),
                        egui::Label::new(RichText::new(title).small().color(MUTED))
                            .halign(egui::Align::Min),
                    );
                    ui.add_enabled_ui(
                        s.waveform != generator::Waveform::Noise || field == 1,
                        |ui| match numeric_field(
                            ui,
                            (s.id as usize, field),
                            &mut g.texts[index][field],
                            &mut g.edited[index][field],
                            *value,
                            g.step,
                            unit,
                        ) {
                            Ok(Some(next)) => *value = next,
                            Ok(None) => {}
                            Err(e) => g.error = Some(e),
                        },
                    );
                });
            }
            preview(ui, *s, g.rate, color);
            ui.add_enabled_ui(g.stopped(), |ui| {
                ui.horizontal(|ui| {
                    if ui
                        .add_enabled(
                            len < generator::SIGNALS,
                            egui::Button::new("Duplicate").small(),
                        )
                        .clicked()
                    {
                        *action = Some(CardAction::Duplicate(index));
                    }
                    if ui.small_button("Remove").clicked() {
                        *action = Some(CardAction::Remove(index));
                    }
                    if ui
                        .add_enabled(index > 0, egui::Button::new("Up").small())
                        .clicked()
                    {
                        *action = Some(CardAction::Move(index, index - 1));
                    }
                    if ui
                        .add_enabled(index + 1 < len, egui::Button::new("Down").small())
                        .clicked()
                    {
                        *action = Some(CardAction::Move(index, index + 1));
                    }
                });
            });
        })
        .response
}

fn numeric_field(
    ui: &mut egui::Ui,
    id: (usize, usize),
    text: &mut String,
    edited: &mut bool,
    value: f64,
    step: f64,
    unit: &str,
) -> Result<Option<f64>, String> {
    let widget_id = ui.make_persistent_id(("generator_number", id));
    if !ui.memory(|m| m.has_focus(widget_id)) && !*edited {
        *text = format!("{value:.3}");
        *edited = false;
    }
    let mut next = None;
    let mut invalid = false;
    ui.horizontal(|ui| {
        let width = (ui.available_width() - 100.0).max(80.0);
        let response = ui.add(
            egui::TextEdit::singleline(text)
                .id(widget_id)
                .font(egui::FontId::monospace(20.0))
                .desired_width(width),
        );
        *edited |= response.changed();
        // egui releases focus at the start of an Escape frame, before TextEdit
        // returns. That loss must cancel rather than commit a dirty value.
        let escape = (response.has_focus() || response.lost_focus())
            && ui.input(|i| i.key_pressed(egui::Key::Escape));
        let enter = response.has_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter));
        if escape {
            *text = format!("{value:.3}");
            *edited = false;
            response.surrender_focus();
        } else if *edited && (response.lost_focus() || enter) {
            match text.trim().parse::<f64>() {
                Ok(v) if v.is_finite() => next = Some(v),
                _ => invalid = true,
            }
            if enter {
                response.surrender_focus();
            }
            *edited = false;
        }
        response
            .clone()
            .on_hover_text("Enter / focus to apply · Esc to cancel · Up / Down to step");
        ui.add_sized(
            vec2(34.0, 24.0),
            egui::Label::new(RichText::new(unit).small().color(MUTED)),
        );
        if ui.small_button("−").clicked() {
            next = Some(next.unwrap_or(value) - step);
        }
        if ui.small_button("+").clicked() {
            next = Some(next.unwrap_or(value) + step);
        }
        if response.has_focus() {
            let delta = ui.input(|i| {
                if i.key_pressed(egui::Key::ArrowUp) {
                    Some(step)
                } else if i.key_pressed(egui::Key::ArrowDown) {
                    Some(-step)
                } else {
                    None
                }
            });
            if let Some(delta) = delta {
                let base = if *edited {
                    text.trim().parse::<f64>().ok()
                } else {
                    Some(value)
                };
                if let Some(base) = base.filter(|v| v.is_finite()) {
                    next = Some(base + delta);
                    *text = format!("{:.3}", base + delta);
                    *edited = false;
                } else {
                    invalid = true;
                }
            }
        }
    });
    if invalid {
        Err("Enter a finite number; settings were not applied".into())
    } else {
        Ok(next)
    }
}

fn preview(ui: &mut egui::Ui, s: generator::Signal, rate: u32, color: Color32) {
    ui.label(
        RichText::new(format!(
            "Settings preview · ±{:.6} FS ceiling · {}",
            s.amplitude_peak(),
            match s.waveform {
                generator::Waveform::Noise => "white noise".into(),
                _ => format!("{:.3} ms / 2 cycles", 2000.0 / s.frequency_hz),
            }
        ))
        .small()
        .color(MUTED),
    );
    let (rect, _) = ui.allocate_exact_size(vec2(ui.available_width(), 28.0), egui::Sense::hover());
    if !ui.is_rect_visible(rect) {
        return;
    }
    let p = ui.painter();
    p.line_segment(
        [
            pos2(rect.left(), rect.center().y),
            pos2(rect.right(), rect.center().y),
        ],
        Stroke::new(1.0, BORDER),
    );
    let mut noise = s.noise_seed;
    let points: Vec<_> = (0..=128)
        .map(|n| {
            let x = n as f64 / 128.0;
            let y = if s.waveform == generator::Waveform::Noise {
                // A deterministic settings sketch, independent of live output state.
                noise ^= noise >> 12;
                noise ^= noise << 25;
                noise ^= noise >> 27;
                2.0 * (noise.wrapping_mul(0x2545_f491_4f6c_dd1d) >> 11) as f64
                    / (1_u64 << 53) as f64
                    - 1.0
            } else {
                s.waveform
                    .periodic(2.0 * x + s.phase_degrees / 360.0, s.frequency_hz, rate)
            };
            pos2(
                rect.left() + x as f32 * rect.width(),
                rect.center().y - y as f32 * rect.height() * 0.45,
            )
        })
        .collect();
    p.add(egui::Shape::line(points, Stroke::new(1.5, color)));
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cards_frame(
        ctx: &egui::Context,
        g: &mut GeneratorUi,
        events: Vec<egui::Event>,
    ) -> egui::FullOutput {
        let mut settings = g.settings;
        let mut output = ctx.run_ui(
            egui::RawInput {
                screen_rect: Some(egui::Rect::from_min_size(
                    pos2(0.0, 0.0),
                    vec2(580.0, 760.0),
                )),
                events,
                ..Default::default()
            },
            |ui| {
                generator_cards(ui, g, &mut settings);
            },
        );
        // Exercise the actual card widgets without issuing audio commands.
        g.settings = settings;
        output.textures_delta.clear();
        output
    }

    fn cards_click(ctx: &egui::Context, g: &mut GeneratorUi, label: &str) {
        fn find(shape: &egui::Shape, label: &str) -> Option<egui::Pos2> {
            match shape {
                egui::Shape::Text(text) if text.galley.text() == label => {
                    Some(text.visual_bounding_rect().center())
                }
                egui::Shape::Vec(shapes) => shapes.iter().find_map(|s| find(s, label)),
                _ => None,
            }
        }
        let output = cards_frame(ctx, g, vec![]);
        let pos = output
            .shapes
            .iter()
            .rev()
            .find_map(|s| find(&s.shape, label).filter(|p| s.clip_rect.contains(*p)))
            .unwrap_or_else(|| panic!("Card control not visible: {label}"));
        for pressed in [true, false] {
            cards_frame(
                ctx,
                g,
                vec![
                    egui::Event::PointerMoved(pos),
                    egui::Event::PointerButton {
                        pos,
                        button: egui::PointerButton::Primary,
                        pressed,
                        modifiers: egui::Modifiers::NONE,
                    },
                ],
            )
            .drop_without_applying_deltas();
        }
    }

    #[test]
    fn card_widgets_select_waveforms_reject_occupied_outputs_and_manage_stable_ids() {
        let ctx = egui::Context::default();
        let mut g = GeneratorUi::default();
        for _ in 0..2 {
            cards_frame(&ctx, &mut g, vec![]).drop_without_applying_deltas();
        }
        cards_click(&ctx, &mut g, "Sine");
        cards_click(&ctx, &mut g, "Square");
        assert_eq!(g.settings.signals[0].waveform, generator::Waveform::Square);
        cards_click(&ctx, &mut g, "OUT 1");
        cards_click(&ctx, &mut g, "OUT 2 · in use");
        assert_eq!(g.settings.signals[0].output_channel, Some(0));
        cards_frame(
            &ctx,
            &mut g,
            vec![key(egui::Key::Escape, egui::Modifiers::NONE)],
        )
        .drop_without_applying_deltas();
        cards_click(&ctx, &mut g, "Duplicate");
        assert_eq!(g.settings.signals.len(), 3);
        assert_eq!(
            (
                g.settings.signals[2].id,
                g.settings.signals[2].output_channel
            ),
            (3, None)
        );
        assert_eq!(g.settings.signals[2].waveform, generator::Waveform::Square);
        assert_eq!(g.selected, 2);
        cards_click(&ctx, &mut g, "Up");
        assert_eq!((g.selected, g.settings.signals[1].id), (1, 3));
        cards_click(&ctx, &mut g, "Remove");
        assert_eq!(
            g.settings
                .signals
                .iter()
                .map(|s| (s.id, s.output_channel))
                .collect::<Vec<_>>(),
            vec![(1, Some(0)), (2, Some(1))]
        );
        cards_click(&ctx, &mut g, "+ Add signal");
        assert_eq!(g.settings.signals[2].id, 4);
        for _ in 0..3 {
            cards_click(&ctx, &mut g, "Remove");
        }
        assert!(g.settings.signals.is_empty());
        cards_click(&ctx, &mut g, "+ Add signal");
        assert_eq!(
            (
                g.settings.signals[0].id,
                g.settings.signals[0].output_channel
            ),
            (5, Some(0))
        );
        cards_click(&ctx, &mut g, "Sine");
        cards_click(&ctx, &mut g, "Noise");
        assert_eq!(g.settings.signals[0].waveform, generator::Waveform::Noise);
        g.settings.validate(48000, 2).unwrap();
        assert_eq!((g.requested_id, g.stop_epoch), (0, 0));
    }

    #[test]
    fn rejected_edit_keeps_card_selection_inside_the_applied_list() {
        let mut g = GeneratorUi::default();
        let mut candidate = g.settings;
        g.selected = candidate.add(None, 2).unwrap();
        candidate.signals[0].frequency_hz = -1.0;
        g.configure(candidate);
        assert_eq!(g.settings.signals.len(), 2);
        assert!(g.selected < g.settings.signals.len());
        assert!(g.error.is_some());
        assert_eq!((g.requested_id, g.stop_epoch), (0, 0));
    }

    #[test]
    fn cards_fit_columns_without_consuming_the_measurement_height() {
        fn text_rects(shape: &egui::Shape, rects: &mut Vec<(String, egui::Rect)>) {
            match shape {
                egui::Shape::Text(text) => {
                    rects.push((text.galley.text().into(), text.visual_bounding_rect()));
                }
                egui::Shape::Vec(shapes) => {
                    for shape in shapes {
                        text_rects(shape, rects);
                    }
                }
                _ => {}
            }
        }
        let mut g = GeneratorUi::default();
        let mut settings = g.settings;
        settings.signals[0].frequency_hz = 345_599.999;
        settings.signals[1].amplitude_dbfs = -120.0;
        settings.signals[1].phase_degrees = -180.0;
        for width in [320.0, 370.0, 540.0, 700.0] {
            let ctx = egui::Context::default();
            ctx.global_style_mut(|style| {
                style.spacing.button_padding = vec2(8.0, 4.0);
            });
            for _ in 0..2 {
                let mut cards = Vec::new();
                let output = ctx.run_ui(
                    egui::RawInput {
                        screen_rect: Some(egui::Rect::from_min_size(
                            pos2(0.0, 0.0),
                            vec2(1440.0, 860.0),
                        )),
                        ..Default::default()
                    },
                    |ui| {
                        ui.set_width(width);
                        for index in 0..2 {
                            let response =
                                generator_card(ui, &mut g, &mut settings, index, &mut None);
                            cards.push(response.rect);
                            assert!(
                                response.rect.width() <= width + 1.0,
                                "card exceeds its column: {:?}",
                                response.rect
                            );
                            assert!(
                                response.rect.height() <= 280.0,
                                "card leaves too little space for measurement: {:?}",
                                response.rect
                            );
                        }
                    },
                );
                let mut texts = Vec::new();
                for shape in &output.shapes {
                    text_rects(&shape.shape, &mut texts);
                }
                for (index, card) in cards.iter().enumerate() {
                    let rect = |label: &str| {
                        texts
                            .iter()
                            .find(|(text, rect)| text == label && card.contains(rect.center()))
                            .unwrap_or_else(|| panic!("Card control not visible: {label}"))
                            .1
                    };
                    let title = rect(&format!("GEN {}", settings.signals[index].id));
                    let on = rect("ON");
                    assert!(
                        (card.right() - 8.0 - on.right()).abs() <= 2.0,
                        "ON must stay at the card's right edge: {on:?}, {card:?}"
                    );
                    assert!((title.center().y - on.center().y).abs() <= 2.0);
                    let waveform = rect("Waveform");
                    for label in ["Frequency", "Peak level", "Phase lead"] {
                        assert!((rect(label).left() - waveform.left()).abs() <= 1.0);
                    }
                    for (_, text) in texts.iter().filter(|(_, r)| card.contains(r.center())) {
                        assert!(card.expand(1.0).contains_rect(*text));
                    }
                }
                output.drop_without_applying_deltas();
            }
        }
    }

    #[test]
    fn on_checkbox_changes_only_its_card_and_requires_an_output() {
        let ctx = egui::Context::default();
        let mut g = GeneratorUi::default();
        for _ in 0..2 {
            cards_frame(&ctx, &mut g, vec![]).drop_without_applying_deltas();
        }
        cards_click(&ctx, &mut g, "ON");
        assert!(g.settings.signals[0].enabled);
        assert!(!g.settings.signals[1].enabled);
        cards_click(&ctx, &mut g, "GEN 2 · OUT 2 · OFF");
        cards_click(&ctx, &mut g, "ON");
        assert!(g.settings.signals.iter().all(|s| s.enabled));
        assert_eq!(g.selected, 1);
        cards_click(&ctx, &mut g, "OUT 2");
        cards_click(&ctx, &mut g, "Unassigned");
        cards_click(&ctx, &mut g, "ON");
        assert_eq!(g.settings.signals[1].output_channel, None);
        assert!(!g.settings.signals[1].enabled);
        assert!(g.settings.signals[0].enabled);
        g.settings.validate(g.rate, g.target.channels()).unwrap();
    }

    fn key(key: egui::Key, modifiers: egui::Modifiers) -> egui::Event {
        egui::Event::Key {
            key,
            physical_key: None,
            pressed: true,
            repeat: false,
            modifiers,
        }
    }
    fn edit_frame(
        ctx: &egui::Context,
        text: &mut String,
        edited: &mut bool,
        events: Vec<egui::Event>,
        focus: bool,
    ) -> Result<Option<f64>, String> {
        let mut result = Ok(None);
        let output = ctx.run_ui(
            egui::RawInput {
                screen_rect: Some(egui::Rect::from_min_size(
                    pos2(0.0, 0.0),
                    vec2(600.0, 200.0),
                )),
                events,
                ..Default::default()
            },
            |ui| {
                if focus {
                    let id = ui.make_persistent_id(("generator_number", (0usize, 0usize)));
                    ui.memory_mut(|m| m.request_focus(id));
                }
                result = numeric_field(ui, (0, 0), text, edited, 750.123456789, 1.0, "Hz");
            },
        );
        output.drop_without_applying_deltas();
        result
    }
    #[test]
    fn numeric_input_cancels_escape_commits_enter_and_steps_drafts_without_rounding_applied_values()
    {
        for (finish, expected) in [
            (egui::Key::Escape, None),
            (egui::Key::Enter, Some(750.987654321)),
            (egui::Key::Tab, Some(750.987654321)),
            (egui::Key::ArrowUp, Some(751.987654321)),
            (egui::Key::ArrowDown, Some(749.987654321)),
        ] {
            let ctx = egui::Context::default();
            let mut text = String::new();
            let mut edited = false;
            edit_frame(&ctx, &mut text, &mut edited, vec![], true).unwrap();
            let result = edit_frame(
                &ctx,
                &mut text,
                &mut edited,
                vec![
                    key(egui::Key::A, egui::Modifiers::COMMAND),
                    egui::Event::Text("750.987654321".into()),
                ],
                false,
            )
            .unwrap();
            assert_eq!(result, None);
            assert_eq!(text, "750.987654321");
            assert!(edited);
            let first = edit_frame(
                &ctx,
                &mut text,
                &mut edited,
                vec![key(finish, egui::Modifiers::NONE)],
                false,
            )
            .unwrap();
            let second = edit_frame(&ctx, &mut text, &mut edited, vec![], false).unwrap();
            assert_eq!(first.or(second), expected, "{finish:?}");
            assert!(!edited);
        }
        let ctx = egui::Context::default();
        let mut text = String::new();
        let mut edited = false;
        edit_frame(&ctx, &mut text, &mut edited, vec![], true).unwrap();
        assert_eq!(
            edit_frame(
                &ctx,
                &mut text,
                &mut edited,
                vec![key(egui::Key::Enter, egui::Modifiers::NONE)],
                false
            )
            .unwrap(),
            None
        );
    }
}
