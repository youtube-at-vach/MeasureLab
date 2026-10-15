//! Numerical STFT retention, collected independently of UI result delivery.
//! The display ring is a separate cache; it is never the source of f64 readings.
use crate::stft::{Config, Results, RowInfo};
use std::{
    collections::VecDeque,
    mem::{size_of, size_of_val},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering},
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

pub const RETENTION_SECONDS: u64 = 120;
pub const HISTORY_BYTES: usize = 96 * 1024 * 1024;
// Leave room for rows still referenced by the previous published snapshot.
// Otherwise a full Hold + live ring could exhaust the frame budget during
// publication exchange, even though both retained views fit individually.
const RETAINED_BYTES: usize = HISTORY_BYTES - 2 * 1024 * 1024;
// Latest and one Hold history share this aggregate frame allocation limit.
// Rasters have a separate 8 MiB lease budget; FFT/result storage is independent.
pub const FRAME_BYTES: usize = 192 * 1024 * 1024;
const PUBLISH_INTERVAL: Duration = Duration::from_millis(20);

#[derive(Default)]
struct Budget {
    used: AtomicUsize,
    peak: AtomicUsize,
}

impl Budget {
    fn reserve(&self, bytes: usize) -> bool {
        let mut previous = self.used.load(Ordering::Acquire);
        loop {
            let Some(total) = previous.checked_add(bytes).filter(|&n| n <= FRAME_BYTES) else {
                return false;
            };
            match self.used.compare_exchange_weak(
                previous,
                total,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => break,
                Err(current) => previous = current,
            }
        }
        self.peak.fetch_max(previous + bytes, Ordering::Relaxed);
        true
    }
}

/// Immutable normalized bin powers with both input and analysis identities.
/// The interval is the actual FFT window, not the display row's hop interval.
pub struct Frame {
    pub input_generation: u64,
    pub info: RowInfo,
    power: Box<[f64]>,
    budget: Arc<Budget>,
    bytes: usize,
}

impl Frame {
    pub fn power(&self) -> &[f64] {
        &self.power
    }

    pub fn amplitude(&self, bin: usize) -> Option<f64> {
        self.power.get(bin).map(|p| p.sqrt())
    }

    pub fn level_db(&self, bin: usize) -> Option<f64> {
        self.power.get(bin).map(|&p| crate::spectrum::level_db(p))
    }

    pub fn valid(&self) -> bool {
        self.power.iter().all(|p| p.is_finite() && *p >= 0.0)
    }

    pub fn db(&self) -> Vec<f32> {
        self.power
            .iter()
            .map(|&p| crate::spectrum::level_db(p) as f32)
            .collect()
    }
}

impl Drop for Frame {
    fn drop(&mut self) {
        drop(std::mem::take(&mut self.power));
        self.budget.used.fetch_sub(self.bytes, Ordering::AcqRel);
    }
}

#[derive(Clone, Default)]
pub struct Snapshot {
    pub input_generation: u64,
    pub generation: u64,
    pub config: Option<Config>,
    frames: VecDeque<Arc<Frame>>,
    pub retired: u64,
    pub capacity_limited: bool,
}

impl Snapshot {
    pub fn frames(&self) -> impl DoubleEndedIterator<Item = &Arc<Frame>> + ExactSizeIterator {
        self.frames.iter()
    }

    pub fn latest(&self) -> Option<&Arc<Frame>> {
        self.frames.back()
    }

    pub fn retained_seconds(&self) -> f64 {
        let (Some(oldest), Some(latest)) = (self.frames.front(), self.frames.back()) else {
            return 0.0;
        };
        (latest.info.end - oldest.info.end + latest.info.config.hop as u64) as f64
            / latest.info.config.sample_rate as f64
    }

    /// Search only actual half-open display hops. An overlapping FFT window
    /// cannot supply data for a missing hop or unretained sample.
    pub fn at_sample(&self, sample: u64) -> Option<&Arc<Frame>> {
        let index = self
            .frames
            .partition_point(|frame| frame.info.end <= sample);
        let frame = self.frames.get(index)?;
        (sample >= frame.info.end - frame.info.config.hop as u64).then_some(frame)
    }

