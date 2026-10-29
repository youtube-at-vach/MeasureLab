//! UI-independent acquisition, shared f64 history and measurement scheduling.
//! The callback transfers fixed frames; this worker never waits for a display.
#![warn(clippy::redundant_clone)]
#[cfg(any(test, feature = "qa"))]
use crate::demo::Demo;
use crate::{
    acquisition::{self, Acquisition},
    activity::Activity,
    audio::Capture,
    calibration::{self, Reading},
    channel::{ChannelId, Pair, SCOPE_CHANNELS, ScopeChannels},
    comparison, comparison_worker, lockin, lockin_worker, loopback, output,
    signal::{self, History, Measurement, Sweep, Trigger},
    spectrum::{self, Settings},
    spectrum_worker, stft,
};
use rtrb::{Consumer, Producer, RingBuffer};
use std::{
    ops::Range,
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU64, Ordering},
        mpsc,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

const SNAPSHOTS: usize = 3;
const DISPLAY_INTERVAL: Duration = Duration::from_nanos(33_333_333);

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SpectrumMode {
    /// Responsive latest-window observation, up to 60 Hz with a CPU budget.
    /// No transient coverage guarantee; independent of UI visibility/cadence.
    Live,
    /// Every complete N/4-hop window; average/hold updates follow sample time.
    #[default]
    Continuous,
    /// Lower-load latest-window observation; transients can go unobserved.
    Latest,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ScopeSettings {
    pub mode: acquisition::Mode,
    pub channels: ScopeChannels,
    pub samples: usize,
    pub trigger: Trigger,
}

impl Default for ScopeSettings {
    fn default() -> Self {
        Self {
            mode: acquisition::Mode::Auto,
            channels: ScopeChannels::default(),
            samples: 480,
            trigger: Trigger::default(),
        }
    }
}

#[derive(Clone, Debug)]
pub struct Config {
    pub comparison: comparison::Settings,
    pub lockin: lockin::Settings,
    pub spectrum: Settings,
    pub spectrum_channel: ChannelId,
    pub spectrum_mode: SpectrumMode,
    pub scope: ScopeSettings,
    /// Scope/Spectrum calibration, fixed for this input generation.
    pub calibrations: calibration::Set,
    pub xy_channels: Pair,
    pub stft_generation: u64,
    pub stft: stft::Config,
}

#[derive(Clone, Debug, Default)]
pub struct SpectrumInfo {
    pub mode: SpectrumMode,
    /// Processed windows since the last settings/input/gap reset.
    pub updates: u64,
    pub contributing: Range<u64>,
    /// Scheduled windows invalidated by input discontinuities, across resets.
    pub missing_windows: u64,
    /// Complete windows invalidated by nonfinite samples/calibrated power.
    pub invalid_windows: u64,
    pub observation_ms: u32,
    pub missed_observations: u64,
    /// Missing source samples observed by the Spectrum transport, separate from capture loss.
    pub input_missing: u64,
    pub input_end: u64,
    pub filled_samples: usize,
}

#[derive(Clone)]
pub struct Snapshot {
    pub generator_output: Option<output::Timeline>,
    pub external_output: Option<output::history::ExternalOutput>,
    pub comparison: Arc<comparison::Result>,
    pub lockin: lockin::Result,
    pub scope_capture: Option<History>,
    pub acquisition_state: acquisition::State,
    pub generation: u64,
    pub revision: u64,
    pub sample_rate: u32,
    pub history: History,
    pub spectrum: spectrum::Result,
    pub spectrum_info: SpectrumInfo,
    /// Additional display traces, delivered only by an explicit result barrier.
    pub spectrum_overlays: Vec<(usize, spectrum::Result, SpectrumInfo)>,
    #[cfg(feature = "qa")]
    pub spectrum_timing: Option<spectrum_worker::Timing>,
    /// Maps independently delivered STFT rows to this input generation.
    pub stft_generation: u64,
    pub stft_config: stft::Config,
    pub scope_settings: ScopeSettings,
    pub xy_channels: Pair,
    pub sweep: Sweep,
    pub measurements: [Measurement; SCOPE_CHANNELS],
    pub scope_readings: [Reading; SCOPE_CHANNELS],
    /// Immutable coefficients/units/reference conditions for numeric readouts.
    pub calibrations: calibration::Set,
    pub scope_missing: u64,
    /// Capture loss is separate from display publications and STFT delivery.
    pub input_dropped: u64,
    pub failed: bool,
    pub fft_ms: f64,
    /// Regular Scope/XY snapshots never carry Spectrum bin arrays.
    pub has_spectrum: bool,
}

#[derive(Default)]
pub struct Metrics {
    pub single_complete: AtomicBool,
    pub failed: AtomicBool,
    pub input_frames: AtomicU64,
    pub display_skipped: AtomicU64,
    pub processing_nanos: AtomicU64,
    pub input_poll_max_nanos: AtomicU64,
    pub demo_interval_max_nanos: AtomicU64,
    pub demo_suspensions: AtomicU64,
}

enum Input {
    Idle,
    Generator {
        capture: output::Capture,
        initialized: bool,
    },
    Software {
        signal: loopback::Generator,
        clock: Instant,
        fraction: f64,
    },
    Audio(Capture, Option<Box<output::history::Session>>),
    #[cfg(any(test, feature = "qa"))]
    Demo {
        signal: Demo,
        clock: Instant,
        fraction: f64,
    },
}

enum Command {
    Comparison(comparison::Settings),
    Lockin(lockin::Settings),
    Autoset(
        usize,
        mpsc::SyncSender<Result<acquisition::Autoset, String>>,
    ),
    Start(u64, Input, u32, usize, Box<Config>),
    Spectrum(Settings, usize, SpectrumMode),
    SpectrumDisplay(bool, [Option<usize>; 3]),
    Stft(u64, stft::Config),
    #[cfg(any(test, feature = "qa"))]
    Demo(Demo),
    Scope(ScopeSettings, mpsc::SyncSender<Reply>),
    Xy(Pair),
    Hold,
    Stop(mpsc::SyncSender<Reply>),
    Shutdown,
}

/// GUI-free core also used directly by deterministic input tests. The worker is
/// only the execution wrapper; all measurement scheduling lives here.
struct Core {
    generator_output: Option<output::Timeline>,
    external_session: Option<output::history::Session>,
    external_output: Option<output::history::ExternalOutput>,
    output_condition: Option<output::Condition>,
    comparison: comparison_worker::Worker,
    lockin: lockin_worker::Worker,
    acquisition: Acquisition,
    generation: u64,
    revision: u64,
    sample_rate: u32,
    history: History,
    spectrum: spectrum_worker::Feeder,
    spectrum_enabled: bool,
    overlay_channels: [Option<usize>; 3],
    overlay_feeders: Vec<spectrum_worker::Feeder>,
    config: Config,
    expected: Option<u64>,
    dropped: u64,
    capture_dropped: u64,
    failed: bool,
    feeder: stft::Feeder,
    metrics: Arc<Metrics>,
}

impl Core {
    fn new(
        feeder: stft::Feeder,
        mut spectrum: spectrum_worker::Feeder,
        metrics: Arc<Metrics>,
    ) -> Self {
        let config = Config {
            comparison: comparison::Settings::default(),
            lockin: lockin::Settings::default(),
            spectrum: Settings::default(),
            spectrum_channel: 0,
            spectrum_mode: SpectrumMode::Continuous,
            scope: ScopeSettings::default(),
            calibrations: calibration::Set::default(),
            xy_channels: Pair::<2>::default(),
            stft_generation: 0,
            stft: stft::Config {
                analysis: crate::stft::Analysis::Spectrogram,
                log_floor_db: crate::cepstrum::DEFAULT_LOG_FLOOR_DB,
                sample_rate: 48000,
                channels: 2,
                channel: 0,
                size: 8192,
                hop: 2048,
                window: spectrum::Window::Hann,
                remove_dc: true,
                precision: spectrum::Precision::F64,
            },
        };
        spectrum.configure(
            spectrum_worker::Source {
                generation: 0,
                rate: 48000,
                channel: 0,
                calibration: None,
            },
            config.spectrum,
            config.spectrum_mode,
            0,
        );
        Self {
            generator_output: None,
            external_session: None,
            external_output: None,
            output_condition: None,
            comparison: comparison_worker::Worker::default(),
            lockin: lockin_worker::Worker::default(),
            acquisition: Acquisition::new(acquisition::Mode::Auto, 480, 2),
            generation: 0,
            revision: 0,
            sample_rate: 48000,
            history: History::new(96000),
            spectrum,
            spectrum_enabled: true,
            overlay_channels: [None; 3],
            overlay_feeders: Vec::new(),
            config,

            expected: None,
            dropped: 0,
            capture_dropped: 0,
            failed: false,

            feeder,
            metrics,
        }
    }

    fn start(&mut self, generation: u64, sample_rate: u32, channels: usize, mut config: Config) {
        self.generator_output = None;
        self.external_session = None;
        self.external_output = None;
        self.output_condition = None;
        self.comparison.configure(
            generation,
            config.comparison,
            sample_rate,
            config.calibrations.clone(),
            0,
            channels,
        );
        self.lockin.configure(
            config.lockin,
            sample_rate,
            config.calibrations.clone(),
            0,
            channels,
        );
        self.acquisition = Acquisition::new(config.scope.mode, config.scope.samples, channels);
        self.metrics.single_complete.store(false, Ordering::Release);
        self.generation = generation;
        self.sample_rate = sample_rate;
        self.history = History::with_channels((sample_rate as usize * 2).max(32768), channels);
        config.spectrum_channel = config.spectrum_channel.min(channels - 1);
        config.stft.sample_rate = sample_rate;
        config.stft.channels = channels;
        config.stft.channel = config.stft.channel.min(channels - 1);
        self.expected = None;
        self.dropped = 0;
        self.capture_dropped = 0;
        self.failed = false;
        self.metrics.failed.store(false, Ordering::Release);
        self.config.calibrations = config.calibrations.clone();
        self.configure_spectrum(
            config.spectrum,
            config.spectrum_channel,
            config.spectrum_mode,
        );
        self.feeder.configure(config.stft_generation, config.stft);
        self.config = config;
    }

    fn configure_spectrum(&mut self, settings: Settings, channel: usize, mode: SpectrumMode) {
        self.config.spectrum = settings;
        self.config.spectrum_channel = channel.min(self.history.channels() - 1);
        self.config.spectrum_mode = mode;
        self.configure_spectrum_at(self.history.range().end);
    }

    fn configure_spectrum_at(&mut self, start: u64) {
        self.spectrum.configure(
            spectrum_worker::Source {
                generation: self.generation,
                rate: self.sample_rate,
                channel: self.config.spectrum_channel,
                calibration: self
                    .config
                    .calibrations
                    .get(self.config.spectrum_channel)
                    .cloned()
                    .map(Arc::new),
            },
            self.config.spectrum,
            self.config.spectrum_mode,
            start,
        );
        for index in 0..self.overlay_feeders.len() {
            self.configure_overlay(index, start);
        }
    }

    fn configure_overlay(&mut self, index: usize, start: u64) {
        let channel = self.overlay_channels[index].unwrap_or(index + 1);
        self.overlay_feeders[index].configure(
            spectrum_worker::Source {
                generation: self.generation,
                rate: self.sample_rate,
                channel,
                calibration: self.config.calibrations.get(channel).cloned().map(Arc::new),
            },
            self.config.spectrum,
            self.config.spectrum_mode,
            start,
        );
    }

    fn spectrum_display(&mut self, enabled: bool, channels: [Option<usize>; 3]) {
        if self.spectrum_enabled != enabled {
            self.spectrum_enabled = enabled;
            // Reset only this trace; toggling another trace preserves its EMA.
            self.spectrum.configure(
                spectrum_worker::Source {
                    generation: self.generation,
                    rate: self.sample_rate,
                    channel: self.config.spectrum_channel,
                    calibration: self
                        .config
                        .calibrations
                        .get(self.config.spectrum_channel)
                        .cloned()
                        .map(Arc::new),
                },
                self.config.spectrum,
                self.config.spectrum_mode,
                self.history.range().end,
            );
        }
        for (index, channel) in channels.into_iter().enumerate() {
            if self.overlay_channels[index] != channel {
                self.overlay_channels[index] = channel;
                self.configure_overlay(index, self.history.range().end);
            }
        }
    }

    fn push_generator(&mut self, frame: output::Frame) {
        if self.acquisition.state == acquisition::State::Complete {
            return;
        }
        if self.output_condition != Some(frame.condition) {
            self.configure_spectrum_at(frame.sequence);
            self.comparison.configure(
                self.generation,
                self.config.comparison,
                self.sample_rate,
                self.config.calibrations.clone(),
                frame.sequence,
                2,
            );
            self.lockin.configure(
                self.config.lockin,
                self.sample_rate,
                self.config.calibrations.clone(),
                frame.sequence,
                2,
            );
            self.output_condition = Some(frame.condition);
        }
        self.generator_output
            .get_or_insert_with(Default::default)
            .push(frame);
        self.push_frame(
            frame.sequence,
            &frame.samples,
            #[cfg(feature = "qa")]
            Some(frame.available_at),
        );
    }

    #[cfg(any(test, feature = "qa"))]
    fn reset_average(&mut self) {
        self.configure_spectrum(
            self.config.spectrum,
            self.config.spectrum_channel,
            self.config.spectrum_mode,
        );
    }

    #[cfg(test)]
    fn push(&mut self, sequence: u64, samples: &[f64]) {
        self.push_frame(
            sequence,
            samples,
            #[cfg(feature = "qa")]
            None,
        );
    }

    fn push_frame(
        &mut self,
        sequence: u64,
        samples: &[f64],
        #[cfg(feature = "qa")] available_at: Option<Instant>,
    ) {
        if self.acquisition.state == acquisition::State::Complete {
            return;
        }
        if self.expected != Some(sequence) {
            self.dropped += self
                .expected
                .map_or(sequence, |end| sequence.saturating_sub(end));
        }
        self.expected = Some(sequence + 1);
        self.history.push_at(sequence, samples);
        let stable = !self.output_condition.is_some_and(|c| c.transitioning);
        if stable {
            self.lockin.submit(sequence, samples);
            self.comparison.submit(sequence, samples);
        }
        if samples.iter().all(|x| x.is_finite()) {
            self.acquisition.push(
                &self.history,
                self.config.scope.samples,
                self.config.scope.trigger,
            );
        } else {
            self.acquisition.invalidate();
        }
        self.feeder.submit(sequence, samples);
        if stable && self.spectrum_enabled {
            self.spectrum.submit_frame(
                sequence,
                samples,
                #[cfg(feature = "qa")]
                available_at,
            );
        }
        if stable {
            for (index, feeder) in self.overlay_feeders.iter_mut().enumerate() {
                if self.overlay_channels[index].is_some_and(|ch| ch < samples.len()) {
                    feeder.submit_frame(
                        sequence,
                        samples,
                        #[cfg(feature = "qa")]
                        available_at,
                    );
                }
            }
        }
        self.metrics.input_frames.fetch_add(1, Ordering::Relaxed);
        self.metrics.single_complete.store(
            self.acquisition.state == acquisition::State::Complete,
            Ordering::Release,
        );
    }

    fn freeze_external_output(&mut self) {
        if let Some(session) = self.external_session.take() {
            self.external_output = session.finish();
        }
    }

    fn reply(&mut self, final_window: bool) -> Reply {
        let spectrum = self
            .spectrum
            .inspect(self.history.range().end, final_window);
        let lockin = if final_window {
            self.lockin.inspect(self.history.range().end)
        } else {
            let (reply, result) = mpsc::sync_channel(1);
            let _ = reply.try_send(self.lockin.latest());
            result
        };
        let comparison = if final_window {
            self.comparison.inspect(self.history.range().end)
        } else {
            let (reply, result) = mpsc::sync_channel(1);
            let _ = reply.try_send(self.comparison.latest());
            result
        };
        Reply {
            overlays: self
                .overlay_feeders
                .iter_mut()
                .enumerate()
                .filter(|(index, _)| {
                    self.overlay_channels[*index].is_some_and(|ch| ch < self.history.channels())
                })
                .map(|(index, feeder)| OverlayReply {
                    index,
                    incoming: feeder.inspect(self.history.range().end, final_window),
                    value: None,
                })
                .collect(),
            comparison,
            comparison_value: None,
            snapshot: self.snapshot(),
            spectrum,
            lockin,
            spectrum_value: None,
            lockin_value: None,
        }
    }

    fn snapshot(&mut self) -> Snapshot {
        let mut snapshot = Snapshot {
            generator_output: None,
            external_output: None,
            comparison: self.comparison.latest(),
            lockin: self.lockin.latest(),
            scope_capture: None,
            acquisition_state: acquisition::State::Waiting,
            generation: 0,
            revision: 0,
            sample_rate: self.sample_rate,
            history: History::new(1),
            spectrum: spectrum::Result::empty(
                Settings {
                    size: 1024,
                    ..Settings::default()
                },
                self.sample_rate,
            ),
            spectrum_info: SpectrumInfo::default(),
            spectrum_overlays: Vec::new(),
            #[cfg(feature = "qa")]
            spectrum_timing: None,
            stft_generation: self.config.stft_generation,
            stft_config: self.config.stft,
            scope_settings: self.config.scope,
            xy_channels: self.config.xy_channels,
            sweep: Sweep::default(),
            measurements: [Measurement::default(); SCOPE_CHANNELS],
            scope_readings: [Reading::Unavailable; SCOPE_CHANNELS],
            calibrations: self.config.calibrations.clone(),
            scope_missing: 0,
            input_dropped: 0,
            failed: false,
            fft_ms: 0.0,
            has_spectrum: false,
        };
        self.copy_snapshot(&mut snapshot);
        snapshot
    }

    fn copy_snapshot(&mut self, snapshot: &mut Snapshot) {
        snapshot.generator_output.clone_from(&self.generator_output);
        snapshot.external_output.clone_from(&self.external_output);
        self.revision += 1;
        snapshot.generation = self.generation;
        snapshot.comparison = self.comparison.latest();
        snapshot.lockin = self.lockin.latest();
        snapshot.revision = self.revision;
        snapshot.sample_rate = self.sample_rate;
        snapshot.history.clone_from(&self.history);
        snapshot.has_spectrum = false;
        snapshot.spectrum_overlays.clear();
        #[cfg(feature = "qa")]
        {
            snapshot.spectrum_timing = None;
        }
        snapshot.stft_generation = self.config.stft_generation;
        snapshot.stft_config = self.config.stft;
        snapshot.scope_settings = self.config.scope;
        snapshot.xy_channels = self.config.xy_channels;
        snapshot.acquisition_state = self.acquisition.state;
        if self.acquisition.mode != acquisition::Mode::Auto {
            snapshot
                .scope_capture
                .get_or_insert_with(|| History::new(1))
                .clone_from(&self.acquisition.capture);
        } else {
            snapshot.scope_capture = None;
        }
        let scope_history = snapshot.scope_capture.as_ref().unwrap_or(&self.history);
        snapshot.sweep = if self.acquisition.mode != acquisition::Mode::Auto {
            self.acquisition.sweep.clone()
        } else if self.history.len() >= self.config.scope.samples {
            self.history
                .sweep(self.config.scope.samples, self.config.scope.trigger)
        } else {
            Sweep::default()
        };
        snapshot.measurements = signal::measure(
            scope_history,
            snapshot.sweep.range.clone(),
            self.config.scope.channels,
        );
        snapshot.calibrations.clone_from(&self.config.calibrations);
        snapshot.scope_readings = calibration::measure(
            scope_history,
            snapshot.sweep.range.clone(),
            self.config.scope.channels,
            &snapshot.calibrations,
        );
        snapshot.scope_missing = snapshot
            .sweep
            .range
            .clone()
            .filter(|&i| scope_history.get(i).is_none())
            .count() as u64;
        snapshot.input_dropped = self.dropped.max(self.capture_dropped);
        snapshot.failed = self.failed;
    }
}

struct Reply {
    overlays: Vec<OverlayReply>,
    comparison: mpsc::Receiver<Arc<comparison::Result>>,
    comparison_value: Option<Arc<comparison::Result>>,
    snapshot: Snapshot,
    spectrum: mpsc::Receiver<spectrum_worker::Publication>,
    lockin: mpsc::Receiver<lockin::Result>,
    spectrum_value: Option<spectrum_worker::Publication>,
    lockin_value: Option<lockin::Result>,
}

struct OverlayReply {
    index: usize,
    incoming: mpsc::Receiver<spectrum_worker::Publication>,
    value: Option<spectrum_worker::Publication>,
}

pub struct PendingSnapshot {
    incoming: mpsc::Receiver<Reply>,
    reply: Option<Reply>,
}
impl PendingSnapshot {
    pub fn try_take(&mut self) -> Option<Snapshot> {
        if self.reply.is_none() {
            self.reply = self.incoming.try_recv().ok();
        }
        let reply = self.reply.as_mut()?;
        for overlay in &mut reply.overlays {
            if overlay.value.is_none() {
                overlay.value = overlay.incoming.try_recv().ok();
            }
        }
        if reply.spectrum_value.is_none() {
            reply.spectrum_value = reply.spectrum.try_recv().ok();
        }
        if reply.lockin_value.is_none() {
            reply.lockin_value = reply.lockin.try_recv().ok();
        }
        if reply.comparison_value.is_none() {
            reply.comparison_value = reply.comparison.try_recv().ok();
        }
        if reply.overlays.iter().any(|overlay| overlay.value.is_none())
            || reply.spectrum_value.is_none()
            || reply.lockin_value.is_none()
            || reply.comparison_value.is_none()
        {
            return None;
        }
        let mut reply = self.reply.take().unwrap();
        for overlay in reply.overlays.drain(..) {
            let p = overlay.value.unwrap();
            reply
                .snapshot
                .spectrum_overlays
                .push((overlay.index, p.result, p.info));
        }
        reply.snapshot.comparison = reply.comparison_value.take().unwrap();
        reply.snapshot.lockin = reply.lockin_value.take().unwrap();
        Some(Self::complete(
            reply.snapshot,
            reply.spectrum_value.take().unwrap(),
        ))
    }
    pub fn wait(self) -> Snapshot {
        let mut reply = self
            .reply
            .unwrap_or_else(|| self.incoming.recv().expect("measurement reply"));
        for overlay in reply.overlays.drain(..) {
            let p = overlay
                .value
                .unwrap_or_else(|| overlay.incoming.recv().expect("Spectrum overlay barrier"));
            reply
                .snapshot
                .spectrum_overlays
                .push((overlay.index, p.result, p.info));
        }
        reply.snapshot.comparison = reply
            .comparison_value
            .take()
            .unwrap_or_else(|| reply.comparison.recv().expect("Comparison barrier"));
        reply.snapshot.lockin = reply
            .lockin_value
            .take()
            .unwrap_or_else(|| reply.lockin.recv().expect("Lock-in barrier"));
        let publication = reply
            .spectrum_value
            .take()
            .unwrap_or_else(|| reply.spectrum.recv().expect("Spectrum barrier"));
        Self::complete(reply.snapshot, publication)
    }
    fn complete(mut snapshot: Snapshot, publication: spectrum_worker::Publication) -> Snapshot {
        snapshot.spectrum = publication.result;
        snapshot.spectrum_info = publication.info;
        snapshot.fft_ms = publication.fft_ms;
        #[cfg(feature = "qa")]
        {
            snapshot.spectrum_timing = publication.timing;
        }
        snapshot.has_spectrum = true;
        snapshot
    }
}

pub struct Worker {
    commands: mpsc::SyncSender<Command>,
    running: AtomicBool,
    results: Consumer<Box<Snapshot>>,
    recycle: Producer<Box<Snapshot>>,
    handle: Option<JoinHandle<()>>,
    pub metrics: Arc<Metrics>,
    pub spectrum: spectrum_worker::Worker,
    pub spectrum_overlays: [spectrum_worker::Worker; 3],
    spectrum_display: [AtomicU64; 4],
}

impl Worker {
    pub fn new(feeder: stft::Feeder) -> Self {
        let (commands, requests) = mpsc::sync_channel(16);
        let (mut outgoing, results) = RingBuffer::new(SNAPSHOTS);
        let (mut recycle, mut free) = RingBuffer::new(SNAPSHOTS);
        let metrics = Arc::new(Metrics::default());
        let counters = metrics.clone();
        let mut spectrum = spectrum_worker::Worker::new();
        let mut core = Core::new(feeder, spectrum.take_feeder(), counters.clone());
        let mut spectrum_overlays = std::array::from_fn(|_| spectrum_worker::Worker::new());
        core.overlay_feeders = spectrum_overlays
            .iter_mut()
            .map(|worker| worker.take_feeder())
            .collect();
        for _ in 0..SNAPSHOTS {
            recycle
                .push(Box::new(core.snapshot()))
                .unwrap_or_else(|_| unreachable!());
        }
        let handle = thread::Builder::new()
            .name("measurelab-core".into())
            .spawn(move || {
                let mut input = Input::Idle;
                let mut activity = None;
                let mut last_display = Instant::now() - DISPLAY_INTERVAL;
                loop {
                    let command = if matches!(input, Input::Idle) {
                        requests.recv().ok()
                    } else {
                        requests.recv_timeout(Duration::from_millis(2)).ok()
                    };
                    let started = Instant::now();
                    if let Some(command) = command {
                        match command {
                            Command::Comparison(settings) => {
                                if !matches!(input, Input::Idle) {
                                    core.config.comparison = settings;
                                    core.comparison.configure(
                                        core.generation,
                                        settings,
                                        core.sample_rate,
                                        core.config.calibrations.clone(),
                                        core.history.range().end,
                                        core.history.channels(),
                                    );
                                }
                            }
                            Command::Lockin(settings) => {
                                if !matches!(input, Input::Idle) {
                                    core.config.lockin = settings;
                                    core.lockin.configure(
                                        settings,
                                        core.sample_rate,
                                        core.config.calibrations.clone(),
                                        core.history.range().end,
                                        core.history.channels(),
                                    );
                                }
                            }
                            Command::Autoset(channel, reply) => {
                                let history = if matches!(input, Input::Idle)
                                    && !core.acquisition.capture.is_empty()
                                {
                                    &core.acquisition.capture
                                } else {
                                    &core.history
                                };
                                let _ = reply.try_send(acquisition::autoset(
                                    history,
                                    core.sample_rate,
                                    channel,
                                ));
                            }
                            Command::Start(generation, mut source, rate, channels, config) => {
                                activity = Some(Activity::new("MeasureLab audio acquisition"));
                                core.start(generation, rate, channels, *config);
                                if let Input::Audio(_, session) = &mut source {
                                    core.external_session = session.take().map(|s| *s);
                                }
                                input = source;
                                if let Input::Software { clock, .. } = &mut input {
                                    *clock = Instant::now();
                                }
                                #[cfg(any(test, feature = "qa"))]
                                if let Input::Demo { clock, .. } = &mut input {
                                    *clock = Instant::now();
                                }
                                last_display = Instant::now() - DISPLAY_INTERVAL;
                            }
                            Command::Spectrum(settings, channel, mode) => {
                                if !matches!(input, Input::Idle) {
                                    core.configure_spectrum(settings, channel, mode);
                                }
                            }
                            Command::SpectrumDisplay(enabled, channels) => {
                                core.spectrum_display(enabled, channels)
                            }
                            Command::Stft(generation, config) => {
                                core.config.stft_generation = generation;
                                core.config.stft = config;
                                core.feeder.configure(generation, config);
                            }
                            #[cfg(any(test, feature = "qa"))]
                            Command::Demo(settings) => {
                                if let Input::Demo { signal, .. } = &mut input {
                                    signal.apply_settings(&settings);
                                    core.reset_average();
                                }
                            }
                            Command::Scope(settings, reply) => {
                                // Held data can be reprojected over a different
                                // interval; channel provenance stays fixed.
                                let channels = core.config.scope.channels;
                                if !matches!(input, Input::Idle) && settings != core.config.scope {
                                    core.acquisition = Acquisition::new(
                                        settings.mode,
                                        settings.samples,
                                        core.history.channels(),
                                    );
                                    counters.single_complete.store(false, Ordering::Release);
                                }
                                if !matches!(input, Input::Idle)
                                    || core.acquisition.mode == acquisition::Mode::Auto
                                {
                                    core.config.scope = settings;
                                }
                                if matches!(input, Input::Idle) {
                                    core.config.scope.channels = channels;
                                }
                                let _ = reply.try_send(core.reply(false));
                            }
                            Command::Xy(channels) => {
                                if !matches!(input, Input::Idle) {
                                    core.config.xy_channels = channels;
                                }
                            }
                            Command::Hold => {
                                core.spectrum.clear_hold();
                                for feeder in &mut core.overlay_feeders {
                                    feeder.clear_hold();
                                }
                            }
                            Command::Stop(reply) => {
                                poll_input(&mut input, &mut core, true);
                                core.freeze_external_output();
                                input = Input::Idle;
                                activity.take();
                                let _ = reply.try_send(core.reply(true));
                            }
                            Command::Shutdown => break,
                        }
                    }
                    if !matches!(input, Input::Idle) {
                        poll_input(&mut input, &mut core, false);
                        if core.failed || core.acquisition.state == acquisition::State::Complete {
                            core.freeze_external_output();
                            input = Input::Idle;
                            activity.take();
                        }
                    }
                    if core.failed || last_display.elapsed() >= DISPLAY_INTERVAL {
                        if let Ok(mut snapshot) = free.pop() {
                            core.copy_snapshot(&mut snapshot);
                            outgoing
                                .push(snapshot)
                                .unwrap_or_else(|_| unreachable!("snapshot pool"));
                        } else {
                            counters.display_skipped.fetch_add(1, Ordering::Relaxed);
                        }
                        last_display = Instant::now();
                    }
                    counters
                        .processing_nanos
                        .fetch_add(started.elapsed().as_nanos() as u64, Ordering::Relaxed);
                }
            })
            .expect("measurement worker");
        Self {
            commands,
            running: AtomicBool::new(false),
            results,
            recycle,
            handle: Some(handle),
            metrics,
            spectrum,
            spectrum_overlays,
            spectrum_display: std::array::from_fn(|i| {
                AtomicU64::new(if i == 0 { 0 } else { u64::MAX })
            }),
        }
    }

    pub fn start_capture(&self, generation: u64, capture: Capture, config: Config) {
        self.start_capture_observed(generation, capture, config, None);
    }

    pub fn start_capture_observed(
        &self,
        generation: u64,
        capture: Capture,
        config: Config,
        output: Option<&output::history::Handle>,
    ) {
        self.running.store(true, Ordering::Release);
        let rate = capture.sample_rate;
        let channels = capture.channels as usize;
        self.send(Command::Start(
            generation,
            Input::Audio(capture, output.map(|h| Box::new(h.begin(generation)))),
            rate,
            channels,
            Box::new(config),
        ));
    }

    pub fn autoset(&self, channel: usize) -> mpsc::Receiver<Result<acquisition::Autoset, String>> {
        let (reply, result) = mpsc::sync_channel(1);
        self.send(Command::Autoset(channel, reply));
        result
    }

    pub fn start_loopback(
        &self,
        generation: u64,
        settings: loopback::Settings,
        rate: u32,
        config: Config,
    ) -> Result<(), String> {
        settings.validate(rate)?;
        config.lockin.validate(rate)?;
        config.comparison.validate(rate)?;
        self.running.store(true, Ordering::Release);
        self.send(Command::Start(
            generation,
            Input::Software {
                signal: loopback::Generator::new(settings),
                clock: Instant::now(),
                fraction: 0.0,
            },
            rate,
            2,
            Box::new(config),
        ));
        Ok(())
    }
    pub fn start_generator(
        &self,
        generation: u64,
        capture: output::Capture,
        rate: u32,
        config: Config,
    ) -> Result<(), String> {
        if !output::RATES.contains(&rate) {
            return Err("Unsupported Generator input rate".into());
        }
        config.lockin.validate(rate)?;
        config.comparison.validate(rate)?;
        self.running.store(true, Ordering::Release);
        self.send(Command::Start(
            generation,
            Input::Generator {
                capture,
                initialized: false,
            },
            rate,
            2,
            Box::new(config),
        ));
        Ok(())
    }
    pub fn configure_comparison(&self, settings: comparison::Settings) {
        self.send(Command::Comparison(settings));
    }
    pub fn configure_lockin(&self, settings: lockin::Settings) {
        self.send(Command::Lockin(settings));
    }
    #[cfg(any(test, feature = "qa"))]
    pub fn start_demo(&self, generation: u64, demo: Demo, config: Config) {
        self.running.store(true, Ordering::Release);
        self.send(Command::Start(
            generation,
            Input::Demo {
                signal: demo,
                clock: Instant::now(),
                fraction: 0.0,
            },
            48000,
            2,
            Box::new(config),
        ));
    }
    pub fn configure_spectrum(&self, settings: Settings, channel: usize, mode: SpectrumMode) {
        if self.running.load(Ordering::Acquire) {
            self.spectrum.invalidate();
            for worker in &self.spectrum_overlays {
                worker.invalidate();
            }
        }
        self.send(Command::Spectrum(settings, channel, mode));
    }
    pub fn configure_stft(&self, generation: u64, config: stft::Config) {
        self.send(Command::Stft(generation, config));
    }
    pub fn configure_spectrum_display(&self, enabled: bool, channels: [Option<usize>; 3]) {
        for (index, value) in std::iter::once(enabled.then_some(0))
            .chain(channels)
            .enumerate()
        {
            let value = value.map_or(u64::MAX, |ch| ch as u64);
            if self.spectrum_display[index].swap(value, Ordering::AcqRel) != value {
                if index == 0 {
                    self.spectrum.invalidate();
                } else {
                    self.spectrum_overlays[index - 1].invalidate();
                }
            }
        }
        self.send(Command::SpectrumDisplay(enabled, channels));
    }
    #[cfg(any(test, feature = "qa"))]
    pub fn configure_demo(&self, demo: Demo) {
        if self.running.load(Ordering::Acquire) {
            self.spectrum.invalidate();
        }
        self.send(Command::Demo(demo));
    }
    pub fn configure_xy(&self, channels: Pair) {
        self.send(Command::Xy(channels));
    }
    pub fn clear_hold(&self) {
        self.send(Command::Hold);
    }
    fn send(&self, command: Command) {
        self.commands
            .send(command)
            .expect("measurement worker exited");
    }

    /// Nonblocking finalization: acquisition fixes a finite input endpoint;
    /// Spectrum drains that endpoint independently while the UI remains usable.
    pub fn stop_async(&self) -> PendingSnapshot {
        self.running.store(false, Ordering::Release);
        let (reply, result) = mpsc::sync_channel(1);
        self.send(Command::Stop(reply));
        PendingSnapshot {
            incoming: result,
            reply: None,
        }
    }
    pub fn scope_async(&self, settings: ScopeSettings) -> PendingSnapshot {
        let (reply, result) = mpsc::sync_channel(1);
        self.send(Command::Scope(settings, reply));
        PendingSnapshot {
            incoming: result,
            reply: None,
        }
    }
    /// Blocking helpers for headless callers; the acquisition thread never waits.
    pub fn stop(&self) -> Snapshot {
        self.stop_async().wait()
    }
    pub fn scope(&self, settings: ScopeSettings) -> Snapshot {
        self.scope_async(settings).wait()
    }
    pub fn take_latest(&mut self) -> Option<Box<Snapshot>> {
        let mut latest = None;
        for _ in 0..self.results.slots() {
            if let Some(previous) = latest.replace(self.results.pop().unwrap()) {
                self.recycle(previous);
            }
        }
        latest
    }
    pub fn recycle(&mut self, snapshot: Box<Snapshot>) {
        self.recycle
            .push(snapshot)
            .unwrap_or_else(|_| unreachable!("snapshot pool"));
    }
}

fn poll_input(input: &mut Input, core: &mut Core, final_window: bool) {
    let clock = Instant::now();
    match input {
        Input::Idle => {}
        Input::Generator {
            capture,
            initialized,
        } => {
            if !capture.metrics.ready.load(Ordering::Acquire) {
                return;
            }
            if !*initialized {
                if capture.metrics.nominal_sample_rate.load(Ordering::Relaxed)
                    != core.sample_rate as u64
                {
                    core.failed = true;
                    core.metrics.failed.store(true, Ordering::Release);
                    return;
                }
                let first = capture.metrics.first_sample.load(Ordering::Relaxed);
                core.expected = Some(first);
                core.history.clear_at(first);
                *initialized = true;
            }
            core.failed = capture.metrics.failed.load(Ordering::Acquire);
            let final_window = final_window || core.failed;
            let end = capture.metrics.input_end.load(Ordering::Acquire);
            // Snapshot the queue once. A continuing output cannot extend input
            // Stop forever, or contaminate its finite metadata and sample range.
            let count = capture.consumer.slots();
            for _ in 0..count {
                if let Ok(frame) = capture.consumer.pop() {
                    if final_window && frame.sequence >= end {
                        break;
                    }
                    core.push_generator(frame);
                }
            }
            if final_window && core.acquisition.state != acquisition::State::Complete {
                let retained_end = core.history.range().end;
                if end > retained_end {
                    core.dropped += end - retained_end;
                    core.expected = Some(end);
                    core.history.advance_to(end);
                    core.acquisition.invalidate();
                }
            }
            core.capture_dropped =
                if final_window || core.acquisition.state == acquisition::State::Complete {
                    core.dropped
                } else {
                    capture.metrics.dropped.load(Ordering::Relaxed)
                };
            core.metrics.failed.store(core.failed, Ordering::Release);
        }
        Input::Software {
            signal,
            clock,
            fraction,
        } => {
            let now = Instant::now();
            let elapsed = now.duration_since(*clock).as_secs_f64();
            *clock = now;
            if elapsed > 0.25 {
                let missing = ((elapsed - 0.25) * core.sample_rate as f64) as u64;
                signal.advance(missing);
                let end = core.history.range().end + missing;
                core.history.advance_to(end);
            }
            *fraction += elapsed.min(0.25) * core.sample_rate as f64;
            let count = *fraction as usize;
            *fraction -= count as f64;
            for _ in 0..count {
                if core.acquisition.state == acquisition::State::Complete {
                    break;
                }
                core.push_frame(
                    core.history.range().end,
                    &signal.next_frame(core.sample_rate),
                    #[cfg(feature = "qa")]
                    Some(now),
                );
            }
        }
        Input::Audio(capture, _) => {
            core.failed = capture.metrics.failed.load(Ordering::Relaxed);
            let final_window = final_window || core.failed;
            // Acquire before reading the queue: every accepted frame below this
            // completed-callback endpoint has already been committed. Take one
            // bounded queue snapshot; later callbacks cannot extend Stop forever.
            let end = if final_window {
                capture.metrics.input_end.load(Ordering::Acquire)
            } else {
                0
            };
            let available = capture.consumer.slots();
            if let Ok(chunk) = capture.consumer.read_chunk(available) {
                for frame in chunk {
                    core.push_frame(
                        frame.sequence,
                        &frame.samples[..capture.channels as usize],
                        #[cfg(feature = "qa")]
                        frame.available_at,
                    );
                }
            }
            if final_window && core.acquisition.state != acquisition::State::Complete {
                let retained_end = core.history.range().end;
                if end > retained_end {
                    core.dropped += end - retained_end;
                    core.expected = Some(end);
                    core.history.advance_to(end);
                    core.acquisition.invalidate();
                }
            }
            core.capture_dropped =
                if final_window || core.acquisition.state == acquisition::State::Complete {
                    // Source gaps up to the finite end are exact. A live cumulative
                    // callback counter may include drops after Stop or Single ended.
                    core.dropped
                } else {
                    capture.metrics.dropped.load(Ordering::Relaxed)
                };
            core.metrics.failed.store(core.failed, Ordering::Release);
        }
        #[cfg(any(test, feature = "qa"))]
        Input::Demo {
            signal,
            clock,
            fraction,
        } => {
            let now = Instant::now();
            let elapsed = now.duration_since(*clock).as_secs_f64();
            core.metrics.demo_interval_max_nanos.fetch_max(
                now.duration_since(*clock).as_nanos() as u64,
                Ordering::Relaxed,
            );
            *clock = now;
            // OS/worker suspension is still a discontinuity, never fabricated input.
            if elapsed > 0.25 {
                core.metrics
                    .demo_suspensions
                    .fetch_add(1, Ordering::Relaxed);
                let missing = ((elapsed - 0.25) * core.sample_rate as f64) as u64;
                let end = core.history.range().end + missing;
                core.history.advance_to(end);
            }
            *fraction += elapsed.min(0.25) * core.sample_rate as f64;
            let count = *fraction as usize;
            *fraction -= count as f64;
            for _ in 0..count {
                let frame = signal.next_frame(core.sample_rate);
                core.push_frame(
                    core.history.range().end,
                    &frame,
                    #[cfg(feature = "qa")]
                    Some(now),
                );
            }
        }
    }
    core.feeder.flush();
    core.spectrum.flush();
    for feeder in &mut core.overlay_feeders {
        feeder.flush();
    }
    core.metrics
        .input_poll_max_nanos
        .fetch_max(clock.elapsed().as_nanos() as u64, Ordering::Relaxed);
}

impl Drop for Worker {
    fn drop(&mut self) {
        let _ = self.commands.send(Command::Shutdown);
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        audio::{AudioFrame, Metrics as AudioMetrics},
        signal::MAX_CHANNELS,
        spectrum::{Precision, Window},
    };
    use std::f64::consts::TAU;

    fn finish(core: &mut Core) -> Snapshot {
        core.feeder.flush();
        core.spectrum.flush();
        let mut reply = core.reply(true);
        reply.snapshot.comparison = reply.comparison.recv().unwrap();
        reply.snapshot.lockin = reply.lockin.recv().unwrap();
        PendingSnapshot::complete(reply.snapshot, reply.spectrum.recv().unwrap())
    }

    #[test]
    fn esd_pulse_uses_existing_worker_and_finite_stop_in_all_update_modes() {
        for size in [1024, 8192] {
            for mode in [
                SpectrumMode::Live,
                SpectrumMode::Continuous,
                SpectrumMode::Latest,
            ] {
                let (_stft, mut core, mut config, _spectrum) = setup(size, 16);
                config.spectrum.select_quantity(spectrum::Quantity::Esd);
                config.spectrum_mode = mode;
                core.start(71, 48000, 16, config);
                for n in 0..size {
                    let mut samples = [0.0; 16];
                    samples[15] = if n == 17 { 0.75 } else { 0.0 };
                    core.push_frame(
                        n as u64,
                        &samples,
                        #[cfg(feature = "qa")]
                        None,
                    );
                }
                let held = finish(&mut core);
                assert_eq!(held.spectrum.window().unwrap().channel, 15);
                assert_eq!(held.spectrum.settings().quantity, spectrum::Quantity::Esd);
                assert_eq!(held.spectrum_info.updates, 1);
                assert!(
                    (held.spectrum.energy().unwrap() / (0.75_f64.powi(2) / 48000.0) - 1.0).abs()
                        < 1e-12
                );
                assert_eq!(held.spectrum.power(), finish(&mut core).spectrum.power());
            }
        }
    }

    #[test]
    fn four_spectrum_traces_share_conditions_and_toggle_without_resetting_peers() {
        for size in [2048, 4096, 8192, 16384, 32768] {
            for window in [Window::Hann, Window::Rectangular] {
                let (_stft, mut core, mut config, _primary) = setup(size, 4);
                let mut overlays: [spectrum_worker::Worker; 3] =
                    std::array::from_fn(|_| spectrum_worker::Worker::new());
                core.overlay_feeders = overlays
                    .iter_mut()
                    .map(|worker| worker.take_feeder())
                    .collect();
                config.spectrum_channel = 0;
                config.spectrum.window = window;
                core.start(50, 48000, 4, config.clone());
                core.spectrum_display(true, [Some(1), Some(2), Some(3)]);
                let push = |core: &mut Core, start: usize, end: usize| {
                    for n in start..end {
                        let samples: [f64; 4] = std::array::from_fn(|ch| {
                            0.5_f64.powi(ch as i32 + 1)
                                * (TAU * (32 + 8 * ch) as f64 * n as f64 / size as f64).sin()
                        });
                        core.push_frame(
                            n as u64,
                            &samples,
                            #[cfg(feature = "qa")]
                            None,
                        );
                    }
                };
                let capture = |core: &mut Core| {
                    let (tx, rx) = mpsc::sync_channel(1);
                    tx.send(core.reply(true))
                        .unwrap_or_else(|_| panic!("test reply"));
                    PendingSnapshot {
                        incoming: rx,
                        reply: None,
                    }
                    .wait()
                };
                push(&mut core, 0, size * 2);
                let first = capture(&mut core);
                assert_eq!(first.spectrum_overlays.len(), 3);
                for ch in 0..4 {
                    let result = if ch == 0 {
                        &first.spectrum
                    } else {
                        &first.spectrum_overlays[ch - 1].1
                    };
                    let reading = result
                        .cursor((32 + 8 * ch) as f64 * 48000.0 / size as f64)
                        .unwrap();
                    assert_eq!(reading.window.channel, ch);
                    assert_eq!(reading.window.settings, config.spectrum);
                    assert!(
                        (reading.level_db - 20.0 * 0.5_f64.powi(ch as i32 + 1).log10()).abs()
                            < 1e-10
                    );
                    assert_eq!(reading.average.updates, 5);
                    assert_eq!(reading.window.end, (size * 2) as u64);
                }
                let disabled_windows = overlays[1].metrics.windows.load(Ordering::Relaxed);
                core.spectrum_display(true, [Some(1), None, Some(3)]);
                push(&mut core, size * 2, size * 3);
                let second = capture(&mut core);
                assert_eq!(
                    overlays[1].metrics.windows.load(Ordering::Relaxed),
                    disabled_windows
                );
                assert_eq!(second.spectrum_overlays.len(), 2);
                assert_eq!(second.spectrum.average().unwrap().updates, 9);
                assert_eq!(second.spectrum_overlays[0].1.average().unwrap().updates, 9);
                core.spectrum_display(false, [Some(1), Some(2), Some(3)]);
                push(&mut core, size * 3, size * 4);
                let third = capture(&mut core);
                assert!(!third.spectrum.is_ready());
                assert_eq!(third.spectrum_overlays[0].1.average().unwrap().updates, 13);
                assert_eq!(third.spectrum_overlays[1].1.average().unwrap().updates, 1);
                assert_eq!(third.spectrum_overlays[2].1.average().unwrap().updates, 13);
                // Changed FFT/window and a new input generation cannot retain averages.
                config.spectrum.window = if window == Window::Hann {
                    Window::Rectangular
                } else {
                    Window::Hann
                };
                core.start(51, 96000, 2, config);
                push(&mut core, 0, size);
                let fresh = capture(&mut core);
                assert_eq!(fresh.spectrum_overlays.len(), 1);
                assert_eq!(fresh.spectrum_overlays[0].1.average().unwrap().updates, 1);
                assert_eq!(fresh.spectrum_overlays[0].1.sample_rate(), 96000);
                assert_eq!(first.spectrum.average().unwrap().updates, 5);
            }
        }
    }

    #[test]
    fn comparison_routes_synchronous_ch16_and_ch8_and_survives_display_pause_and_restart() {
        let (_stft, mut core, mut config, _spectrum) = setup(1024, 16);
        config.comparison = comparison::Settings {
            enabled: true,
            size: 1024,
            averages: 4,
            reference_channel: 15,
            response_channel: 7,
            window: Window::Rectangular,
            ..Default::default()
        };
        core.start(88, 48000, 16, config.clone());
        for n in 0..8192 {
            let p = TAU * 16.0 * n as f64 / 1024.0;
            let mut frame = [0.0; 16];
            frame[15] = 0.125 * p.sin();
            frame[7] = 0.0625 * (p + 0.5).sin();
            core.push_frame(
                n,
                &frame,
                #[cfg(feature = "qa")]
                None,
            );
        }
        let held = finish(&mut core);
        assert_eq!(held.comparison.generation, 88);
        assert_eq!(held.comparison.state, comparison::State::Valid);
        assert_eq!(held.comparison.processed_windows, 8);
        assert_eq!(held.comparison.input_end, 8192);
        assert!((held.comparison.bins[16].gain.unwrap() - 0.5).abs() < 1e-10);
        assert_eq!(held.comparison, finish(&mut core).comparison);
        core.start(89, 48000, 1, config);
        let next = finish(&mut core);
        assert_eq!(next.comparison.generation, 89);
        assert_eq!(next.comparison.state, comparison::State::Unavailable);
        assert!(next.comparison.bins.is_empty());
        assert_eq!(held.comparison.generation, 88);
    }

    #[test]
    fn single_stops_at_exact_terminal_sample_and_does_not_fabricate_large_fft() {
        let (_stft, mut core, mut config, _spectrum) = setup(1024, 16);
        config.spectrum.size = 524288;
        config.scope.samples = 10;
        config.scope.mode = acquisition::Mode::Single;
        config.scope.channels = Pair([15, 7]).scope();
        config.scope.trigger = Trigger {
            channel: 15,
            level: 0.5,
            edge: signal::Edge::Rising,
        };
        core.start(8, 48000, 16, config);
        for n in 0..1000 {
            let mut frame = [0.0; 16];
            if n == 12 {
                frame[15] = 1.0;
            }
            core.push(n, &frame);
        }
        let result = finish(&mut core);
        assert_eq!(result.history.range(), 0..20);
        assert_eq!(result.sweep.range, 10..20);
        assert_eq!(result.acquisition_state, acquisition::State::Complete);
        assert_eq!(
            result.scope_capture.as_ref().unwrap().get(12).unwrap()[15],
            1.0
        );
        assert_eq!(result.measurements[0].samples, 10);
        assert!(!result.spectrum.is_ready());
        assert_eq!(result.spectrum_info.filled_samples, 20);
    }

    #[test]
    fn four_channel_single_preserves_all_samples_statistics_and_channel_four_trigger() {
        let (_stft, mut core, mut config, _spectrum) = setup(1024, 4);
        config.scope.samples = 10;
        config.scope.mode = acquisition::Mode::Single;
        config.scope.trigger = Trigger {
            channel: 3,
            level: 0.5,
            edge: signal::Edge::Rising,
        };
        core.start(8, 48000, 4, config.clone());
        for n in 0..100 {
            core.push(n, &[0.125, -0.25, 0.375, if n == 12 { 1.0 } else { 0.0 }]);
        }
        let held = finish(&mut core);
        assert_eq!(held.sweep.range, 10..20);
        assert_eq!(held.acquisition_state, acquisition::State::Complete);
        for index in 0..4 {
            assert_eq!(held.measurements[index].samples, 10);
            assert!(matches!(held.scope_readings[index], Reading::Valid(_)));
        }
        assert_eq!(held.measurements[2].rms, 0.375);
        assert!((held.measurements[3].rms - 0.1_f64.sqrt()).abs() < 1e-14);
        assert_eq!(
            held.scope_capture.as_ref().unwrap().get(12).unwrap()[3],
            1.0
        );
        core.start(9, 48000, 2, config);
        for n in 0..100 {
            core.push(n, &[0.125, -0.25]);
        }
        let unavailable = finish(&mut core);
        assert!(!unavailable.sweep.triggered);
        assert_eq!(unavailable.scope_readings[2..], [Reading::Unavailable; 2]);
        assert_eq!(held.scope_settings.channels.0, [0, 1, 2, 3]);
    }

    #[test]
    fn normal_waits_and_keeps_fixed_capture_across_history_wrap_and_invalidates_on_gap() {
        let (_stft, mut core, mut config, _spectrum) = setup(1024, 2);
        config.scope.samples = 10;
        config.scope.mode = acquisition::Mode::Normal;
        config.scope.trigger = Trigger {
            channel: 0,
            level: 0.5,
            edge: signal::Edge::Rising,
        };
        core.start(9, 48000, 2, config);
        for n in 0..1000 {
            core.push(n, &[0.0, 0.0]);
        }
        assert!(core.snapshot().sweep.range.is_empty());
        for n in 1000..98000 {
            core.push(n, &[if n == 1012 { 1.0 } else { 0.0 }, 0.0]);
        }
        let result = core.snapshot();
        assert_eq!(result.sweep.range, 1010..1020);
        assert!(result.history.get(1012).is_none());
        assert_eq!(result.scope_capture.unwrap().get(1012).unwrap()[0], 1.0);
        core.push(98010, &[0.0, 0.0]);
        assert!(core.snapshot().sweep.range.is_empty());
    }

    #[test]
    fn software_dut_common_input_lockin_and_fft_agree_without_ui() {
        let (_stft, mut core, mut config, _spectrum) = setup(8192, 2);
        config.spectrum_channel = 1;
        config.spectrum.averages = 1;
        config.spectrum_mode = SpectrumMode::Latest;
        config.lockin = lockin::Settings {
            enabled: true,
            frequency_hz: 750.0,
            integration_samples: 4096,
            ..Default::default()
        };
        core.start(10, 48000, 2, config);
        let mut generator = loopback::Generator::new(loopback::Settings {
            frequency_hz: 750.0,
            gain: 0.5,
            phase_degrees: 30.0,
            delay_samples: 3,
            dc_offset: 0.2,
            ..Default::default()
        });
        for n in 0..96000 {
            core.push(n, &generator.next_frame(48000));
        }
        let result = finish(&mut core);
        let r = &result.lockin;
        assert_eq!(r.state, lockin::State::Valid);
        assert_eq!(r.missing_samples, 0);
        assert!((r.amplitude_peak.unwrap() - 0.0625).abs() < 1e-10);
        assert!((r.phase_degrees.unwrap() - (30.0 - 360.0 * 750.0 * 3.0 / 48000.0)).abs() < 1e-7);
        assert!((result.spectrum.power()[128].sqrt() - r.amplitude_peak.unwrap()).abs() < 1e-10);
        assert_eq!(result.spectrum_info.input_missing, 0);
        assert_eq!(result.history.range().end, 96000);
    }

    fn setup(
        size: usize,
        channels: usize,
    ) -> (stft::Worker, Core, Config, spectrum_worker::Worker) {
        let mut stft = stft::Worker::new();
        let spectrum = Settings {
            size,
            window: Window::Rectangular,
            averages: 4,
            remove_dc: false,
            precision: Precision::F64,
            quantity: spectrum::Quantity::Amplitude,
        };
        let config = Config {
            comparison: comparison::Settings::default(),
            lockin: lockin::Settings::default(),
            spectrum,
            spectrum_channel: channels - 1,
            spectrum_mode: SpectrumMode::Continuous,
            scope: ScopeSettings {
                mode: acquisition::Mode::Auto,
                channels: ScopeChannels::default(),
                samples: size,
                trigger: Trigger {
                    edge: signal::Edge::Free,
                    ..Trigger::default()
                },
            },
            calibrations: calibration::Set::default(),
            xy_channels: Pair::<2>::default(),
            stft_generation: 0,
            stft: stft::Config {
                analysis: crate::stft::Analysis::Spectrogram,
                log_floor_db: crate::cepstrum::DEFAULT_LOG_FLOOR_DB,
                sample_rate: 48000,
                channels,
                channel: channels - 1,
                size,
                hop: size / 4,
                window: spectrum.window,
                remove_dc: false,
                precision: spectrum.precision,
            },
        };
        let mut config = config;
        config.stft_generation = stft.configure(config.stft).unwrap();
        let mut spectrum = spectrum_worker::Worker::new();
        let mut core = Core::new(
            stft.take_feeder(),
            spectrum.take_feeder(),
            Arc::new(Metrics::default()),
        );
        core.start(1, 48000, channels, config.clone());
        (stft, core, config, spectrum)
    }

    fn frame(sequence: u64, size: usize, channels: usize, amplitude: f64) -> [f64; MAX_CHANNELS] {
        let mut samples = [0.0; MAX_CHANNELS];
        for (channel, value) in samples.iter_mut().enumerate().take(channels) {
            *value = amplitude * (channel + 1) as f64 / channels as f64
                * (TAU * 32.0 * sequence as f64 / size as f64).sin();
        }
        samples
    }

    fn wait_for_frames(worker: &Worker, count: u64) {
        let deadline = Instant::now() + Duration::from_secs(3);
        while worker.metrics.input_frames.load(Ordering::Relaxed) < count {
            assert!(
                Instant::now() < deadline,
                "measurement worker stopped consuming input"
            );
            thread::sleep(Duration::from_millis(2));
        }
    }

    #[test]
    fn generator_live_changes_reset_spectrum_and_lockin_on_the_actual_sample_boundary() {
        use crate::generator::{self, Settings as GeneratorSettings};
        let (_stft, mut core, mut config, _spectrum) = setup(8192, 2);
        config.lockin = lockin::Settings {
            enabled: true,
            frequency_hz: 750.0,
            time_constant_seconds: 0.005,
            ..Default::default()
        };
        config.scope.samples = 512;
        core.start(81, 48_000, 2, config);
        let mut settings = GeneratorSettings::default();
        for (i, s) in settings.signals.iter_mut().enumerate() {
            s.enabled = true;
            s.frequency_hz = 750.0;
            s.amplitude_dbfs = 20.0 * (0.125 / (i + 1) as f64).log10();
        }
        settings.signals[1].phase_degrees = 30.0;
        let mut engine = generator::Engine::new(48_000, 2, settings, 0).unwrap();
        engine.start(settings, 1).unwrap();
        for sequence in 0..96_000 {
            if sequence == 48_000 {
                settings.signals[1].amplitude_dbfs = 20.0 * 0.03125_f64.log10();
                settings.signals[1].phase_degrees = -90.0;
                engine.configure(settings, 2).unwrap();
            }
            let condition = output::Condition::from_status(engine.status());
            let f = engine.next_frame().unwrap();
            core.push_generator(output::Frame {
                sequence: f.sequence,
                samples: [f.samples[0], f.samples[1]],
                condition,
                #[cfg(feature = "qa")]
                available_at: Instant::now(),
            });
        }
        let snapshot = finish(&mut core);
        let timeline = snapshot.generator_output.as_ref().unwrap();
        timeline.validate(48_000, 96_000).unwrap();
        assert!(
            timeline
                .spans
                .iter()
                .any(|s| s.sample_range.start == 48_000 && s.condition.transitioning)
        );
        let condition = timeline
            .stationary(snapshot.lockin.sample_range.clone())
            .unwrap();
        assert_eq!(condition.revision, 2);
        assert_eq!(snapshot.lockin.state, lockin::State::Valid);
        assert!(snapshot.lockin.sample_range.start >= 48_480);
        assert!(snapshot.spectrum_info.contributing.start >= 48_480);
        assert!((snapshot.lockin.amplitude_peak.unwrap() - 0.03125).abs() < 1e-8);
        assert!((snapshot.lockin.phase_degrees.unwrap() + 90.0).abs() < 1e-6);
        assert!((snapshot.lockin.reference_frequency_hz.unwrap() - 750.0).abs() < 1e-7);
        assert!((snapshot.spectrum.power()[128].sqrt() - 0.03125).abs() < 1e-8);
        assert!((snapshot.measurements[1].rms - 0.03125 / 2.0_f64.sqrt()).abs() < 1e-8);
        assert_eq!(snapshot.input_dropped, 0);
    }

    #[test]
    fn generator_input_and_output_stop_independently_with_held_conditions_and_continuing_silence() {
        let (_stft, core, mut config, _spectrum) = setup(8192, 2);
        config.lockin = lockin::Settings {
            enabled: true,
            frequency_hz: 750.0,
            time_constant_seconds: 0.005,
            ..Default::default()
        };
        let worker = Worker::new(core.feeder);
        let mut output = output::Worker::new();
        let mut settings = crate::generator::Settings::default();
        for s in &mut settings.signals {
            s.enabled = true;
            s.frequency_hz = 750.0;
        }
        output.start(settings).unwrap();
        worker
            .start_generator(90, output.capture().unwrap(), 48_000, config.clone())
            .unwrap();
        wait_for_frames(&worker, 24_000);
        let held = worker.stop();
        assert_eq!(held.input_dropped, 0);
        assert!(!held.failed);
        assert_eq!(held.lockin.state, lockin::State::Valid);
        assert!((held.spectrum.power()[128].sqrt() - 0.1).abs() < 1e-8);
        let end = held.history.range().end;
        let deadline = Instant::now() + Duration::from_secs(3);
        loop {
            if let Some(u) = output.poll()
                && u.status.next_sample > end + 1024
            {
                assert_eq!(u.status.state, crate::generator::State::Running);
                break;
            }
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(2));
        }
        worker
            .start_generator(91, output.capture().unwrap(), 48_000, config)
            .unwrap();
        wait_for_frames(&worker, 36_000);
        output.stop();
        let deadline = Instant::now() + Duration::from_secs(3);
        loop {
            if let Some(u) = output.poll()
                && u.status.state == crate::generator::State::Stopped
            {
                break;
            }
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(2));
        }
        let count = worker.metrics.input_frames.load(Ordering::Relaxed);
        wait_for_frames(&worker, count + 10_000);
        let silent = worker.stop();
        assert!(silent.history.range().start > end);
        assert_eq!(silent.input_dropped, 0);
        assert!(!silent.failed);
        assert_eq!(silent.measurements[0].rms, 0.0);
        assert_eq!(silent.spectrum.power()[128], 0.0);
        assert_eq!(silent.lockin.state, lockin::State::ReferenceLost);
        assert!(
            held.generator_output
                .unwrap()
                .spans
                .iter()
                .all(|s| s.condition.active)
        );
        assert!(
            !silent
                .generator_output
                .unwrap()
                .spans
                .last()
                .unwrap()
                .condition
                .active
        );
    }

    #[test]
    fn stop_and_stream_failure_include_capture_loss_after_the_last_accepted_frame() {
        for failed in [false, true] {
            let (_stft, core, mut config, _spectrum) = setup(1024, 2);
            config.lockin = lockin::Settings {
                enabled: true,
                frequency_hz: 1500.0,
                integration_samples: 1024,
                time_constant_seconds: 0.001,
                track_reference: false,
                ..Default::default()
            };
            let worker = Worker::new(core.feeder);
            let (mut producer, consumer) = RingBuffer::new(1024);
            let metrics = Arc::new(AudioMetrics::default());
            let input: Vec<f64> = (0..1055)
                .flat_map(|n| {
                    let x = (TAU * 1500.0 * n as f64 / 48000.0).sin();
                    [0.125 * x, 0.0625 * x]
                })
                .collect();
            crate::audio::write_callback(&input, 2, &mut producer, &mut 0, &metrics);
            assert_eq!(metrics.dropped.load(Ordering::Relaxed), 31);
            metrics.failed.store(failed, Ordering::Relaxed);
            worker.start_capture(
                17,
                Capture {
                    consumer,
                    sample_rate: 48000,
                    channels: 2,
                    format: "test f64".into(),
                    metrics,
                },
                config.clone(),
            );
            if failed {
                wait_for_frames(&worker, 1024);
                let automatic_stop = worker.scope(config.scope);
                assert!(automatic_stop.failed);
                assert_eq!(automatic_stop.history.range(), 0..1055);
            }
            let stopped = worker.stop();
            assert_eq!(stopped.history.range(), 0..1055);
            assert!(stopped.history.get(1023).is_some());
            assert!(stopped.history.get(1024).is_none());
            assert_eq!(stopped.input_dropped, 31);
            assert_eq!(stopped.failed, failed);
            assert_eq!(stopped.scope_missing, 31);
            assert_eq!(stopped.lockin.state, lockin::State::Missing);
            assert_eq!(stopped.lockin.missing_samples, 31);
            assert_eq!(stopped.lockin.processed_windows, 0);
            assert!(stopped.lockin.amplitude_peak.is_none());
            assert!(stopped.lockin.x.is_none());
            assert_eq!(stopped.spectrum_info.input_end, 1055);
            assert_eq!(stopped.spectrum_info.input_missing, 31);
            assert_eq!(stopped.spectrum_info.updates, 0);
            assert!(!stopped.spectrum.is_ready());
            let held = worker.stop();
            assert_eq!(held.history.range(), stopped.history.range());
            assert_eq!(held.input_dropped, 31);
            assert_eq!(held.lockin, stopped.lockin);
            assert_eq!(held.spectrum_info.input_missing, 31);
        }
    }

    #[test]
    fn external_output_is_frozen_at_input_stop_single_and_failure() {
        for mode in ["stop", "single", "failure"] {
            let (_stft, core, mut config, _spectrum) = setup(1024, 2);
            if mode == "single" {
                config.scope.mode = acquisition::Mode::Single;
                config.scope.samples = 128;
                config.scope.trigger.level = 0.0;
                config.scope.trigger.channel = 0;
                config.scope.trigger.edge = signal::Edge::Rising;
            }
            let mut worker = Worker::new(core.feeder);
            let (mut producer, consumer) = RingBuffer::new(1024);
            let metrics = Arc::new(AudioMetrics::default());
            let input: Vec<f64> = (0..1024)
                .flat_map(|n| {
                    let x = (TAU * 1500.0 * n as f64 / 48000.0).sin();
                    [0.125 * x, 0.0625 * x]
                })
                .collect();
            crate::audio::write_callback(&input, 2, &mut producer, &mut 0, &metrics);
            metrics.failed.store(mode == "failure", Ordering::Release);
            let history = output::history::tests::fixture_handle();
            worker.start_capture_observed(
                51,
                Capture {
                    consumer,
                    sample_rate: 48_000,
                    channels: 2,
                    format: "test f64".into(),
                    metrics,
                },
                config.clone(),
                Some(&history),
            );
            wait_for_frames(&worker, 128);
            let held = worker.stop();
            if mode == "single" {
                assert_eq!(held.acquisition_state, acquisition::State::Complete);
            }
            if mode == "failure" {
                assert!(held.failed);
            }
            let output = held.external_output.as_ref().unwrap();
            output.validate(51).unwrap();
            assert_eq!(
                output.latest.as_ref().unwrap().status.nominal_sample_rate,
                96_000
            );
            thread::sleep(Duration::from_millis(3));
            let reprojected = worker.scope(config.scope);
            assert_eq!(held.external_output, reprojected.external_output);
            // A new unobserved input generation cannot inherit old evidence.
            let (producer, consumer) = RingBuffer::new(4);
            worker.start_capture(
                52,
                Capture {
                    consumer,
                    sample_rate: 48_000,
                    channels: 2,
                    format: "test f64".into(),
                    metrics: Arc::new(AudioMetrics::default()),
                },
                config.clone(),
            );
            assert!(worker.stop().external_output.is_none());
            drop(producer);
            while let Some(snapshot) = worker.take_latest() {
                worker.recycle(snapshot);
            }
        }
    }

    #[test]
    fn capture_tail_loss_invalidates_normal_capture_but_does_not_extend_single() {
        for mode in [acquisition::Mode::Normal, acquisition::Mode::Single] {
            let (_stft, core, mut config, _spectrum) = setup(1024, 2);
            config.scope.mode = mode;
            config.scope.samples = 10;
            config.scope.trigger = Trigger {
                channel: 0,
                level: 0.5,
                edge: signal::Edge::Rising,
            };
            let worker = Worker::new(core.feeder);
            let (mut producer, consumer) = RingBuffer::new(1024);
            let metrics = Arc::new(AudioMetrics::default());
            let input: Vec<f64> = (0..1055)
                .flat_map(|n| [if n == 12 { 1.0 } else { 0.0 }, 0.0])
                .collect();
            crate::audio::write_callback(&input, 2, &mut producer, &mut 0, &metrics);
            worker.start_capture(
                18,
                Capture {
                    consumer,
                    sample_rate: 48000,
                    channels: 2,
                    format: "test f64".into(),
                    metrics: metrics.clone(),
                },
                config,
            );
            let stopped = worker.stop();
            assert_eq!(metrics.dropped.load(Ordering::Relaxed), 31);
            if mode == acquisition::Mode::Single {
                assert_eq!(stopped.history.range(), 0..20);
                assert_eq!(stopped.acquisition_state, acquisition::State::Complete);
                assert_eq!(stopped.scope_capture.unwrap().range(), 10..20);
                assert_eq!(stopped.input_dropped, 0);
                assert_eq!(stopped.spectrum_info.input_end, 20);
                assert_eq!(stopped.spectrum_info.input_missing, 0);
            } else {
                assert_eq!(stopped.history.range(), 0..1055);
                assert_eq!(stopped.acquisition_state, acquisition::State::Waiting);
                assert!(stopped.scope_capture.unwrap().is_empty());
                assert_eq!(stopped.input_dropped, 31);
                assert_eq!(stopped.spectrum_info.input_end, 1055);
                assert_eq!(stopped.spectrum_info.input_missing, 31);
            }
        }
    }

    #[test]
    fn variable_callbacks_keep_lockin_fft_and_history_consistent_across_input_changes() {
        let (mut stft, core, mut config, _spectrum) = setup(1024, 2);
        let worker = Worker::new(core.feeder);
        let mut received = 0;
        let mut held: Option<Snapshot> = None;
        for (index, (channels, rate)) in
            [(1, 48000), (2, 44100), (16, 96000), (2, 192000), (1, 48000)]
                .into_iter()
                .enumerate()
        {
            let generation = index as u64 + 30;
            let frequency = 32.0 * rate as f64 / 1024.0;
            let amplitude = if channels == 1 { 0.125 } else { 0.0625 };
            let phase: f64 = if channels == 1 { 0.0 } else { 30.0 };
            let sample = |n: u64, ch: usize| {
                let angle = TAU * frequency * n as f64 / rate as f64;
                if ch == 0 {
                    0.1 + 0.125 * angle.sin()
                } else if ch == channels - 1 {
                    0.2 + amplitude * (angle + phase.to_radians()).sin()
                } else {
                    ch as f64 * 1e-8
                }
            };
            config.lockin = lockin::Settings {
                enabled: true,
                frequency_hz: frequency,
                reference_channel: 0,
                response_channel: channels - 1,
                integration_samples: 1024,
                time_constant_seconds: 0.001,
                track_reference: false,
                ..Default::default()
            };
            config.spectrum_channel = channels - 1;
            config.spectrum.remove_dc = true;
            config.stft.sample_rate = rate;
            config.stft.channels = channels;
            config.stft.channel = channels - 1;
            config.stft_generation = stft.configure(config.stft).unwrap();
            let (mut producer, consumer) = RingBuffer::new(2048);
            let metrics = Arc::new(AudioMetrics::default());
            worker.start_capture(
                generation,
                Capture {
                    consumer,
                    sample_rate: rate,
                    channels: channels as u16,
                    format: "test f64".into(),
                    metrics: metrics.clone(),
                },
                config.clone(),
            );
            let fresh = worker.scope(config.scope);
            assert_eq!(fresh.generation, generation);
            assert_eq!(fresh.sample_rate, rate);
            assert_eq!(fresh.lockin.settings, config.lockin);
            assert!(fresh.lockin.amplitude_peak.is_none());
            assert!(fresh.history.is_empty());
            assert!(!fresh.spectrum.is_ready());
            #[cfg(feature = "qa")]
            assert!(fresh.spectrum_timing.is_none());
            let mut sequence = 0;
            #[cfg(feature = "qa")]
            let mut endpoint_callback = None;
            for count in [0, 1, 17, 63, 256, 511, 1025, 7].into_iter().cycle() {
                let count = count.min(8229 - sequence as usize);
                let end = sequence + count as u64;
                let input: Vec<f64> = (sequence..end)
                    .flat_map(|n| (0..channels).map(move |ch| sample(n, ch)))
                    .collect();
                #[cfg(feature = "qa")]
                let before = Instant::now();
                #[cfg(feature = "qa")]
                let includes_endpoint = sequence < 8192 && end >= 8192;
                crate::audio::write_callback(
                    &input,
                    channels,
                    &mut producer,
                    &mut sequence,
                    &metrics,
                );
                #[cfg(feature = "qa")]
                if includes_endpoint {
                    endpoint_callback = Some((before, Instant::now()));
                }
                received += count as u64;
                wait_for_frames(&worker, received);
                stft.drain(|row| {
                    assert_eq!(row.info.generation, config.stft_generation);
                    assert_eq!(row.info.config.sample_rate, rate);
                    assert_eq!(row.info.config.channel, channels - 1);
                    assert_eq!(row.info.gap.input_frames, 0);
                });
                if sequence == 8229 {
                    break;
                }
            }
            let captured = worker.stop();
            assert_eq!(metrics.input_end.load(Ordering::Acquire), 8229);
            assert_eq!(captured.history.range(), 0..8229);
            assert_eq!(captured.history.channels(), channels);
            assert_eq!(captured.input_dropped, 0);
            assert_eq!(captured.scope_missing, 0);
            assert!(!captured.failed);
            for n in [0, 1, 1023, 1024, 8191, 8228] {
                for ch in 0..channels {
                    assert_eq!(captured.history.get(n).unwrap()[ch], sample(n, ch));
                }
            }
            let r = &captured.lockin;
            assert_eq!(r.state, lockin::State::Valid);
            assert_eq!(r.settings, config.lockin);
            assert_eq!(r.sample_range, 0..8192);
            assert_eq!(r.latest_window, 7168..8192);
            assert_eq!(r.processed_windows, 8);
            assert_eq!(r.missing_samples, 0);
            assert!((r.amplitude_peak.unwrap() - amplitude).abs() < 1e-10);
            assert!((r.phase_degrees.unwrap() - phase).abs() < 1e-7);
            assert!((r.gain.unwrap() - amplitude / 0.125).abs() < 1e-10);
            assert_eq!(captured.spectrum_info.input_end, 8229);
            assert_eq!(captured.spectrum_info.input_missing, 0);
            assert_eq!(captured.spectrum_info.updates, 29);
            assert_eq!(captured.spectrum.window().unwrap().end, 8192);
            #[cfg(feature = "qa")]
            {
                let timing = captured.spectrum_timing.unwrap();
                let (before, after) = endpoint_callback.unwrap();
                assert_eq!(timing.end, 8192);
                assert!((before..=after).contains(&timing.input_available));
                assert!(timing.analysis_completed >= timing.input_available);
                if let Some(previous) = &held {
                    assert_ne!(timing.epoch, previous.spectrum_timing.unwrap().epoch);
                }
            }
            assert_eq!(captured.spectrum.window().unwrap().sample_rate, rate);
            assert_eq!(captured.spectrum.window().unwrap().channel, channels - 1);
            assert!((captured.spectrum.cursor(frequency).unwrap().value - amplitude).abs() < 1e-10);
            assert_eq!(stft.metrics.input_dropped.load(Ordering::Relaxed), 0);
            if let Some(previous) = &held {
                assert_ne!(previous.generation, captured.generation);
                assert_eq!(previous.history.range(), 0..8229);
                assert_eq!(previous.lockin.processed_windows, 8);
                assert_eq!(previous.spectrum_info.updates, 29);
            }
            held = Some(captured);
        }
    }

    #[test]
    fn live_rate_changes_update_analysis_and_preserve_held_conditions() {
        let (_stft, core, config, _spectrum) = setup(1024, 2);
        let worker = Worker::new(core.feeder);
        let mut held: Option<Snapshot> = None;
        for (index, rate) in [44_100, 48_000, 96_000, 192_000, 48_000]
            .into_iter()
            .enumerate()
        {
            let (mut producer, consumer) = RingBuffer::new(1024);
            let generation = index as u64 + 10;
            worker.start_capture(
                generation,
                Capture {
                    consumer,
                    sample_rate: rate,
                    channels: 2,
                    format: "test f64".into(),
                    metrics: Arc::new(AudioMetrics::default()),
                },
                config.clone(),
            );
            let fresh = worker.scope(config.scope);
            assert_eq!(fresh.generation, generation);
            assert_eq!(fresh.sample_rate, rate);
            assert_eq!(fresh.stft_config.sample_rate, rate);
            assert!(fresh.history.is_empty());
            assert!(!fresh.spectrum.is_ready());
            if let Some(previous) = &held {
                assert_eq!(
                    previous.spectrum.window().unwrap().sample_rate,
                    previous.sample_rate
                );
                assert_ne!(previous.generation, fresh.generation);
                assert_eq!(previous.history.range(), 0..1024);
            }
            for sequence in 0..1024 {
                producer
                    .push(AudioFrame {
                        #[cfg(feature = "qa")]
                        available_at: None,
                        sequence,
                        samples: frame(sequence, 1024, 2, 0.25),
                    })
                    .unwrap();
            }
            let captured = worker.stop_async().wait();
            assert_eq!(captured.sample_rate, rate);
            assert_eq!(captured.stft_config.sample_rate, rate);
            assert_eq!(captured.spectrum.window().unwrap().sample_rate, rate);
            assert_eq!(captured.spectrum.average().unwrap().updates, 1);
            assert_eq!(captured.spectrum_info.input_missing, 0);
            assert_eq!(captured.history.range(), 0..1024);
            let hz = 32.0 * rate as f64 / 1024.0;
            let reading = captured.spectrum.cursor(hz).unwrap();
            assert_eq!(reading.frequency_hz, hz);
            assert!((reading.value - 0.25).abs() < 1e-13);
            assert!((captured.measurements[1].rms - 0.25 / 2.0_f64.sqrt()).abs() < 1e-13);
            assert_eq!(
                crate::cursor::sample_at_age(1024, 511.5 / rate as f64, rate),
                Some(512)
            );
            held = Some(captured);
        }
    }

    fn stalled_display(channels: usize, size: usize) {
        let (mut stft, core, mut config, _spectrum) = setup(size, channels);
        // Exercise PSD at the maximum FFT while retaining amplitude regression.
        if size == 32768 {
            config.spectrum.quantity = spectrum::Quantity::Psd;
        }
        let mut worker = Worker::new(core.feeder);
        let (mut producer, consumer) = RingBuffer::new(24000); // 0.5 seconds
        let capture_metrics = Arc::new(AudioMetrics::default());
        worker.start_capture(
            10,
            Capture {
                consumer,
                sample_rate: 48000,
                channels: channels as u16,
                format: "test f64".into(),
                metrics: capture_metrics,
            },
            config.clone(),
        );
        let total = if size == 1024 {
            // Leave more than the full small-FFT tier unread so this remains
            // a saturation test as the bounded result headroom improves.
            config.stft.size + (stft::RESULT_ROWS + stft::SMALL_RESULT_ROWS + 16) * config.stft.hop
        } else {
            49152
        };
        let clock = Instant::now();
        // No display snapshot or STFT result is consumed for over twice the
        // audio queue duration. Real input is paced separately from the UI.
        for start in (0..total).step_by(256) {
            let end = (start + 256).min(total);
            for sequence in start..end {
                assert!(
                    producer
                        .push(AudioFrame {
                            #[cfg(feature = "qa")]
                            available_at: None,
                            sequence: sequence as u64,
                            samples: frame(sequence as u64, size, channels, 0.25),
                        })
                        .is_ok(),
                    "UI stall overflowed capture queue"
                );
            }
            let deadline = clock + Duration::from_secs_f64(end as f64 / 48000.0);
            if let Some(delay) = deadline.checked_duration_since(Instant::now()) {
                thread::sleep(delay);
            }
        }
        wait_for_frames(&worker, total as u64);
        let stopped = worker.stop();
        assert_eq!(stopped.generation, 10);
        assert_eq!(stopped.history.range().end, total as u64);
        assert_eq!(stopped.input_dropped, 0);
        assert_eq!(stopped.spectrum_info.missing_windows, 0);
        assert_eq!(
            stopped.spectrum_info.updates,
            (1 + (total - size) / (size / 4)) as u64
        );
        let expected = if config.spectrum.quantity == spectrum::Quantity::Psd {
            0.03125 / (48000.0 / size as f64)
        } else {
            0.0625
        };
        assert!((stopped.spectrum.power()[32] - expected).abs() < 1e-12);
        if config.spectrum.quantity == spectrum::Quantity::Psd {
            assert!((stopped.spectrum.band(0.0, 24000.0).unwrap().power - 0.03125).abs() < 1e-12);
        }
        assert!(worker.metrics.display_skipped.load(Ordering::Relaxed) > 0);
        assert_eq!(stft.metrics.input_dropped.load(Ordering::Relaxed), 0);
        if size == 1024 {
            let deadline = Instant::now() + Duration::from_secs(5);
            while stft.metrics.processed_frames.load(Ordering::Acquire) < total as u64 {
                assert!(Instant::now() < deadline);
                thread::sleep(Duration::from_millis(1));
            }
            assert!(stft.metrics.result_dropped.load(Ordering::Relaxed) > 0);
        }
        // Next-run edits and unread old publications cannot change held input.
        worker.configure_spectrum(Settings::default(), 0, SpectrumMode::Latest);
        let held = worker.scope(config.scope);
        assert_eq!(held.history.range(), stopped.history.range());
        assert_eq!(held.spectrum.window(), stopped.spectrum.window());
        assert_eq!(held.spectrum.power(), stopped.spectrum.power());
        assert_eq!(held.spectrum.settings(), stopped.spectrum.settings());
        assert_eq!(held.spectrum.average(), stopped.spectrum.average());
        assert_eq!(held.spectrum.hold_power(), stopped.spectrum.hold_power());
        let old = worker.take_latest().unwrap();
        assert!(old.revision < held.revision);
        worker.recycle(old);
        stft.pause();
        // A new input generation resets coordinates, averages and source CH.
        let mut resumed = config.clone();
        resumed.stft_generation = stft.configure(config.stft).unwrap();
        worker.start_demo(11, Demo::default(), resumed);
        let fresh = worker.scope(config.scope);
        assert_eq!(fresh.generation, 11);
        assert!(fresh.spectrum.window().is_none());
        assert_eq!(fresh.spectrum_info.updates, 0);
        let final_result = worker.stop();
        assert_eq!(final_result.generation, 11);
        assert!(final_result.history.range().end < stopped.history.range().end);
        drop(worker); // joins an active/idle worker before its STFT endpoint
    }

    #[test]
    fn mono_measurement_continues_when_ui_and_stft_delivery_stall() {
        stalled_display(1, 1024);
    }
    #[test]
    fn stereo_maximum_fft_continues_when_ui_stalls() {
        stalled_display(2, 32768);
    }
    #[test]
    fn sixteen_channel_maximum_fft_continues_when_ui_stalls() {
        stalled_display(16, 32768);
    }

    #[test]
    fn saturated_capture_reports_loss_once_and_recovers_without_mixing_generations() {
        let (mut stft, core, mut config, _spectrum) = setup(1024, 1);
        config.scope.samples = 2048;
        let worker = Worker::new(core.feeder);
        let (mut producer, consumer) = RingBuffer::new(8);
        let capture_metrics = Arc::new(AudioMetrics::default());
        for sequence in 0..16 {
            if producer
                .push(AudioFrame {
                    #[cfg(feature = "qa")]
                    available_at: None,
                    sequence,
                    samples: frame(sequence, 1024, 1, 0.25),
                })
                .is_err()
            {
                capture_metrics.dropped.fetch_add(1, Ordering::Relaxed);
            }
        }
        worker.start_capture(
            7,
            Capture {
                consumer,
                sample_rate: 48000,
                channels: 1,
                format: "test".into(),
                metrics: capture_metrics,
            },
            config,
        );
        wait_for_frames(&worker, 8);
        for sequence in 16..2064 {
            let mut audio_frame = AudioFrame {
                #[cfg(feature = "qa")]
                available_at: None,
                sequence,
                samples: frame(sequence, 1024, 1, 0.5),
            };
            loop {
                match producer.push(audio_frame) {
                    Ok(()) => break,
                    Err(rtrb::PushError::Full(value)) => {
                        audio_frame = value;
                        thread::sleep(Duration::from_millis(1));
                    }
                }
            }
        }
        wait_for_frames(&worker, 2056);
        let result = worker.stop();
        assert_eq!(result.input_dropped, 8);
        assert_eq!(result.spectrum_info.missing_windows, 1);
        assert_eq!(result.spectrum_info.updates, 5);
        assert_eq!(result.spectrum_info.contributing, 16..2064);
        assert!((result.spectrum.power()[32] - 0.25).abs() < 1e-12);
        assert_eq!(result.scope_missing, 0);
        stft.pause();
    }

    #[test]
    fn route_changes_hold_provenance_and_device_reduction_keeps_unavailable_ids() {
        let (mut stft, core, mut config, _spectrum) = setup(1024, 16);
        config.scope.channels = Pair([15, 7]).scope();
        config.xy_channels = Pair([7, 15]);
        config.scope.trigger = Trigger {
            edge: signal::Edge::Rising,
            level: 0.0,
            channel: 15,
        };
        let worker = Worker::new(core.feeder);
        let (mut producer, consumer) = RingBuffer::new(2048);
        for sequence in 0..2048 {
            producer
                .push(AudioFrame {
                    #[cfg(feature = "qa")]
                    available_at: None,
                    sequence,
                    samples: frame(sequence, 1024, 16, 0.25),
                })
                .unwrap();
        }
        worker.start_capture(
            1,
            Capture {
                consumer,
                sample_rate: 48000,
                channels: 16,
                format: "test f64".into(),
                metrics: Arc::new(AudioMetrics::default()),
            },
            config.clone(),
        );
        wait_for_frames(&worker, 2048);
        let first = worker.scope(config.scope);
        assert_eq!(first.scope_settings.channels, Pair([15, 7]).scope());
        assert_eq!(first.xy_channels, Pair([7, 15]));
        assert!(first.sweep.triggered);
        assert_eq!(first.measurements[0].samples, 1024);
        assert!((first.measurements[0].rms - 0.25 / 2.0_f64.sqrt()).abs() < 1e-14);
        let swapped = ScopeSettings {
            channels: Pair([7, 15]).scope(),
            ..config.scope
        };
        worker.configure_xy(Pair([15, 7]));
        let rerouted = worker.scope(swapped);
        assert_eq!(
            rerouted.measurements,
            [
                first.measurements[1],
                first.measurements[0],
                first.measurements[2],
                first.measurements[3]
            ]
        );
        assert_eq!(rerouted.xy_channels, Pair([15, 7]));
        assert_eq!(rerouted.spectrum_info.updates, first.spectrum_info.updates);
        let held = worker.stop();
        worker.configure_xy(Pair([0, 1]));
        let unchanged = worker.scope(config.scope);
        assert_eq!(unchanged.scope_settings.channels, swapped.channels);
        assert_eq!(unchanged.xy_channels, held.xy_channels);
        assert_eq!(unchanged.measurements, held.measurements);
        config.scope.channels = Pair([15, 0]).scope();
        config.xy_channels = Pair([15, 7]);
        config.stft_generation = stft.configure(config.stft).unwrap();
        worker.start_demo(2, Demo::default(), config.clone());
        let fresh = worker.scope(config.scope);
        assert_eq!(fresh.generation, 2);
        assert_eq!(fresh.history.channels(), 2);
        assert_eq!(fresh.scope_settings.channels, Pair([15, 0]).scope());
        assert_eq!(fresh.scope_settings.trigger.channel, 15);
        assert_eq!(fresh.xy_channels, Pair([15, 7]));
        assert!(!fresh.sweep.triggered);
        assert_eq!(fresh.measurements[0].samples, 0);
        drop(worker);
    }
    #[test]
    fn stream_failure_is_observable_even_when_the_snapshot_pool_is_full() {
        let (stft, core, config, _spectrum) = setup(1024, 1);
        let worker = Worker::new(core.feeder);
        let (_producer, consumer) = RingBuffer::new(1024);
        let audio_metrics = Arc::new(AudioMetrics::default());
        worker.start_capture(
            42,
            Capture {
                consumer,
                sample_rate: 48000,
                channels: 1,
                format: "test".into(),
                metrics: audio_metrics.clone(),
            },
            config.clone(),
        );
        thread::sleep(Duration::from_millis(150));
        assert!(worker.metrics.display_skipped.load(Ordering::Relaxed) > 0);
        audio_metrics.failed.store(true, Ordering::Relaxed);
        let deadline = Instant::now() + Duration::from_secs(3);
        while !worker.metrics.failed.load(Ordering::Acquire) {
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(2));
        }
        let result = worker.stop();
        assert_eq!(result.generation, 42);
        assert!(result.failed);
        worker.start_demo(43, Demo::default(), config.clone());
        let resumed = worker.scope(config.scope);
        assert_eq!(resumed.generation, 43);
        assert!(!resumed.failed);
        drop(worker);
        drop(stft);
    }

    #[test]
    fn channel_calibration_is_fixed_to_scope_and_spectrum_across_hold_route_and_restart() {
        let (_stft, core, mut config, _spectrum) = setup(1024, 16);
        config.scope.channels = Pair([15, 7]).scope();
        let definition = |revision, gain, offset| {
            calibration::Calibration::new(
                "known-input-ch16".into(),
                revision,
                gain,
                offset,
                "V".into(),
                "Test: 0.25 FS peak sine, 48 kHz nominal, 16 synchronized channels".into(),
            )
            .unwrap()
        };
        config.calibrations = config
            .calibrations
            .with(15, Some(definition(1, 4.0, 0.5)))
            .unwrap();
        let worker = Worker::new(core.feeder);
        let capture = || {
            let (mut producer, consumer) = RingBuffer::new(2048);
            for sequence in 0..2048 {
                producer
                    .push(AudioFrame {
                        #[cfg(feature = "qa")]
                        available_at: None,
                        sequence,
                        samples: frame(sequence, 1024, 16, 0.25),
                    })
                    .unwrap();
            }
            Capture {
                consumer,
                sample_rate: 48000,
                channels: 16,
                format: "test f64".into(),
                metrics: Arc::new(AudioMetrics::default()),
            }
        };
        worker.start_capture(1, capture(), config.clone());
        wait_for_frames(&worker, 2048);
        let measured = worker.scope(config.scope);
        let Reading::Valid(m) = measured.scope_readings[0] else {
            panic!("calibrated readout")
        };
        assert!((m.rms - 0.75_f64.sqrt()).abs() < 1e-14);
        assert_eq!(m.peak, 1.5);
        assert_eq!(m.peak_to_peak, 2.0);
        assert_eq!(m.samples, 1024);
        assert_eq!(measured.calibrations.get(15).unwrap().revision(), 1);
        assert_eq!(measured.calibrations.unit(7), "FS");
        assert!((measured.measurements[0].rms - 0.25 / 2.0_f64.sqrt()).abs() < 1e-14);
        assert!((measured.spectrum.power()[32] - 1.0).abs() < 1e-14);
        assert!((measured.spectrum.cursor(0.0).unwrap().value - 0.5).abs() < 1e-14);
        assert_eq!(measured.spectrum.window().unwrap().channel, 15);
        assert_eq!(measured.spectrum.calibration().unwrap().revision(), 1);
        assert_eq!(measured.spectrum.db_unit(), "dB re 1 V peak");
        assert_eq!(measured.history.get(8).unwrap()[15], 0.25);

        let rerouted = worker.scope(ScopeSettings {
            channels: Pair([7, 15]).scope(),
            ..config.scope
        });
        assert_eq!(
            rerouted.scope_readings,
            [
                measured.scope_readings[1],
                measured.scope_readings[0],
                measured.scope_readings[2],
                measured.scope_readings[3]
            ]
        );
        let held = worker.stop();
        config.calibrations = config
            .calibrations
            .with(15, Some(definition(2, -8.0, -1.0)))
            .unwrap();
        let display = worker.scope(ScopeSettings {
            samples: 2048,
            ..config.scope
        });
        // Reprojecting retained data and editing the next input's calibration
        // do not relabel or recalibrate the held generation.
        assert_eq!(display.calibrations, held.calibrations);
        assert_eq!(display.scope_settings.channels, Pair([7, 15]).scope());
        let Reading::Valid(m) = display.scope_readings[1] else {
            panic!("held calibration")
        };
        assert!((m.rms - 0.75_f64.sqrt()).abs() < 1e-14);
        assert_eq!(display.sweep.range, 0..2048);
        assert_eq!(display.scope_missing, 0);
        assert_eq!(display.input_dropped, 0);
        assert_eq!(display.spectrum.window(), held.spectrum.window());
        assert_eq!(display.spectrum.power(), held.spectrum.power());
        assert_eq!(display.spectrum.hold_power(), held.spectrum.hold_power());

        config.spectrum.quantity = spectrum::Quantity::Psd;
        worker.start_capture(2, capture(), config.clone());
        wait_for_frames(&worker, 4096);
        let fresh = worker.stop();
        assert_eq!(fresh.generation, 2);
        assert_eq!(fresh.calibrations.get(15).unwrap().revision(), 2);
        let Reading::Valid(m) = fresh.scope_readings[0] else {
            panic!("new calibration")
        };
        assert!((m.rms - 3.0_f64.sqrt()).abs() < 1e-14);
        assert_eq!(m.peak, 3.0);
        assert_eq!(m.peak_to_peak, 4.0);
        assert_eq!(fresh.spectrum.calibration().unwrap().revision(), 2);
        assert_eq!(fresh.spectrum.db_unit(), "dB re 1 V²/Hz");
        assert!((fresh.spectrum.band(0.0, 24000.0).unwrap().power - 3.0).abs() < 1e-14);
        assert_eq!(fresh.spectrum_info.invalid_windows, 0);
        // An already-delivered result still identifies its original revision.
        assert_eq!(measured.calibrations.get(15).unwrap().gain(), 4.0);
        assert_eq!(measured.calibrations.get(15).unwrap().revision(), 1);
        assert_eq!(measured.spectrum.calibration().unwrap().revision(), 1);
        config.spectrum_channel = 7;
        worker.start_capture(3, capture(), config.clone());
        wait_for_frames(&worker, 6144);
        let uncalibrated = worker.stop();
        assert_eq!(uncalibrated.spectrum.window().unwrap().channel, 7);
        assert!(uncalibrated.spectrum.calibration().is_none());
        assert_eq!(uncalibrated.spectrum.db_unit(), "dB re FS²/Hz");
        assert!(
            (uncalibrated.spectrum.band(0.0, 24000.0).unwrap().power - 0.0078125).abs() < 1e-14
        );
        worker.start_demo(4, Demo::default(), config.clone());
        let reduced = worker.scope(config.scope);
        assert_eq!(reduced.scope_readings[0], Reading::Unavailable);
        assert_eq!(reduced.calibrations.get(15).unwrap().revision(), 2);
        assert_eq!(reduced.history.channels(), 2);
        assert!(reduced.spectrum.calibration().is_none());
    }
    #[test]
    fn large_fft_transport_stop_and_restart_keep_acquisition_history_bounded() {
        for (channels, rate, mode) in [
            (1, 44100, SpectrumMode::Continuous),
            (2, 48000, SpectrumMode::Continuous),
            (2, 96000, SpectrumMode::Latest),
            (16, 192000, SpectrumMode::Live),
            (16, 192000, SpectrumMode::Continuous),
        ] {
            let (_stft, core, mut config, _unused_spectrum) = setup(1024, channels);
            config.spectrum.size = 524288;
            config.spectrum_mode = mode;
            let mut worker = Worker::new(core.feeder);
            let (mut producer, consumer) = RingBuffer::new(8192);
            worker.start_capture(
                71,
                Capture {
                    consumer,
                    sample_rate: rate,
                    channels: channels as u16,
                    format: "test f64".into(),
                    metrics: Arc::new(AudioMetrics::default()),
                },
                config.clone(),
            );
            let total = 524288 + 2 * 131072;
            for start in (0..total).step_by(1024) {
                for sequence in start..start + 1024 {
                    let mut samples = [0.125; MAX_CHANNELS];
                    samples[channels - 1] = if sequence < 524288 { 0.25 } else { 0.5 };
                    producer
                        .push(AudioFrame {
                            #[cfg(feature = "qa")]
                            available_at: None,
                            sequence: sequence as u64,
                            samples,
                        })
                        .unwrap();
                }
                wait_for_frames(&worker, (start + 1024) as u64);
            }
            let raw = worker.take_latest().unwrap();
            assert!(
                !raw.has_spectrum,
                "Scope publications must not copy FFT bins"
            );
            worker.recycle(raw);
            let pending = worker.stop_async();
            // Next-run edits while the finite-end FFT barrier is pending must
            // not invalidate its queued samples or held analysis settings.
            worker.configure_spectrum(Settings::default(), 0, SpectrumMode::Latest);
            let mut stopped = pending.wait();
            assert_eq!(stopped.history.len(), (2 * rate as usize).max(32768));
            assert_eq!(stopped.history.channels(), channels);
            assert_eq!(stopped.input_dropped, 0);
            assert_eq!(stopped.spectrum_info.input_missing, 0);
            assert_eq!(stopped.spectrum_info.missing_windows, 0);
            assert_eq!(stopped.spectrum.window().unwrap().end, total as u64);
            assert_eq!(stopped.spectrum.window().unwrap().channel, channels - 1);
            assert_eq!(stopped.spectrum.settings().size, 524288);
            if mode == SpectrumMode::Continuous {
                assert_eq!(stopped.spectrum_info.updates, 3);
            }
            worker.clear_hold();
            let held = worker.scope(config.scope);
            assert_eq!(held.spectrum.hold_power(), held.spectrum.power());
            assert_eq!(held.spectrum.average(), stopped.spectrum.average());
            worker.configure_spectrum(Settings::default(), 0, SpectrumMode::Latest);
            let edited = worker.scope(config.scope);
            assert_eq!(edited.spectrum.settings(), stopped.spectrum.settings());
            worker.start_demo(72, Demo::default(), config.clone());
            let fresh = worker.scope(config.scope);
            assert_eq!(fresh.generation, 72);
            assert!(!fresh.spectrum.is_ready());
            assert_eq!(fresh.spectrum_info.updates, 0);
            // Previously returned values remain valid after pool recycling and restart.
            assert!(stopped.spectrum.is_ready());
            stopped.spectrum.clear_hold();
        }
    }
}
