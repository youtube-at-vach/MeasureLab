//! Bounded selected-channel Spectrum transport. Acquisition never executes FFTs
//! or waits for their completion; display pressure never skips continuous windows.
#![warn(clippy::redundant_clone)]
use crate::{
    calibration::Calibration,
    measurement::{SpectrumInfo, SpectrumMode},
    signal::History,
    spectrum::{self, Analyzer, Settings},
};
use rtrb::{Consumer, Producer, RingBuffer};
use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU64, Ordering},
        mpsc,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

pub const BLOCK_FRAMES: usize = 1024;
pub const INPUT_BLOCKS: usize = 256;
pub const RESULT_SLOTS: usize = 3;
pub const LATEST_INTERVAL: Duration = Duration::from_millis(100);
pub const LIVE_INTERVAL: Duration = Duration::from_nanos(16_666_667);

/// Leave at least half of a core for queue ingestion/publication and other
/// instruments. Smooth the measured cost to avoid cadence jitter; a slow FFT
/// immediately increases the budget, while recovery is gradual.
fn live_interval(fft_ms: f64) -> Duration {
    LIVE_INTERVAL.max(Duration::from_secs_f64(fft_ms * 2.0 / 1000.0))
}

pub fn observation_interval(size: usize) -> Duration {
    if size <= 32768 {
        Duration::from_millis(33)
    } else {
        LATEST_INTERVAL
    }
}

pub struct Source {
    pub generation: u64,
    pub rate: u32,
    pub channel: usize,
    pub calibration: Option<Arc<Calibration>>,
}

#[derive(Clone, Debug)]
struct Config {
    epoch: u64,
    generation: u64,
    rate: u32,
    channel: usize,
    settings: Settings,
    mode: SpectrumMode,
    start: u64,
    calibration: Option<Arc<Calibration>>,
}

#[derive(Clone)]
struct Block {
    config: Config,
    start: u64,
    len: usize,
    samples: [f64; BLOCK_FRAMES],
    // A continuous window can end inside a block containing several callbacks.
    // Keep the exact endpoint's timestamp rather than assigning the block tail.
    #[cfg(feature = "qa")]
    available_at: [Option<Instant>; BLOCK_FRAMES],
}

/// Monotonic host timestamps paired with one analysis window. QA only: these
/// are neither ADC clock calibration nor GPU/display presentation timestamps.
#[cfg(feature = "qa")]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Timing {
    pub epoch: u64,
    pub end: u64,
    pub input_available: Instant,
    pub analysis_completed: Instant,
}

pub struct Publication {
    pub generation: u64,
    pub epoch: u64,
    pub revision: u64,
    pub channel: usize,
    pub result: spectrum::Result,
    pub info: SpectrumInfo,
    pub fft_ms: f64,
    #[cfg(feature = "qa")]
    pub timing: Option<Timing>,
}

pub struct Metrics {
    pub input_dropped: AtomicU64,
    pub input_high_water: AtomicU64,
    pub display_skipped: AtomicU64,
    pub windows: AtomicU64,
    pub processing_nanos: AtomicU64,
    pub fft_max_nanos: AtomicU64,
    pub planning_max_nanos: AtomicU64,
    fft_histogram: [AtomicU64; 1000],
}

impl Default for Metrics {
    fn default() -> Self {
        Self {
            input_dropped: AtomicU64::new(0),
            input_high_water: AtomicU64::new(0),
            display_skipped: AtomicU64::new(0),
            windows: AtomicU64::new(0),
            processing_nanos: AtomicU64::new(0),
            fft_max_nanos: AtomicU64::new(0),
            planning_max_nanos: AtomicU64::new(0),
            fft_histogram: std::array::from_fn(|_| AtomicU64::new(0)),
        }
    }
}
impl Metrics {
    /// Upper edge of 0.1 ms buckets; overflow uses the measured maximum.
    pub fn fft_p95_ms(&self) -> f64 {
        let count: u64 = self
            .fft_histogram
            .iter()
            .map(|b| b.load(Ordering::Relaxed))
            .sum();
        if count == 0 {
            return 0.0;
        }
        let target = (count * 95).div_ceil(100);
        let mut sum = 0;
        for (i, bucket) in self.fft_histogram.iter().enumerate() {
            sum += bucket.load(Ordering::Relaxed);
            if sum >= target {
                return if i == 999 {
                    self.fft_max_nanos.load(Ordering::Relaxed) as f64 / 1e6
                } else {
                    (i + 1) as f64 / 10.0
                };
            }
        }
        self.fft_max_nanos.load(Ordering::Relaxed) as f64 / 1e6
    }
}

struct Processor {
    config: Config,
    history: History,
    analyzer: Analyzer,
    info: SpectrumInfo,
    expected: u64,
    next_end: u64,
    revision: u64,
    fft_ms: f64,
    budget_ms: f64,
    last_latest: Instant,
    last_nonfinite: Option<u64>,
    #[cfg(feature = "qa")]
    last_available: Option<Instant>,
    #[cfg(feature = "qa")]
    timing: Option<Timing>,
}