    /// Half-open display hops intersecting a sample interval. Binary searches
    /// keep viewport reduction independent of unshown older/newer frames.
    pub(super) fn overlapping_hops(
        &self,
        start: i128,
        end: i128,
    ) -> impl ExactSizeIterator<Item = &Arc<Frame>> {
        let first = self
            .frames
            .partition_point(|frame| frame.info.end as i128 <= start);
        let last = self.frames.partition_point(|frame| {
            frame.info.end as i128 - (frame.info.config.hop as i128) < end
        });
        self.frames.range(first..last)
    }

    pub fn storage_bytes(&self) -> usize {
        self.frames.iter().map(|f| f.bytes).sum::<usize>()
            + self.frames.capacity() * size_of::<Arc<Frame>>()
    }
}

struct Archive {
    snapshot: Snapshot,
    budget: Arc<Budget>,
    bytes: usize,
    pending_lost: u64,
}

impl Archive {
    fn new(
        input_generation: u64,
        generation: u64,
        config: Option<Config>,
        budget: Arc<Budget>,
    ) -> Self {
        let frames = config.map_or_else(VecDeque::new, |config| {
            let bytes = size_of::<Frame>()
                + 2 * size_of::<usize>()
                + (config.size / 2 + 1) * size_of::<f64>()
                + size_of::<Arc<Frame>>();
            let by_time = (RETENTION_SECONDS * config.sample_rate as u64)
                .div_ceil(config.hop as u64) as usize;
            VecDeque::with_capacity((RETAINED_BYTES / bytes).min(by_time).max(1))
        });
        Self {
            snapshot: Snapshot {
                input_generation,
                generation,
                config,
                frames,
                ..Snapshot::default()
            },
            budget,
            bytes: 0,
            pending_lost: 0,
        }
    }

    fn retire(&mut self) {
        let frame = self.snapshot.frames.pop_front().unwrap();
        self.bytes -= frame.bytes;
        self.snapshot.retired += 1;
    }

    fn push(&mut self, mut info: RowInfo, power: &[f64]) -> bool {
        if self.snapshot.config != Some(info.config)
            || self.snapshot.generation != info.generation
            || power.len() != info.config.size / 2 + 1
            || info.end.checked_sub(info.start) != Some(info.config.size as u64)
            || self
                .snapshot
                .latest()
                .is_some_and(|last| last.info.end >= info.end)
        {
            return false;
        }
        // Count allocator payload and reference ownership conservatively. The
        // deque itself is bounded separately and included in storage_bytes().
        let bytes = size_of::<Frame>() + 2 * size_of::<usize>() + size_of_val(power);
        let span = RETENTION_SECONDS * info.config.sample_rate as u64;
        while let Some(oldest) = self.snapshot.frames.front() {
            let over_time = info.end - oldest.info.end + info.config.hop as u64 > span;
            let over_bytes =
                self.bytes + bytes + self.snapshot.frames.capacity() * size_of::<Arc<Frame>>()
                    > RETAINED_BYTES;
            if !over_time && !over_bytes {
                break;
            }
            self.snapshot.capacity_limited |= over_bytes;
            self.retire();
        }
        // Snapshot readers cannot force unbounded allocations. If old pinned
        // frames fill the aggregate budget, retire unpinned live data first.
        while !self.budget.reserve(bytes) {
            self.snapshot.capacity_limited = true;
            if self.snapshot.frames.is_empty() {
                self.pending_lost += 1;
                return false;
            }
            self.retire();
        }
        info.gap.result_rows = info.gap.result_rows.saturating_add(self.pending_lost);
        self.pending_lost = 0;
        self.snapshot.frames.push_back(Arc::new(Frame {
            input_generation: self.snapshot.input_generation,
            info,
            power: power.into(),
            budget: self.budget.clone(),
            bytes,
        }));
        self.bytes += bytes;
        true
    }
}

#[derive(Default)]
pub struct Metrics {
    pub collected: AtomicU64,
    pub storage_dropped: AtomicU64,
    pub published: AtomicU64,
    pub processing_nanos: AtomicU64,
}

struct Shared {
    input_generation: u64,
    generation: u64,
    config: Option<Config>,
    accepting: bool,
    snapshot: Arc<Snapshot>,
}

/// Sole consumer of the STFT pool. Publication is an Arc exchange under a
/// short mailbox lock; readers perform conversion and statistics after unlock.
/// Snapshots may outlive ring wrap without copying or mutating their frames.
pub struct Collector {
    shared: Arc<Mutex<Shared>>,
    budget: Arc<Budget>,
    shutdown: Arc<AtomicBool>,
    handle: Option<JoinHandle<()>>,
    pub metrics: Arc<Metrics>,
}

