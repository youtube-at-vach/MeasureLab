//! Continuous, sample-clocked STFT on a dedicated worker. All queues and result
//! storage are bounded; the producer never waits for analysis or result delivery.
use crate::{
    signal::{History, MAX_CHANNELS},
    spectrum::{Analyzer, FFT_SIZES, Precision, Settings, Window},
};
use rtrb::{Consumer, Producer, RingBuffer};
use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

pub const BLOCK_FRAMES: usize = 256;
pub const INPUT_BLOCKS: usize = 64;
/// About 0.68 s at 48 kHz / hop 256 (8 MiB at the maximum FFT size).
pub const RESULT_ROWS: usize = 128;
const MAX_BINS: usize = 32768 / 2 + 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Config {
    pub sample_rate: u32,
    pub channels: usize,
    /// Zero-based source channel, independent of the number of displayed traces.
    pub channel: usize,
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
            || !FFT_SIZES.contains(&self.size)
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
    /// Complete windows lost because the UI did not recycle result storage.
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
    db: Box<[f32]>,
}

impl Row {
    pub fn db(&self) -> &[f32] {
        &self.db[..self.info.config.size / 2 + 1]
    }
}

#[derive(Default)]
pub struct Metrics {
    pub input_dropped: AtomicU64,
    pub result_dropped: AtomicU64,
    pub produced: AtomicU64,
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
                    size: config.size,
                    window: config.window,
                    averages: 1,
                    remove_dc: config.remove_dc,
                    precision: config.precision,
                },
                config.sample_rate,
            ),
            expected: None,
            next_end: 0,
            gap: Gap {
                discontinuity: true,
                ..Gap::default()
            },
        }
    }

    fn process(&mut self, block: &InputBlock, mut emit: impl FnMut(RowInfo, &[f32]) -> bool) {
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
            if emit(info, self.analyzer.db()) {
                self.gap = Gap::default();
            } else {
                self.gap.result_rows += 1;
            }
            self.next_end += self.config.hop as u64;
        }
        self.expected = Some(block.start + block.len as u64);
    }
}

/// Input endpoint can be moved to the measurement worker while the UI retains
/// result delivery and recycling. Neither endpoint waits for the other.
pub struct Feeder {
    input: Producer<InputBlock>,
    pending: Option<InputBlock>,
    generation: Arc<AtomicU64>,
    wake: thread::Thread,
    metrics: Arc<Metrics>,
}

pub struct Worker {
    feeder: Option<Feeder>,
    results: Consumer<Row>,
    recycle: Producer<Row>,
    generation: Arc<AtomicU64>,
    shutdown: Arc<AtomicBool>,
    handle: Option<JoinHandle<()>>,
    pub metrics: Arc<Metrics>,
}

impl Worker {
    pub fn new() -> Self {
        Self::with_capacity(INPUT_BLOCKS, RESULT_ROWS)
    }

    fn with_capacity(input_blocks: usize, result_rows: usize) -> Self {
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
        for _ in 0..result_rows {
            recycle
                .push(Row {
                    info: RowInfo {
                        generation: 0,
                        config: placeholder,
                        start: 0,
                        end: 0,
                        gap: Gap::default(),
                    },
                    db: vec![0.0; MAX_BINS].into_boxed_slice(),
                })
                .unwrap_or_else(|_| unreachable!("result pool capacity"));
        }
        let generation = Arc::new(AtomicU64::new(0));
        let shutdown = Arc::new(AtomicBool::new(false));
        let metrics = Arc::new(Metrics::default());
        let active = generation.clone();
        let stop = shutdown.clone();
        let counters = metrics.clone();
        let handle = thread::spawn(move || {
            let mut processor: Option<Processor> = None;
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
                    processor = Some(Processor::new(block.generation, block.config));
                }
                let started = Instant::now();
                processor.as_mut().unwrap().process(&block, |info, db| {
                    if info.generation != active.load(Ordering::Acquire) {
                        return true; // obsolete data cannot become a visible result
                    }
                    let Ok(mut row) = free.pop() else {
                        counters.result_dropped.fetch_add(1, Ordering::Relaxed);
                        return false;
                    };
                    row.info = info;
                    row.db[..db.len()].copy_from_slice(db);
                    // Pool size equals queue capacity: owning a free row guarantees a slot.
                    outgoing
                        .push(row)
                        .unwrap_or_else(|_| unreachable!("result pool invariant"));
                    counters.produced.fetch_add(1, Ordering::Relaxed);
                    true
                });
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
            results,
            recycle,
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

    /// Bounded drain, preserving every available row in order for future texture
    /// history. The callback borrows pool storage; it cannot keep or grow the pool.
    pub fn drain(&mut self, mut consume: impl FnMut(&Row)) {
        let generation = self.generation.load(Ordering::Acquire);
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
pub fn smoke_test(device_name: Option<&str>, channel: usize) -> Result<(), String> {
    let device = crate::audio::input_device(device_name)?;
    let (_stream, mut capture) = crate::audio::start_device(&device)?;
    let config = Config {
        sample_rate: capture.sample_rate,
        channels: capture.channels as usize,
        channel,
        size: 8192,
        hop: 2048,
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
                processor.process(&input, |info, db| {
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
            processor.process(&block(start, len, config), |info, db| {
                rows.push((info, db.to_vec()));
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
            processor.process(&b, |_, db| {
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

    fn submit(worker: &mut Worker, start: u64, count: usize) {
        for i in 0..count {
            let mut samples = [0.0; 16];
            samples[15] = 0.5 * (TAU * 32.0 * (start + i as u64) as f64 / 1024.0).cos();
            worker.submit(start + i as u64, &samples);
        }
        worker.flush();
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
        let cfg = Config {
            sample_rate: 96000,
            channels: 1,
            channel: 0,
            size: 2048,
            hop: 512,
            precision: Precision::F32,
            ..config()
        };
        let second = worker.configure(cfg).unwrap();
        assert!(second > first);
        for sequence in 0..3072 {
            worker.submit(sequence, &[0.0]);
        }
        worker.flush();
        let mut received = 0;
        wait_until(|| {
            worker.drain(|row| {
                assert_eq!(row.info.generation, second);
                assert_eq!(row.info.config, cfg);
                assert_eq!(row.info.start, received * 512);
                received += 1;
            });
            received == 3
        });
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
}
