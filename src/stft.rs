//! Continuous, sample-clocked STFT on a dedicated worker. All queues and result
//! storage are bounded; the producer never waits for analysis or result delivery.
#![warn(clippy::redundant_clone)]
use crate::{
    channel::ChannelId,
    signal::{History, MAX_CHANNELS},
    spectrum::{Analyzer, Precision, STFT_SIZES, Settings, Window},
};
use rtrb::{Consumer, Producer, RingBuffer};
use std::{
    sync::{
        Arc, OnceLock,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

pub const BLOCK_FRAMES: usize = 256;
// Capture may already be full when measurement starts (or resumes after a
// scheduling delay). Accept that bounded burst even before FFT planning runs,
// plus a partially flushed block from the preceding poll. No producer waits.
pub const INPUT_BLOCKS: usize = crate::audio::MAX_CAPTURE_FRAMES.div_ceil(BLOCK_FRAMES) + 1;
/// About 0.68 s at 48 kHz / hop 256 (16 MiB of f64 values at maximum N).
pub const RESULT_ROWS: usize = 128;
const MAX_BINS: usize = 32768 / 2 + 1;
/// Small/high-cadence FFTs need more scheduling headroom without reserving
/// another full-size buffer per row. This tier adds only about 8 MiB.
pub const SMALL_RESULT_ROWS: usize = 512;
const SMALL_BINS: usize = 4096 / 2 + 1;

/// Spectrogram cadence only. Spectrum Continuous keeps its independent N/4 hop.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Overlap {
    Half,
    #[default]
    ThreeQuarters,
    SevenEighths,
}

impl Overlap {
    pub const ALL: [Self; 3] = [Self::Half, Self::ThreeQuarters, Self::SevenEighths];

    pub fn name(self) -> &'static str {
        match self {
            Self::Half => "50%",
            Self::ThreeQuarters => "75%",
            Self::SevenEighths => "87.5%",
        }
    }

    pub fn hop(self, size: usize) -> usize {
        size / match self {
            Self::Half => 2,
            Self::ThreeQuarters => 4,
            Self::SevenEighths => 8,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Config {
    pub sample_rate: u32,
    pub channels: usize,
    /// Zero-based source channel, independent of the number of displayed traces.
    pub channel: ChannelId,
    pub size: usize,
    pub hop: usize,
    pub window: Window,
    pub remove_dc: bool,
    pub precision: Precision,
}

impl Config {
    pub fn validate(self) -> Result<(), &'static str> {
        if self.sample_rate == 0
            || !(1..=MAX_CHANNELS).contains(&self.channels)
            || self.channel >= self.channels
            || !STFT_SIZES.contains(&self.size)
            || self.hop == 0
            || self.hop > self.size
        {
            return Err("Invalid STFT sample rate, channels, FFT size or hop");
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Gap {
    /// Source frames missing between consecutive input blocks, including losses
    /// in capture and in this worker's input queue. Time stays in sample indices.
    pub input_frames: u64,
    /// Complete windows lost because the result consumer did not recycle storage.
    pub result_rows: u64,
    /// First window of a generation, or first window after an input discontinuity.
    pub discontinuity: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RowInfo {
    pub generation: u64,
    pub config: Config,
    pub start: u64,
    /// Exclusive end of the analyzed window; time is end / sample_rate.
    pub end: u64,
    pub gap: Gap,
}

pub struct Row {
    pub info: RowInfo,
    power: Box<[f64]>,
}

impl Row {
    /// Squared peak-bin amplitude in uncalibrated FS², never reconstructed from dB.
    pub fn power(&self) -> &[f64] {
        &self.power[..self.info.config.size / 2 + 1]
    }

    /// Compatibility adapter for display-only consumers. Silence stays −∞,
    /// invalid windows stay NaN, and no measurement floor is imposed.
    pub fn db(&self) -> Vec<f32> {
        self.power()
            .iter()
            .map(|&p| crate::spectrum::level_db(p) as f32)
            .collect()
    }
}

#[derive(Default)]
pub struct Metrics {
    pub input_dropped: AtomicU64,
    /// Peak queued blocks; each contains at most BLOCK_FRAMES source frames.
    pub input_high_water: AtomicU64,
    pub planning_max_nanos: AtomicU64,
    pub result_dropped: AtomicU64,
    pub produced: AtomicU64,
    /// Accepted samples processed by the worker, across analysis generations.
    /// Finite-input QA can await consumption without polling result delivery.
    pub processed_frames: AtomicU64,
    pub processing_nanos: AtomicU64,
}

#[derive(Clone)]
struct InputBlock {
    generation: u64,
    config: Config,
    start: u64,
    len: usize,
    /// Frames lost in this queue before this block (also when the first block
    /// of a new generation could not be enqueued).
    dropped_before: u64,
    // All source channels remain in common history. Each analysis queue carries
    // only its selected channel, with its original source identity attached.
    samples: [f64; BLOCK_FRAMES],
}

impl InputBlock {
    fn empty(generation: u64, config: Config) -> Self {
        Self {
            generation,
            config,
            start: 0,
            len: 0,
            dropped_before: 0,
            samples: [0.0; BLOCK_FRAMES],
        }
    }
}

struct Processor {
    generation: u64,
    config: Config,
    history: History,
    analyzer: Analyzer,
    invalid_power: Box<[f64]>,
    expected: Option<u64>,
    next_end: u64,
    gap: Gap,
}

impl Processor {
    fn new(generation: u64, config: Config) -> Self {
        Self {
            generation,
            config,
            history: History::with_channels(config.size, 1),
            analyzer: Analyzer::new(
                Settings {
                    quantity: crate::spectrum::Quantity::Amplitude,
                    size: config.size,
                    window: config.window,
                    averages: 1,
                    remove_dc: config.remove_dc,
                    precision: config.precision,
                },
                config.sample_rate,
            ),
            invalid_power: vec![f64::NAN; config.size / 2 + 1].into_boxed_slice(),
            expected: None,
            next_end: 0,
            gap: Gap {
                discontinuity: true,
                ..Gap::default()
            },
        }
    }

    fn process(&mut self, block: &InputBlock, mut emit: impl FnMut(RowInfo, &[f64]) -> bool) {
        if block.len == 0 {
            return;
        }
        if self.expected != Some(block.start) {
            self.gap.input_frames += self.expected.map_or(block.dropped_before, |expected| {
                block
                    .start
                    .saturating_sub(expected)
                    .max(block.dropped_before)
            });
            self.gap.discontinuity = true;
            self.history.clear();
            self.analyzer.reset();
            self.next_end = block.start + self.config.size as u64;
        }
        for (offset, &sample) in block.samples[..block.len].iter().enumerate() {
            let sequence = block.start + offset as u64;
            self.history.push_at(sequence, [sample]);
            let end = sequence + 1;
            if end != self.next_end {
                continue;
            }
            let start = end - self.config.size as u64;
            self.analyzer.update_window(&self.history, start..end, 0);
            let info = RowInfo {
                generation: self.generation,
                config: self.config,
                start,
                end,
                gap: self.gap,
            };
            // The shared Analyzer owns normalization and invalidity. Its f64
            // power values are the numerical result; dB belongs to display.
            let power = if self.analyzer.validity() == crate::spectrum::Validity::Valid {
                self.analyzer.power()
            } else {
                &self.invalid_power
            };
            if emit(info, power) {
                self.gap = Gap::default();
            } else {
                self.gap.result_rows += 1;
            }
            self.next_end += self.config.hop as u64;
        }
        self.expected = Some(block.start + block.len as u64);
    }
}

/// Input endpoint can be moved to the measurement worker while its owner retains
/// result delivery and recycling elsewhere. Neither endpoint waits for the other.
pub struct Feeder {
    input: Producer<InputBlock>,
    pending: Option<InputBlock>,
    generation: Arc<AtomicU64>,
    wake: thread::Thread,
    metrics: Arc<Metrics>,
}

pub struct Worker {
    feeder: Option<Feeder>,
    results: Option<Results>,
    generation: Arc<AtomicU64>,
    shutdown: Arc<AtomicBool>,
    handle: Option<JoinHandle<()>>,
    pub metrics: Arc<Metrics>,
}

impl Worker {
    pub fn new() -> Self {
        Self::with_pools(INPUT_BLOCKS, RESULT_ROWS, SMALL_RESULT_ROWS)
    }

    #[cfg(test)]
    fn with_capacity(input_blocks: usize, result_rows: usize) -> Self {
        Self::with_pools(input_blocks, result_rows, 0)
    }

    fn with_pools(input_blocks: usize, full_rows: usize, small_rows: usize) -> Self {
        let result_rows = full_rows + small_rows;
        let (input, mut incoming) = RingBuffer::<InputBlock>::new(input_blocks);
        let (mut outgoing, results) = RingBuffer::new(result_rows);
        let (mut recycle, mut free) = RingBuffer::new(result_rows);
        let placeholder = Config {
            sample_rate: 48000,
            channels: 1,
            channel: 0,
            size: 1024,
            hop: 256,
            window: Window::Hann,
            remove_dc: true,
            precision: Precision::F64,
        };
        for index in 0..result_rows {
            recycle
                .push(Row {
                    info: RowInfo {
                        generation: 0,
                        config: placeholder,
                        start: 0,
                        end: 0,
                        gap: Gap::default(),
                    },
                    power: vec![
                        0.0;
                        if index < full_rows {
                            MAX_BINS
                        } else {
                            SMALL_BINS
                        }
                    ]
                    .into_boxed_slice(),
                })
                .unwrap_or_else(|_| unreachable!("result pool capacity"));
        }
        let generation = Arc::new(AtomicU64::new(0));
        let shutdown = Arc::new(AtomicBool::new(false));
        let result_wake = Arc::new(OnceLock::<thread::Thread>::new());
        let notify = result_wake.clone();
        let metrics = Arc::new(Metrics::default());
        let active = generation.clone();
        let stop = shutdown.clone();
        let counters = metrics.clone();
        let handle = thread::spawn(move || {
            let mut processor: Option<Processor> = None;
            // Park the small tier while a large FFT is active. The vector is
            // reserved once; rows always return through the same recycle ring.
            let mut parked = Vec::with_capacity(small_rows);
            while !stop.load(Ordering::Acquire) {
                let Ok(block) = incoming.pop() else {
                    // unpark retains a token even if it precedes park, so an
                    // idle or paused worker needs neither polling nor a timer.
                    thread::park();
                    continue;
                };
                if block.generation != active.load(Ordering::Acquire) {
                    continue;
                }
                if processor
                    .as_ref()
                    .is_none_or(|p| p.generation != block.generation)
                {
                    let started = Instant::now();
                    processor = Some(Processor::new(block.generation, block.config));
                    counters
                        .planning_max_nanos
                        .fetch_max(started.elapsed().as_nanos() as u64, Ordering::Relaxed);
                }
                let started = Instant::now();
                processor.as_mut().unwrap().process(&block, |info, power| {
                    if info.generation != active.load(Ordering::Acquire) {
                        return true; // obsolete data cannot become a visible result
                    }
                    let Some(mut row) = take_row(&mut free, &mut parked, power.len()) else {
                        counters.result_dropped.fetch_add(1, Ordering::Relaxed);
                        return false;
                    };
                    row.info = info;
                    row.power[..power.len()].copy_from_slice(power);
                    // Pool size equals queue capacity: owning a free row guarantees a slot.
                    outgoing
                        .push(row)
                        .unwrap_or_else(|_| unreachable!("result pool invariant"));
                    counters.produced.fetch_add(1, Ordering::Relaxed);
                    if let Some(wake) = notify.get() {
                        wake.unpark();
                    }
                    true
                });
                counters
                    .processed_frames
                    .fetch_add(block.len as u64, Ordering::Release);
                counters
                    .processing_nanos
                    .fetch_add(started.elapsed().as_nanos() as u64, Ordering::Relaxed);
            }
        });
        Self {
            feeder: Some(Feeder {
                input,
                pending: None,
                generation: generation.clone(),
                wake: handle.thread().clone(),
                metrics: metrics.clone(),
            }),
            results: Some(Results {
                results,
                recycle,
                generation: generation.clone(),
                wake: result_wake,
            }),
            generation,
            shutdown,
            handle: Some(handle),
            metrics,
        }
    }

    /// Configuration takes effect by publishing an epoch, without waiting for
    /// old input or a command queue. Planning happens on the worker's first block.
    pub fn configure(&mut self, config: Config) -> Result<u64, &'static str> {
        config.validate()?;
        let generation = self.generation.fetch_add(1, Ordering::AcqRel) + 1;
        if let Some(feeder) = &mut self.feeder {
            feeder.configure(generation, config);
        }
        Ok(generation)
    }

    /// Move only the input endpoint; configuration epochs are still published by
    /// this result owner and carried with measurement commands.
    pub fn take_feeder(&mut self) -> Feeder {
        self.feeder.take().expect("STFT feeder already transferred")
    }

    /// Invalidate even results already queued or currently being computed.
    pub fn pause(&mut self) {
        self.generation.fetch_add(1, Ordering::AcqRel);
        if let Some(feeder) = &mut self.feeder {
            feeder.pending = None;
        }
    }

    pub fn submit(&mut self, sequence: u64, samples: &[f64]) {
        self.feeder
            .as_mut()
            .expect("detached feeder")
            .submit(sequence, samples);
    }

    pub fn flush(&mut self) {
        self.feeder.as_mut().expect("detached feeder").flush();
    }

    /// Transfer result collection independently of the input endpoint and FFT.
    pub fn take_results(&mut self) -> Results {
        self.results
            .take()
            .expect("STFT results already transferred")
    }

    pub fn drain(&mut self, consume: impl FnMut(&Row)) {
        self.results
            .as_mut()
            .expect("detached STFT results")
            .drain(consume);
    }
}

fn take_row(free: &mut Consumer<Row>, parked: &mut Vec<Row>, bins: usize) -> Option<Row> {
    if bins <= SMALL_BINS
        && let Some(row) = parked.pop()
    {
        return Some(row);
    }
    while let Ok(row) = free.pop() {
        if row.power.len() >= bins {
            return Some(row);
        }
        parked.push(row);
    }
    None
}

/// Sole owner of result delivery/recycling. Moving this endpoint to a history
/// collector does not change the nonblocking acquisition or FFT queues.
pub struct Results {
    results: Consumer<Row>,
    recycle: Producer<Row>,
    generation: Arc<AtomicU64>,
    wake: Arc<OnceLock<thread::Thread>>,
}

impl Results {
    /// Register the sole result consumer for event-driven collection. Results
    /// already queued before registration are drained by its first iteration.
    pub fn wake_on_result(&self, consumer: thread::Thread) {
        self.wake
            .set(consumer)
            .expect("result consumer already registered");
    }

    pub fn generation(&self) -> u64 {
        self.generation.load(Ordering::Acquire)
    }

    pub fn drain(&mut self, mut consume: impl FnMut(&Row)) {
        let generation = self.generation();
        for _ in 0..self.results.slots() {
            let row = self.results.pop().unwrap();
            if row.info.generation == generation {
                consume(&row);
            }
            self.recycle
                .push(row)
                .unwrap_or_else(|_| unreachable!("result pool invariant"));
        }
    }
}

impl Feeder {
    pub fn configure(&mut self, generation: u64, config: Config) {
        config.validate().expect("validated STFT configuration");
        self.pending = Some(InputBlock::empty(generation, config));
    }

    pub fn submit(&mut self, sequence: u64, samples: &[f64]) {
        let Some(block) = &self.pending else { return };
        if block.generation != self.generation.load(Ordering::Acquire) {
            return;
        }
        if samples.len() < block.config.channels {
            self.flush();
            self.pending.as_mut().unwrap().dropped_before += 1;
            self.metrics.input_dropped.fetch_add(1, Ordering::Relaxed);
            return;
        }
        if block.len > 0 && sequence != block.start + block.len as u64 {
            self.flush();
        }
        let block = self.pending.as_mut().unwrap();
        if block.len == 0 {
            block.start = sequence;
        }
        block.samples[block.len] = samples[block.config.channel];
        block.len += 1;
        if block.len == BLOCK_FRAMES {
            self.flush();
        }
    }

    pub fn flush(&mut self) {
        let Some(block) = &mut self.pending else {
            return;
        };
        if block.len == 0 {
            return;
        }
        if block.generation == self.generation.load(Ordering::Acquire) {
            enqueue(&mut self.input, block, &self.metrics);
            self.wake.unpark();
        } else {
            block.len = 0;
        }
    }
}

fn enqueue(input: &mut Producer<InputBlock>, block: &mut InputBlock, metrics: &Metrics) {
    if input.push(block.clone()).is_err() {
        metrics
            .input_dropped
            .fetch_add(block.len as u64, Ordering::Relaxed);
        block.dropped_before += block.len as u64;
    } else {
        block.dropped_before = 0;
        metrics.input_high_water.fetch_max(
            (input.buffer().capacity() - input.slots()) as u64,
            Ordering::Relaxed,
        );
    }
    block.len = 0;
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

/// Explicit local hardware check: validates window order on a chosen input CH.
/// Silence is valid input; spectral accuracy is checked with synthetic signals.
pub fn smoke_test(
    device_name: Option<&str>,
    channel: usize,
    sample_rate: Option<u32>,
) -> Result<(), String> {
    let device = crate::audio::input_device(device_name)?;
    let (_stream, mut capture) = crate::audio::start_device(&device, sample_rate)?;
    let config = Config {
        sample_rate: capture.sample_rate,
        channels: capture.channels as usize,
        channel,
        size: 8192,
        hop: Overlap::default().hop(8192),
        window: Window::Hann,
        remove_dc: true,
        precision: crate::spectrum::Precision::F64,
    };
    let mut worker = Worker::new();
    let generation = worker.configure(config)?;
    let deadline = Instant::now() + Duration::from_secs(2);
    let mut frames = 0;
    let mut rows = 0;
    let mut last_end = None;
    let mut last_sample = None;
    let mut order_error = false;
    let mut consume = |row: &Row| {
        if row.info.generation != generation
            || row.info.config != config
            || row.info.end - row.info.start != config.size as u64
            || last_end.is_some_and(|end| {
                row.info.end <= end
                    || (row.info.gap == Gap::default() && row.info.end - end != config.hop as u64)
            })
        {
            order_error = true;
        }
        last_end = Some(row.info.end);
        rows += 1;
    };
    while Instant::now() < deadline {
        let available = capture.consumer.slots();
        if let Ok(chunk) = capture.consumer.read_chunk(available) {
            for frame in chunk {
                frames += 1;
                last_sample = Some(frame.sequence + 1);
                worker.submit(frame.sequence, &frame.samples[..config.channels]);
            }
        }
        worker.flush();
        worker.drain(&mut consume);
        thread::sleep(Duration::from_millis(5));
    }
    // Bounded settlement of already submitted input; acquisition still never waits.
    let settle = Instant::now() + Duration::from_millis(100);
    while Instant::now() < settle {
        worker.drain(&mut consume);
        thread::sleep(Duration::from_millis(2));
    }
    if capture.metrics.failed.load(Ordering::Relaxed) || frames == 0 || rows == 0 || order_error {
        return Err("STFT hardware check failed: stream, frames, results or window order".into());
    }
    let input_dropped = capture.metrics.dropped.load(Ordering::Relaxed);
    let worker_dropped = worker.metrics.input_dropped.load(Ordering::Relaxed);
    let result_dropped = worker.metrics.result_dropped.load(Ordering::Relaxed);
    if input_dropped == 0 && worker_dropped == 0 && result_dropped == 0 {
        let expected = (frames - config.size as u64) / config.hop as u64 + 1;
        if rows != expected || last_sample.unwrap() - last_end.unwrap() >= config.hop as u64 {
            return Err(format!(
                "STFT lost windows: expected {expected}, received {rows}"
            ));
        }
    }
    println!(
        "STFT OK: {device} / {} Hz / {} ch / CH {} / {frames} frames / {rows} ordered rows / N {} hop {} / capture dropped {input_dropped} / worker dropped {worker_dropped} / result dropped {result_dropped} / worker CPU {:.3} ms/row",
        config.sample_rate,
        config.channels,
        config.channel + 1,
        config.size,
        config.hop,
        worker.metrics.processing_nanos.load(Ordering::Relaxed) as f64 / rows as f64 / 1e6
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f64::consts::TAU;

    #[test]
    fn overlap_preserves_complete_windows_f64_levels_and_long_sample_times() {
        let origin = (1_u64 << 54) + 137;
        for size in STFT_SIZES {
            for overlap in Overlap::ALL {
                for precision in [Precision::F64, Precision::F32] {
                    for window in [Window::Rectangular, Window::Hann, Window::BlackmanHarris] {
                        for remove_dc in [false, true] {
                            let cfg = Config {
                                size,
                                hop: overlap.hop(size),
                                precision,
                                window,
                                remove_dc,
                                ..config()
                            };
                            cfg.validate().unwrap();
                            let mut processor = Processor::new(71, cfg);
                            let mut rows = 0;
                            for offset in (0..size + 2 * cfg.hop).step_by(BLOCK_FRAMES) {
                                let mut input = InputBlock::empty(71, cfg);
                                input.start = origin + offset as u64;
                                input.len = BLOCK_FRAMES;
                                for (i, value) in input.samples.iter_mut().enumerate() {
                                    let n = offset + i;
                                    *value = 0.125
                                        + 0.5
                                            * (TAU * 32.0 * (n % size) as f64 / size as f64).cos()
                                        + if n.is_multiple_of(2) { 0.0625 } else { -0.0625 };
                                }
                                processor.process(&input, |info, power| {
                                    assert_eq!(info.generation, 71);
                                    assert_eq!(info.start, origin + (rows * cfg.hop) as u64);
                                    assert_eq!(info.end, info.start + size as u64);
                                    assert_eq!(info.config, cfg);
                                    let tolerance = if precision == Precision::F64 {
                                        2e-13
                                    } else {
                                        2e-7
                                    };
                                    for (bin, amplitude) in [
                                        (0, if remove_dc { 0.0 } else { 0.125 }),
                                        (32, 0.5),
                                        (size / 2, 0.0625),
                                    ] {
                                        assert!(
                                            (power[bin].sqrt() - amplitude).abs() < tolerance,
                                            "{cfg:?}, bin {bin}"
                                        );
                                    }
                                    let result =
                                        crate::spectrum::Result::from_stft(info, power).unwrap();
                                    assert_eq!(result.power(), power);
                                    let reading = result
                                        .cursor(32.0 * cfg.sample_rate as f64 / size as f64)
                                        .unwrap();
                                    assert_eq!(reading.window.start, info.start);
                                    assert_eq!(reading.window.end, info.end);
                                    assert_eq!(reading.window.channel, 15);
                                    assert_eq!(reading.window.settings.averages, 1);
                                    assert!(reading.window.calibration.is_none());
                                    assert!((reading.value - 0.5).abs() < tolerance);
                                    rows += 1;
                                    true
                                });
                            }
                            assert_eq!(rows, 3);
                            // An acquisition gap requires another complete N,
                            // independently of overlap; no partial/zero-filled FFT.
                            let start = origin + (size * 3) as u64;
                            let mut recovered = 0;
                            for offset in (0..size).step_by(BLOCK_FRAMES) {
                                let mut input = block(start + offset as u64, BLOCK_FRAMES, cfg);
                                input.samples.fill(0.0);
                                processor.process(&input, |info, power| {
                                    assert_eq!(info.start, start);
                                    assert_eq!(info.end, start + size as u64);
                                    assert!(info.gap.discontinuity);
                                    assert!(info.gap.input_frames > 0);
                                    assert!(power.iter().all(|&p| p == 0.0));
                                    recovered += 1;
                                    true
                                });
                            }
                            assert_eq!(recovered, 1);
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn retained_spectrum_adapter_keeps_weak_bins_silence_and_invalidity() {
        let cfg = config();
        let info = RowInfo {
            generation: 9,
            config: cfg,
            start: 1 << 54,
            end: (1 << 54) + cfg.size as u64,
            gap: Gap::default(),
        };
        let mut power = vec![0.0; cfg.size / 2 + 1];
        power[32] = 1e-300 + f64::MIN_POSITIVE;
        let result = crate::spectrum::Result::from_stft(info, &power).unwrap();
        assert_eq!(result.power()[32].to_bits(), power[32].to_bits());
        let reading = result.cursor(1500.0).unwrap();
        assert_eq!(reading.value, power[32].sqrt());
        assert_eq!(reading.level_db, 10.0 * power[32].log10());
        assert_eq!(result.cursor(0.0).unwrap().level_db, f64::NEG_INFINITY);
        assert_eq!(result.db()[32], crate::spectrum::DB_MIN);
        power[32] = f64::NAN;
        let invalid = crate::spectrum::Result::from_stft(info, &power).unwrap();
        assert_eq!(invalid.validity(), crate::spectrum::Validity::NonFinite);
        assert!(invalid.cursor(1500.0).is_none());
        assert!(crate::spectrum::Result::from_stft(info, &power[..512]).is_none());
        assert!(
            crate::spectrum::Result::from_stft(
                RowInfo {
                    start: info.start + 1,
                    ..info
                },
                &power
            )
            .is_none()
        );
    }

    #[test]
    fn display_cache_distinguishes_silence_nonfinite_and_sub_floor_signal() {
        for precision in [Precision::F64, Precision::F32] {
            for value in [0.0, f64::NAN, f64::INFINITY, 1e-12] {
                let cfg = Config {
                    precision,
                    ..config()
                };
                let mut processor = Processor::new(1, cfg);
                let mut rows = 0;
                for start in (0..1024).step_by(BLOCK_FRAMES) {
                    let mut input = block(start, BLOCK_FRAMES, cfg);
                    for sample in &mut input.samples {
                        *sample *= value;
                    }
                    processor.process(&input, |_, power| {
                        let db: Vec<f32> = power
                            .iter()
                            .map(|&p| crate::spectrum::level_db(p) as f32)
                            .collect();
                        if value == 0.0 {
                            assert!(db.iter().all(|v| *v == f32::NEG_INFINITY));
                        } else if !value.is_finite() {
                            assert!(db.iter().all(|v| v.is_nan()));
                        } else {
                            assert!((db[32] + 246.0206).abs() < 0.01);
                        }
                        rows += 1;
                        true
                    });
                }
                assert_eq!(rows, 1);
            }
        }
    }

    fn config() -> Config {
        Config {
            sample_rate: 48000,
            channels: 16,
            channel: 15,
            size: 1024,
            hop: 256,
            window: Window::Hann,
            remove_dc: true,
            precision: crate::spectrum::Precision::F64,
        }
    }

    fn block(start: u64, len: usize, config: Config) -> InputBlock {
        let mut block = InputBlock::empty(1, config);
        block.start = start;
        block.len = len;
        for (i, sample) in block.samples[..len].iter_mut().enumerate() {
            *sample = 0.5 * (TAU * 32.0 * (start + i as u64) as f64 / config.size as f64).cos();
        }
        block
    }

    #[test]
    fn both_fft_precisions_preserve_f64_input_and_window_metadata() {
        for precision in [Precision::F64, Precision::F32] {
            let cfg = Config {
                precision,
                ..config()
            };
            let mut processor = Processor::new(7, cfg);
            let mut rows = 0;
            for start in (0..2048).step_by(BLOCK_FRAMES) {
                let mut input = block(start, BLOCK_FRAMES, cfg);
                for sample in &mut input.samples {
                    *sample = 1.0 + *sample * 2e-8;
                }
                processor.process(&input, |info, power| {
                    let db: Vec<f32> = power
                        .iter()
                        .map(|&p| crate::spectrum::level_db(p) as f32)
                        .collect();
                    assert_eq!(info.generation, 7);
                    assert_eq!(info.config.precision, precision);
                    assert_eq!(info.start, rows * cfg.hop as u64);
                    assert!((db[32] + 160.0).abs() < 0.001);
                    rows += 1;
                    true
                });
            }
            assert_eq!(rows, 5);
        }
    }

    fn process_chunks(chunks: &[usize], config: Config) -> Vec<(RowInfo, Vec<f32>)> {
        let mut processor = Processor::new(1, config);
        let mut start = 7000; // absolute coordinates must survive history wrapping
        let mut rows = Vec::new();
        for &len in chunks {
            processor.process(&block(start, len, config), |info, power| {
                rows.push((
                    info,
                    power
                        .iter()
                        .map(|&p| crate::spectrum::level_db(p) as f32)
                        .collect(),
                ));
                true
            });
            start += len as u64;
        }
        rows
    }

    #[test]
    fn chunk_boundaries_wrapping_and_hops_preserve_every_window() {
        for hop in [1, 173, 256, 1024] {
            let config = Config { hop, ..config() };
            let whole = process_chunks(&[256; 12], config);
            let split = process_chunks(
                &[113; 27].into_iter().chain([21]).collect::<Vec<_>>(),
                config,
            );
            assert_eq!(whole, split);
            assert_eq!(whole.len(), (3072 - config.size) / hop + 1);
            for (i, (info, db)) in whole.iter().enumerate() {
                assert_eq!(info.start, 7000 + (i * hop) as u64);
                assert_eq!(info.end, info.start + 1024);
                assert_eq!(info.config.channel, 15);
                assert!((db[32] + 6.0206).abs() < 0.003);
                assert_eq!(info.gap.discontinuity, i == 0);
            }
        }
    }

    #[test]
    fn windows_use_the_shared_dc_nyquist_and_window_normalization() {
        for window in [Window::Rectangular, Window::Hann, Window::BlackmanHarris] {
            let rows = process_chunks(&[256; 4], Config { window, ..config() });
            assert!((rows[0].1[32] + 6.0206).abs() < 0.003);
        }
        let cfg = Config {
            window: Window::Rectangular,
            remove_dc: false,
            ..config()
        };
        let mut processor = Processor::new(1, cfg);
        for start in (0..1024).step_by(256) {
            let mut b = block(start, 256, cfg);
            for (i, sample) in b.samples.iter_mut().enumerate() {
                *sample = 0.5 + if i % 2 == 0 { 0.25 } else { -0.25 };
            }
            processor.process(&b, |_, power| {
                let db: Vec<f32> = power
                    .iter()
                    .map(|&p| crate::spectrum::level_db(p) as f32)
                    .collect();
                assert!((db[0] + 6.0206).abs() < 0.002);
                assert!((db[512] + 12.0412).abs() < 0.002);
                true
            });
        }
    }

    #[test]
    fn input_gaps_discard_partial_windows_and_keep_source_time() {
        let cfg = config();
        let mut processor = Processor::new(1, cfg);
        let mut rows = Vec::new();
        for start in [0, 256, 512, 768, 1024, 2000, 2256, 2512, 2768, 3024] {
            processor.process(&block(start, 256, cfg), |info, _| {
                rows.push(info);
                true
            });
        }
        assert_eq!(
            rows.iter().map(|r| r.start).collect::<Vec<_>>(),
            [0, 256, 2000, 2256]
        );
        assert_eq!(rows[2].gap.input_frames, 720);
        assert!(rows[2].gap.discontinuity);
        assert_eq!(rows[3].gap, Gap::default());
    }

    #[test]
    fn capture_catch_up_has_three_hundred_ms_of_high_rate_headroom() {
        let cfg = config();
        let (mut input, mut incoming) = RingBuffer::new(INPUT_BLOCKS);
        let metrics = Metrics::default();
        // Pause the consumer while acquisition delivers a catch-up burst.
        // At the supported ceiling the old queue covered only ~21 ms.
        let frames = 768000 * 3 / 10;
        for start in (0..frames).step_by(BLOCK_FRAMES) {
            enqueue(
                &mut input,
                &mut block(start as u64, BLOCK_FRAMES, cfg),
                &metrics,
            );
        }
        assert_eq!(metrics.input_dropped.load(Ordering::Relaxed), 0);
        assert!(std::mem::size_of::<InputBlock>() * INPUT_BLOCKS <= 3 * 1024 * 1024);
        for start in (0..frames).step_by(BLOCK_FRAMES) {
            let next = incoming.pop().unwrap();
            assert_eq!(next.start, start as u64);
            assert_eq!(next.dropped_before, 0);
        }
        assert!(incoming.is_empty());
    }

    #[test]
    fn queue_saturation_is_nonblocking_and_reports_losses_even_before_first_block() {
        let cfg = config();
        let (mut input, mut incoming) = RingBuffer::new(1);
        let metrics = Metrics::default();
        let mut pending = block(0, 256, cfg);
        enqueue(&mut input, &mut pending, &metrics);
        for start in [256, 512] {
            pending.start = start;
            pending.len = 256;
            enqueue(&mut input, &mut pending, &metrics);
        }
        assert_eq!(metrics.input_dropped.load(Ordering::Relaxed), 512);
        incoming.pop().unwrap();
        pending.start = 768;
        pending.len = 256;
        enqueue(&mut input, &mut pending, &metrics);
        let first = incoming.pop().unwrap();
        assert_eq!(first.dropped_before, 512);
        let mut processor = Processor::new(1, cfg);
        let mut gap = Gap::default();
        processor.process(&first, |_, _| unreachable!());
        for start in [1024, 1280, 1536] {
            processor.process(&block(start, 256, cfg), |info, _| {
                gap = info.gap;
                true
            });
        }
        assert_eq!(gap.input_frames, 512);
        assert!(gap.discontinuity);
    }

    fn wait_until(mut condition: impl FnMut() -> bool) {
        let deadline = Instant::now() + Duration::from_secs(5);
        while !condition() {
            assert!(Instant::now() < deadline, "worker timed out");
            thread::sleep(Duration::from_millis(1));
        }
    }

    #[test]
    fn capture_backlog_survives_delayed_stft_start_without_losing_windows() {
        // Audio starts before the GUI hands Capture to the measurement worker.
        // Its first drain can therefore contain an entire capture queue. Keep
        // the FFT consumer unscheduled until that finite burst has been sent.
        for rate in [192_000, 768_000] {
            let cfg = Config {
                sample_rate: rate,
                size: 32768,
                hop: 4096,
                ..config()
            };
            let frames = crate::audio::capture_capacity(rate);
            let (input, mut incoming) = RingBuffer::new(INPUT_BLOCKS);
            let metrics = Arc::new(Metrics::default());
            let mut feeder = Feeder {
                input,
                pending: None,
                generation: Arc::new(AtomicU64::new(1)),
                wake: thread::current(),
                metrics: metrics.clone(),
            };
            feeder.configure(1, cfg);
            let mut first = [0.0; 16];
            first[15] = 0.5;
            feeder.submit(0, &first);
            feeder.flush();
            for n in 1..=frames {
                let mut samples = [0.0; 16];
                samples[15] = 0.5 * (TAU * 32.0 * (n % cfg.size) as f64 / cfg.size as f64).cos();
                feeder.submit(n as u64, &samples);
            }
            feeder.flush();
            assert_eq!(
                metrics.input_dropped.load(Ordering::Relaxed),
                0,
                "{rate} Hz backlog"
            );
            let mut processor = Processor::new(1, cfg);
            let mut rows = 0;
            while let Ok(block) = incoming.pop() {
                processor.process(&block, |info, power| {
                    assert_eq!(info.start, rows * cfg.hop as u64);
                    assert_eq!(info.end, info.start + cfg.size as u64);
                    assert_eq!(info.gap.input_frames, 0);
                    assert_eq!(info.gap.result_rows, 0);
                    assert_eq!(info.gap.discontinuity, rows == 0);
                    assert!((power[32].sqrt() - 0.5).abs() < 2e-13);
                    rows += 1;
                    true
                });
            }
            assert_eq!(rows as usize, 1 + (frames + 1 - cfg.size) / cfg.hop);
        }
    }

    fn submit(worker: &mut Worker, start: u64, count: usize) {
        for i in 0..count {
            let mut samples = [0.0; 16];
            samples[15] = 0.5 * (TAU * 32.0 * (start + i as u64) as f64 / 1024.0).cos();
            worker.submit(start + i as u64, &samples);
        }
        worker.flush();
    }

    #[test]
    fn high_rate_small_fft_retains_one_hundred_ms_without_result_recycling() {
        let cfg = Config {
            sample_rate: 768000,
            hop: 128,
            ..config()
        };
        let mut worker = Worker::new();
        worker.configure(cfg).unwrap();
        let rows = 600;
        let frames = cfg.size + (rows - 1) * cfg.hop;
        submit(&mut worker, 0, frames);
        wait_until(|| {
            worker.metrics.produced.load(Ordering::Relaxed)
                + worker.metrics.result_dropped.load(Ordering::Relaxed)
                == rows as u64
        });
        assert_eq!(worker.metrics.result_dropped.load(Ordering::Relaxed), 0);
        assert_eq!(worker.metrics.input_dropped.load(Ordering::Relaxed), 0);
        let mut received = 0;
        worker.drain(|row| {
            assert_eq!(row.info.start, (received * cfg.hop) as u64);
            assert_eq!(row.info.gap.result_rows, 0);
            assert!((row.power()[32] - 0.25).abs() < 1e-10);
            received += 1;
        });
        assert_eq!(received, rows);
    }

    #[test]
    fn small_result_tier_survives_large_fft_saturation_and_reconfiguration() {
        let mut worker = Worker::with_pools(256, 1, 2);
        let small = config();
        worker.configure(small).unwrap();
        submit(&mut worker, 0, small.size + 2 * small.hop);
        wait_until(|| worker.metrics.produced.load(Ordering::Relaxed) == 3);
        worker.drain(|_| {});
        let large = Config {
            size: 8192,
            hop: 8192,
            ..small
        };
        let generation = worker.configure(large).unwrap();
        submit(&mut worker, 0, 16384);
        wait_until(|| {
            worker.metrics.produced.load(Ordering::Relaxed)
                + worker.metrics.result_dropped.load(Ordering::Relaxed)
                == 5
        });
        assert_eq!(worker.metrics.result_dropped.load(Ordering::Relaxed), 1);
        let mut received = 0;
        worker.drain(|row| {
            assert_eq!(row.info.generation, generation);
            assert_eq!(row.power().len(), 4097);
            assert!((row.power()[256] - 0.25).abs() < 1e-10);
            received += 1;
        });
        assert_eq!(received, 1);
        let generation = worker.configure(small).unwrap();
        submit(&mut worker, 0, small.size + 2 * small.hop);
        wait_until(|| worker.metrics.produced.load(Ordering::Relaxed) == 7);
        let mut received = 0;
        worker.drain(|row| {
            assert_eq!(row.info.generation, generation);
            assert_eq!(row.power().len(), 513);
            assert_eq!(row.info.gap.result_rows, 0);
            received += 1;
        });
        assert_eq!(received, 3);
    }

    #[test]
    fn result_pool_saturation_recycles_storage_and_marks_missing_rows() {
        let mut worker = Worker::with_capacity(32, 1);
        worker.configure(config()).unwrap();
        submit(&mut worker, 0, 2048);
        wait_until(|| worker.metrics.result_dropped.load(Ordering::Relaxed) == 4);
        worker.drain(|row| {
            assert_eq!(row.info.start, 0);
            assert!((row.db()[32] + 6.0206).abs() < 0.003);
        });
        submit(&mut worker, 2048, 256);
        let mut next = None;
        wait_until(|| {
            worker.drain(|row| next = Some(row.info));
            next.is_some()
        });
        assert_eq!(next.unwrap().start, 1280);
        assert_eq!(next.unwrap().gap.result_rows, 4);
    }

    #[test]
    fn default_result_pool_retains_more_than_100_ms_without_ui_recycling() {
        let cfg = config();
        let mut worker = Worker::new();
        worker.configure(cfg).unwrap();
        // 24 rows span 128 ms at 48 kHz / hop 256, exceeding the old 16-row pool.
        let rows = 24;
        let frames = cfg.size + (rows - 1) * cfg.hop;
        submit(&mut worker, 0, frames);
        wait_until(|| {
            worker.metrics.produced.load(Ordering::Relaxed)
                + worker.metrics.result_dropped.load(Ordering::Relaxed)
                == rows as u64
        });
        assert_eq!(worker.metrics.result_dropped.load(Ordering::Relaxed), 0);
        assert_eq!(worker.metrics.input_dropped.load(Ordering::Relaxed), 0);
        let mut received = 0;
        worker.drain(|row| {
            assert_eq!(row.info.start, (received * cfg.hop) as u64);
            assert_eq!(row.info.gap.result_rows, 0);
            assert!((row.db()[32] + 6.0206).abs() < 0.003);
            received += 1;
        });
        assert_eq!(received, rows);
        submit(&mut worker, frames as u64, rows * cfg.hop);
        wait_until(|| worker.metrics.produced.load(Ordering::Relaxed) == (rows * 2) as u64);
        worker.drain(|row| {
            assert_eq!(row.info.start, (received * cfg.hop) as u64);
            assert_eq!(row.info.gap, Gap::default());
            received += 1;
        });
        assert_eq!(received, rows * 2);
    }

    #[test]
    fn incomplete_channel_frames_do_not_panic_or_enter_fft_windows() {
        for malformed_at in [0, 128] {
            let mut worker = Worker::new();
            worker.configure(config()).unwrap();
            submit(&mut worker, 0, malformed_at as usize);
            worker.submit(malformed_at, &[0.5; 15]);
            let start = malformed_at + 1;
            submit(&mut worker, start, 1024);
            wait_until(|| worker.metrics.produced.load(Ordering::Relaxed) == 1);
            let mut received = 0;
            worker.drain(|row| {
                assert_eq!(row.info.start, start);
                assert_eq!(row.info.end, start + 1024);
                assert_eq!(row.info.gap.input_frames, 1);
                assert!(row.info.gap.discontinuity);
                received += 1;
            });
            assert_eq!(received, 1);
            assert_eq!(worker.metrics.input_dropped.load(Ordering::Relaxed), 1);
        }
    }

    #[test]
    fn configuration_and_pause_exclude_queued_and_late_generations() {
        let mut worker = Worker::new();
        let first = worker.configure(config()).unwrap();
        submit(&mut worker, 0, 2048);
        wait_until(|| worker.metrics.produced.load(Ordering::Relaxed) >= 1);
        worker.pause();
        worker.drain(|_| panic!("paused result changed the display"));
        let mut previous = first;
        for overlap in Overlap::ALL {
            let cfg = Config {
                sample_rate: 96000,
                channels: 1,
                channel: 0,
                size: 2048,
                hop: overlap.hop(2048),
                precision: Precision::F32,
                ..config()
            };
            let generation = worker.configure(cfg).unwrap();
            assert!(generation > previous);
            previous = generation;
            for sequence in 0..(cfg.size + 2 * cfg.hop) as u64 {
                worker.submit(sequence, &[0.0]);
            }
            worker.flush();
            let mut received = 0;
            wait_until(|| {
                worker.drain(|row| {
                    assert_eq!(row.info.generation, generation);
                    assert_eq!(row.info.config, cfg);
                    assert_eq!(row.info.start, received * cfg.hop as u64);
                    received += 1;
                });
                received == 3
            });
        }
    }

    #[test]
    fn invalid_configuration_is_rejected_without_changing_generation() {
        let mut worker = Worker::new();
        let generation = worker.configure(config()).unwrap();
        for cfg in [
            Config {
                channels: 17,
                ..config()
            },
            Config {
                channel: 16,
                ..config()
            },
            Config { hop: 0, ..config() },
            Config {
                hop: 1025,
                ..config()
            },
            Config {
                sample_rate: 0,
                ..config()
            },
            Config {
                size: 512,
                ..config()
            },
        ] {
            assert!(worker.configure(cfg).is_err());
        }
        assert_eq!(worker.generation.load(Ordering::Relaxed), generation);
    }
    #[test]
    fn spectrum_large_sizes_cannot_exceed_stft_result_or_texture_capacity() {
        for size in [65536, 131072, 262144, 524288] {
            assert!(Config { size, ..config() }.validate().is_err());
        }
    }
}
