//! Fixed-capacity two-channel transport; FFT comparison cannot stall acquisition.
#![warn(clippy::redundant_clone)]
use crate::{calibration, comparison};
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
    generation: u64,
    settings: comparison::Settings,
    rate: u32,
    calibrations: calibration::Set,
    start: u64,
    channels: usize,
}
enum Command {
    Inspect(
        Configuration,
        u64,
        mpsc::SyncSender<Arc<comparison::Result>>,
    ),
}
fn configure(analyzer: &mut comparison::Analyzer, epoch: &mut u64, config: Configuration) {
    if config.epoch > *epoch {
        *epoch = config.epoch;
        *analyzer = comparison::Analyzer::new(
            config.settings,
            config.rate,
            config.generation,
            config.epoch,
            config.channels,
            config.calibrations,
        );
        analyzer.gap_to(config.start);
    }
}
pub struct Worker {
    input: Producer<Frame>,
    commands: Option<mpsc::SyncSender<Command>>,
    latest: Arc<Mutex<(u64, Arc<comparison::Result>)>>,
    cached: Arc<comparison::Result>,
    epoch: u64,
    settings: comparison::Settings,
    desired: Arc<Mutex<Option<Configuration>>>,
    configuration: Configuration,
    pending_configuration: bool,
    handle: Option<JoinHandle<()>>,
}
impl Default for Worker {
    fn default() -> Self {
        let settings = comparison::Settings::default();
        let cached = Arc::new(comparison::Result::empty(settings, 48000, 0, 0, 2));
        let latest = Arc::new(Mutex::new((0, cached.clone())));
        let shared = latest.clone();
        let (input, mut source) = RingBuffer::new(CAPACITY);
        let desired: Arc<Mutex<Option<Configuration>>> = Arc::default();
        let requested = desired.clone();
        let configuration = Configuration {
            epoch: 0,
            generation: 0,
            settings,
            rate: 48000,
            calibrations: calibration::Set::default(),
            start: 0,
            channels: 2,
        };
        let (commands, receiver) = mpsc::sync_channel(4);
        let handle = thread::Builder::new()
            .name("measurelab-comparison".into())
            .spawn(move || {
                let mut epoch = 0;
                let mut analyzer = comparison::Analyzer::new(
                    settings,
                    48000,
                    0,
                    0,
                    2,
                    calibration::Set::default(),
                );
                let mut publish = Instant::now();
                let mut worked = false;
                let mut pending = None;
                loop {
                    let requested_config = requested.lock().unwrap().take();
                    if let Some(config) = requested_config {
                        pending = Some(config);
                    }
                    // Drain a backlog without an extra timer wait per batch;
                    // commands still take priority at every bounded batch.
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
                                let _ = reply.try_send(Arc::new(analyzer.result().clone()));
                            }
                            // Preserve FIFO barriers before applying a newer
                            // coalesced configuration from the same producer.
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
                        *latest = (epoch, Arc::new(analyzer.result().clone()));
                        publish = Instant::now();
                    }
                }
            })
            .expect("Comparison worker");
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
    analyzer: &mut comparison::Analyzer,
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
        generation: u64,
        settings: comparison::Settings,
        rate: u32,
        set: calibration::Set,
        start: u64,
        channels: usize,
    ) {
        self.epoch += 1;
        self.settings = settings;
        self.configuration = Configuration {
            epoch: self.epoch,
            generation,
            settings,
            rate,
            calibrations: set,
            start,
            channels,
        };
        self.pending_configuration = true;
        self.cached = Arc::new(comparison::Result::empty(
            settings, rate, generation, self.epoch, channels,
        ));
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
    pub fn latest(&mut self) -> Arc<comparison::Result> {
        self.flush_configuration();
        if let Ok(result) = self.latest.try_lock()
            && result.0 == self.epoch
        {
            self.cached = result.1.clone();
        }
        self.cached.clone()
    }
    pub fn inspect(&self, end: u64) -> mpsc::Receiver<Arc<comparison::Result>> {
        let (reply, result) = mpsc::sync_channel(1);
        self.commands
            .as_ref()
            .unwrap()
            .try_send(Command::Inspect(self.configuration.clone(), end, reply))
            .unwrap_or_else(|_| panic!("too many Comparison barriers"));
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
    fn settings() -> comparison::Settings {
        comparison::Settings {
            enabled: true,
            size: 1024,
            averages: 2,
            window: crate::spectrum::Window::Rectangular,
            ..Default::default()
        }
    }
    #[test]
    fn coalesced_settings_do_not_overtake_queued_stop_barriers() {
        let mut worker = Worker::default();
        let desired = worker.desired.clone();
        let mut mailbox = desired.lock().unwrap();
        thread::sleep(Duration::from_millis(40));
        worker.configure(1, settings(), 48000, calibration::Set::default(), 0, 2);
        let replies = [worker.inspect(0), worker.inspect(0)];
        worker.configure(2, settings(), 48000, calibration::Set::default(), 0, 2);
        *mailbox = Some(worker.configuration.clone());
        worker.pending_configuration = false;
        drop(mailbox);
        for reply in replies {
            assert_eq!(
                reply
                    .recv_timeout(Duration::from_secs(10))
                    .unwrap()
                    .generation,
                1
            );
        }
        assert_eq!(
            worker
                .inspect(0)
                .recv_timeout(Duration::from_secs(10))
                .unwrap()
                .generation,
            2
        );
    }
    #[test]
    fn result_reader_cannot_block_analysis_or_the_finite_stop_barrier() {
        let mut worker = Worker::default();
        worker.configure(1, settings(), 48000, calibration::Set::default(), 0, 2);
        let shared = worker.latest.clone();
        let _reader = shared.lock().unwrap();
        for n in 0..2048 {
            let x = (std::f64::consts::TAU * n as f64 / 64.0).sin();
            worker.submit(n, &[0.125 * x, -0.0625 * x]);
        }
        thread::sleep(Duration::from_millis(40));
        let result = worker
            .inspect(2048)
            .recv_timeout(Duration::from_secs(10))
            .unwrap();
        assert_eq!(result.processed_windows, 2);
        assert_eq!(result.missing_samples, 0);
        assert_eq!(result.state, comparison::State::Valid);
    }
    #[test]
    fn rapid_changes_coalesce_without_waiting_or_mixing_epochs_and_stop_drains_finite_end() {
        let mut w = Worker::default();
        for generation in 1..=200 {
            w.configure(
                generation,
                settings(),
                48000,
                calibration::Set::default(),
                0,
                2,
            );
            w.submit(0, &[1.0, 2.0]);
        }
        let start = (1u64 << 54) + 3;
        w.configure(
            201,
            settings(),
            48000,
            calibration::Set::default(),
            start,
            2,
        );
        for n in 0..2048 {
            let p = std::f64::consts::TAU * 16.0 * n as f64 / 1024.0;
            w.submit(start + n, &[0.1 * p.sin(), -0.05 * p.sin()]);
        }
        let r = w
            .inspect(start + 2048)
            .recv_timeout(Duration::from_secs(10))
            .unwrap();
        assert_eq!(r.generation, 201);
        assert_eq!(r.sample_range, start..start + 2048);
        assert_eq!(r.missing_samples, 0);
        assert_eq!(r.processed_windows, 2);
        assert!((r.bins[16].gain.unwrap() - 0.5).abs() < 1e-10);
        assert_eq!(
            w.inspect(start + 2048)
                .recv_timeout(Duration::from_secs(10))
                .unwrap(),
            r
        );
    }
    #[test]
    fn saturated_transport_and_missing_tail_invalidate_previous_batch() {
        let s = settings();
        let mut a = comparison::Analyzer::new(s, 48000, 1, 1, 2, calibration::Set::default());
        for n in 0..2048 {
            a.push_pair(
                n,
                [0.1 * (std::f64::consts::TAU * n as f64 / 64.0).sin(); 2],
            );
        }
        assert_eq!(a.result().state, comparison::State::Valid);
        let (mut p, mut c) = RingBuffer::new(4);
        for n in 2048..2060 {
            let _ = p.push(Frame {
                epoch: 1,
                sequence: n,
                pair: [0.1; 2],
            });
        }
        drain(&mut c, 4, 1, &mut a);
        a.gap_to(2060);
        assert_eq!(a.result().state, comparison::State::Missing);
        assert_eq!(a.result().missing_samples, 8);
        assert!(a.result().bins.is_empty());
    }
}