impl Processor {
    fn new(config: Config) -> Self {
        let mut history = History::with_channels(config.settings.size, 1);
        history.clear_at(config.start);
        let mut analyzer = Analyzer::new(config.settings, config.rate);
        analyzer.set_calibration(config.calibration.clone());
        Self {
            history,
            analyzer,
            info: SpectrumInfo {
                mode: config.mode,
                observation_ms: match config.mode {
                    SpectrumMode::Live => LIVE_INTERVAL.as_micros().div_ceil(1000) as u32,
                    SpectrumMode::Latest => {
                        observation_interval(config.settings.size).as_millis() as u32
                    }
                    SpectrumMode::Continuous => 0,
                },
                ..SpectrumInfo::default()
            },
            expected: config.start,
            next_end: config.start + config.settings.size as u64,
            revision: 1,
            fft_ms: 0.0,
            budget_ms: 0.0,
            last_latest: Instant::now() - observation_interval(config.settings.size),
            last_nonfinite: None,
            #[cfg(feature = "qa")]
            last_available: None,
            #[cfg(feature = "qa")]
            timing: None,
            config,
        }
    }

    fn gap_to(&mut self, next: u64) {
        if next == self.expected {
            return;
        }
        self.info.input_missing += next.saturating_sub(self.expected);
        if self.config.mode == SpectrumMode::Continuous {
            let recovered = next + self.config.settings.size as u64;
            self.info.missing_windows += recovered
                .saturating_sub(self.next_end)
                .div_ceil((self.config.settings.size / 4) as u64);
        }
        self.history.clear_at(next);
        self.last_nonfinite = None;
        #[cfg(feature = "qa")]
        {
            self.last_available = None;
            self.timing = None;
        }
        self.analyzer.reset();
        self.info.updates = 0;
        self.info.contributing = 0..0;
        self.next_end = next + self.config.settings.size as u64;
        self.expected = next;
        self.revision += 1;
    }

    fn process(&mut self, block: &Block, metrics: &Metrics) {
        self.gap_to(block.start);
        for (offset, &sample) in block.samples[..block.len].iter().enumerate() {
            let end = block.start + offset as u64 + 1;
            if !sample.is_finite() {
                // Shared History sanitizes nonfinite values for drawing. Keep
                // the source position so Spectrum cannot measure that zero.
                self.last_nonfinite = Some(end - 1);
            }
            self.history.push_at(end - 1, [sample]);
            #[cfg(feature = "qa")]
            {
                self.last_available = block.available_at[offset];
            }
            if self.config.mode == SpectrumMode::Continuous && end == self.next_end {
                self.analyze(end, metrics);
                self.next_end += (self.config.settings.size / 4) as u64;
            }
        }
        if !self.analyzer.is_ready()
            && self.history.len() / (self.config.rate as usize / 10).max(1)
                != self.info.filled_samples / (self.config.rate as usize / 10).max(1)
        {
            self.revision += 1;
        }
        self.expected = block.start + block.len as u64;
        self.info.input_end = self.expected;
        self.info.filled_samples = self.history.len();
    }

    fn analyze(&mut self, end: u64, metrics: &Metrics) {
        if self.analyzer.window().is_some_and(|w| w.end == end) {
            return;
        }
        let Some(start) = end.checked_sub(self.config.settings.size as u64) else {
            return;
        };
        let clock = Instant::now();
        if self
            .last_nonfinite
            .is_some_and(|sample| (start..end).contains(&sample))
        {
            self.analyzer.invalidate(end, 0);
        } else if !self.analyzer.update_window(&self.history, start..end, 0) {
            return;
        }
        let elapsed = clock.elapsed().as_nanos() as u64;
        #[cfg(feature = "qa")]
        {
            let completed = Instant::now();
            self.timing = self
                .last_available
                .filter(|&available| {
                    available <= completed && self.analyzer.validity() == spectrum::Validity::Valid
                })
                .map(|input_available| Timing {
                    epoch: self.config.epoch,
                    end,
                    input_available,
                    analysis_completed: completed,
                });
        }
        self.fft_ms = elapsed as f64 / 1e6;
        metrics.fft_max_nanos.fetch_max(elapsed, Ordering::Relaxed);
        metrics.fft_histogram[(elapsed / 100_000).min(999) as usize]
            .fetch_add(1, Ordering::Relaxed);
        metrics.windows.fetch_add(1, Ordering::Relaxed);
        let average = self.analyzer.average().unwrap();
        if self.analyzer.validity() == spectrum::Validity::NonFinite {
            self.info.invalid_windows += 1;
        }
        self.info.updates = average.updates;
        self.info.contributing = average.start..average.end;
        self.revision += 1;
    }

    fn latest(&mut self, final_window: bool, metrics: &Metrics) {
        if self.config.mode == SpectrumMode::Continuous {
            return;
        }
        let elapsed = self.last_latest.elapsed();
        let interval = if self.config.mode == SpectrumMode::Live {
            live_interval(self.budget_ms)
        } else {
            observation_interval(self.config.settings.size)
        };
        if !final_window && elapsed < interval {
            return;
        }
        let end = self.history.range().end;
        if end - self.history.contiguous_range().start < self.config.settings.size as u64
            || self.analyzer.window().is_some_and(|w| w.end == end)
            || (!final_window
                && self.config.mode == SpectrumMode::Latest
                && self.config.settings.size <= 32768
                && self.analyzer.window().is_some_and(|w| {
                    end.saturating_sub(w.end) < (self.config.settings.size / 4) as u64
                }))
        {
            return;
        }
        if !final_window
            && self.analyzer.is_ready()
            && (self.config.mode == SpectrumMode::Live || self.config.settings.size > 32768)
        {
            self.info.missed_observations +=
                (elapsed.as_nanos().saturating_sub(interval.as_nanos()) / interval.as_nanos())
                    as u64;
        }
        let observed = Instant::now();
        self.analyze(end, metrics);
        self.last_latest = observed;
        if self.config.mode == SpectrumMode::Live {
            self.budget_ms = self.fft_ms.max(self.budget_ms * 0.9 + self.fft_ms * 0.1);
            self.info.observation_ms =
                (live_interval(self.budget_ms).as_secs_f64() * 1000.0).ceil() as u32;
        }
    }

