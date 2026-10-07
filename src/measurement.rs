//! UI-independent acquisition, shared f64 history and measurement scheduling.
//! The callback transfers fixed frames; this worker never waits for a display.
use crate::{
    audio::Capture,
    channel::{ChannelId, Pair},
    demo::Demo,
    signal::{self, History, Measurement, Sweep, Trigger},
    spectrum::{self, Analyzer, Settings},
    stft,
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
    /// Every complete N/4-hop window; average/hold updates follow sample time.
    #[default]
    Continuous,
    /// Newest complete window, at most 30/s; transients can go unobserved.
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

#[derive(Clone, Copy, Debug)]
pub struct Config {
    pub spectrum: Settings,
    pub spectrum_channel: ChannelId,
    pub spectrum_mode: SpectrumMode,
    pub scope: ScopeSettings,
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
    pub scope_missing: u64,
    /// Capture loss is separate from display publications and STFT delivery.
    pub input_dropped: u64,
    pub failed: bool,
    pub fft_ms: f64,
}

#[derive(Default)]
pub struct Metrics {
    pub failed: AtomicBool,
    pub input_frames: AtomicU64,
    pub spectrum_windows: AtomicU64,
    pub display_skipped: AtomicU64,
    pub processing_nanos: AtomicU64,
}

enum Input {
    Idle,
    Audio(Capture),
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
    Demo(Demo),
    Scope(ScopeSettings, mpsc::SyncSender<Snapshot>),
    Xy(Pair),
    Hold,
    Stop(mpsc::SyncSender<Snapshot>),
    Shutdown,
}

/// GUI-free core also used directly by deterministic input tests. The worker is
/// only the execution wrapper; all measurement scheduling lives here.
struct Core {
    generation: u64,
    revision: u64,
    sample_rate: u32,
    history: History,
    analyzer: Analyzer,
    config: Config,
    spectrum_info: SpectrumInfo,
    next_end: Option<u64>,
    expected: Option<u64>,
    dropped: u64,
    capture_dropped: u64,
    failed: bool,
    fft_ms: f64,
    last_latest: Instant,
    feeder: stft::Feeder,
    metrics: Arc<Metrics>,
}

impl Core {
    fn new(feeder: stft::Feeder, metrics: Arc<Metrics>) -> Self {
        let config = Config {
            spectrum: Settings::default(),
            spectrum_channel: 0,
            spectrum_mode: SpectrumMode::Continuous,
            scope: ScopeSettings::default(),
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
        Self {
            generation: 0,
            revision: 0,
            sample_rate: 48000,
            history: History::new(96000),
            analyzer: Analyzer::new(config.spectrum, 48000),
            config,
            spectrum_info: SpectrumInfo::default(),
            next_end: None,
            expected: None,
            dropped: 0,
            capture_dropped: 0,
            failed: false,
            fft_ms: 0.0,
            last_latest: Instant::now() - DISPLAY_INTERVAL,
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
        self.config = config;
        self.expected = None;
        self.dropped = 0;
        self.capture_dropped = 0;
        self.failed = false;
        self.metrics.failed.store(false, Ordering::Release);
        self.spectrum_info.missing_windows = 0;
        self.configure_spectrum(
            config.spectrum,
            config.spectrum_channel,
            config.spectrum_mode,
        );
        self.feeder.configure(config.stft_generation, config.stft);
    }

    fn configure_spectrum(&mut self, settings: Settings, channel: usize, mode: SpectrumMode) {
        self.config.spectrum = settings;
        self.config.spectrum_channel = channel.min(self.history.channels() - 1);
        self.config.spectrum_mode = mode;
        self.analyzer = Analyzer::new(settings, self.sample_rate);
        self.reset_average();
        let start = self.history.range().end;
        self.next_end = Some(start + settings.size as u64);
        self.last_latest = Instant::now() - DISPLAY_INTERVAL;
    }

    fn reset_average(&mut self) {
        self.analyzer.reset();
        self.spectrum_info.mode = self.config.spectrum_mode;
        self.spectrum_info.updates = 0;
        self.spectrum_info.contributing = 0..0;
    }

    fn push(&mut self, sequence: u64, samples: &[f64]) {
        if self.expected != Some(sequence) {
            let missing = self
                .expected
                .map_or(sequence, |end| sequence.saturating_sub(end));
            self.dropped += missing;
            if self.expected.is_some()
                && self.config.spectrum_mode == SpectrumMode::Continuous
                && let Some(next) = self.next_end
            {
                // Windows overlapping a gap are invalid, not zero-filled. A
                // discontinuity restarts the hop grid after a full valid window.
                let recovered = sequence + self.config.spectrum.size as u64;
                if recovered > next {
                    let hop = (self.config.spectrum.size / 4) as u64;
                    self.spectrum_info.missing_windows += (recovered - next).div_ceil(hop);
                }
            }
            self.reset_average();
            self.next_end = Some(sequence + self.config.spectrum.size as u64);
        }
        self.expected = Some(sequence + 1);
        self.history.push_at(sequence, samples);
        self.feeder.submit(sequence, samples);
        self.metrics.input_frames.fetch_add(1, Ordering::Relaxed);
        if self.config.spectrum_mode == SpectrumMode::Continuous
            && self.next_end == Some(sequence + 1)
        {
            self.analyze(sequence + 1);
            self.next_end = Some(sequence + 1 + (self.config.spectrum.size / 4) as u64);
        }
    }

    fn analyze(&mut self, end: u64) {
        if self.analyzer.window().is_some_and(|info| info.end == end) {
            return;
        }
        let Some(start) = end.checked_sub(self.config.spectrum.size as u64) else {
            return;
        };
        let started = Instant::now();
        if self
            .analyzer
            .update_window(&self.history, start..end, self.config.spectrum_channel)
        {
            self.fft_ms = started.elapsed().as_secs_f64() * 1000.0;
            let average = self.analyzer.average().unwrap();
            self.spectrum_info.updates = average.updates;
            self.spectrum_info.contributing = average.start..average.end;
            self.metrics
                .spectrum_windows
                .fetch_add(1, Ordering::Relaxed);
        }
    }

    fn latest(&mut self, final_snapshot: bool) {
        if self.config.spectrum_mode == SpectrumMode::Latest
            && (final_snapshot || self.last_latest.elapsed() >= DISPLAY_INTERVAL)
        {
            let end = self.history.range().end;
            let hop = (self.config.spectrum.size / 4) as u64;
            if end - self.history.contiguous_range().start >= self.config.spectrum.size as u64
                && self
                    .analyzer
                    .window()
                    .is_none_or(|w| end.saturating_sub(w.end) >= hop)
            {
                self.analyze(end);
                self.last_latest = Instant::now();
            }
        }
    }

    fn snapshot(&mut self) -> Snapshot {
        let mut snapshot = Snapshot {
            generation: 0,
            revision: 0,
            sample_rate: self.sample_rate,
            history: History::new(1),
            spectrum: spectrum::Result::empty(self.config.spectrum, self.sample_rate),
            spectrum_info: SpectrumInfo::default(),
            stft_generation: self.config.stft_generation,
            stft_config: self.config.stft,
            scope_settings: self.config.scope,
            xy_channels: self.config.xy_channels,
            sweep: Sweep::default(),
            measurements: [Measurement::default(); 2],
            scope_missing: 0,
            input_dropped: 0,
            failed: false,
            fft_ms: 0.0,
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
        self.analyzer.copy_result(&mut snapshot.spectrum);
        snapshot.spectrum_info.clone_from(&self.spectrum_info);
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
        snapshot.scope_missing = snapshot
            .sweep
            .range
            .clone()
            .filter(|&i| self.history.get(i).is_none())
            .count() as u64;
        snapshot.input_dropped = self.dropped.max(self.capture_dropped);
        snapshot.failed = self.failed;
        snapshot.fft_ms = self.fft_ms;
    }
}

pub struct Worker {
    commands: mpsc::SyncSender<Command>,
    results: Consumer<Box<Snapshot>>,
    recycle: Producer<Box<Snapshot>>,
    handle: Option<JoinHandle<()>>,
    pub metrics: Arc<Metrics>,
}

impl Worker {
    pub fn new(feeder: stft::Feeder) -> Self {
        let (commands, requests) = mpsc::sync_channel(16);
        let (mut outgoing, results) = RingBuffer::new(SNAPSHOTS);
        let (mut recycle, mut free) = RingBuffer::new(SNAPSHOTS);
        let metrics = Arc::new(Metrics::default());
        let counters = metrics.clone();
        let mut core = Core::new(feeder, counters.clone());
        for _ in 0..SNAPSHOTS {
            recycle
                .push(Box::new(core.snapshot()))
                .unwrap_or_else(|_| unreachable!());
        }
        let handle = thread::Builder::new()
            .name("measurelab-core".into())
            .spawn(move || {
                let mut input = Input::Idle;
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
                                core.start(generation, rate, channels, config);
                                input = source;
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
                            Command::Demo(settings) => {
                                if let Input::Demo { signal, .. } = &mut input {
                                    signal.apply_settings(&settings);
                                    core.reset_average();
                                    core.next_end = Some(
                                        core.history.range().end + core.config.spectrum.size as u64,
                                    );
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
                                let _ = reply.try_send(core.snapshot());
                            }
                            Command::Xy(channels) => {
                                if !matches!(input, Input::Idle) {
                                    core.config.xy_channels = channels;
                                }
                            }
                            Command::Hold => core.analyzer.clear_hold(),
                            Command::Stop(reply) => {
                                poll_input(&mut input, &mut core);
                                core.latest(true);
                                input = Input::Idle;
                                let _ = reply.try_send(core.snapshot());
                            }
                            Command::Shutdown => break,
                        }
                    }
                    if !matches!(input, Input::Idle) {
                        poll_input(&mut input, &mut core);
                        core.latest(false);
                        if core.failed {
                            input = Input::Idle;
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
            results,
            recycle,
            handle: Some(handle),
            metrics,
        }
    }

    pub fn start_capture(&self, generation: u64, capture: Capture, config: Config) {
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
    pub fn start_demo(&self, generation: u64, demo: Demo, config: Config) {
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
        self.send(Command::Spectrum(settings, channel, mode));
    }
    pub fn configure_stft(&self, generation: u64, config: stft::Config) {
        self.send(Command::Stft(generation, config));
    }
    pub fn configure_demo(&self, demo: Demo) {
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

    /// Control barriers only wait for bounded current work. The core never
    /// waits for UI delivery; stop fixes the exact final history and FFT result.
    pub fn stop(&self) -> Snapshot {
        let (reply, result) = mpsc::sync_channel(1);
        self.send(Command::Stop(reply));
        result.recv().expect("measurement stop")
    }
    pub fn scope(&self, settings: ScopeSettings) -> Snapshot {
        let (reply, result) = mpsc::sync_channel(1);
        self.send(Command::Scope(settings, reply));
        result.recv().expect("measurement scope")
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
        Input::Demo {
            signal,
            clock,
            fraction,
        } => {
            let now = Instant::now();
            let elapsed = now.duration_since(*clock).as_secs_f64();
            *clock = now;
            // OS/worker suspension is still a discontinuity, never fabricated input.
            if elapsed > 0.25 {
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

    fn setup(size: usize, channels: usize) -> (stft::Worker, Core, Config) {
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
        let mut core = Core::new(stft.take_feeder(), Arc::new(Metrics::default()));
        core.start(1, 48000, channels, config);
        (stft, core, config)
    }

    fn frame(sequence: u64, size: usize, channels: usize, amplitude: f64) -> [f64; MAX_CHANNELS] {
        let mut samples = [0.0; MAX_CHANNELS];
        for (channel, value) in samples.iter_mut().enumerate().take(channels) {
            *value = amplitude * (channel + 1) as f64 / channels as f64
                * (TAU * 32.0 * sequence as f64 / size as f64).sin();
        }
        samples
    }

    #[test]
    fn continuous_windows_and_power_average_are_independent_of_snapshot_delivery() {
        for quantity in [spectrum::Quantity::Amplitude, spectrum::Quantity::Psd] {
            for channels in [1, 2, 16] {
                for size in [1024, 32768] {
                    let (_stft, mut core, mut config) = setup(size, channels);
                    config.spectrum.quantity = quantity;
                    core.configure_spectrum(
                        config.spectrum,
                        channels - 1,
                        SpectrumMode::Continuous,
                    );
                    let mut reference = Analyzer::new(config.spectrum, 48000);
                    let mut history = History::with_channels(size, channels);
                    let count = size * 3;
                    for sequence in 0..count as u64 {
                        let amplitude = if sequence < size as u64 { 0.25 } else { 0.5 };
                        let samples = frame(sequence, size, channels, amplitude);
                        core.push(sequence, &samples[..channels]);
                        history.push_at(sequence, samples);
                        let end = sequence + 1;
                        if end >= size as u64
                            && (end - size as u64).is_multiple_of((size / 4) as u64)
                        {
                            reference.update_window(&history, end - size as u64..end, channels - 1);
                        }
                        // Delivery can be skipped or duplicated without updating an average.
                        if sequence.is_multiple_of(size as u64 / 2 + 1) {
                            core.snapshot();
                        }
                    }
                    let result = core.snapshot();
                    let mut expected = spectrum::Result::empty(config.spectrum, 48000);
                    reference.copy_result(&mut expected);
                    assert_eq!(result.spectrum.power(), expected.power());
                    assert_eq!(result.spectrum.average(), expected.average());
                    assert_eq!(result.spectrum.hold_power(), expected.hold_power());
                    if quantity == spectrum::Quantity::Psd {
                        assert!(result.spectrum.band(0.0, 24000.0).unwrap().power_fs2 > 0.0);
                    }
                    assert_eq!(result.spectrum.db(), expected.db());
                    assert_eq!(result.spectrum_info.updates, 9);
                    assert_eq!(result.spectrum_info.contributing, 0..count as u64);
                    assert_eq!(result.spectrum_info.missing_windows, 0);
                    assert_eq!(result.input_dropped, 0);
                    assert_eq!(result.scope_missing, 0);
                    assert!(
                        (result.measurements[0].rms - 0.5 / channels as f64 / 2.0_f64.sqrt()).abs()
                            < 1e-12
                    );
                    assert_eq!(result.spectrum.window().unwrap().channel, channels - 1);
                    assert_eq!(result.spectrum.window().unwrap().end, count as u64);
                }
            }
        }
    }

    #[test]
    fn gaps_reset_averaging_count_invalid_windows_and_recover_after_a_full_window() {
        for quantity in [spectrum::Quantity::Amplitude, spectrum::Quantity::Psd] {
            let (_stft, mut core, mut config) = setup(1024, 2);
            config.spectrum.quantity = quantity;
            core.configure_spectrum(config.spectrum, 1, SpectrumMode::Continuous);
            for sequence in 0..2048 {
                core.push(sequence, &frame(sequence, 1024, 2, 0.25)[..2]);
            }
            let before = core.snapshot();
            assert_eq!(before.spectrum_info.updates, 5);
            for sequence in 2080..3103 {
                core.push(sequence, &frame(sequence, 1024, 2, 0.5)[..2]);
            }
            let invalid = core.snapshot();
            assert_eq!(invalid.input_dropped, 32);
            assert_eq!(invalid.spectrum_info.missing_windows, 4);
            assert!(invalid.spectrum.window().is_none());
            assert_eq!(invalid.scope_missing, 1);
            core.push(3103, &frame(3103, 1024, 2, 0.5)[..2]);
            let recovered = core.snapshot();
            assert_eq!(recovered.spectrum_info.updates, 1);
            assert_eq!(recovered.spectrum_info.contributing, 2080..3104);
            assert_eq!(recovered.spectrum_info.missing_windows, 4);
            let expected = if quantity == spectrum::Quantity::Amplitude {
                0.25
            } else {
                0.125 / (48000.0 / 1024.0)
            };
            assert!((recovered.spectrum.power()[32] - expected).abs() < 1e-12);
            assert_eq!(recovered.spectrum.average().unwrap().updates, 1);
            if quantity == spectrum::Quantity::Psd {
                assert!(
                    (recovered.spectrum.band(0.0, 24000.0).unwrap().power_fs2 - 0.125).abs()
                        < 1e-12
                );
            }
            assert_eq!(recovered.scope_missing, 0);
        }
    }

    #[test]
    fn latest_mode_uses_new_windows_and_stop_never_reaverages_the_same_window() {
        let (_stft, mut core, config) = setup(1024, 1);
        core.configure_spectrum(config.spectrum, 0, SpectrumMode::Latest);
        for sequence in 0..4096 {
            core.push(sequence, &frame(sequence, 1024, 1, 0.25)[..1]);
        }
        assert_eq!(core.spectrum_info.updates, 0);
        core.latest(true);
        let before = core.snapshot();
        for _ in 0..4 {
            core.latest(true);
        }
        let after = core.snapshot();
        assert_eq!(after.spectrum_info.updates, 1);
        assert_eq!(after.spectrum_info.mode, SpectrumMode::Latest);
        assert_eq!(after.spectrum.window(), before.spectrum.window());
        assert_eq!(after.spectrum.power(), before.spectrum.power());
        assert_eq!(after.spectrum_info.contributing, 3072..4096);
    }

    #[test]
    fn continuous_psd_observes_a_transient_that_latest_window_can_miss() {
        for mode in [SpectrumMode::Continuous, SpectrumMode::Latest] {
            let (_stft, mut core, mut config) = setup(1024, 1);
            config.spectrum.quantity = spectrum::Quantity::Psd;
            config.spectrum.averages = 1;
            core.configure_spectrum(config.spectrum, 0, mode);
            for sequence in 0..4096 {
                core.push(sequence, &[if sequence == 1024 { 0.5 } else { 0.0 }]);
            }
            core.latest(true);
            let result = core.snapshot();
            assert_eq!(result.spectrum.band(0.0, 24000.0).unwrap().power_fs2, 0.0);
            assert_eq!(result.spectrum_info.contributing, 3072..4096);
            if mode == SpectrumMode::Continuous {
                assert_eq!(result.spectrum_info.updates, 13);
                // Rectangular-window impulse: interior density 2*A²/(Fs*N).
                assert!(
                    (result.spectrum.hold_power()[32] - 0.5 / (48000.0 * 1024.0)).abs() < 1e-20
                );
            } else {
                assert_eq!(result.spectrum_info.updates, 1);
                assert_eq!(result.spectrum.hold_power()[32], 0.0);
            }
            assert_eq!(result.spectrum_info.missing_windows, 0);
        }
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

    fn stalled_display(channels: usize, size: usize) {
        let (mut stft, core, mut config) = setup(size, channels);
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
            config,
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
            assert!(
                (stopped.spectrum.band(0.0, 24000.0).unwrap().power_fs2 - 0.03125).abs() < 1e-12
            );
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
        let mut resumed = config;
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
        let (mut stft, core, mut config) = setup(1024, 1);
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
            config,
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
        let (mut stft, core, mut config) = setup(1024, 16);
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
            config,
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
        worker.start_demo(2, Demo::default(), config);
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
        let (stft, core, config) = setup(1024, 1);
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
            config,
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
        worker.start_demo(43, Demo::default(), config);
        let resumed = worker.scope(config.scope);
        assert_eq!(resumed.generation, 43);
        assert!(!resumed.failed);
        drop(worker);
        drop(stft);
    }
}
