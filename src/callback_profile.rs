//! Bounded QA telemetry for the application's PCM callbacks. Host elapsed
//! time includes preemption; it is not thread CPU time, ADC/DAC latency or the
//! backend's callback wrapper. No allocation, locking or logging when recording.
use std::{
    sync::atomic::{AtomicU64, Ordering},
    time::Duration,
};

const BINS: usize = 1000;
const TIME_STEP_NS: u64 = 10_000;
const BUDGET_STEP_PPM: u64 = 1000;

#[derive(Debug)]
struct Histogram {
    bins: [AtomicU64; BINS],
    maximum: AtomicU64,
}
impl Default for Histogram {
    fn default() -> Self {
        Self {
            bins: std::array::from_fn(|_| AtomicU64::new(0)),
            maximum: AtomicU64::new(0),
        }
    }
}
impl Histogram {
    fn record(&self, value: u64, step: u64) {
        self.maximum.fetch_max(value, Ordering::Relaxed);
        self.bins[(value / step).min(BINS as u64 - 1) as usize].fetch_add(1, Ordering::Relaxed);
    }
    fn p95_upper(&self, step: u64) -> Option<u64> {
        // Read each bucket once. A live report is approximate; an audit after
        // stream release sees the complete distribution for that stream.
        let bins = self.bins.each_ref().map(|b| b.load(Ordering::Relaxed));
        let count: u64 = bins.iter().sum();
        if count == 0 {
            return None;
        }
        let target = (count * 95).div_ceil(100);
        let mut sum = 0;
        for (i, n) in bins.into_iter().enumerate() {
            sum += n;
            if sum >= target {
                return Some(if i == BINS - 1 {
                    self.maximum.load(Ordering::Relaxed)
                } else {
                    (i as u64 + 1) * step
                });
            }
        }
        unreachable!()
    }
}

#[derive(Debug, Default)]
pub struct Metrics {
    callbacks: AtomicU64,
    frames: AtomicU64,
    min_frames: AtomicU64,
    max_frames: AtomicU64,
    processing_ns: AtomicU64,
    time: Histogram,
    budget: Histogram,
    over_budget: AtomicU64,
    notifications: AtomicU64,
    xruns: AtomicU64,
}

#[derive(Debug, serde::Serialize)]
pub struct Report {
    pub callbacks: u64,
    pub frames: u64,
    pub min_nonempty_frames: Option<u64>,
    pub max_frames: u64,
    pub processing_ns: u64,
    pub processing_p95_upper_ns: Option<u64>,
    pub processing_max_ns: u64,
    /// Ratio is computed for each nonempty callback using its actual frame
    /// count and nominal Fs; it is never a ratio of separate p95 statistics.
    pub budget_fraction_p95_upper: Option<f64>,
    pub budget_fraction_max: Option<f64>,
    pub over_budget_callbacks: u64,
    pub notifications: u64,
    pub xruns: u64,
}
impl Metrics {
    /// Completed application callback frames, readable without scanning timing
    /// histograms. The terminal notification/state audit determines validity.
    pub fn frames(&self) -> u64 {
        self.frames.load(Ordering::Relaxed)
    }

    pub fn record(&self, elapsed: Duration, frames: usize, rate: u32) {
        let ns = elapsed.as_nanos().min(u64::MAX as u128) as u64;
        self.time.record(ns, TIME_STEP_NS);
        self.processing_ns.fetch_add(ns, Ordering::Relaxed);
        self.callbacks.fetch_add(1, Ordering::Relaxed);
        self.frames.fetch_add(frames as u64, Ordering::Relaxed);
        self.max_frames.fetch_max(frames as u64, Ordering::Relaxed);
        if frames > 0 && rate > 0 {
            // One data callback writer; zero denotes no nonempty block yet.
            let min = self.min_frames.load(Ordering::Relaxed);
            self.min_frames.store(
                if min == 0 {
                    frames as u64
                } else {
                    min.min(frames as u64)
                },
                Ordering::Relaxed,
            );
            let scaled = ns as u128 * rate as u128;
            let denominator = frames as u128 * 1000;
            let ppm = scaled.div_ceil(denominator).min(u64::MAX as u128) as u64;
            self.budget.record(ppm, BUDGET_STEP_PPM);
            if scaled > frames as u128 * 1_000_000_000 {
                self.over_budget.fetch_add(1, Ordering::Relaxed);
            }
        }
    }

