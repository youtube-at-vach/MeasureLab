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
    pub visible: bool,
    pub pending: bool,
    pub starting: bool,
    pub stopping: bool,
    pub error: Option<String>,
    requested_id: u64,
    stop_epoch: u64,
    texts: [[String; 3]; 2],
    edited: [[bool; 3]; 2],
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
            visible: false,
            pending: false,
            starting: false,
            stopping: false,
            error: None,
            requested_id: 0,
            stop_epoch: 0,
            texts: std::array::from_fn(|_| std::array::from_fn(|_| String::new())),
            edited: [[false; 3]; 2],
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
        }
    }
}
impl GeneratorUi {
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
    fn select(
        &mut self,
        target: output::Target,
        rate: u32,
        settings: generator::Settings,
    ) -> Result<(), String> {
        self.requested_id = self.worker.select(target.clone(), rate, settings)?;
        self.target = target;
        self.rate = rate;
        self.settings = settings;
        self.pending = true;
        self.error = None;
        Ok(())
    }
    fn configure(&mut self, settings: generator::Settings) {
        match settings
            .validate(self.rate, self.target.channels())
            .map_err(|e| e.to_string())
            .and_then(|()| self.worker.configure(settings))
        {
            Ok(id) => {
                self.requested_id = id;
                self.settings = settings;
                self.pending = true;
                self.error = None;
            }
            Err(e) => self.error = Some(e),
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
    fn label(&self) -> &'static str {
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
    pub(super) fn start_generator_profile_input(&mut self) {
        if std::env::var_os("MEASURELAB_PROFILE_GENERATOR_DEVICE").is_none()
            || self.generator.profile_input_started
            || self.created.elapsed() < Duration::from_secs(2)
            || self.devices.is_empty()
            || self.generator.starting
            || self.generator.pending
        {
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
        self.scope_channels = Pair([0, response]);
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
        self.generator.visible = true;
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
        self.generator.visible = true;
        self.sidebar.visible = mode == "narrow";
        if mode == "narrow" {
            self.generator.selected = 1;
        }
        self.visible = [
            mode == "scope" || mode == "narrow",
            mode == "spectrum",
            false,
            false,
        ];
        self.lockin_visible = mode == "lockin";
        self.lockin_settings = lockin::Settings {
            enabled: true,
            frequency_hz: 750.0,
            time_constant_seconds: 0.005,
            ..Default::default()
        };
        self.spectrum_channel = 1;
        self.spectrum_settings.size = 8192;
        self.spectrum_settings.averages = 1;
        self.spectrum_settings.window = Window::Rectangular;
        self.spectrum_mode = SpectrumMode::Continuous;
        self.ms_per_div = 512.0 / 480.0;
        self.fs_per_div = 0.05;
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
        ui.horizontal_wrapped(|ui| {
            ui.label(
                RichText::new(format!("OUTPUT · {} · {}", g.label(), g.target.label()))
                    .monospace()
                    .color(if g.stopped() { MUTED } else { GREEN }),
            );
            if ui.small_button("Stop all outputs").clicked() {
                g.stop();
            }
            ui.label(
                RichText::new("Input Stop holds the measurement; output continues.")
                    .small()
                    .color(MUTED),
            );
        });
    }

    pub(super) fn generator_panel(&mut self, ui: &mut egui::Ui) {
        let input_running = self.running() || self.pending_stop.is_some();
        let restoring =
            self.workspace_restoring || self.settings_task == Some(SettingsTask::Restore);
        egui::Frame::new()
            .fill(Color32::from_rgb(15, 22, 29))
            .stroke(Stroke::new(1.0, BORDER))
            .corner_radius(5.0)
            .inner_margin(10.0)
            .show(ui, |ui| {
                ui.horizontal_wrapped(|ui| {
                    ui.label(RichText::new("Generator").strong().color(GREEN));
                    let g = &mut self.generator;
                    ui.label(format!("{}ch · {} · nominal Fs", g.target.channels(), g.target.pcm_label()));
                });
                let g = &mut self.generator;
                ui.add_enabled_ui(g.stopped() && !input_running && !restoring, |ui| {
                    ui.horizontal_wrapped(|ui| {
                        let mut selected = g.target.clone();
                        let mut rate = g.rate;
                        egui::ComboBox::from_id_salt("generator_destination")
                            .width(180.0).truncate()
                            .selected_text(g.target.label()).show_ui(ui, |ui| {
                                ui.selectable_value(&mut selected, output::Target::Internal, "Internal loopback");
                                for device in &g.devices {
                                    let config = device.preferred;
                                    let candidate = output::Target::Audio { device_id: device.id.clone(),
                                        device_name: device.name.clone(), channels: config.channels, pcm: config.pcm };
                                    let active = matches!(&g.target, output::Target::Audio { device_id, .. } if device_id == &device.id);
                                    if ui.selectable_label(active, &device.name).clicked() && !active {
                                        selected = candidate; rate = config.rate;
                                    }
                                }
                            });
                        if ui.small_button("Refresh outputs").clicked()
                            && let Err(e) = g.worker.refresh() { g.error = Some(e); }
                        if selected != g.target {
                            if selected == output::Target::Internal { rate = 48000; }
                            let mut settings = g.settings;
                            for signal in &mut settings.signals {
                                if signal.output_channel.is_some_and(|ch| ch >= selected.channels()) {
                                    signal.output_channel = None; signal.enabled = false;
                                }
                            }
                            if let Err(e) = g.select(selected, rate, settings) { g.error = Some(e); }
                        }
                        let mut config = output::device::Config { rate: g.rate,
                            channels: g.target.channels() as u16,
                            pcm: match &g.target { output::Target::Audio { pcm, .. } => *pcm, _ => output::device::Pcm::F64 } };
                        let before = config;
                        egui::ComboBox::from_id_salt("generator_rate")
                            .width(180.0).truncate()
                            .selected_text(format!("{} Hz · {}ch · {}", config.rate, config.channels, config.pcm.label()))
                            .show_ui(ui, |ui| {
                                let configs: Vec<_> = match &g.target {
                                    output::Target::Internal => output::RATES.into_iter().map(|rate| output::device::Config { rate, ..config }).collect(),
                                    output::Target::Audio { device_id, .. } => g.devices.iter().find(|d| &d.id == device_id).map(|d| d.configs.clone()).unwrap_or_default(),
                                };
                                for value in configs { ui.selectable_value(&mut config, value,
                                    format!("{} Hz · {}ch · {}", value.rate, value.channels, value.pcm.label())); }
                            });
                        if config != before {
                            let mut target = g.target.clone();
                            if let output::Target::Audio { channels, pcm, .. } = &mut target { *channels = config.channels; *pcm = config.pcm; }
                            if let Err(e) = g.select(target, config.rate, g.settings) { g.error = Some(e); }
                        }
                    });
                });
                ui.horizontal_wrapped(|ui| {
                    ui.add_enabled_ui(!g.stopping && !restoring, |ui| {
                        if ui
                            .button(if g.stopped() {
                                "Start output"
                            } else {
                                "Stop output"
                            })
                            .clicked()
                        {
                            if g.stopped() {
                                g.start();
                            } else {
                                g.stop();
                            }
                        }
                        if ui
                            .add_enabled(
                                !g.stopped() && !g.starting,
                                egui::Button::new("Align phases"),
                            )
                            .clicked()
                        {
                            match g.worker.align() {
                                Ok(id) => {
                                    g.pending = true;
                                    g.requested_id = id;
                                }
                                Err(e) => g.error = Some(e),
                            }
                        }
                    });
                });
                ui.horizontal_wrapped(|ui| {
                    if ui
                        .add_enabled(
                            !input_running && !self.busy && !restoring && self.generator.target == output::Target::Internal,
                            egui::Button::new("Observe Generator")
                                .selected(self.source == Source::Generator),
                        )
                        .clicked()
                        && self.source != Source::Generator
                    {
                        self.source = Source::Generator;
                        self.switch_source();
                    }
                    ui.label(
                        RichText::new("Select ON channels, then Start output and Start input.")
                            .small()
                            .color(MUTED),
                    );
                });
                let g = &mut self.generator;
                ui.horizontal_wrapped(|ui| {
                    ui.label(
                        RichText::new(if g.pending {
                            "PENDING"
                        } else if g.status.transitioning() {
                            "TRANSITION"
                        } else {
                            "APPLIED"
                        })
                        .monospace()
                        .color(YELLOW),
                    );
                    ui.label(
                        RichText::new(format!(
                            "Applied Fs: {} Hz · sine amplitude uses FS peak",
                            g.status.nominal_sample_rate,
                        ))
                        .small()
                        .color(MUTED),
                    );
                });
                if let Some(error) = &g.error {
                    ui.colored_label(TRIGGER, error);
                }
                if matches!(g.status.state, generator::State::Error(_))
                    && !input_running
                    && ui.button("Reset output (stays OFF)").clicked()
                {
                    match g.worker.select(g.target.clone(), g.rate, g.settings) {
                        Ok(id) => {
                            g.pending = true;
                            g.requested_id = id;
                        }
                        Err(e) => g.error = Some(e),
                    }
                }
                ui.collapsing("Output details", |ui| {
                    ui.label(format!(
                        "generation {} · revision {} · applied sample {} · transition ends {}, {}",
                        g.status.output_generation,
                        g.status.revision,
                        g.status.applied_sample,
                        g.status.transition_end[0],
                        g.status.transition_end[1]
                    ));
                    for (i, s) in g.status.settings.signals.iter().enumerate() {
                        ui.label(format!(
                            "Applied GEN {}: {} Hz · {} dBFS peak · {}° · {}",
                            i + 1,
                            s.frequency_hz,
                            s.amplitude_dbfs,
                            s.phase_degrees,
                            if s.enabled { "ON" } else { "OFF" }
                        ));
                    }
                });
                let mut settings = g.settings;
                let editable = !g.stopping
                    && !restoring
                    && !matches!(
                        g.status.state,
                        generator::State::Stopping | generator::State::Error(_)
                    );
                let routing = g.stopped();
                ui.add_enabled_ui(editable, |ui| {
                    if ui.available_width() >= 680.0 {
                        ui.columns(2, |cols| {
                            for (i, col) in cols.iter_mut().enumerate() {
                                generator_card(col, g, &mut settings, i, routing);
                            }
                        });
                    } else if ui.available_height() >= 620.0 {
                        for i in 0..2 {
                            generator_card(ui, g, &mut settings, i, routing);
                        }
                    } else {
                        // One compact card with a fixed summary for both outputs.
                        ui.horizontal(|ui| {
                            for (i, s) in settings.signals.iter().enumerate() {
                                ui.selectable_value(
                                    &mut g.selected,
                                    i,
                                    format!(
                                        "GEN {} · OUT {} · {}",
                                        i + 1,
                                        s.output_channel
                                            .map_or("—".into(), |c| (c + 1).to_string()),
                                        if s.enabled { "ON" } else { "OFF" }
                                    ),
                                );
                            }
                        });
                        generator_card(ui, g, &mut settings, g.selected, routing);
                    }
                });
                if settings != g.settings {
                    g.configure(settings);
                }
            });
        if self.source == Source::Generator && self.generator.target != output::Target::Internal {
            self.source = Source::Live;
            self.switch_source();
        }
    }
}

fn generator_card(
    ui: &mut egui::Ui,
    g: &mut GeneratorUi,
    settings: &mut generator::Settings,
    index: usize,
    routing: bool,
) {
    let color = if index == 0 { GREEN } else { BLUE };
    let s = &mut settings.signals[index];
    egui::Frame::new()
        .fill(Color32::from_rgb(7, 14, 19))
        .stroke(Stroke::new(1.0, color.gamma_multiply(0.45)))
        .corner_radius(4.0)
        .inner_margin(8.0)
        .show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.label(
                    RichText::new(format!("GEN {} · Sine", index + 1))
                        .strong()
                        .color(color),
                );
                ui.checkbox(&mut s.enabled, "ON");
                ui.add_enabled_ui(routing, |ui| {
                    egui::ComboBox::from_id_salt(("generator_channel", index))
                        .selected_text(
                            s.output_channel
                                .map_or("Unassigned".into(), |c| format!("OUT {}", c + 1)),
                        )
                        .show_ui(ui, |ui| {
                            ui.selectable_value(&mut s.output_channel, None, "Unassigned");
                            for c in 0..g.target.channels() {
                                ui.selectable_value(
                                    &mut s.output_channel,
                                    Some(c),
                                    format!("OUT {}", c + 1),
                                );
                            }
                        });
                });
            });
            ui.horizontal(|ui| {
                ui.label(RichText::new("Step").small().color(MUTED));
                egui::ComboBox::from_id_salt(("generator_step", index))
                    .selected_text(format!("{}", g.step))
                    .show_ui(ui, |ui| {
                        for value in [0.01, 0.1, 1.0, 10.0, 100.0] {
                            ui.selectable_value(&mut g.step, value, format!("{value}"));
                        }
                    });
                ui.label(
                    RichText::new("Enter / focus to apply · Esc to cancel")
                        .small()
                        .color(MUTED),
                );
            });
            for (field, (title, unit, value)) in [
                ("FREQUENCY", "Hz", &mut s.frequency_hz),
                ("AMPLITUDE · PEAK", "dBFS", &mut s.amplitude_dbfs),
                ("PHASE · LEAD", "°", &mut s.phase_degrees),
            ]
            .into_iter()
            .enumerate()
            {
                ui.label(RichText::new(title).small().color(MUTED));
                match numeric_field(
                    ui,
                    (index, field),
                    &mut g.texts[index][field],
                    &mut g.edited[index][field],
                    *value,
                    g.step,
                    unit,
                ) {
                    Ok(Some(next)) => *value = next,
                    Ok(None) => {}
                    Err(e) => g.error = Some(e),
                }
            }
            preview(ui, *s, color);
        });
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
        let width = (ui.available_width() - 120.0).max(100.0);
        let response = ui.add(
            egui::TextEdit::singleline(text)
                .id(widget_id)
                .font(egui::FontId::monospace(27.0))
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
        ui.label(RichText::new(unit).color(MUTED));
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

fn preview(ui: &mut egui::Ui, s: generator::Signal, color: Color32) {
    ui.label(
        RichText::new(format!(
            "Settings preview · ±{:.6} FS peak · {:.3} ms / 2 cycles",
            s.amplitude_peak(),
            2000.0 / s.frequency_hz
        ))
        .small()
        .color(MUTED),
    );
    let (rect, _) = ui.allocate_exact_size(vec2(ui.available_width(), 52.0), egui::Sense::hover());
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
    let points: Vec<_> = (0..=128)
        .map(|n| {
            let x = n as f64 / 128.0;
            let y = (std::f64::consts::TAU * 2.0 * x + s.phase_degrees.to_radians()).sin();
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
