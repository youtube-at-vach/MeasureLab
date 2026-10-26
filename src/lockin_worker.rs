//! Fixed-capacity two-channel transport; frequency fitting cannot stall acquisition.
#![warn(clippy::redundant_clone)]
use crate::{calibration, lockin};
use rtrb::{Consumer, Producer, RingBuffer};
use std::{
    sync::{Arc, Mutex, mpsc},
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};
const CAPACITY: usize = 262144;
#[derive(Clone, Copy)]
struct Frame {
    epoch: u64,
    sequence: u64,
    pair: [f64; 2],
}
#[derive(Clone)]
struct Configuration {
    epoch: u64,
    settings: lockin::Settings,
    rate: u32,
    calibrations: calibration::Set,
    start: u64,
    channels: usize,
}
enum Command {
    Inspect(Configuration, u64, mpsc::SyncSender<lockin::Result>),
}
fn configure(analyzer: &mut lockin::Analyzer, epoch: &mut u64, config: Configuration) {
    if config.epoch > *epoch {
        *epoch = config.epoch;
        *analyzer = lockin::Analyzer::new(config.settings, config.rate);
        analyzer.set_calibrations(config.calibrations);
        analyzer.gap_to(config.start);
        if config.settings.reference_channel >= config.channels
            || config.settings.response_channel >= config.channels
        {
            analyzer.push(config.start, &[]);
        }
    }
}
pub struct Worker {
    input: Producer<Frame>,
    commands: Option<mpsc::SyncSender<Command>>,
    latest: Arc<Mutex<(u64, lockin::Result)>>,
    cached: lockin::Result,
    epoch: u64,
    settings: lockin::Settings,
    desired: Arc<Mutex<Option<Configuration>>>,
    configuration: Configuration,
    pending_configuration: bool,
    handle: Option<JoinHandle<()>>,
}
impl Default for Worker {
    fn default() -> Self {
        let settings = lockin::Settings::default();
        let cached = lockin::Analyzer::new(settings, 48000).result().clone();
        let latest = Arc::new(Mutex::new((0, cached.clone())));
        let shared = latest.clone();
        let desired: Arc<Mutex<Option<Configuration>>> = Arc::default();
        let requested = desired.clone();
        let configuration = Configuration {
            epoch: 0,
            settings,
            rate: 48000,
            calibrations: calibration::Set::default(),
            start: 0,
            channels: 2,
        };
        let (input, mut source) = RingBuffer::new(CAPACITY);
        let (commands, receiver) = mpsc::sync_channel(16);
        let handle = thread::Builder::new()
            .name("measurelab-lockin".into())
            .spawn(move || {
                let mut epoch = 0;
                let mut analyzer = lockin::Analyzer::new(settings, 48000);
                let mut publish = Instant::now();
                let mut worked = false;
                let mut pending = None;
                loop {
                    let requested_config = requested.lock().unwrap().take();
                    if let Some(config) = requested_config {
                        pending = Some(config);
                    }
                    // Only wait when the previous pass could not consume input.
                    // Sleeping once per batch adds an artificial throughput limit
                    // precisely when CPU contention has built up a backlog.
                    let command = if worked || pending.is_some() {
                        receiver.try_recv().map_err(|error| match error {
                            mpsc::TryRecvError::Empty => mpsc::RecvTimeoutError::Timeout,
                            mpsc::TryRecvError::Disconnected => {
                                mpsc::RecvTimeoutError::Disconnected
                            }
                        })
                    } else {
                        receiver.recv_timeout(Duration::from_millis(2))
                    };
                    match command {
                        Ok(Command::Inspect(config, end, reply)) => {
                            let requested_epoch = config.epoch;
                            configure(&mut analyzer, &mut epoch, config);
                            drain(&mut source, CAPACITY, epoch, &mut analyzer);
                            if requested_epoch == epoch {
                                analyzer.gap_to(end);
                                let _ = reply.try_send(analyzer.result().clone());
                            }
                            // Inspect was queued before any newer configuration
                            // published by this producer. Finish all such barriers
                            // before allowing the coalesced setting to overtake it.
                            continue;
                        }
                        Err(mpsc::RecvTimeoutError::Disconnected) => break,
                        Err(mpsc::RecvTimeoutError::Timeout) => {}
                    }
                    if let Some(config) = pending.take() {
                        configure(&mut analyzer, &mut epoch, config);
                    }
                    worked = drain(&mut source, 4096, epoch, &mut analyzer) > 0;
                    if publish.elapsed() >= Duration::from_millis(20)
                        && let Ok(mut latest) = shared.try_lock()
                    {
                        *latest = (epoch, analyzer.result().clone());
                        publish = Instant::now();
                    }
                }
            })
            .expect("Lock-in worker");
        Self {
            input,
            commands: Some(commands),
            latest,
            cached,
            epoch: 0,
            settings,
            desired,
            configuration,
            pending_configuration: false,
            handle: Some(handle),
        }
    }
}
fn drain(
    source: &mut Consumer<Frame>,
    limit: usize,
    epoch: u64,
    analyzer: &mut lockin::Analyzer,
) -> usize {
    let count = source.slots().min(limit);
    if let Ok(chunk) = source.read_chunk(count) {
        let (a, b) = chunk.as_slices();
        let mut consumed = 0;
        for frame in a.iter().chain(b) {
            // A timeout can race Configure on the separate command queue.
            // Keep future frames until their configuration arrives; discarding
            // them would silently lose the beginning of a new measurement.
            if frame.epoch > epoch {
                break;
            }
            if frame.epoch == epoch {
                analyzer.push_pair(frame.sequence, frame.pair);
            }
            consumed += 1;
        }
        chunk.commit(consumed);
        return consumed;
    }
    0
}
impl Worker {
    pub fn configure(
        &mut self,
        settings: lockin::Settings,
        rate: u32,
        set: calibration::Set,
        start: u64,
        channels: usize,
    ) {
        self.epoch += 1;
        self.settings = settings;
        self.configuration = Configuration {
            epoch: self.epoch,
            settings,
            rate,
            calibrations: set,
            start,
            channels,
        };
        self.pending_configuration = true;
        self.cached = lockin::Analyzer::new(settings, rate).result().clone();
        self.flush_configuration();
    }
    fn flush_configuration(&mut self) {
        if self.pending_configuration
            && let Ok(mut desired) = self.desired.try_lock()
        {
            *desired = Some(self.configuration.clone());
            self.pending_configuration = false;
        }
    }
    pub fn submit(&mut self, n: u64, samples: &[f64]) {
        self.flush_configuration();
        if !self.settings.enabled
            || self.settings.reference_channel >= samples.len()
            || self.settings.response_channel >= samples.len()
        {
            return;
        }
        // Overflow is a source-clock gap at the next frame or finite-end barrier.
        let _ = self.input.push(Frame {
            epoch: self.epoch,
            sequence: n,
            pair: [
                samples[self.settings.reference_channel],
                samples[self.settings.response_channel],
            ],
        });
    }
    pub fn latest(&mut self) -> lockin::Result {
        self.flush_configuration();
        if let Ok(result) = self.latest.try_lock()
            && result.0 == self.epoch
        {
            self.cached = result.1.clone();
        }
        self.cached.clone()
    }
    pub fn inspect(&self, end: u64) -> mpsc::Receiver<lockin::Result> {
        let (reply, result) = mpsc::sync_channel(1);
        self.commands
            .as_ref()
            .unwrap()
            .try_send(Command::Inspect(self.configuration.clone(), end, reply))
            .unwrap_or_else(|_| panic!("too many Lock-in barriers"));
        result
    }
}
impl Drop for Worker {
    fn drop(&mut self) {
        self.commands.take();
        if let Some(h) = self.handle.take() {
            let _ = h.join();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f64::consts::TAU;
    fn settings() -> lockin::Settings {
        lockin::Settings {
            enabled: true,
            integration_samples: 1024,
            time_constant_seconds: 0.001,
            ..Default::default()
        }
    }
    #[test]
    fn rapid_configuration_during_blocked_publication_keeps_the_latest_epoch() {
        let mut worker = Worker::default();
        let shared = worker.latest.clone();
        let publication = shared.lock().unwrap();
        let desired = worker.desired.clone();
        let configuration = desired.lock().unwrap();
        for _ in 0..200 {
            worker.configure(settings(), 48000, calibration::Set::default(), 0, 2);
        }
        drop(configuration);
        drop(publication);
        for n in 0..2048 {
            let x = (TAU * 1000.0 * n as f64 / 48000.0).sin();
            worker.submit(n, &[0.125 * x, -0.0625 * x]);
        }
        let result = worker
            .inspect(2048)
            .recv_timeout(Duration::from_secs(10))
            .unwrap();
        assert_eq!(result.state, lockin::State::Valid);
        assert_eq!(result.processed_windows, 2);
        assert_eq!(result.missing_samples, 0);
        assert!((result.gain.unwrap() - 0.5).abs() < 1e-10);
    }
    #[test]
    fn coalesced_settings_do_not_overtake_queued_stop_barriers() {
        let mut worker = Worker::default();
        let desired = worker.desired.clone();
        let mut mailbox = desired.lock().unwrap();
        thread::sleep(Duration::from_millis(40));
        let first = settings();
        worker.configure(first, 48000, calibration::Set::default(), 0, 2);
        let replies = [worker.inspect(0), worker.inspect(0)];
        worker.configure(
            lockin::Settings {
                frequency_hz: 2000.0,
                ..first
            },
            48000,
            calibration::Set::default(),
            0,
            2,
        );
        *mailbox = Some(worker.configuration.clone());
        worker.pending_configuration = false;
        drop(mailbox);
        for reply in replies {
            assert_eq!(
                reply
                    .recv_timeout(Duration::from_secs(10))
                    .unwrap()
                    .settings,
                first
            );
        }
        assert_eq!(
            worker
                .inspect(0)
                .recv_timeout(Duration::from_secs(10))
                .unwrap()
                .settings
                .frequency_hz,
            2000.0
        );
    }
    #[test]
    fn result_reader_cannot_block_analysis_or_the_finite_stop_barrier() {
        let mut worker = Worker::default();
        worker.configure(settings(), 48000, calibration::Set::default(), 0, 2);
        let shared = worker.latest.clone();
        let _reader = shared.lock().unwrap();
        for n in 0..2048 {
            let x = (TAU * 1000.0 * n as f64 / 48000.0).sin();
            worker.submit(n, &[0.125 * x, -0.0625 * x]);
        }
        thread::sleep(Duration::from_millis(40));
        let result = worker
            .inspect(2048)
            .recv_timeout(Duration::from_secs(10))
            .unwrap();
        assert_eq!(result.processed_windows, 2);
        assert_eq!(result.missing_samples, 0);
        assert_eq!(result.state, lockin::State::Valid);
    }
    #[test]
    fn overflow_and_finite_end_barrier_invalidate_the_previous_value() {
        let mut a = lockin::Analyzer::new(settings(), 48000);
        for n in 0..1024 {
            let x = (TAU * 1000.0 * n as f64 / 48000.0).sin();
            a.push_pair(n, [0.125 * x, 0.0625 * x]);
        }
        assert_eq!(a.result().state, lockin::State::Valid);
        let (mut producer, mut consumer) = RingBuffer::new(4);
        for n in 1024..1044 {
            let _ = producer.push(Frame {
                epoch: 1,
                sequence: n,
                pair: [0.1, 0.2],
            });
        }
        drain(&mut consumer, 4, 1, &mut a);
        a.gap_to(1044);
        assert_eq!(a.result().state, lockin::State::Missing);
        assert_eq!(a.result().missing_samples, 16);
        assert!(a.result().x.is_none());
        assert_eq!(a.result().processed_windows, 0);
    }
    #[test]
    fn frames_arriving_after_command_timeout_wait_for_their_configuration() {
        let (mut producer, mut consumer) = RingBuffer::new(8);
        producer
            .push(Frame {
                epoch: 0,
                sequence: 99,
                pair: [0.0; 2],
            })
            .ok()
            .unwrap();
        for n in 0..4 {
            producer
                .push(Frame {
                    epoch: 1,
                    sequence: n,
                    pair: [0.1, 0.2],
                })
                .ok()
                .unwrap();
        }
        let mut a = lockin::Analyzer::new(settings(), 48000);
        drain(&mut consumer, 8, 0, &mut a);
        assert_eq!(consumer.slots(), 4);
        let mut next = lockin::Analyzer::new(settings(), 48000);
        next.gap_to(0);
        drain(&mut consumer, 8, 1, &mut next);
        next.gap_to(4);
        assert_eq!(next.result().missing_samples, 0);
        assert_eq!(consumer.slots(), 0);
    }
    #[test]
    fn new_epoch_excludes_queued_old_frames_and_barrier_is_repeatable() {
        let mut worker = Worker::default();
        worker.configure(settings(), 48000, calibration::Set::default(), 0, 2);
        for n in 0..5000 {
            worker.submit(n, &[0.0, 0.0]);
        }
        let start = (1u64 << 54) + 7;
        worker.configure(settings(), 48000, calibration::Set::default(), start, 2);
        for i in 0..2048 {
            let x = (TAU * 1000.0 * i as f64 / 48000.0).sin();
            worker.submit(start + i, &[0.125 * x, -0.0625 * x]);
        }
        let r = worker
            .inspect(start + 2048)
            .recv_timeout(Duration::from_secs(10))
            .unwrap();
        assert_eq!(r.state, lockin::State::Valid);
        assert_eq!(r.sample_range, start..start + 2048);
        assert_eq!(r.missing_samples, 0);
        assert_eq!(r.processed_windows, 2);
        assert!((r.amplitude_peak.unwrap() - 0.0625).abs() < 1e-10);
        assert!(r.y.unwrap().abs() < 1e-10);
        assert_eq!(
            worker
                .inspect(start + 2048)
                .recv_timeout(Duration::from_secs(10))
                .unwrap(),
            r
        );
        worker.configure(settings(), 48000, calibration::Set::default(), 0, 1);
        assert_eq!(
            worker
                .inspect(10)
                .recv_timeout(Duration::from_secs(10))
                .unwrap()
                .state,
            lockin::State::Unavailable
        );
    }
}
