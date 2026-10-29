//! One isolated process measures allocation payload for the complete CPU path.
//! Do not split this into concurrent tests: the allocator counts every thread.
use measurelab::{
    spectrogram::{
        ROWS,
        history::{Collector, FRAME_BYTES, HISTORY_BYTES, Snapshot},
        viewport::{CACHE_BYTES, MAX_COLUMNS, Parameters, Prepared, Worker as ViewWorker},
    },
    spectrum::{FrequencyScale, Precision, View, Window},
    stft::{Config, Overlap, Worker},
};
use std::{
    alloc::{GlobalAlloc, Layout, System},
    f64::consts::TAU,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    thread,
    time::{Duration, Instant},
};

// 192 MiB for retained frames plus 48 MiB for bounded working storage,
// including the ~2 MiB input queue and ~8 MiB small-FFT result tier.
const CPU_BYTES: usize = 240 * 1024 * 1024;
static LIVE: AtomicUsize = AtomicUsize::new(0);
static PEAK: AtomicUsize = AtomicUsize::new(0);
struct CountingAllocator;

fn allocated(bytes: usize) {
    // Match the atomic counter's wrapping arithmetic; hooks must not unwind.
    let live = LIVE.fetch_add(bytes, Ordering::SeqCst).wrapping_add(bytes);
    PEAK.fetch_max(live, Ordering::SeqCst);
}

// SAFETY: every allocation and deallocation delegates to System with unchanged
// arguments and returns its pointer unchanged. Accounting uses only atomics,
// which neither allocate nor unwind and cover all worker threads.
unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        // SAFETY: the caller supplies a valid, nonzero allocation layout.
        let pointer = unsafe { System.alloc(layout) };
        if !pointer.is_null() {
            allocated(layout.size());
        }
        pointer
    }
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        // SAFETY: the caller supplies a valid, nonzero allocation layout.
        let pointer = unsafe { System.alloc_zeroed(layout) };
        if !pointer.is_null() {
            allocated(layout.size());
        }
        pointer
    }
    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        // SAFETY: the caller supplies a live pointer from this allocator and
        // its original layout; all allocations above delegate to System.
        unsafe { System.dealloc(pointer, layout) };
        LIVE.fetch_sub(layout.size(), Ordering::SeqCst);
    }
    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        // SAFETY: the caller supplies a live System allocation, its original
        // layout, and a nonzero size satisfying GlobalAlloc::realloc's bounds.
        let replacement = unsafe { System.realloc(pointer, layout, size) };
        if !replacement.is_null() {
            // Conservatively include old + new at the replacement boundary.
            allocated(size);
            LIVE.fetch_sub(layout.size(), Ordering::SeqCst);
        }
        replacement
    }
}

#[global_allocator]
static ALLOCATOR: CountingAllocator = CountingAllocator;

fn wait(mut ready: impl FnMut() -> bool) {
    let deadline = Instant::now() + Duration::from_secs(20);
    while !ready() {
        assert!(Instant::now() < deadline, "STFT capacity QA timed out");
        thread::sleep(Duration::from_micros(100));
    }
}

fn parameters(config: Config, anchor: Option<u64>) -> Parameters {
    Parameters {
        quefrency: (config.analysis == measurelab::stft::Analysis::Cepstrogram)
            .then(Default::default),
        manual_range: Default::default(),
        anchor,
        seconds: 60.0,
        view: View::full(config.sample_rate, FrequencyScale::Linear, -120.0),
        columns: MAX_COLUMNS,
        rows: ROWS,
        auto: true,
        live: anchor.is_none(),
    }
}

fn prepare(view: &mut ViewWorker, snapshot: Arc<Snapshot>, anchor: Option<u64>) -> Prepared {
    view.submit(
        snapshot.clone(),
        parameters(snapshot.config.unwrap(), anchor),
    );
    let mut result = None;
    wait(|| {
        result = view.take();
        result.is_some()
    });
    result.unwrap()
}