    fn copy(&self, publication: &mut Publication) {
        let copy_bins = self.analyzer.window().is_some()
            || publication.result.window().is_some()
            || publication.epoch != self.config.epoch
            || publication.result.settings() != self.config.settings;
        publication.generation = self.config.generation;
        publication.epoch = self.config.epoch;
        publication.revision = self.revision;
        publication.channel = self.config.channel;
        publication.info.clone_from(&self.info);
        publication.fft_ms = self.fft_ms;
        #[cfg(feature = "qa")]
        {
            publication.timing = self.timing;
        }
        if copy_bins {
            self.analyzer.copy_result(&mut publication.result);
        }
        publication.result.source_channel(self.config.channel);
    }

    fn publication(&self) -> Publication {
        let mut publication = Publication {
            generation: self.config.generation,
            epoch: self.config.epoch,
            revision: 0,
            channel: self.config.channel,
            result: spectrum::Result::empty(self.config.settings, self.config.rate),
            info: SpectrumInfo::default(),
            fft_ms: 0.0,
            #[cfg(feature = "qa")]
            timing: None,
        };
        self.copy(&mut publication);
        publication
    }
}

enum Control {
    Inspect {
        config: Config,
        target: u64,
        end: u64,
        final_window: bool,
        reply: mpsc::SyncSender<Publication>,
    },
    Clear {
        config: Config,
        target: u64,
    },
}
impl Control {
    fn target(&self) -> u64 {
        match self {
            Self::Inspect { target, .. } | Self::Clear { target, .. } => *target,
        }
    }
    fn config(&self) -> Config {
        match self {
            Self::Inspect { config, .. } | Self::Clear { config, .. } => config.clone(),
        }
    }
}

pub struct Feeder {
    input: Producer<Block>,
    pending: Option<Block>,
    controls: mpsc::SyncSender<Control>,
    submitted: u64,
    active: Arc<AtomicU64>,
    wake: thread::Thread,
    pub metrics: Arc<Metrics>,
}

pub struct Worker {
    feeder: Option<Feeder>,
    results: Consumer<Box<Publication>>,
    recycle: Producer<Box<Publication>>,
    active: Arc<AtomicU64>,
    shutdown: Arc<AtomicBool>,
    handle: Option<JoinHandle<()>>,
    pub metrics: Arc<Metrics>,
}

impl Worker {
    pub fn new() -> Self {
        Self::with_capacity(INPUT_BLOCKS)
    }

    fn with_capacity(capacity: usize) -> Self {
        let (input, mut incoming) = RingBuffer::<Block>::new(capacity);
        let (mut outgoing, results) = RingBuffer::new(RESULT_SLOTS);
        let (mut recycle, mut free) = RingBuffer::new(RESULT_SLOTS);
        let (controls, requests) = mpsc::sync_channel::<Control>(32);
        let config = Config {
            epoch: 0,
            generation: 0,
            rate: 48000,
            channel: 0,
            settings: Settings::default(),
            mode: SpectrumMode::Continuous,
            start: 0,
            calibration: None,
        };
        let placeholder = Processor::new(config);
        for _ in 0..RESULT_SLOTS {
            recycle
                .push(Box::new(placeholder.publication()))
                .unwrap_or_else(|_| unreachable!());
        }
        let active = Arc::new(AtomicU64::new(0));
        let shutdown = Arc::new(AtomicBool::new(false));
        let metrics = Arc::new(Metrics::default());
        let epoch = active.clone();
        let stop = shutdown.clone();
        let counters = metrics.clone();
        let handle = thread::Builder::new()
            .name("measurelab-spectrum".into())
            .spawn(move || {
                let mut processor: Option<Processor> = None;
                let mut read = 0;
                let mut control: Option<Control> = None;
                let mut published = (0, 0);
                while !stop.load(Ordering::Acquire) {
                    if control.is_none() {
                        control = requests.try_recv().ok();
                    }
                    let mut worked = false;
                    if control.as_ref().is_some_and(|c| read >= c.target()) {
                        let command = control.take().unwrap();
                        let config = command.config();
                        prepare(&mut processor, config, &counters);
                        let p = processor.as_mut().unwrap();
                        match command {
                            Control::Inspect {
                                end,
                                final_window,
                                reply,
                                ..
                            } => {
                                // Includes a dropped tail even when no later block reveals it.
                                if end > p.expected {
                                    p.gap_to(end);
                                }
                                p.info.input_end = p.expected;
                                p.info.filled_samples = p.history.len();
                                if final_window {
                                    p.latest(true, &counters);
                                }
                                let _ = reply.try_send(p.publication());
                            }
                            Control::Clear { .. } => {
                                p.analyzer.clear_hold();
                                p.revision += 1;
                            }
                        }
                        worked = true;
                    } else if let Ok(block) = incoming.pop() {
                        read += 1;
                        if block.config.epoch == epoch.load(Ordering::Acquire) {
                            prepare(&mut processor, block.config.clone(), &counters);
                            let clock = Instant::now();
                            processor.as_mut().unwrap().process(&block, &counters);
                            counters
                                .processing_nanos
                                .fetch_add(clock.elapsed().as_nanos() as u64, Ordering::Relaxed);
                        }
                        worked = true;
                    }
                    if let Some(p) = processor.as_mut()
                        && p.config.epoch == epoch.load(Ordering::Acquire)
                    {
                        // Observe the newest consumed window after draining the current
                        // queue, rather than repeatedly transforming a stale backlog.
                        if incoming.is_empty() {
                            let clock = Instant::now();
                            p.latest(false, &counters);
                            counters
                                .processing_nanos
                                .fetch_add(clock.elapsed().as_nanos() as u64, Ordering::Relaxed);
                        }
                        if published != (p.config.epoch, p.revision) {
                            if let Ok(mut publication) = free.pop() {
                                p.copy(&mut publication);
                                published = (p.config.epoch, p.revision);
                                outgoing
                                    .push(publication)
                                    .unwrap_or_else(|_| unreachable!("Spectrum result pool"));
                            } else if worked {
                                counters.display_skipped.fetch_add(1, Ordering::Relaxed);
                            }
                        }
                    }
                    if !worked {
                        thread::park_timeout(Duration::from_millis(2));
                    }
                }
            })
            .expect("Spectrum worker");
        Self {
            feeder: Some(Feeder {
                input,
                pending: None,
                controls,
                submitted: 0,
                active: active.clone(),
                wake: handle.thread().clone(),
                metrics: metrics.clone(),
            }),
            results,
            recycle,
            active,
            shutdown,
            handle: Some(handle),
            metrics,
        }
    }