impl Collector {
    pub fn new(mut results: Results) -> Self {
        let shared = Arc::new(Mutex::new(Shared {
            input_generation: 0,
            generation: 0,
            config: None,
            accepting: false,
            snapshot: Arc::new(Snapshot::default()),
        }));
        let shutdown = Arc::new(AtomicBool::new(false));
        let budget = Arc::new(Budget::default());
        let metrics = Arc::new(Metrics::default());
        let (state, stop, allocation, counters) = (
            shared.clone(),
            shutdown.clone(),
            budget.clone(),
            metrics.clone(),
        );
        let handle = thread::spawn(move || {
            results.wake_on_result(thread::current());
            let mut archive = Archive::new(0, 0, None, allocation.clone());
            let mut published_at = Instant::now() - PUBLISH_INTERVAL;
            let mut dirty = false;
            while !stop.load(Ordering::Acquire) {
                let started = Instant::now();
                let (input_generation, generation, config) = {
                    let state = state.lock().unwrap();
                    (state.input_generation, state.generation, state.config)
                };
                if archive.snapshot.generation != generation
                    || archive.snapshot.input_generation != input_generation
                {
                    archive =
                        Archive::new(input_generation, generation, config, allocation.clone());
                    dirty = false;
                }
                results.drain(|row| {
                    // Re-read the gate per row: configuration may have changed
                    // after the batch began, before a new generation arrived.
                    let (input_generation, generation, config, accepting) = {
                        let state = state.lock().unwrap();
                        (
                            state.input_generation,
                            state.generation,
                            state.config,
                            state.accepting,
                        )
                    };
                    if archive.snapshot.generation != generation
                        || archive.snapshot.input_generation != input_generation
                    {
                        archive =
                            Archive::new(input_generation, generation, config, allocation.clone());
                        dirty = false;
                    }
                    if accepting && row.info.generation == generation {
                        if archive.push(row.info, row.power()) {
                            counters.collected.fetch_add(1, Ordering::Relaxed);
                            dirty = true;
                        } else {
                            counters.storage_dropped.fetch_add(1, Ordering::Relaxed);
                        }
                    }
                });
                if dirty && published_at.elapsed() >= PUBLISH_INTERVAL {
                    // Clone reference metadata outside the mailbox lock. No FFT,
                    // full-bin conversion or GPU work holds the publication lock.
                    let snapshot = Arc::new(archive.snapshot.clone());
                    let input_generation = snapshot.input_generation;
                    let generation = snapshot.generation;
                    let previous = {
                        let mut state = state.lock().unwrap();
                        if state.accepting
                            && state.generation == generation
                            && state.input_generation == input_generation
                        {
                            counters.published.fetch_add(1, Ordering::Relaxed);
                            Some(std::mem::replace(&mut state.snapshot, snapshot))
                        } else {
                            None
                        }
                    };
                    drop(previous); // releasing large retired snapshots is off-lock
                    published_at = Instant::now();
                    dirty = false;
                }
                counters
                    .processing_nanos
                    .fetch_add(started.elapsed().as_nanos() as u64, Ordering::Relaxed);
                if dirty {
                    thread::park_timeout(PUBLISH_INTERVAL.saturating_sub(published_at.elapsed()));
                } else {
                    thread::park();
                }
            }
        });
        Self {
            shared,
            budget,
            shutdown,
            handle: Some(handle),
            metrics,
        }
    }

    pub fn configure(&self, input_generation: u64, generation: u64, config: Config) {
        config.validate().expect("validated history configuration");
        let snapshot = Arc::new(Snapshot {
            input_generation,
            generation,
            config: Some(config),
            ..Snapshot::default()
        });
        let previous = {
            let mut state = self.shared.lock().unwrap();
            state.input_generation = input_generation;
            state.generation = generation;
            state.config = Some(config);
            state.accepting = true;
            std::mem::replace(&mut state.snapshot, snapshot)
        };
        drop(previous);
        self.handle.as_ref().unwrap().thread().unpark();
    }

    /// Fix the last published boundary. A collection/publication already in
    /// flight cannot replace it after this returns. Acquisition control stays
    /// with the existing common Stop, never a display snapshot operation.
    pub fn freeze(&self) {
        self.shared.lock().unwrap().accepting = false;
    }

