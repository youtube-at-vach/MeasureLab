//! Fixed-capacity two-channel transport; frequency fitting cannot stall acquisition.
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
enum Command {
    Configure(u64, lockin::Settings, u32, calibration::Set, u64, usize),
    Inspect(u64, u64, mpsc::SyncSender<lockin::Result>),
}
pub struct Worker {
    input: Producer<Frame>,
    commands: Option<mpsc::SyncSender<Command>>,
    latest: Arc<Mutex<(u64, lockin::Result)>>,
    cached: lockin::Result,
    epoch: u64,
    settings: lockin::Settings,
    channels: usize,
    handle: Option<JoinHandle<()>>,
}
impl Default for Worker {
    fn default() -> Self {
        let settings = lockin::Settings::default();
        let cached = lockin::Analyzer::new(settings, 48000).result().clone();
        let latest = Arc::new(Mutex::new((0, cached.clone())));
        let shared = latest.clone();
        let (input, mut source) = RingBuffer::new(CAPACITY);
        let (commands, receiver) = mpsc::sync_channel(16);
        let handle = thread::Builder::new()
            .name("measurelab-lockin".into())
            .spawn(move || {
                let mut epoch = 0;
                let mut analyzer = lockin::Analyzer::new(settings, 48000);
                let mut publish = Instant::now();
                loop {
                    match receiver.recv_timeout(Duration::from_millis(2)) {
                        Ok(Command::Configure(next, settings, rate, set, start, channels)) => {
                            epoch = next;
                            analyzer = lockin::Analyzer::new(settings, rate);
                            analyzer.set_calibrations(set);
                            analyzer.gap_to(start);
                            if settings.reference_channel >= channels
                                || settings.response_channel >= channels
                            {
                                analyzer.push(start, &[]);
                            }
                            *shared.lock().unwrap() = (epoch, analyzer.result().clone());
                        }
                        Ok(Command::Inspect(target, end, reply)) => {
                            drain(&mut source, source_capacity(), epoch, &mut analyzer);
                            if target == epoch {
                                analyzer.gap_to(end);
                                let _ = reply.try_send(analyzer.result().clone());
                            }
                        }
                        Err(mpsc::RecvTimeoutError::Disconnected) => break,
                        Err(mpsc::RecvTimeoutError::Timeout) => {}
                    }
                    drain(&mut source, 4096, epoch, &mut analyzer);
                    if publish.elapsed() >= Duration::from_millis(20) {
                        *shared.lock().unwrap() = (epoch, analyzer.result().clone());
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
            channels: 2,
            handle: Some(handle),
        }
    }
}
fn source_capacity() -> usize {
    CAPACITY
}
fn drain(source: &mut Consumer<Frame>, limit: usize, epoch: u64, analyzer: &mut lockin::Analyzer) {
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
    }
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
        self.channels = channels;
        self.cached = lockin::Analyzer::new(settings, rate).result().clone();
        self.commands
            .as_ref()
            .unwrap()
            .try_send(Command::Configure(
                self.epoch, settings, rate, set, start, channels,
            ))
            .unwrap_or_else(|_| panic!("too many Lock-in configuration requests"));
    }
    pub fn submit(&mut self, n: u64, samples: &[f64]) {
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
            .try_send(Command::Inspect(self.epoch, end, reply))
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
