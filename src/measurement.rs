//! UI-independent acquisition, shared f64 history and measurement scheduling.
//! The callback transfers fixed frames; this worker never waits for a display.
#[cfg(any(test, feature = "qa"))]
use crate::demo::Demo;
use crate::{
    audio::Capture,
    calibration::{self, Reading},
    channel::{ChannelId, Pair},
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

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
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
    pub channels: Pair,
    pub samples: usize,
    pub trigger: Trigger,
}

impl Default for ScopeSettings {
    fn default() -> Self {
        Self {
            channels: Pair::default(),
            samples: 480,
            trigger: Trigger::default(),
        }
    }
}

#[derive(Clone, Debug)]
pub struct Config {
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
    pub generation: u64,
    pub revision: u64,
    pub sample_rate: u32,
    pub history: History,
    pub spectrum: spectrum::Result,
    pub spectrum_info: SpectrumInfo,
    /// Maps independently delivered STFT rows to this input generation.
    pub stft_generation: u64,
    pub stft_config: stft::Config,
    pub scope_settings: ScopeSettings,
    pub xy_channels: Pair,
    pub sweep: Sweep,
    pub measurements: [Measurement; 2],
    pub scope_readings: [Reading; 2],
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
    pub failed: AtomicBool,
    pub input_frames: AtomicU64,
    pub display_skipped: AtomicU64,
    pub processing_nanos: AtomicU64,
    pub input_poll_max_nanos: AtomicU64,
    pub demo_interval_max_nanos: AtomicU64,
    pub demo_suspensions: AtomicU64,
}

// Acquisition is a user-started, timing-sensitive operation even when its
// window is occluded. Keep the OS activity scoped to the live input lifetime.
#[cfg(target_os = "macos")]
struct InputActivity {
    process: objc2::rc::Retained<objc2_foundation::NSProcessInfo>,
    token:
        objc2::rc::Retained<objc2::runtime::ProtocolObject<dyn objc2::runtime::NSObjectProtocol>>,
}
#[cfg(not(target_os = "macos"))]
struct InputActivity;
impl InputActivity {
    fn new() -> Self {
        #[cfg(target_os = "macos")]
        {
            use objc2_foundation::{NSActivityOptions, NSProcessInfo, NSString};
            let process = NSProcessInfo::processInfo();
            let token = process.beginActivityWithOptions_reason(
                NSActivityOptions::UserInitiated | NSActivityOptions::LatencyCritical,
                &NSString::from_str("MeasureLab audio acquisition"),
            );
            Self { process, token }
        }
        #[cfg(not(target_os = "macos"))]
        Self
    }
}
#[cfg(target_os = "macos")]
impl Drop for InputActivity {
    fn drop(&mut self) {
        // SAFETY: this is the activity token returned by this process above.
        unsafe { self.process.endActivity(&self.token) };
    }
}

enum Input {
    Idle,
    Audio(Capture),
    #[cfg(any(test, feature = "qa"))]
    Demo {
        signal: Demo,
        clock: Instant,
        fraction: f64,
    },
}