fn feed(
    worker: &mut Worker,
    collector: &Collector,
    config: Config,
    sequence: &mut u64,
    rows: usize,
    mut display: impl FnMut(Arc<Snapshot>),
) {
    let target = if *sequence == 0 {
        config.size as u64 + (rows - 1) as u64 * config.hop as u64
    } else {
        *sequence + rows as u64 * config.hop as u64
    };
    let before = collector.metrics.collected.load(Ordering::Acquire);
    let mut publication_checkpoint = before;
    let row_bytes = ((config.size / 2 + 1) * size_of::<f64>()) as u64;
    let wave: [f64; 256] = std::array::from_fn(|n| 0.5 * (TAU * n as f64 / 256.0).cos());
    while *sequence < target {
        // At most half the input queue; await processing and collection so a
        // slower collector cannot exhaust the finite result pool. This is
        // accelerated finite input, not a real-time throughput assertion.
        let end = (*sequence + 8192).min(target);
        let processed = worker.metrics.processed_frames.load(Ordering::Acquire);
        let count = end - *sequence;
        for sample in *sequence..end {
            let mut channels = [0.0; 16];
            channels[config.channel] = wave[sample as usize % wave.len()];
            worker.submit(sample, &channels[..config.channels]);
        }
        worker.flush();
        wait(|| worker.metrics.processed_frames.load(Ordering::Acquire) >= processed + count);
        let produced = worker.metrics.produced.load(Ordering::Acquire);
        wait(|| collector.metrics.collected.load(Ordering::Acquire) == produced);
        // Publication is throttled to 20 ms independently of collection. Pace
        // this accelerated source at about 1 MiB of new rows per publication:
        // otherwise an old published snapshot can pin most of an extra ring
        // alongside Hold + live, far beyond the real input rate.
        if (produced - publication_checkpoint) * row_bytes >= 1024 * 1024 {
            let latest_end = end - (end - config.size as u64) % config.hop as u64;
            wait(|| {
                collector
                    .snapshot()
                    .latest()
                    .is_some_and(|f| f.info.end == latest_end)
            });
            publication_checkpoint = produced;
        }
        *sequence = end;
        display(collector.snapshot());
    }
    wait(|| collector.metrics.collected.load(Ordering::Acquire) == before + rows as u64);
    wait(|| {
        collector
            .snapshot()
            .latest()
            .is_some_and(|f| f.info.end == target)
    });
    assert_eq!(worker.metrics.input_dropped.load(Ordering::Relaxed), 0);
    assert_eq!(worker.metrics.result_dropped.load(Ordering::Relaxed), 0);
    assert_eq!(collector.metrics.storage_dropped.load(Ordering::Relaxed), 0);
}