    pub fn invalidate(&self) {
        self.active.fetch_add(1, Ordering::AcqRel);
    }
    pub fn take_feeder(&mut self) -> Feeder {
        self.feeder
            .take()
            .expect("Spectrum feeder already transferred")
    }
    pub fn take_latest(&mut self) -> Option<Box<Publication>> {
        let mut latest = None;
        for _ in 0..self.results.slots() {
            let result = self.results.pop().unwrap();
            if result.epoch != self.active.load(Ordering::Acquire) {
                self.recycle(result);
                continue;
            }
            if let Some(old) = latest.replace(result) {
                self.recycle(old);
            }
        }
        latest
    }
    pub fn recycle(&mut self, result: Box<Publication>) {
        self.recycle
            .push(result)
            .unwrap_or_else(|_| unreachable!("Spectrum result pool"));
    }
}
impl Default for Worker {
    fn default() -> Self {
        Self::new()
    }
}
impl Drop for Worker {
    fn drop(&mut self) {
        self.shutdown.store(true, Ordering::Release);
        if let Some(handle) = self.handle.take() {
            handle.thread().unpark();
            let _ = handle.join();
        }
    }
}

fn prepare(processor: &mut Option<Processor>, config: Config, metrics: &Metrics) {
    if processor
        .as_ref()
        .is_none_or(|p| p.config.epoch != config.epoch)
    {
        let clock = Instant::now();
        *processor = Some(Processor::new(config));
        metrics
            .planning_max_nanos
            .fetch_max(clock.elapsed().as_nanos() as u64, Ordering::Relaxed);
    }
}