enum Command {
    Start(u64, Input, u32, usize, Config),
    Spectrum(Settings, usize, SpectrumMode),
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
    generation: u64,
    revision: u64,
    sample_rate: u32,
    history: History,
    spectrum: spectrum_worker::Feeder,
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
            spectrum: Settings::default(),
            spectrum_channel: 0,
            spectrum_mode: SpectrumMode::Continuous,
            scope: ScopeSettings::default(),
            calibrations: calibration::Set::default(),
            xy_channels: Pair::default(),
            stft_generation: 0,
            stft: stft::Config {
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
            generation: 0,
            revision: 0,
            sample_rate: 48000,
            history: History::new(96000),
            spectrum,
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
            settings,
            mode,
            self.history.range().end,
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

    fn push(&mut self, sequence: u64, samples: &[f64]) {
        if self.expected != Some(sequence) {
            self.dropped += self
                .expected
                .map_or(sequence, |end| sequence.saturating_sub(end));
        }
        self.expected = Some(sequence + 1);
        self.history.push_at(sequence, samples);
        self.feeder.submit(sequence, samples);
        self.spectrum.submit(sequence, samples);
        self.metrics.input_frames.fetch_add(1, Ordering::Relaxed);
    }

    fn reply(&mut self, final_window: bool) -> Reply {
        let spectrum = self
            .spectrum
            .inspect(self.history.range().end, final_window);
        Reply {
            snapshot: self.snapshot(),
            spectrum,
        }
    }

    fn snapshot(&mut self) -> Snapshot {
        let mut snapshot = Snapshot {
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
            stft_generation: self.config.stft_generation,
            stft_config: self.config.stft,
            scope_settings: self.config.scope,
            xy_channels: self.config.xy_channels,
            sweep: Sweep::default(),
            measurements: [Measurement::default(); 2],
            scope_readings: [Reading::Unavailable; 2],
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
        self.revision += 1;
        snapshot.generation = self.generation;
        snapshot.revision = self.revision;
        snapshot.sample_rate = self.sample_rate;
        snapshot.history.clone_from(&self.history);
        snapshot.has_spectrum = false;
        snapshot.stft_generation = self.config.stft_generation;
        snapshot.stft_config = self.config.stft;
        snapshot.scope_settings = self.config.scope;
        snapshot.xy_channels = self.config.xy_channels;
        snapshot.sweep = if self.history.len() >= self.config.scope.samples {
            self.history
                .sweep(self.config.scope.samples, self.config.scope.trigger)
        } else {
            Sweep::default()
        };
        snapshot.measurements = signal::measure(
            &self.history,
            snapshot.sweep.range.clone(),
            self.config.scope.channels,
        );
        snapshot.calibrations.clone_from(&self.config.calibrations);
        snapshot.scope_readings = calibration::measure(
            &self.history,
            snapshot.sweep.range.clone(),
            self.config.scope.channels,
            &snapshot.calibrations,
        );
        snapshot.scope_missing = snapshot
            .sweep
            .range
            .clone()
            .filter(|&i| self.history.get(i).is_none())
            .count() as u64;
        snapshot.input_dropped = self.dropped.max(self.capture_dropped);
        snapshot.failed = self.failed;
    }
}

struct Reply {
    snapshot: Snapshot,
    spectrum: mpsc::Receiver<spectrum_worker::Publication>,
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
        let publication = self.reply.as_ref()?.spectrum.try_recv().ok()?;
        Some(Self::complete(
            self.reply.take().unwrap().snapshot,
            publication,
        ))
    }
    pub fn wait(self) -> Snapshot {
        let reply = self
            .reply
            .unwrap_or_else(|| self.incoming.recv().expect("measurement reply"));
        let publication = reply.spectrum.recv().expect("Spectrum barrier");
        Self::complete(reply.snapshot, publication)
    }
    fn complete(mut snapshot: Snapshot, publication: spectrum_worker::Publication) -> Snapshot {
        snapshot.spectrum = publication.result;
        snapshot.spectrum_info = publication.info;
        snapshot.fft_ms = publication.fft_ms;
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
                            Command::Start(generation, source, rate, channels, config) => {
                                activity = Some(InputActivity::new());
                                core.start(generation, rate, channels, config);
                                input = source;
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
                                core.config.scope = settings;
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
                            Command::Hold => core.spectrum.clear_hold(),
                            Command::Stop(reply) => {
                                poll_input(&mut input, &mut core);
                                input = Input::Idle;
                                activity.take();
                                let _ = reply.try_send(core.reply(true));
                            }
                            Command::Shutdown => break,
                        }
                    }
                    if !matches!(input, Input::Idle) {
                        poll_input(&mut input, &mut core);
                        if core.failed {
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
        }
    }

    pub fn start_capture(&self, generation: u64, capture: Capture, config: Config) {
        self.running.store(true, Ordering::Release);
        let rate = capture.sample_rate;
        let channels = capture.channels as usize;
        self.send(Command::Start(
            generation,
            Input::Audio(capture),
            rate,
            channels,
            config,
        ));
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
            config,
        ));
    }
    pub fn configure_spectrum(&self, settings: Settings, channel: usize, mode: SpectrumMode) {
        if self.running.load(Ordering::Acquire) {
            self.spectrum.invalidate();
        }
        self.send(Command::Spectrum(settings, channel, mode));
    }
    pub fn configure_stft(&self, generation: u64, config: stft::Config) {
        self.send(Command::Stft(generation, config));
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

fn poll_input(input: &mut Input, core: &mut Core) {
    let clock = Instant::now();
    match input {
        Input::Idle => {}
        Input::Audio(capture) => {
            let available = capture.consumer.slots();
            if let Ok(chunk) = capture.consumer.read_chunk(available) {
                for frame in chunk {
                    core.push(frame.sequence, &frame.samples[..capture.channels as usize]);
                }
            }
            core.capture_dropped = capture.metrics.dropped.load(Ordering::Relaxed);
            core.failed = capture.metrics.failed.load(Ordering::Relaxed);
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
                core.push(core.history.range().end, &frame);
            }
        }
    }
    core.feeder.flush();
    core.spectrum.flush();
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
            spectrum,
            spectrum_channel: channels - 1,
            spectrum_mode: SpectrumMode::Continuous,
            scope: ScopeSettings {
                channels: Pair::default(),
                samples: size,
                trigger: Trigger {
                    edge: signal::Edge::Free,
                    ..Trigger::default()
                },
            },
            calibrations: calibration::Set::default(),
            xy_channels: Pair::default(),
            stft_generation: 0,
            stft: stft::Config {
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
                metrics: capture_metrics.clone(),
            },
            config.clone(),
        );
        let total = if size == 1024 { 48000 } else { 49152 };
        let clock = Instant::now();
        // No display snapshot or STFT result is consumed for over twice the
        // audio queue duration. Real input is paced separately from the UI.
        for start in (0..total).step_by(256) {
            let end = (start + 256).min(total);
            for sequence in start..end {
                assert!(
                    producer
                        .push(AudioFrame {
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
            config.clone(),
        );
        wait_for_frames(&worker, 8);
        for sequence in 16..2064 {
            let mut audio_frame = AudioFrame {
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
        config.scope.channels = Pair([15, 7]);
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
        assert_eq!(first.scope_settings.channels, Pair([15, 7]));
        assert_eq!(first.xy_channels, Pair([7, 15]));
        assert!(first.sweep.triggered);
        assert_eq!(first.measurements[0].samples, 1024);
        assert!((first.measurements[0].rms - 0.25 / 2.0_f64.sqrt()).abs() < 1e-14);
        let swapped = ScopeSettings {
            channels: Pair([7, 15]),
            ..config.scope
        };
        worker.configure_xy(Pair([15, 7]));
        let rerouted = worker.scope(swapped);
        assert_eq!(
            rerouted.measurements,
            [first.measurements[1], first.measurements[0]]
        );
        assert_eq!(rerouted.xy_channels, Pair([15, 7]));
        assert_eq!(rerouted.spectrum_info.updates, first.spectrum_info.updates);
        let held = worker.stop();
        worker.configure_xy(Pair([0, 1]));
        let unchanged = worker.scope(config.scope);
        assert_eq!(unchanged.scope_settings.channels, swapped.channels);
        assert_eq!(unchanged.xy_channels, held.xy_channels);
        assert_eq!(unchanged.measurements, held.measurements);
        config.scope.channels = Pair([15, 0]);
        config.xy_channels = Pair([15, 7]);
        config.stft_generation = stft.configure(config.stft).unwrap();
        worker.start_demo(2, Demo::default(), config.clone());
        let fresh = worker.scope(config.scope);
        assert_eq!(fresh.generation, 2);
        assert_eq!(fresh.history.channels(), 2);
        assert_eq!(fresh.scope_settings.channels, Pair([15, 0]));
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
        config.scope.channels = Pair([15, 7]);
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
            channels: Pair([7, 15]),
            ..config.scope
        });
        assert_eq!(
            rerouted.scope_readings,
            [measured.scope_readings[1], measured.scope_readings[0]]
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
        assert_eq!(display.scope_settings.channels, Pair([7, 15]));
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