    pub fn clear(&self) {
        let previous = {
            let mut state = self.shared.lock().unwrap();
            state.accepting = false;
            state.generation = 0;
            state.input_generation = 0;
            state.config = None;
            std::mem::replace(&mut state.snapshot, Arc::new(Snapshot::default()))
        };
        drop(previous);
        self.handle.as_ref().unwrap().thread().unpark();
    }

    pub fn snapshot(&self) -> Arc<Snapshot> {
        self.shared.lock().unwrap().snapshot.clone()
    }

    /// Display polling stops at the common Stop boundary; numerical snapshots
    /// remain available for subsequent read-only history views.
    pub fn live_snapshot(&self) -> Option<Arc<Snapshot>> {
        let state = self.shared.lock().unwrap();
        state.accepting.then(|| state.snapshot.clone())
    }

    /// Widget QA uses a deterministic finite source, never startup races.
    #[cfg(feature = "qa")]
    pub(crate) fn replace_frozen_snapshot(&self, snapshot: Arc<Snapshot>) -> Arc<Snapshot> {
        let mut state = self.shared.lock().unwrap();
        assert!(!state.accepting, "QA fixture requires a frozen collector");
        std::mem::replace(&mut state.snapshot, snapshot)
    }

    pub fn allocated_frame_bytes(&self) -> usize {
        self.budget.used.load(Ordering::Acquire)
    }

    pub fn peak_frame_bytes(&self) -> usize {
        self.budget.peak.load(Ordering::Relaxed)
    }
}

impl Drop for Collector {
    fn drop(&mut self) {
        self.shutdown.store(true, Ordering::Release);
        if let Some(handle) = self.handle.take() {
            handle.thread().unpark();
            let _ = handle.join();
        }
    }
}