    pub fn notification(&self, error: &cpal::Error) {
        self.notifications.fetch_add(1, Ordering::Relaxed);
        if error.kind() == cpal::ErrorKind::Xrun {
            self.xruns.fetch_add(1, Ordering::Relaxed);
        }
    }

    pub fn report(&self) -> Report {
        let budget_p95 = self.budget.p95_upper(BUDGET_STEP_PPM);
        Report {
            callbacks: self.callbacks.load(Ordering::Relaxed),
            frames: self.frames.load(Ordering::Relaxed),
            min_nonempty_frames: match self.min_frames.load(Ordering::Relaxed) {
                0 => None,
                n => Some(n),
            },
            max_frames: self.max_frames.load(Ordering::Relaxed),
            processing_ns: self.processing_ns.load(Ordering::Relaxed),
            processing_p95_upper_ns: self.time.p95_upper(TIME_STEP_NS),
            processing_max_ns: self.time.maximum.load(Ordering::Relaxed),
            budget_fraction_p95_upper: budget_p95.map(|n| n as f64 / 1e6),
            budget_fraction_max: budget_p95
                .map(|_| self.budget.maximum.load(Ordering::Relaxed) as f64 / 1e6),
            over_budget_callbacks: self.over_budget.load(Ordering::Relaxed),
            notifications: self.notifications.load(Ordering::Relaxed),
            xruns: self.xruns.load(Ordering::Relaxed),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn variable_blocks_use_each_callbacks_own_budget_and_keep_the_tail() {
        let metrics = Metrics::default();
        for _ in 0..50 {
            metrics.record(Duration::from_micros(20), 480, 48000);
        }
        // Same processing time, much shorter block: 96% of its budget.
        for _ in 0..49 {
            metrics.record(Duration::from_micros(20), 1, 48000);
        }
        metrics.record(Duration::from_millis(12), 480, 48000);
        let report = metrics.report();
        assert_eq!(report.callbacks, 100);
        assert_eq!(report.frames, 51 * 480 + 49);
        assert_eq!(report.min_nonempty_frames, Some(1));
        assert_eq!(report.max_frames, 480);
        assert_eq!(report.processing_p95_upper_ns, Some(30_000));
        assert_eq!(report.processing_max_ns, 12_000_000);
        assert_eq!(report.budget_fraction_p95_upper, Some(0.961));
        assert_eq!(report.budget_fraction_max, Some(1.2));
        assert_eq!(report.over_budget_callbacks, 1);
        // Overflow p95 must retain the observed maximum, never the last bin edge.
        for _ in 0..100 {
            metrics.record(Duration::from_millis(15), 480, 48000);
        }
        let report = metrics.report();
        assert_eq!(report.processing_p95_upper_ns, Some(15_000_000));
        assert_eq!(report.budget_fraction_p95_upper, Some(1.5));
    }

    #[test]
    fn no_samples_have_no_budget_and_notifications_survive_data_recording() {
        let metrics = Metrics::default();
        assert_eq!(metrics.report().processing_p95_upper_ns, None);
        metrics.record(Duration::ZERO, 0, 48000);
        metrics.notification(&cpal::ErrorKind::Xrun.into());
        metrics.notification(&cpal::ErrorKind::DeviceNotAvailable.into());
        metrics.record(Duration::from_micros(5), 0, 48000);
        let report = metrics.report();
        assert_eq!(report.callbacks, 2);
        assert_eq!(report.min_nonempty_frames, None);
        assert_eq!(report.budget_fraction_p95_upper, None);
        assert_eq!(report.budget_fraction_max, None);
        assert_eq!(report.over_budget_callbacks, 0);
        assert_eq!(report.notifications, 2);
        assert_eq!(report.xruns, 1);
    }
}