#[test]
fn full_pipeline_hold_wrap_reconfigure_and_release_fit_cpu_budget() {
    let baseline = LIVE.load(Ordering::SeqCst);
    PEAK.store(baseline, Ordering::SeqCst);
    let mut worker = Worker::new();
    let collector = Collector::new(worker.take_results());
    let mut view = ViewWorker::default();
    let mut image = None;
    for (index, (size, sample_rate, channels, precision, overlap, analysis)) in [
        (
            32768,
            768000,
            16,
            Precision::F64,
            Overlap::Half,
            measurelab::stft::Analysis::Spectrogram,
        ),
        (
            32768,
            768000,
            16,
            Precision::F64,
            Overlap::SevenEighths,
            measurelab::stft::Analysis::Cepstrogram,
        ),
        (
            1024,
            48000,
            1,
            Precision::F32,
            Overlap::ThreeQuarters,
            measurelab::stft::Analysis::Spectrogram,
        ),
        (
            1024,
            48000,
            1,
            Precision::F64,
            Overlap::SevenEighths,
            measurelab::stft::Analysis::Cepstrogram,
        ),
        (
            32768,
            768000,
            16,
            Precision::F32,
            Overlap::SevenEighths,
            measurelab::stft::Analysis::Spectrogram,
        ),
    ]
    .into_iter()
    .enumerate()
    {
        let config = Config {
            analysis,
            log_floor_db: measurelab::cepstrum::DEFAULT_LOG_FLOOR_DB,
            sample_rate,
            size,
            channels,
            channel: channels - 1,
            hop: overlap.hop(size),
            window: Window::Hann,
            remove_dc: false,
            precision,
        };
        let generation = worker.configure(config).unwrap();
        // Retain the previous image/Hold across configuration exchange to
        // include old/new generations and FFT plans in the measured peak.
        collector.configure(index as u64 + 1, generation, config);
        let mut sequence = 0;
        let rows = HISTORY_BYTES / ((size / 2 + 1) * 8) + 128;
        feed(&mut worker, &collector, config, &mut sequence, rows, |_| {});
        let snapshot = collector.snapshot();
        let row_bytes = std::mem::size_of::<measurelab::spectrogram::history::Frame>()
            + 2 * std::mem::size_of::<usize>()
            + (size / 2 + 1) * 8
            + std::mem::size_of::<Arc<measurelab::spectrogram::history::Frame>>();
        let full_span_bytes = (120 * sample_rate as usize).div_ceil(config.hop) * row_bytes;
        assert_eq!(
            snapshot.capacity_limited,
            full_span_bytes > HISTORY_BYTES - 2 * 1024 * 1024
        );
        assert!(snapshot.retired > 0);
        assert!(snapshot.storage_bytes() <= HISTORY_BYTES);
        assert!(snapshot.retained_seconds() <= 120.0);
        assert!(
            snapshot.storage_bytes() > 80 * 1024 * 1024,
            "history retention collapsed for {config:?}: {} bytes, {} rows, {} retired, {} allocated frame bytes",
            snapshot.storage_bytes(),
            snapshot.frames().len(),
            snapshot.retired,
            collector.allocated_frame_bytes(),
        );
        if !snapshot.capacity_limited {
            assert_eq!(snapshot.retained_seconds(), 120.0);
        }
        let next_image = prepare(&mut view, snapshot.clone(), None);
        drop(image.replace(next_image));
        let held = snapshot;
        let selected = held.latest().unwrap().clone();
        let spectra = std::array::from_fn::<_, 2, _>(|_| {
            measurelab::spectrum::Result::from_stft(selected.info, selected.values())
        });
        let value = |frame: &measurelab::spectrogram::history::Frame| {
            if analysis == measurelab::stft::Analysis::Cepstrogram {
                frame.coefficient(size / 256).unwrap()
            } else {
                frame.power()[size / 256]
            }
        };
        let selected_power = value(&selected);
        if analysis == measurelab::stft::Analysis::Spectrogram {
            assert!((selected_power - 0.25).abs() < 1e-6);
        } else {
            assert!(spectra.iter().all(Option::is_none));
        }
        let fixed_end = selected.info.end;
        // Leave an image unread while producing a second full ring and flood
        // the single-slot request mailbox with pans, zooms, Auto and widths.
        let mut requests = 0;
        feed(
            &mut worker,
            &collector,
            config,
            &mut sequence,
            rows,
            |latest| {
                for _ in 0..4 {
                    let mut p = parameters(config, Some(fixed_end));
                    p.seconds = [5.0, 10.0, 30.0, 60.0][requests % 4];
                    p.columns = [1, 128, 512, MAX_COLUMNS][requests % 4];
                    p.auto = requests.is_multiple_of(2);
                    view.submit(held.clone(), p);
                    requests += 1;
                }
                assert!(latest.storage_bytes() <= HISTORY_BYTES);
            },
        );
        assert_eq!(value(&selected).to_bits(), selected_power.to_bits());
        assert_eq!(held.latest().unwrap().info.end, fixed_end);
        if let Some(spectrum) = &spectra[0] {
            assert_eq!(spectrum.power(), selected.power());
        }
        assert!(collector.snapshot().at_sample(fixed_end - 1).is_none());
        assert!(collector.snapshot().retired > rows as u64);
        assert!(collector.peak_frame_bytes() <= FRAME_BYTES);
        assert!(view.peak_cache_bytes() <= CACHE_BYTES);
        let peak = PEAK.load(Ordering::SeqCst) - baseline;
        assert!(
            peak <= CPU_BYTES,
            "CPU allocation payload peak {peak} > {CPU_BYTES}"
        );
        drop(selected);
        let live = collector.snapshot();
        let live_image = prepare(&mut view, live.clone(), None);
        assert_eq!(live_image.anchor, live.latest().unwrap().info.end);
        assert_eq!(live_image.snapshot.generation, generation);
        drop(image.replace(live_image));
    }
    drop(image);
    drop(view);
    drop(collector);
    drop(worker);
    let remaining = LIVE.load(Ordering::SeqCst).saturating_sub(baseline);
    assert!(
        remaining < 64 * 1024,
        "STFT allocations retained after shutdown: {remaining}"
    );
    println!(
        "STFT CPU allocation payload peak: {:.3} MiB / {} MiB; after shutdown: {remaining} bytes",
        (PEAK.load(Ordering::SeqCst) - baseline) as f64 / 1048576.0,
        CPU_BYTES / 1048576,
    );
}
