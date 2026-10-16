//! One isolated process measures allocation payload for the complete CPU path.
//! Do not split this into concurrent tests: the allocator counts every thread.
use measurelab::{
    spectrogram::{
        ROWS,
        history::{Collector, FRAME_BYTES, HISTORY_BYTES, Snapshot},
        viewport::{CACHE_BYTES, MAX_COLUMNS, Parameters, Prepared, Worker as ViewWorker},
    },
    spectrum::{FrequencyScale, Precision, View, Window},
    stft::{Config, Worker},
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

const CPU_BYTES: usize = 224 * 1024 * 1024;
static LIVE: AtomicUsize = AtomicUsize::new(0);
static PEAK: AtomicUsize = AtomicUsize::new(0);
struct CountingAllocator;

fn allocated(bytes: usize) {
    let live = LIVE.fetch_add(bytes, Ordering::SeqCst) + bytes;
    PEAK.fetch_max(live, Ordering::SeqCst);
}

// Forward the unchanged layouts/pointers to System. Atomics neither allocate
// nor lock, so these hooks also cover FFT/collector/viewport worker threads.
unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let pointer = unsafe { System.alloc(layout) };
        if !pointer.is_null() {
            allocated(layout.size());
        }
        pointer
    }
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        let pointer = unsafe { System.alloc_zeroed(layout) };
        if !pointer.is_null() {
            allocated(layout.size());
        }
        pointer
    }
    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        unsafe { System.dealloc(pointer, layout) };
        LIVE.fetch_sub(layout.size(), Ordering::SeqCst);
    }
    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, size: usize) -> *mut u8 {
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
    let wave: [f64; 256] = std::array::from_fn(|n| 0.5 * (TAU * n as f64 / 256.0).cos());
    while *sequence < target {
        // At most half the input queue; await actual worker consumption. This
        // is accelerated finite input, not a real-time throughput assertion.
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
    for (index, (size, sample_rate, channels, precision)) in [
        (32768, 768000, 16, Precision::F64),
        (1024, 48000, 1, Precision::F32),
        (32768, 768000, 16, Precision::F32),
    ]
    .into_iter()
    .enumerate()
    {
        let config = Config {
            sample_rate,
            size,
            channels,
            channel: channels - 1,
            hop: size / 4,
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
        assert_eq!(snapshot.capacity_limited, sample_rate == 768000);
        assert!(snapshot.retired > 0);
        assert!(snapshot.storage_bytes() <= HISTORY_BYTES);
        assert!(snapshot.retained_seconds() <= 120.0);
        assert!(snapshot.storage_bytes() > 80 * 1024 * 1024);
        if !snapshot.capacity_limited {
            assert_eq!(snapshot.retained_seconds(), 120.0);
        }
        let next_image = prepare(&mut view, snapshot.clone(), None);
        drop(image.replace(next_image));
        let held = snapshot;
        let selected = held.latest().unwrap().clone();
        let selected_power = selected.power()[size / 256];
        assert!((selected_power - 0.25).abs() < 1e-6);
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
        assert_eq!(
            selected.power()[size / 256].to_bits(),
            selected_power.to_bits()
        );
        assert_eq!(held.latest().unwrap().info.end, fixed_end);
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
        "STFT CPU allocation payload peak: {:.3} MiB / 224 MiB; after shutdown: {remaining} bytes",
        (PEAK.load(Ordering::SeqCst) - baseline) as f64 / 1048576.0
    );
}