#[cfg(any(test, feature = "qa"))]
pub(crate) fn fixture(
    input_generation: u64,
    generation: u64,
    config: Config,
    rows: impl IntoIterator<Item = (RowInfo, Vec<f64>)>,
) -> Arc<Snapshot> {
    let mut archive = Archive::new(input_generation, generation, Some(config), Arc::default());
    for (info, power) in rows {
        assert!(archive.push(info, &power));
    }
    Arc::new(archive.snapshot.clone())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        spectrum::{Precision, Window},
        stft::{Gap, Worker},
    };
    use std::f64::consts::TAU;

    fn config() -> Config {
        Config {
            sample_rate: 1024,
            channels: 1,
            channel: 0,
            size: 1024,
            hop: 256,
            window: Window::Rectangular,
            remove_dc: false,
            precision: Precision::F64,
        }
    }

    fn info(config: Config, generation: u64, end: u64) -> RowInfo {
        RowInfo {
            generation,
            config,
            start: end - config.size as u64,
            end,
            gap: Gap::default(),
        }
    }

    fn wait(mut condition: impl FnMut() -> bool) {
        let deadline = Instant::now() + Duration::from_secs(10);
        while !condition() {
            assert!(Instant::now() < deadline, "history collector timed out");
            thread::sleep(Duration::from_millis(1));
        }
    }

    #[test]
    fn wrap_and_snapshot_keep_original_f64_values_and_sample_identity() {
        let config = config();
        let budget = Arc::new(Budget::default());
        let mut archive = Archive::new(71, 3, Some(config), budget.clone());
        let origin = (1_u64 << 54) + 1024;
        let mut power = vec![0.0; 513];
        // This value cannot survive a round trip through f32 dB.
        power[32] = 0.25 + f64::EPSILON;
        for index in 0..480 {
            assert!(archive.push(info(config, 3, origin + index * 256), &power));
        }
        let held = archive.snapshot.clone();
        let selected = held.at_sample(origin + 32 * 256 - 1).unwrap().clone();
        for index in 480..1600 {
            power[32] = index as f64;
            assert!(archive.push(info(config, 3, origin + index * 256), &power));
        }
        assert_eq!(held.frames.len(), 480);
        assert_eq!(held.retained_seconds(), 120.0);
        assert_eq!(archive.snapshot.retained_seconds(), 120.0);
        assert_eq!(archive.snapshot.retired, 1120);
        assert!(archive.snapshot.at_sample(selected.info.end - 1).is_none());
        assert_eq!(selected.input_generation, 71);
        assert_eq!(selected.info.generation, 3);
        assert_eq!(
            selected.power()[32].to_bits(),
            (0.25 + f64::EPSILON).to_bits()
        );
        assert_eq!(selected.amplitude(32), Some((0.25 + f64::EPSILON).sqrt()));
        assert_eq!(
            selected.level_db(32),
            Some(10.0 * (0.25 + f64::EPSILON).log10())
        );
        assert!(selected.valid());
        assert!(budget.used.load(Ordering::Relaxed) <= FRAME_BYTES);
        drop(selected);
        drop(held);
        drop(archive);
        assert_eq!(budget.used.load(Ordering::Relaxed), 0);
    }

    #[test]
    fn missing_hops_invalidity_and_silence_are_not_replaced() {
        let config = config();
        let mut archive = Archive::new(1, 2, Some(config), Arc::default());
        let mut power = vec![0.0; 513];
        assert!(archive.push(info(config, 2, 1024), &power));
        power.fill(f64::NAN);
        let mut after_gap = info(config, 2, 2048);
        after_gap.gap.result_rows = 3;
        assert!(archive.push(after_gap, &power));
        let snapshot = &archive.snapshot;
        let silence = snapshot.at_sample(1023).unwrap();
        assert_eq!(silence.level_db(0), Some(f64::NEG_INFINITY));
        assert!(silence.valid());
        assert!(snapshot.at_sample(767).is_none());
        assert!(snapshot.at_sample(1024).is_none());
        assert!(snapshot.at_sample(1500).is_none());
        let invalid = snapshot.at_sample(2047).unwrap();
        assert!(invalid.level_db(0).unwrap().is_nan());
        assert!(!invalid.valid());
        assert_eq!(invalid.info.gap.result_rows, 3);
        assert!(snapshot.at_sample(2048).is_none());
        assert!(!archive.push(info(config, 2, 2048), &power));
        assert!(!archive.push(info(config, 1, 2304), &power));
        assert!(!archive.push(info(config, 2, 2304), &power[..512]));
    }

    #[test]
    fn maximum_fft_high_rate_and_pinned_generations_stay_bounded() {
        let config = Config {
            sample_rate: 768000,
            size: 32768,
            hop: 8192,
            ..config()
        };
        let budget = Arc::new(Budget::default());
        let power = vec![0.25; 16385];
        let mut archive = Archive::new(1, 1, Some(config), budget.clone());
        for index in 0..1500 {
            assert!(archive.push(info(config, 1, 32768 + index * 8192), &power));
            assert!(archive.snapshot.storage_bytes() <= HISTORY_BYTES);
        }
        assert!(archive.snapshot.capacity_limited);
        assert!(archive.snapshot.retained_seconds() < 60.0);
        let held = archive.snapshot.clone();
        let first = held.frames.front().unwrap().info;
        // Repeat replacement while the old generation is still pinned.
        for generation in 2..6 {
            archive = Archive::new(generation, generation, Some(config), budget.clone());
            for index in 0..1500 {
                let accepted = archive.push(info(config, generation, 32768 + index * 8192), &power);
                assert!(accepted);
                assert!(archive.snapshot.storage_bytes() <= HISTORY_BYTES);
                assert!(budget.used.load(Ordering::Relaxed) <= FRAME_BYTES);
            }
            assert!(archive.snapshot.capacity_limited);
            assert_eq!(held.frames.front().unwrap().info, first);
        }
        assert!(budget.peak.load(Ordering::Relaxed) <= FRAME_BYTES);
        drop(held);
        drop(archive);
        assert_eq!(budget.used.load(Ordering::Relaxed), 0);
    }

    #[test]
    fn full_hold_and_live_publication_exchange_do_not_collapse_retention() {
        let config = Config {
            sample_rate: 768000,
            size: 32768,
            hop: 8192,
            ..config()
        };
        let budget = Arc::new(Budget::default());
        let mut archive = Archive::new(1, 1, Some(config), budget.clone());
        let power = vec![0.25; config.size / 2 + 1];
        for index in 0..1000 {
            assert!(archive.push(info(config, 1, 32768 + index * 8192), &power));
        }
        let held = archive.snapshot.clone();
        let mut published = archive.snapshot.clone();
        for index in 1000..2600 {
            assert!(archive.push(info(config, 1, 32768 + index * 8192), &power));
            assert!(
                archive.snapshot.frames.len() > 700,
                "publication exhausted live retention"
            );
            if index % 2 == 0 {
                published = archive.snapshot.clone();
            }
        }
        assert!(published.latest().unwrap().info.end > held.latest().unwrap().info.end);
        assert_eq!(held.frames.front().unwrap().power()[32], 0.25);
        assert!(budget.peak.load(Ordering::Relaxed) <= FRAME_BYTES);
    }

    #[test]
    fn budget_exhaustion_reports_lost_rows_on_the_next_real_frame() {
        let config = config();
        let budget = Arc::new(Budget::default());
        let mut archive = Archive::new(1, 1, Some(config), budget.clone());
        // Model other immutable readers occupying the aggregate reservation.
        assert!(budget.reserve(FRAME_BYTES));
        assert!(!archive.push(info(config, 1, 1024), &vec![0.0; 513]));
        budget.used.fetch_sub(FRAME_BYTES, Ordering::Relaxed);
        assert!(archive.push(info(config, 1, 1280), &vec![0.0; 513]));
        assert_eq!(archive.snapshot.latest().unwrap().info.gap.result_rows, 1);
        assert_eq!(archive.snapshot.frames.len(), 1);
        assert_eq!(archive.snapshot.retired, 0);
    }

    #[test]
    fn collector_recycles_during_ui_stall_freezes_and_rejects_old_generations() {
        for precision in [Precision::F64, Precision::F32] {
            let mut worker = Worker::new();
            let collector = Collector::new(worker.take_results());
            let config = Config {
                precision,
                ..config()
            };
            let generation = worker.configure(config).unwrap();
            collector.configure(19, generation, config);
            // More than the result pool and old display ring, without a UI poll.
            let rows = 640;
            let frames = config.size + (rows - 1) * config.hop;
            for start in (0..frames).step_by(1024) {
                for n in start..(start + 1024).min(frames) {
                    worker.submit(n as u64, &[0.5 * (TAU * 32.0 * n as f64 / 1024.0).cos()]);
                }
                worker.flush();
                // Deterministic finite-input pacing waits for the corresponding
                // result, without consuming/recycling any results on this thread.
                let expected = ((start + 1024).min(frames) - config.size) / config.hop + 1;
                wait(|| collector.metrics.collected.load(Ordering::Relaxed) == expected as u64);
            }
            wait(|| {
                collector
                    .snapshot()
                    .latest()
                    .is_some_and(|f| f.info.end == frames as u64)
            });
            let held = collector.snapshot();
            assert_eq!(held.input_generation, 19);
            assert_eq!(held.frames.len(), 480);
            assert_eq!(held.retained_seconds(), 120.0);
            assert_eq!(worker.metrics.result_dropped.load(Ordering::Relaxed), 0);
            assert_eq!(worker.metrics.input_dropped.load(Ordering::Relaxed), 0);
            let tolerance = if precision == Precision::F64 {
                1e-12
            } else {
                1e-6
            };
            assert!((held.latest().unwrap().power()[32] - 0.25).abs() < tolerance);
            assert_eq!(held.latest().unwrap().info.config.precision, precision);
            collector.freeze();
            let frozen = collector.snapshot();
            for n in frames..frames + 2048 {
                worker.submit(n as u64, &[0.0]);
            }
            worker.flush();
            wait(|| worker.metrics.produced.load(Ordering::Relaxed) == rows as u64 + 8);
            assert!(Arc::ptr_eq(&collector.snapshot(), &frozen));
            worker.pause();
            let next = worker.configure(config).unwrap();
            collector.configure(20, next, config);
            assert!(collector.snapshot().latest().is_none());
            for n in 0..1024 {
                worker.submit(n, &[0.0]);
            }
            worker.flush();
            wait(|| collector.snapshot().latest().is_some());
            let snapshot = collector.snapshot();
            assert_eq!(snapshot.frames.len(), 1);
            assert_eq!(snapshot.input_generation, 20);
            assert_eq!(snapshot.latest().unwrap().info.generation, next);
            assert_eq!(snapshot.latest().unwrap().power()[32], 0.0);
            assert_eq!(held.latest().unwrap().info.generation, generation);
            collector.clear();
            assert!(collector.snapshot().config.is_none());
            assert!(collector.snapshot().latest().is_none());
            assert!(collector.peak_frame_bytes() <= FRAME_BYTES);
        }
    }
}