impl Feeder {
    pub fn configure(
        &mut self,
        source: Source,
        settings: Settings,
        mode: SpectrumMode,
        start: u64,
    ) {
        let epoch = self.active.fetch_add(1, Ordering::AcqRel) + 1;
        self.pending = Some(Block {
            config: Config {
                epoch,
                generation: source.generation,
                rate: source.rate,
                channel: source.channel,
                settings,
                mode,
                start,
                calibration: source.calibration,
            },
            start,
            len: 0,
            samples: [0.0; BLOCK_FRAMES],
            #[cfg(feature = "qa")]
            available_at: [None; BLOCK_FRAMES],
        });
    }
    pub fn submit(&mut self, sequence: u64, samples: &[f64]) {
        self.submit_frame(
            sequence,
            samples,
            #[cfg(feature = "qa")]
            None,
        );
    }
    pub(crate) fn submit_frame(
        &mut self,
        sequence: u64,
        samples: &[f64],
        #[cfg(feature = "qa")] available_at: Option<Instant>,
    ) {
        let Some(block) = self.pending.as_ref() else {
            return;
        };
        if block.len > 0 && sequence != block.start + block.len as u64 {
            self.flush();
        }
        let block = self.pending.as_mut().unwrap();
        let Some(&sample) = samples.get(block.config.channel) else {
            self.metrics.input_dropped.fetch_add(1, Ordering::Relaxed);
            return;
        };
        if block.len == 0 {
            block.start = sequence;
        }
        block.samples[block.len] = sample;
        #[cfg(feature = "qa")]
        {
            block.available_at[block.len] = available_at;
        }
        block.len += 1;
        if block.len == BLOCK_FRAMES {
            self.flush();
        }
    }
    pub fn flush(&mut self) {
        let Some(block) = self.pending.as_mut() else {
            return;
        };
        if block.len == 0 {
            return;
        }
        if self.input.push(block.clone()).is_ok() {
            self.submitted += 1;
            self.metrics.input_high_water.fetch_max(
                self.input.buffer().capacity() as u64 - self.input.slots() as u64,
                Ordering::Relaxed,
            );
        } else {
            self.metrics
                .input_dropped
                .fetch_add(block.len as u64, Ordering::Relaxed);
        }
        block.len = 0;
        self.wake.unpark();
    }
    pub fn inspect(&mut self, end: u64, final_window: bool) -> mpsc::Receiver<Publication> {
        self.flush();
        let (reply, result) = mpsc::sync_channel(1);
        let config = self
            .pending
            .as_ref()
            .expect("configured Spectrum")
            .config
            .clone();
        self.controls
            .try_send(Control::Inspect {
                config,
                target: self.submitted,
                end,
                final_window,
                reply,
            })
            .unwrap_or_else(|_| panic!("too many pending Spectrum barriers"));
        self.wake.unpark();
        result
    }
    pub fn clear_hold(&mut self) {
        self.flush();
        if let Some(block) = &self.pending {
            self.controls
                .try_send(Control::Clear {
                    config: block.config.clone(),
                    target: self.submitted,
                })
                .unwrap_or_else(|_| panic!("too many pending Spectrum barriers"));
            self.wake.unpark();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::spectrum::{Precision, Quantity, Window};
    use std::f64::consts::TAU;

    fn config(size: usize, mode: SpectrumMode, quantity: Quantity) -> Config {
        Config {
            epoch: 1,
            generation: 7,
            rate: 48000,
            channel: 15,
            settings: Settings {
                size,
                quantity,
                window: Window::Rectangular,
                averages: 4,
                remove_dc: false,
                precision: Precision::F64,
            },
            mode,
            start: 0,
            calibration: None,
        }
    }
    fn block(config: Config, start: u64, len: usize, amplitude: f64) -> Block {
        let mut block = Block {
            config: config.clone(),
            start,
            len,
            samples: [0.0; BLOCK_FRAMES],
            #[cfg(feature = "qa")]
            available_at: [None; BLOCK_FRAMES],
        };
        for (i, sample) in block.samples[..len].iter_mut().enumerate() {
            *sample = amplitude
                * (TAU * 32.0 * (start + i as u64) as f64 / config.settings.size as f64).sin();
        }
        block
    }

    #[cfg(feature = "qa")]
    #[test]
    fn latency_follows_the_exact_window_endpoint_across_modes_and_gaps() {
        for size in [1024, 524288] {
            for mode in [
                SpectrumMode::Continuous,
                SpectrumMode::Live,
                SpectrumMode::Latest,
            ] {
                let config = config(size, mode, Quantity::Amplitude);
                let metrics = Metrics::default();
                let mut p = Processor::new(config.clone());
                let endpoint = Instant::now() - Duration::from_secs(2);
                let tail = endpoint + Duration::from_millis(20);
                let mut start = 0;
                while start < size - 100 {
                    let len = (size - 100 - start).min(BLOCK_FRAMES);
                    let mut b = block(config.clone(), start as u64, len, 0.25);
                    b.available_at[..len].fill(Some(endpoint - Duration::from_millis(10)));
                    p.process(&b, &metrics);
                    start += len;
                }
                assert!(
                    p.publication().timing.is_none(),
                    "unfilled window has no latency"
                );
                let mut b = block(config.clone(), start as u64, 137, 0.25);
                b.available_at[..100].fill(Some(endpoint));
                b.available_at[100..137].fill(Some(tail));
                p.process(&b, &metrics);
                p.latest(true, &metrics);
                let publication = p.publication();
                let timing = publication.timing.unwrap();
                assert_eq!(timing.epoch, config.epoch);
                assert_eq!(timing.end, publication.result.window().unwrap().end);
                assert_eq!(
                    (timing.end, timing.input_available),
                    if mode == SpectrumMode::Continuous {
                        (size as u64, endpoint)
                    } else {
                        (size as u64 + 37, tail)
                    }
                );
                assert!(timing.analysis_completed >= timing.input_available);
                // Republish/Clear hold must preserve the original analysis time.
                p.analyzer.clear_hold();
                p.revision += 1;
                assert_eq!(p.publication().timing, Some(timing));
                p.gap_to(size as u64 + 55);
                assert!(p.publication().timing.is_none());
                assert!(!p.publication().result.is_ready());
                p.process(&block(config, size as u64 + 55, 100, 0.25), &metrics);
                p.latest(true, &metrics);
                assert!(
                    p.publication().timing.is_none(),
                    "gap cannot reuse a stale timestamp"
                );
            }
        }
    }

    #[cfg(feature = "qa")]
    #[test]
    fn untimed_or_nonfinite_input_cannot_publish_a_latency() {
        let config = config(1024, SpectrumMode::Continuous, Quantity::Amplitude);
        let metrics = Metrics::default();
        let mut p = Processor::new(config.clone());
        p.process(&block(config.clone(), 0, 1024, 0.25), &metrics);
        assert!(p.publication().result.is_ready());
        assert!(p.publication().timing.is_none());
        let mut b = block(config, 1024, 1024, 0.25);
        b.samples[1023] = f64::NAN;
        b.available_at
            .fill(Some(Instant::now() - Duration::from_secs(1)));
        p.process(&b, &metrics);
        assert_eq!(p.analyzer.validity(), spectrum::Validity::NonFinite);
        assert!(p.publication().timing.is_none());
    }

    #[test]
    fn calibrated_transport_all_modes_keep_conditions_and_reset_after_gap() {
        let definition = Arc::new(
            Calibration::new(
                "ch16-input".into(),
                7,
                -4.0,
                0.5,
                "V".into(),
                "Known internal fixture".into(),
            )
            .unwrap(),
        );
        for mode in [
            SpectrumMode::Continuous,
            SpectrumMode::Live,
            SpectrumMode::Latest,
        ] {
            for size in [1024, 524288] {
                let mut config = config(size, mode, Quantity::Psd);
                config.calibration = Some(definition.clone());
                let mut p = Processor::new(config.clone());
                let metrics = Metrics::default();
                for start in (0..size).step_by(BLOCK_FRAMES) {
                    p.process(
                        &block(config.clone(), start as u64, BLOCK_FRAMES, 0.25),
                        &metrics,
                    );
                }
                p.latest(true, &metrics);
                let held = p.publication();
                let window = held.result.window().unwrap();
                assert_eq!(window.channel, 15);
                assert_eq!(window.calibration.as_deref(), Some(definition.as_ref()));
                assert_eq!(held.generation, 7);
                assert!((held.result.band(0.0, 24000.0).unwrap().power - 0.75).abs() < 1e-12);
                let updates = held.info.updates;
                p.latest(true, &metrics);
                assert_eq!(
                    p.info.updates, updates,
                    "Stop must not average the same window twice"
                );
                let recovered = size as u64 + 12;
                for offset in (0..size).step_by(BLOCK_FRAMES) {
                    p.process(
                        &block(
                            config.clone(),
                            recovered + offset as u64,
                            BLOCK_FRAMES,
                            0.125,
                        ),
                        &metrics,
                    );
                }
                p.latest(true, &metrics);
                let fresh = p.publication();
                assert_eq!(fresh.info.input_missing, 12);
                assert_eq!(fresh.info.invalid_windows, 0);
                assert_eq!(fresh.info.updates, 1);
                assert_eq!(fresh.info.contributing, recovered..recovered + size as u64);
                assert_eq!(fresh.result.hold_power(), fresh.result.power());
                assert!((fresh.result.band(0.0, 24000.0).unwrap().power - 0.375).abs() < 1e-12);
                assert_eq!(held.result.window().unwrap(), window);
                assert!((held.result.band(0.0, 24000.0).unwrap().power - 0.75).abs() < 1e-12);
            }
        }
    }

    #[test]
    fn nonfinite_windows_count_separately_from_input_loss_and_recover() {
        let config = config(1024, SpectrumMode::Continuous, Quantity::Psd);
        let mut p = Processor::new(config.clone());
        let metrics = Metrics::default();
        p.process(&block(config.clone(), 0, BLOCK_FRAMES, 0.25), &metrics);
        let mut bad = block(config.clone(), 1024, BLOCK_FRAMES, 0.25);
        bad.samples[0] = f64::NAN;
        p.process(&bad, &metrics);
        let invalid = p.publication();
        assert_eq!(invalid.result.validity(), spectrum::Validity::NonFinite);
        assert_eq!(invalid.info.invalid_windows, 4);
        assert_eq!(invalid.info.updates, 0);
        assert_eq!(invalid.info.input_missing, 0);
        assert_eq!(invalid.info.missing_windows, 0);
        p.process(&block(config, 2048, BLOCK_FRAMES, 0.125), &metrics);
        let recovered = p.publication();
        assert_eq!(recovered.result.validity(), spectrum::Validity::Valid);
        assert_eq!(recovered.info.invalid_windows, 4);
        assert_eq!(recovered.info.updates, 4);
        assert_eq!(recovered.info.contributing, 1280..3072);
        assert!(
            (recovered.result.band(0.0, 24000.0).unwrap().power - 0.017974853515625).abs() < 1e-12
        );
    }

    #[test]
    fn continuous_all_windows_average_and_hold_match_headless_reference() {
        for size in [1024, 32768, 65536, 131072, 262144, 524288] {
            for quantity in [Quantity::Amplitude, Quantity::Psd, Quantity::Esd] {
                let config = config(size, SpectrumMode::Continuous, quantity);
                let mut processor = Processor::new(config.clone());
                let mut reference = Analyzer::new(config.settings, config.rate);
                let mut history = History::with_channels(size, 1);
                let metrics = Metrics::default();
                for start in (0..size * 3).step_by(BLOCK_FRAMES) {
                    let amplitude = if start < size { 0.25 } else { 0.5 };
                    let block = block(config.clone(), start as u64, BLOCK_FRAMES, amplitude);
                    processor.process(&block, &metrics);
                    for (offset, &sample) in block.samples.iter().enumerate() {
                        let end = start + offset + 1;
                        history.push_at(end as u64 - 1, [sample]);
                        if end >= size && (end - size).is_multiple_of(size / 4) {
                            reference.update_window(&history, (end - size) as u64..end as u64, 0);
                        }
                    }
                    // No publications are consumed; acquisition/render cadence
                    // cannot change any of the 9 scheduled EMA/hold updates.
                }
                let result = processor.publication();
                assert_eq!(result.result.power(), reference.power());
                assert_eq!(result.result.hold_power(), reference.hold_power());
                assert_eq!(result.result.average(), reference.average());
                assert_eq!(result.info.updates, 9);
                assert_eq!(result.info.contributing, 0..(size * 3) as u64);
                assert_eq!(result.info.missing_windows, 0);
                assert_eq!(result.result.window().unwrap().channel, 15);
            }
        }
    }

    #[test]
    fn gap_resets_average_and_hold_and_requires_a_complete_window() {
        for size in [1024, 524288] {
            let config = config(size, SpectrumMode::Continuous, Quantity::Psd);
            let mut p = Processor::new(config.clone());
            let metrics = Metrics::default();
            for start in (0..size * 2).step_by(BLOCK_FRAMES) {
                p.process(
                    &block(config.clone(), start as u64, BLOCK_FRAMES, 0.25),
                    &metrics,
                );
            }
            assert_eq!(p.info.updates, 5);
            let recovered = (size * 2 + 32) as u64;
            for offset in (0..size - BLOCK_FRAMES).step_by(BLOCK_FRAMES) {
                p.process(
                    &block(config.clone(), recovered + offset as u64, BLOCK_FRAMES, 0.5),
                    &metrics,
                );
            }
            if size == BLOCK_FRAMES {
                p.process(
                    &block(config.clone(), recovered, BLOCK_FRAMES - 1, 0.5),
                    &metrics,
                );
            }
            assert_eq!(p.info.input_missing, 32);
            assert_eq!(p.info.missing_windows, 4);
            assert!(!p.analyzer.is_ready());
            if size == BLOCK_FRAMES {
                p.process(
                    &block(config.clone(), recovered + size as u64 - 1, 1, 0.5),
                    &metrics,
                );
            } else {
                p.process(
                    &block(
                        config,
                        recovered + (size - BLOCK_FRAMES) as u64,
                        BLOCK_FRAMES,
                        0.5,
                    ),
                    &metrics,
                );
            }
            assert_eq!(p.info.updates, 1);
            assert_eq!(p.info.contributing, recovered..recovered + size as u64);
            assert!((p.analyzer.band(0.0, 24000.0).unwrap().power - 0.125).abs() < 1e-12);
            assert_eq!(p.analyzer.hold_power(), p.analyzer.power());
        }
    }

    #[test]
    fn latest_accepts_new_ends_below_hop_and_final_window_is_not_reaveraged() {
        let config = config(524288, SpectrumMode::Latest, Quantity::Amplitude);
        let mut p = Processor::new(config.clone());
        let metrics = Metrics::default();
        for start in (0..config.settings.size).step_by(BLOCK_FRAMES) {
            p.process(
                &block(config.clone(), start as u64, BLOCK_FRAMES, 0.5),
                &metrics,
            );
        }
        p.latest(false, &metrics);
        assert_eq!(p.info.updates, 1);
        p.process(
            &block(config, 524288, 4800.min(BLOCK_FRAMES), 0.25),
            &metrics,
        );
        p.last_latest -= LATEST_INTERVAL;
        p.latest(false, &metrics);
        assert_eq!(p.info.updates, 2);
        let power = p.analyzer.power().to_vec();
        let hold = p.analyzer.hold_power().to_vec();
        for _ in 0..4 {
            p.latest(true, &metrics);
        }
        assert_eq!(p.info.updates, 2);
        assert_eq!(p.analyzer.power(), power);
        assert_eq!(p.analyzer.hold_power(), hold);
        assert_eq!(p.info.observation_ms, 100);
    }

    #[test]
    fn small_latest_keeps_periodic_hop_gate_but_finishes_new_endpoint_once() {
        for size in [1024, 8192, 32768] {
            let config = config(size, SpectrumMode::Latest, Quantity::Amplitude);
            let mut p = Processor::new(config.clone());
            let metrics = Metrics::default();
            for start in (0..size).step_by(BLOCK_FRAMES) {
                p.process(
                    &block(config.clone(), start as u64, BLOCK_FRAMES, 0.5),
                    &metrics,
                );
            }
            p.latest(false, &metrics);
            assert_eq!(p.info.updates, 1);
            p.process(&block(config.clone(), size as u64, 1, 0.25), &metrics);
            p.last_latest -= observation_interval(size);
            p.latest(false, &metrics);
            assert_eq!(p.info.updates, 1);
            p.latest(true, &metrics);
            p.latest(true, &metrics);
            assert_eq!(p.info.updates, 2);
            assert_eq!(p.info.observation_ms, 33);
            assert_eq!(p.info.missed_observations, 0);
        }
    }

    #[test]
    fn live_observes_sub_hop_windows_with_exact_power_hold_and_gap_recovery() {
        for size in [1024, 8192, 32768, 524288] {
            for quantity in [Quantity::Amplitude, Quantity::Psd, Quantity::Esd] {
                let config = config(size, SpectrumMode::Live, quantity);
                let mut p = Processor::new(config.clone());
                let mut reference = Analyzer::new(config.settings, config.rate);
                let mut history = History::with_channels(size, 1);
                let metrics = Metrics::default();
                let mut end = 0;
                // Observe several different complete windows below the N/4
                // gate. Scheduling follows elapsed worker time, never drawing.
                for count in [size, 97, 101] {
                    for offset in (0..count).step_by(BLOCK_FRAMES) {
                        let len = (count - offset).min(BLOCK_FRAMES);
                        let b = block(
                            config.clone(),
                            end,
                            len,
                            if end < size as u64 { 0.5 } else { 0.25 },
                        );
                        p.process(&b, &metrics);
                        for (i, &sample) in b.samples[..len].iter().enumerate() {
                            history.push_at(end + i as u64, [sample]);
                        }
                        end += len as u64;
                    }
                    p.last_latest = Instant::now() - live_interval(p.budget_ms);
                    p.latest(false, &metrics);
                    reference.update_window(&history, end - size as u64..end, 0);
                    assert_eq!(p.analyzer.power(), reference.power());
                    assert_eq!(p.analyzer.hold_power(), reference.hold_power());
                    assert_eq!(p.analyzer.average(), reference.average());
                }
                assert_eq!(p.info.updates, 3);
                p.latest(true, &metrics);
                p.latest(true, &metrics);
                assert_eq!(p.info.updates, 3, "Stop must not reaverage the same window");
                p.process(&block(config.clone(), end + 12, 1, 0.125), &metrics);
                p.latest(true, &metrics);
                assert!(!p.analyzer.is_ready());
                assert_eq!(p.info.input_missing, 12);
                let start = end + 12;
                end = start + 1;
                for offset in (0..size - 1).step_by(BLOCK_FRAMES) {
                    let len = (size - 1 - offset).min(BLOCK_FRAMES);
                    p.process(&block(config.clone(), end, len, 0.125), &metrics);
                    end += len as u64;
                }
                p.latest(true, &metrics);
                assert_eq!(p.info.updates, 1);
                assert_eq!(p.info.contributing, start..end);
                assert_eq!(p.analyzer.hold_power(), p.analyzer.power());
            }
        }
    }

    #[test]
    fn live_budget_leaves_half_a_core_and_does_not_gate_on_fft_length() {
        assert_eq!(live_interval(0.2), LIVE_INTERVAL);
        assert_eq!(live_interval(20.0), Duration::from_millis(40));
        assert_eq!(live_interval(120.0), Duration::from_millis(240));
    }

    #[test]
    fn continuous_hold_captures_transient_that_latest_can_miss() {
        for mode in [SpectrumMode::Continuous, SpectrumMode::Latest] {
            let mut config = config(524288, mode, Quantity::Psd);
            config.settings.averages = 1;
            let mut p = Processor::new(config.clone());
            let metrics = Metrics::default();
            for start in (0..config.settings.size * 4).step_by(BLOCK_FRAMES) {
                let mut b = block(config.clone(), start as u64, BLOCK_FRAMES, 0.0);
                if start == config.settings.size {
                    b.samples[0] = 0.5;
                }
                p.process(&b, &metrics);
            }
            p.latest(true, &metrics);
            assert_eq!(p.analyzer.band(0.0, 24000.0).unwrap().power, 0.0);
            if mode == SpectrumMode::Continuous {
                assert_eq!(p.info.updates, 13);
                assert!((p.analyzer.hold_power()[32] - 0.5 / (48000.0 * 524288.0)).abs() < 1e-20);
            } else {
                assert_eq!(p.info.updates, 1);
                assert_eq!(p.analyzer.hold_power()[32], 0.0);
            }
            p.analyzer.clear_hold();
            assert_eq!(p.analyzer.hold_power(), p.analyzer.power());
        }
    }

    #[test]
    fn bounded_queue_loss_including_initial_and_final_tail_is_explicit() {
        // Exercise the actual producer without scheduling a consumer. This makes
        // saturation deterministic, independent of the test host's FFT speed.
        let (input, mut incoming) = RingBuffer::new(1);
        let (controls, requests) = mpsc::sync_channel(32);
        let metrics = Arc::new(Metrics::default());
        let mut feeder = Feeder {
            input,
            pending: None,
            controls,
            submitted: 0,
            active: Arc::new(AtomicU64::new(0)),
            wake: thread::current(),
            metrics: metrics.clone(),
        };
        feeder.configure(
            Source {
                generation: 7,
                rate: 48000,
                channel: 0,
                calibration: None,
            },
            config(1024, SpectrumMode::Continuous, Quantity::Amplitude).settings,
            SpectrumMode::Continuous,
            0,
        );
        for i in 0..2048 {
            feeder.submit(i, &[0.25]);
        }
        assert_eq!(metrics.input_dropped.load(Ordering::Relaxed), 1024);
        let mut p = Processor::new(feeder.pending.as_ref().unwrap().config.clone());
        p.process(&incoming.pop().unwrap(), &metrics);
        let reply = feeder.inspect(2048, true);
        let Control::Inspect {
            end, reply: sender, ..
        } = requests.recv().unwrap()
        else {
            unreachable!()
        };
        p.gap_to(end);
        sender
            .try_send(p.publication())
            .unwrap_or_else(|_| unreachable!());
        let result = reply.recv().unwrap();
        assert_eq!(result.info.input_missing, 1024);
        assert_eq!(result.info.missing_windows, 7);
        assert!(!result.result.is_ready());
        for i in 2048..3072 {
            feeder.submit(i, &[0.5]);
        }
        p.process(&incoming.pop().unwrap(), &metrics);
        assert_eq!(p.info.updates, 1);
        assert_eq!(p.info.contributing, 2048..3072);
        assert_eq!(p.analyzer.power()[0], 0.25);
    }
}
