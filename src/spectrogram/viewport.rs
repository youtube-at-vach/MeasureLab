//! Bounded, replaceable display requests. No FFT or acquisition work runs here.
//! The raster is a peak-preserving view; numerical reads always use Snapshot.
use super::{ColorRange, History, Placement, ROWS, history::Snapshot};
use crate::{spectrum::View, stft::RowInfo};
use std::{
    mem::size_of,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering},
    },
    thread::{self, JoinHandle},
    time::Instant,
};

pub const MAX_COLUMNS: usize = 1024;
/// Includes all in-flight rasters, including callbacks retaining an old image.
pub const CACHE_BYTES: usize = 8 * 1024 * 1024;
const RASTER_BYTES: usize = ROWS * MAX_COLUMNS * size_of::<f32>()
    + ROWS
        * (2 * size_of::<Option<RowInfo>>()
            + 2 * size_of::<Placement>()
            + 2 * size_of::<u64>()
            + size_of::<Option<(u64, u64)>>()
            + 1)
    + MAX_COLUMNS * (2 * size_of::<usize>() + size_of::<f32>())
    + size_of::<History>()
    + size_of::<Raster>();

#[derive(Default)]
struct Budget {
    used: AtomicUsize,
    peak: AtomicUsize,
}
struct Lease {
    budget: Arc<Budget>,
}
impl Drop for Lease {
    fn drop(&mut self) {
        self.budget.used.fetch_sub(RASTER_BYTES, Ordering::AcqRel);
    }
}
impl Budget {
    fn lease(self: &Arc<Self>) -> Option<Lease> {
        let mut previous = self.used.load(Ordering::Acquire);
        loop {
            let total = previous
                .checked_add(RASTER_BYTES)
                .filter(|&n| n <= CACHE_BYTES)?;
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
        self.peak
            .fetch_max(previous + RASTER_BYTES, Ordering::Relaxed);
        Some(Lease {
            budget: self.clone(),
        })
    }
}

pub(super) struct Raster {
    pub width: usize,
    pub db: Vec<f32>,
    pub rows: Vec<Option<RowInfo>>,
    pub placements: Vec<Placement>,
    pub versions: Vec<u64>,
    pub latest: RowInfo,
    pub retained_seconds: f64,
    _lease: Lease,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Parameters {
    /// None follows the latest complete frame; Some fixes a Hold upper edge.
    pub anchor: Option<u64>,
    pub seconds: f64,
    pub view: View,
    pub columns: usize,
    pub rows: usize,
    pub auto: bool,
    pub live: bool,
}

struct Request {
    id: u64,
    snapshot: Arc<Snapshot>,
    parameters: Parameters,
}
pub struct Prepared {
    pub id: u64,
    pub snapshot: Arc<Snapshot>,
    pub anchor: u64,
    pub history: History,
    pub range: ColorRange,
    pub processing_ms: f64,
}
#[derive(Default)]
struct Mailbox {
    request: Option<Request>,
    response: Option<Prepared>,
}

pub struct Worker {
    mailbox: Arc<Mutex<Mailbox>>,
    shutdown: Arc<AtomicBool>,
    handle: Option<JoinHandle<()>>,
    key: Option<(u64, u64, Parameters)>,
    last_end: Option<u64>,
    id: u64,
    submitted_at: Option<Instant>,
    budget: Arc<Budget>,
    pub replaced: Arc<AtomicU64>,
    retry: Arc<AtomicBool>,
}

impl Default for Worker {
    fn default() -> Self {
        let mailbox = Arc::new(Mutex::new(Mailbox::default()));
        let shutdown = Arc::new(AtomicBool::new(false));
        let budget = Arc::new(Budget::default());
        let replaced = Arc::new(AtomicU64::new(0));
        let retry = Arc::new(AtomicBool::new(false));
        let (queue, stop, allocation, retry_worker) = (
            mailbox.clone(),
            shutdown.clone(),
            budget.clone(),
            retry.clone(),
        );
        let handle = thread::spawn(move || {
            let mut range = None;
            let mut range_key = None;
            let mut auto_at: Option<Instant> = None;
            while !stop.load(Ordering::Acquire) {
                let request = queue.lock().unwrap().request.take();
                let Some(mut request) = request else {
                    thread::park();
                    continue;
                };
                let started = Instant::now();
                if range_key
                    != Some((
                        request.snapshot.input_generation,
                        request.snapshot.generation,
                    ))
                {
                    range = None;
                    range_key = Some((
                        request.snapshot.input_generation,
                        request.snapshot.generation,
                    ));
                }
                if request.parameters.auto
                    && request.parameters.live
                    && auto_at.is_some_and(|t| t.elapsed().as_secs_f64() < 0.25)
                {
                    request.parameters.auto = false;
                } else if request.parameters.auto {
                    auto_at = Some(Instant::now());
                }
                let Some(mut prepared) = prepare(&request, &allocation, &mut range) else {
                    retry_worker.store(true, Ordering::Release);
                    continue;
                };
                prepared.processing_ms = started.elapsed().as_secs_f64() * 1000.0;
                let previous = {
                    let mut queue = queue.lock().unwrap();
                    // A superseded pan or generation must never replace its view.
                    if queue
                        .request
                        .as_ref()
                        .is_some_and(|next| next.id != request.id)
                    {
                        None
                    } else {
                        queue.response.replace(prepared)
                    }
                };
                drop(previous);
            }
        });
        Self {
            mailbox,
            shutdown,
            handle: Some(handle),
            key: None,
            last_end: None,
            id: 0,
            submitted_at: None,
            budget,
            replaced,
            retry,
        }
    }
}

impl Worker {
    pub fn submit(&mut self, snapshot: Arc<Snapshot>, parameters: Parameters) {
        let mut parameters = parameters;
        parameters.view.floor_db = 0.0;
        parameters.view.ceiling_db = 0.0;
        let key = (snapshot.input_generation, snapshot.generation, parameters);
        let end = snapshot.latest().map(|f| f.info.end);
        if !self.retry.swap(false, Ordering::AcqRel)
            && self.key == Some(key)
            && (self.last_end == end
                || self
                    .submitted_at
                    .is_some_and(|t| t.elapsed().as_secs_f64() < 0.05))
        {
            return;
        }
        self.submitted_at = Some(Instant::now());
        if self.key != Some(key) {
            self.id = self.id.wrapping_add(1);
        }
        self.key = Some(key);
        self.last_end = end;
        let previous = self.mailbox.lock().unwrap().request.replace(Request {
            id: self.id,
            snapshot,
            parameters,
        });
        if previous.is_some() {
            self.replaced.fetch_add(1, Ordering::Relaxed);
        }
        drop(previous);
        self.handle.as_ref().unwrap().thread().unpark();
    }
    pub fn current_id(&self) -> u64 {
        self.id
    }
    pub fn take(&self) -> Option<Prepared> {
        let response = self.mailbox.lock().unwrap().response.take();
        response.filter(|r| r.id == self.id)
    }
    pub fn clear(&mut self) {
        self.id = self.id.wrapping_add(1);
        self.key = None;
        self.last_end = None;
        let previous = std::mem::take(&mut *self.mailbox.lock().unwrap());
        drop(previous);
    }
    pub fn peak_cache_bytes(&self) -> usize {
        self.budget.peak.load(Ordering::Relaxed)
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

fn prepare(
    request: &Request,
    budget: &Arc<Budget>,
    range: &mut Option<ColorRange>,
) -> Option<Prepared> {
    let snapshot = &request.snapshot;
    let latest = snapshot.latest()?.info;
    let p = request.parameters;
    if !p.seconds.is_finite() || p.seconds <= 0.0 {
        return None;
    }
    let anchor = p.anchor.unwrap_or(latest.end);

    let span = (p.seconds * latest.config.sample_rate as f64)
        .round()
        .max(1.0) as i128;
    let width = p.columns.clamp(1, MAX_COLUMNS);
    let height = p.rows.clamp(1, ROWS);
    let lease = budget.lease()?;
    let mut db = vec![f32::NEG_INFINITY; width * height];
    let mut rows = vec![None; height];
    let mut missing = vec![false; height];
    let mut coverage: Vec<Option<(u64, u64)>> = vec![None; height];
    let bin_hz = latest.config.sample_rate as f32 / latest.config.size as f32;
    let max_bin = latest.config.size / 2;
    let min = (p.view.min_hz / bin_hz).ceil() as usize;
    let max = ((p.view.max_hz / bin_hz).floor() as usize).min(max_bin);
    if min > max {
        return None;
    }
    let bins: Vec<_> = (0..width)
        .map(|x| {
            let first = (p.view.frequency(x as f32 / width as f32) / bin_hz).ceil() as usize;
            let last = (p.view.frequency((x + 1) as f32 / width as f32) / bin_hz).floor() as usize;
            if first <= last {
                (first.clamp(min, max), last.clamp(min, max))
            } else {
                let nearest =
                    (p.view.frequency((x as f32 + 0.5) / width as f32) / bin_hz).round() as usize;
                (nearest.clamp(min, max), nearest.clamp(min, max))
            }
        })
        .collect();
    // f32 linear maxima are only a display accumulator. Readouts use f64 frames.
    // Convert to dB before accumulation so tiny f64 powers never underflow to zero.
    let mut histogram = [0_u32; 6656];
    let mut count = 0_u64;
    let mut peak_power = 0.0_f64;
    let step = (snapshot.frames().len() * (max.saturating_sub(min) + 1))
        .div_ceil(65536)
        .max(1);
    let mut sampled = 0;
    let mut previous = None;
    for (frame_index, frame) in snapshot.frames().enumerate() {
        let info = frame.info;
        let start = info.end - info.config.hop as u64;
        let age_top = anchor as i128 - info.end as i128;
        let age_bottom = anchor as i128 - start as i128;
        let preceding =
            previous.or_else(|| {
                if info.gap.input_frames > 0 {
                    Some(info.start.saturating_sub(info.gap.input_frames))
                } else if info.gap.result_rows > 0 {
                    Some(start.saturating_sub(
                        info.gap.result_rows.saturating_mul(info.config.hop as u64),
                    ))
                } else {
                    None
                }
            });
        if let Some(end) = preceding.filter(|&end| end < start) {
            mark_interval(
                anchor as i128 - start as i128,
                anchor as i128 - end as i128,
                span,
                height,
                |y| missing[y] = true,
            );
        }
        previous = Some(info.end);
        if age_bottom <= 0 || age_top >= span {
            continue;
        }
        let mut levels = Vec::with_capacity(width);
        for &(first, last) in &bins {
            let mut power = 0.0_f64;
            for &value in &frame.power()[first..=last] {
                if !value.is_finite() || value < 0.0 {
                    power = f64::NAN;
                    break;
                }
                power = power.max(value);
            }
            levels.push(crate::spectrum::level_db(power) as f32);
        }
        mark_interval(age_top, age_bottom, span, height, |y| {
            rows[y] = Some(info);
            coverage[y] = Some(
                coverage[y].map_or((start, info.end), |(old_start, old_end)| {
                    (old_start.min(start), old_end.max(info.end))
                }),
            );
            for (out, &value) in db[y * width..(y + 1) * width].iter_mut().zip(&levels) {
                *out = if out.is_nan() || value.is_nan() {
                    f32::NAN
                } else {
                    out.max(value)
                };
            }
        });
        if p.auto && min <= max {
            for &power in &frame.power()[min..=max] {
                if power.is_finite() && power > 0.0 {
                    peak_power = peak_power.max(power);
                }
            }
            for &power in frame.power()[min..=max]
                .iter()
                .skip(frame_index % step)
                .step_by(step)
            {
                if sampled >= 65536 {
                    break;
                }
                sampled += 1;
                if power.is_finite() && power > 0.0 {
                    let value = crate::spectrum::level_db(power) as f32;
                    histogram[(value.floor() + 3328.0).clamp(0.0, 6655.0) as usize] += 1;
                    count += 1;
                }
            }
        }
    }
    if p.auto && count >= 8 {
        let mut cumulative = 0;
        let percentile = histogram
            .iter()
            .position(|&n| {
                cumulative += n as u64;
                cumulative >= count.div_ceil(5)
            })
            .unwrap();
        let max = crate::spectrum::level_db(peak_power) as f32 + 3.0;
        if let Some(target) = ColorRange::new((percentile as f32 - 3331.0).min(max - 12.0), max) {
            *range = Some(if p.live {
                range.map_or(target, |old| ColorRange {
                    min: if (target.min - old.min).abs() < 1.0 {
                        old.min
                    } else {
                        old.min + 0.25 * (target.min - old.min)
                    },
                    max: if target.max > old.max {
                        target.max
                    } else if old.max - target.max < 1.0 {
                        old.max
                    } else {
                        old.max + 0.25 * (target.max - old.max)
                    },
                })
            } else {
                target
            });
        }
    }
    let mut placements = Vec::with_capacity(height * 2);
    let mut versions = vec![0; ROWS];
    for y in 0..height {
        let top = y as f32 / height as f32;
        let bottom = (y + 1) as f32 / height as f32;
        if rows[y].is_some() {
            let (start, end) = coverage[y].unwrap();
            placements.push(Placement {
                slot: Some(y),
                top: top.max((anchor as i128 - end as i128) as f32 / span as f32),
                bottom: bottom.min((anchor as i128 - start as i128) as f32 / span as f32),
            });
            // Same raster values do not need another GPU upload when panning.
            versions[y] = db[y * width..(y + 1) * width]
                .iter()
                .fold(0xcbf29ce484222325_u64, |hash, value| {
                    (hash ^ value.to_bits() as u64).wrapping_mul(0x100000001b3)
                });
        }
        if missing[y] {
            // Preserve both a strong bin and any subpixel gap in a reduced row.
            placements.push(Placement {
                slot: None,
                top,
                bottom: if rows[y].is_some() {
                    top + (bottom - top) * 0.25
                } else {
                    bottom
                },
            });
        }
    }
    static REVISION: AtomicU64 = AtomicU64::new(1);
    let history = History {
        config: Some(latest.config),
        generation: latest.generation,
        len: rows.iter().flatten().count(),
        revision: REVISION.fetch_add(1, Ordering::Relaxed),
        raster: Some(Raster {
            width,
            db,
            rows,
            placements,
            versions,
            latest,
            retained_seconds: snapshot.retained_seconds(),
            _lease: lease,
        }),
        ..History::default()
    };

    Some(Prepared {
        id: request.id,
        snapshot: snapshot.clone(),
        anchor,
        history,
        range: range.unwrap_or_default(),
        processing_ms: 0.0,
    })
}

fn mark_interval(top: i128, bottom: i128, span: i128, height: usize, mut visit: impl FnMut(usize)) {
    if bottom <= 0 || top >= span {
        return;
    }
    let first = (top.max(0) * height as i128 / span) as usize;
    let last = ((bottom.min(span) * height as i128 + span - 1) / span) as usize;
    for y in first..last.min(height) {
        visit(y);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        spectrogram::history,
        spectrum::{FrequencyScale, Precision, Window},
        stft::{Config, Gap},
    };
    use std::time::Duration;

    fn config() -> Config {
        Config {
            sample_rate: 48000,
            channels: 16,
            channel: 15,
            size: 1024,
            hop: 256,
            window: Window::Rectangular,
            remove_dc: false,
            precision: Precision::F64,
        }
    }
    fn snapshot(generation: u64, origin: u64, count: usize) -> Arc<Snapshot> {
        let config = config();
        history::fixture(
            73,
            generation,
            config,
            (0..count).map(|i| {
                let end = origin + 1024 + i as u64 * 256;
                let mut power = vec![1e-10; 513];
                // A single old transient must survive reduction beyond 512 frames.
                if i == 1 {
                    power[32] = 0.25 + f64::EPSILON;
                }
                (
                    RowInfo {
                        generation,
                        config,
                        start: end - 1024,
                        end,
                        gap: Gap::default(),
                    },
                    power,
                )
            }),
        )
    }
    fn parameters() -> Parameters {
        Parameters {
            anchor: None,
            seconds: 10.0,
            view: View::full(48000, FrequencyScale::Linear, -120.0),
            columns: 32,
            rows: 8,
            auto: true,
            live: false,
        }
    }
    fn request(snapshot: Arc<Snapshot>, parameters: Parameters) -> Request {
        Request {
            id: 19,
            snapshot,
            parameters,
        }
    }
    fn wait(mut condition: impl FnMut() -> bool) {
        let deadline = Instant::now() + Duration::from_secs(10);
        while !condition() {
            assert!(Instant::now() < deadline, "display worker timed out");
            thread::sleep(Duration::from_millis(1));
        }
    }

    #[test]
    fn reduction_preserves_old_peaks_and_original_f64_values_after_long_sample_runs() {
        let snapshot = snapshot(3, 1_u64 << 54, 1000);
        let original = snapshot.frames().nth(1).unwrap().clone();
        let mut range = None;
        let prepared = prepare(
            &request(snapshot.clone(), parameters()),
            &Arc::default(),
            &mut range,
        )
        .unwrap();
        let raster = prepared.history.raster.as_ref().unwrap();
        let peak = raster.db.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        assert!((peak - (-6.0206)).abs() < 1e-5);
        assert_eq!(
            original.power()[32].to_bits(),
            (0.25 + f64::EPSILON).to_bits()
        );
        assert!(
            prepared.history.at_sample(original.info.end - 1).is_none(),
            "raster must never provide numerical bins"
        );
        assert!(Arc::ptr_eq(
            prepared.snapshot.at_sample(original.info.end - 1).unwrap(),
            &original
        ));
        assert_eq!(prepared.anchor, snapshot.latest().unwrap().info.end);
        assert_eq!(range.unwrap().max, peak + 3.0);
        assert!(raster.placements.iter().any(|p| p.slot.is_some()));
    }

    #[test]
    fn pixel_fallback_excludes_dc_on_log_and_bins_outside_the_visible_range() {
        for (scale, min_hz, max_hz, excluded_bin) in [
            (FrequencyScale::Log, 20.0, 24000.0, 0),
            (FrequencyScale::Linear, 100.0, 200.0, 2),
        ] {
            let config = config();
            let mut power = vec![0.25; 513];
            power[excluded_bin] = 1e6;
            let source = history::fixture(
                73,
                6,
                config,
                [(
                    RowInfo {
                        generation: 6,
                        config,
                        start: 0,
                        end: 1024,
                        gap: Gap::default(),
                    },
                    power,
                )],
            );
            let mut p = parameters();
            p.view = View {
                scale,
                min_hz,
                max_hz,
                ..p.view
            };
            p.columns = MAX_COLUMNS;
            let prepared = prepare(&request(source, p), &Arc::default(), &mut None).unwrap();
            let peak = prepared
                .history
                .raster
                .as_ref()
                .unwrap()
                .db
                .iter()
                .copied()
                .fold(f32::NEG_INFINITY, f32::max);
            assert!(
                (peak + 6.0206).abs() < 1e-5,
                "{scale:?} leaked excluded bin: {peak}"
            );
        }
    }

    #[test]
    fn partial_raster_rows_do_not_paint_unacquired_history() {
        let source = snapshot(7, 1_u64 << 54, 1);
        let mut p = parameters();
        p.seconds = 60.0;
        let prepared = prepare(&request(source, p), &Arc::default(), &mut None).unwrap();
        let placements = &prepared.history.raster.as_ref().unwrap().placements;
        assert_eq!(placements.len(), 1);
        assert_eq!(placements[0].top, 0.0);
        let actual = config().hop as f32 / config().sample_rate as f32 / 60.0;
        assert!((placements[0].bottom - actual).abs() < 1e-9);
    }

    #[test]
    fn held_anchor_excludes_newer_rows_and_keeps_gaps_invalidity_and_blank_distinct() {
        let config = config();
        let origin = 1_u64 << 54;
        let snapshot = history::fixture(
            73,
            4,
            config,
            [
                (1024, 0.0, Gap::default()),
                (1280, 0.25, Gap::default()),
                (
                    2304,
                    f64::NAN,
                    Gap {
                        result_rows: 3,
                        ..Gap::default()
                    },
                ),
                (2560, 1.0, Gap::default()),
            ]
            .map(|(offset, power, gap)| {
                (
                    RowInfo {
                        generation: 4,
                        config,
                        start: origin + offset - 1024,
                        end: origin + offset,
                        gap,
                    },
                    vec![power; 513],
                )
            }),
        );
        let mut parameters = parameters();
        parameters.anchor = Some(origin + 2304);
        parameters.seconds = 4096.0 / 48000.0;
        parameters.rows = 16;
        let prepared = prepare(
            &request(snapshot.clone(), parameters),
            &Arc::default(),
            &mut None,
        )
        .unwrap();
        let raster = prepared.history.raster.as_ref().unwrap();
        assert!(raster.db.iter().any(|p| p.is_nan()));
        assert!(raster.db.contains(&f32::NEG_INFINITY));
        assert!(
            !raster.db.contains(&0.0),
            "newer frame must be outside the held viewport"
        );
        assert!(raster.placements.iter().any(|p| p.slot.is_none()));
        assert!(raster.rows.iter().any(Option::is_none));
        assert!(snapshot.at_sample(origin + 1500).is_none());
        assert!(!snapshot.at_sample(origin + 2303).unwrap().valid());
        assert_eq!(snapshot.at_sample(origin + 1023).unwrap().power()[0], 0.0);
    }

    #[test]
    fn all_inflight_cache_leases_are_bounded_and_released_on_replacement() {
        let snapshot = snapshot(5, 0, 8);
        let budget = Arc::new(Budget::default());
        let mut retained = Vec::new();
        while let Some(prepared) =
            prepare(&request(snapshot.clone(), parameters()), &budget, &mut None)
        {
            retained.push(prepared);
        }
        assert!(!retained.is_empty());
        assert!(budget.peak.load(Ordering::Relaxed) <= CACHE_BYTES);
        retained.pop();
        assert!(prepare(&request(snapshot.clone(), parameters()), &budget, &mut None).is_some());
        drop(retained);
        assert_eq!(budget.used.load(Ordering::Relaxed), 0);
    }

    #[test]
    fn requests_coalesce_and_old_views_and_generations_cannot_be_applied() {
        let mut worker = Worker::default();
        let original = snapshot(1, 0, 1000);
        let mut p = parameters();
        for i in 0..64 {
            p.anchor = Some(1024 + i * 256);
            worker.submit(original.clone(), p);
        }
        let mut prepared = None;
        wait(|| {
            prepared = worker.take();
            prepared.is_some()
        });
        let held = prepared.take().unwrap();
        assert_eq!(held.anchor, p.anchor.unwrap());
        assert_eq!(held.id, worker.current_id());
        let data = held.history.raster.as_ref().unwrap().db.clone();
        // Holding the image and original spectrum does not block new generation work.
        worker.clear();
        worker.submit(snapshot(2, 0, 2000), parameters());
        wait(|| {
            prepared = worker.take();
            prepared.is_some()
        });
        assert_eq!(prepared.unwrap().snapshot.generation, 2);
        assert_eq!(held.snapshot.generation, 1);
        assert_eq!(held.history.raster.as_ref().unwrap().db, data);
        assert!(worker.peak_cache_bytes() <= CACHE_BYTES);
    }
}
