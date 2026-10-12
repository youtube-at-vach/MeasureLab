//! Normal-build internal output. Generation has its own execution thread and
//! never waits for measurement or UI consumers. This adapter has no DAC path.
use crate::generator::{self, Engine, Settings, State, Status, control};
use rtrb::{Consumer, Producer, RingBuffer};
use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU64, Ordering},
        mpsc,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

pub const CAPACITY: usize = 16_384;
pub const CONDITION_CAPACITY: usize = 128;
pub const RATES: [u32; 4] = [44_100, 48_000, 96_000, 192_000];

#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Saved {
    pub nominal_sample_rate: u32,
    pub signals: Settings,
    pub use_as_input: bool,
}
impl Saved {
    pub fn validate(self) -> Result<(), String> {
        if !RATES.contains(&self.nominal_sample_rate) {
            return Err("Unsupported internal output rate".into());
        }
        self.signals
            .validate(self.nominal_sample_rate, 2)
            .map_err(|e| e.to_string())
    }
}

/// The condition of the generated frame, on the same integer clock as input.
#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Condition {
    pub output_generation: u64,
    pub revision: u64,
    pub settings: Settings,
    pub active: bool,
    pub transitioning: bool,
    pub applied_sample: u64,
    pub carrier_phase_cycles: [f64; 2],
    pub transition_end: [u64; 2],
}
impl Condition {
    /// Compare relative phase only for equal frequencies and carrier histories.
    pub fn same_excitation(self, other: Self) -> bool {
        if self.settings != other.settings
            || self.settings.signals[0].frequency_hz != self.settings.signals[1].frequency_hz
        {
            return false;
        }
        let phase = |c: Self| c.carrier_phase_cycles[1] - c.carrier_phase_cycles[0];
        ((phase(self) - phase(other) + 0.5).rem_euclid(1.0) - 0.5).abs() < 1e-12
    }
    pub fn from_status(status: Status) -> Self {
        Self {
            output_generation: status.output_generation,
            revision: status.revision,
            settings: status.settings,
            active: matches!(
                status.state,
                State::Starting | State::Running | State::Stopping
            ),
            transitioning: status.transitioning() || status.state == State::Stopping,
            applied_sample: status.applied_sample,
            carrier_phase_cycles: status.carrier_phase_cycles,
            transition_end: status.transition_end,
        }
    }
}

#[derive(Clone, Copy)]
pub struct Frame {
    pub sequence: u64,
    pub samples: [f64; 2],
    pub condition: Condition,
    #[cfg(feature = "qa")]
    pub available_at: Instant,
}

#[derive(Default)]
pub struct Metrics {
    pub active: AtomicBool,
    pub ready: AtomicBool,
    pub first_sample: AtomicU64,
    pub nominal_sample_rate: AtomicU64,
    pub input_end: AtomicU64,
    pub dropped: AtomicU64,
    pub failed: AtomicBool,
}

pub struct Capture {
    pub consumer: Consumer<Frame>,
    pub metrics: Arc<Metrics>,
}
impl Drop for Capture {
    fn drop(&mut self) {
        self.metrics.active.store(false, Ordering::Release);
    }
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Span {
    pub sample_range: std::ops::Range<u64>,
    pub condition: Condition,
}

/// A bounded history. Missing/evicted intervals have no condition, and are
/// never inferred from the UI's latest settings or from a neighboring span.
#[derive(Clone, Debug, Default, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Timeline {
    pub spans: Vec<Span>,
}
impl Timeline {
    pub fn push(&mut self, frame: Frame) {
        if let Some(last) = self.spans.last_mut()
            && last.sample_range.end == frame.sequence
            && last.condition == frame.condition
        {
            last.sample_range.end += 1;
            return;
        }
        if self.spans.len() == CONDITION_CAPACITY {
            self.spans.remove(0);
        }
        self.spans.push(Span {
            sample_range: frame.sequence..frame.sequence + 1,
            condition: frame.condition,
        });
    }

    pub fn stationary(&self, range: std::ops::Range<u64>) -> Option<Condition> {
        if range.is_empty() {
            return None;
        }
        self.spans
            .iter()
            .find(|s| {
                s.sample_range.start <= range.start
                    && s.sample_range.end >= range.end
                    && !s.condition.transitioning
                    && s.condition.active
            })
            .map(|s| s.condition)
    }

    pub fn validate(&self, rate: u32, end: u64) -> Result<(), String> {
        if self.spans.len() > CONDITION_CAPACITY {
            return Err("Too many output conditions".into());
        }
        let mut previous = 0;
        for span in &self.spans {
            let c = span.condition;
            c.settings.validate(rate, 2).map_err(|e| e.to_string())?;
            if span.sample_range.is_empty()
                || span.sample_range.start < previous
                || span.sample_range.end > end
                || c.applied_sample > span.sample_range.start
                || (c.active && c.output_generation == 0)
                || c.carrier_phase_cycles
                    .iter()
                    .any(|p| !p.is_finite() || !(0.0..1.0).contains(p))
                || (c.active
                    && !c.transitioning
                    && c.transition_end
                        .iter()
                        .any(|&n| n > span.sample_range.start))
            {
                return Err("Invalid internal output condition interval".into());
            }
            previous = span.sample_range.end;
        }
        Ok(())
    }
}

enum Command {
    Configure(Settings),
    Start(Settings),
    Align,
    Rate(u32, Settings),
    Attach(Producer<Frame>, Arc<Metrics>),
    Shutdown,
}
struct Request {
    id: u64,
    stop_epoch: u64,
    command: Command,
}

#[derive(Clone, Copy, Debug)]
pub struct Update {
    pub acknowledged_request: u64,
    pub stop_epoch: u64,
    pub status: Status,
    pub error: Option<generator::Error>,
}

/// Non-real-time command adapter. Stop bypasses both queues and fences older
/// Start/edit requests. A successful send is never an execution acknowledgement.
pub struct Worker {
    next_request: AtomicU64,
    commands: mpsc::SyncSender<Request>,
    stop_epoch: Arc<AtomicU64>,
    updates: Consumer<Update>,
    handle: Option<JoinHandle<()>>,
}

impl Default for Worker {
    fn default() -> Self {
        Self::new()
    }
}
impl Worker {
    pub fn new() -> Self {
        let (commands, requests) = mpsc::sync_channel::<Request>(16);
        let (mut feedback, updates) = RingBuffer::new(4);
        let stop_epoch = Arc::new(AtomicU64::new(0));
        let stop = stop_epoch.clone();
        let handle = thread::Builder::new()
            .name("measurelab-generator".into())
            .spawn(move || {
                let (mut controller, mut execution) =
                    control::new(48_000, 2, Settings::default(), 0).unwrap();
                let mut capture: Option<(Producer<Frame>, Arc<Metrics>)> = None;
                let mut seen_stop = 0;
                let mut clock = Instant::now();
                let mut fraction = 0.0;
                let mut error = None;
                let mut acknowledged_request = 0;
                let mut pending_request = 0;
                let mut pending_revision = None;
                let mut activity = None;
                loop {
                    let epoch = stop.load(Ordering::Acquire);
                    if epoch != seen_stop {
                        let _ = controller.stop();
                        seen_stop = epoch;
                        pending_revision = None;
                    }
                    for _ in 0..16 {
                        let Ok(request) = requests.try_recv() else {
                            break;
                        };
                        if matches!(request.command, Command::Shutdown) {
                            return;
                        }
                        let epoch = stop.load(Ordering::Acquire);
                        if epoch != seen_stop {
                            let _ = controller.stop();
                            seen_stop = epoch;
                            pending_revision = None;
                        }
                        // Attach is input acquisition, independent of output Stop.
                        if request.stop_epoch != epoch
                            && !matches!(request.command, Command::Attach(..))
                        {
                            acknowledged_request = acknowledged_request.max(request.id);
                            continue;
                        }
                        let is_control = !matches!(request.command, Command::Attach(..));
                        if is_control {
                            pending_request = request.id;
                        }
                        let result = match request.command {
                            Command::Configure(settings) => controller
                                .configure(settings)
                                .map(|rev| pending_revision = Some(rev)),
                            Command::Start(settings) => controller
                                .start(settings)
                                .map(|rev| pending_revision = Some(rev)),
                            Command::Align => controller
                                .align_phases()
                                .map(|rev| pending_revision = Some(rev)),
                            Command::Rate(rate, settings) => {
                                if !matches!(
                                    execution.status().state,
                                    State::Stopped | State::Error(_)
                                ) || pending_revision
                                    .is_some_and(|rev| rev > execution.status().revision)
                                    || capture
                                        .as_ref()
                                        .is_some_and(|(_, m)| m.active.load(Ordering::Acquire))
                                {
                                    Err(generator::Error::AlreadyActive)
                                } else if !RATES.contains(&rate) {
                                    Err(generator::Error::SampleRate)
                                } else {
                                    let s = execution.status();
                                    Engine::with_clock(
                                        rate,
                                        2,
                                        settings,
                                        s.next_sample,
                                        s.output_generation,
                                    )
                                    .map(|engine| {
                                        (controller, execution) = control::from_engine(engine);
                                        pending_revision = None;
                                        clock = Instant::now();
                                        fraction = 0.0;
                                    })
                                }
                            }
                            Command::Attach(producer, metrics) => {
                                if let Some((_, old)) = &capture {
                                    old.active.store(false, Ordering::Release);
                                }
                                let n = execution.status().next_sample;
                                metrics.nominal_sample_rate.store(
                                    execution.status().nominal_sample_rate as u64,
                                    Ordering::Relaxed,
                                );
                                metrics.first_sample.store(n, Ordering::Relaxed);
                                metrics.input_end.store(n, Ordering::Relaxed);
                                metrics.ready.store(true, Ordering::Release);
                                if capture.is_none() && execution.status().state == State::Stopped {
                                    clock = Instant::now();
                                    fraction = 0.0;
                                }
                                capture = Some((producer, metrics));
                                Ok(())
                            }
                            Command::Shutdown => unreachable!(),
                        };
                        if is_control {
                            error = result.err();
                            if error.is_some() {
                                pending_revision = None;
                            }
                        }
                    }
                    if capture
                        .as_ref()
                        .is_some_and(|(_, m)| !m.active.load(Ordering::Acquire))
                    {
                        capture = None;
                    }
                    controller.flush();
                    execution.begin_block();
                    let now = Instant::now();
                    let elapsed = now.duration_since(clock).as_secs_f64();
                    clock = now;
                    let s = execution.status();
                    if capture.is_some() || !matches!(s.state, State::Stopped | State::Error(_)) {
                        if activity.is_none() {
                            activity = Some(crate::activity::Activity::new(
                                "MeasureLab signal generation",
                            ));
                        }
                    } else {
                        activity.take();
                    }
                    if capture.is_some() || !matches!(s.state, State::Stopped | State::Error(_)) {
                        fraction += elapsed * s.nominal_sample_rate as f64;
                        // A suspended producer cannot manufacture an arbitrarily
                        // long catch-up batch. Fail and expose the input boundary.
                        if fraction > s.nominal_sample_rate as f64 * 0.25 {
                            execution.fail(generator::Error::ProducerSuspended);
                            error = Some(generator::Error::ProducerSuspended);
                            if let Some((_, m)) = &capture {
                                m.failed.store(true, Ordering::Release);
                            }
                            fraction = 0.0;
                        }
                        let count = fraction as usize;
                        fraction -= count as f64;
                        for _ in 0..count {
                            let condition = Condition::from_status(execution.status());
                            match execution.next_frame() {
                                Ok(frame) => {
                                    if let Some((producer, m)) = &mut capture {
                                        let frame = Frame {
                                            sequence: frame.sequence,
                                            samples: [frame.samples[0], frame.samples[1]],
                                            condition,
                                            #[cfg(feature = "qa")]
                                            available_at: now,
                                        };
                                        if producer.push(frame).is_err() {
                                            m.dropped.fetch_add(1, Ordering::Relaxed);
                                        }
                                        m.input_end.store(frame.sequence + 1, Ordering::Release);
                                    }
                                }
                                Err(e) => {
                                    error = Some(e);
                                    if let Some((_, m)) = &capture {
                                        m.failed.store(true, Ordering::Release);
                                    }
                                    break;
                                }
                            }
                        }
                    }
                    execution.end_block();
                    if let Some(report) = controller.poll()
                        && let Some(rejected) = report.rejected
                        && pending_revision == Some(rejected.revision)
                    {
                        error = Some(rejected.error);
                        pending_revision = None;
                    }
                    if pending_revision
                        .is_none_or(|revision| execution.status().revision >= revision)
                    {
                        acknowledged_request = acknowledged_request.max(pending_request);
                    }
                    let _ = feedback.push(Update {
                        acknowledged_request,
                        stop_epoch: seen_stop,
                        status: execution.status(),
                        error,
                    });
                    thread::sleep(Duration::from_millis(2));
                }
            })
            .expect("generator worker");
        Self {
            next_request: AtomicU64::new(0),
            commands,
            stop_epoch,
            updates,
            handle: Some(handle),
        }
    }
    fn send(&self, command: Command) -> Result<u64, String> {
        let id = self.next_request.fetch_add(1, Ordering::Relaxed) + 1;
        self.commands
            .try_send(Request {
                id,
                stop_epoch: self.stop_epoch.load(Ordering::Acquire),
                command,
            })
            .map(|()| id)
            .map_err(|_| "Output control queue is busy; retry the operation".into())
    }
    pub fn configure(&self, settings: Settings) -> Result<u64, String> {
        self.send(Command::Configure(settings))
    }
    pub fn start(&self, settings: Settings) -> Result<u64, String> {
        self.send(Command::Start(settings))
    }
    pub fn align(&self) -> Result<u64, String> {
        self.send(Command::Align)
    }
    pub fn set_rate(&self, rate: u32, settings: Settings) -> Result<u64, String> {
        if !RATES.contains(&rate) {
            return Err(generator::Error::SampleRate.to_string());
        }
        settings.validate(rate, 2).map_err(|e| e.to_string())?;
        self.send(Command::Rate(rate, settings))
    }
    pub fn stop(&self) -> u64 {
        self.stop_epoch.fetch_add(1, Ordering::Release) + 1
    }
    pub fn capture(&self) -> Result<Capture, String> {
        let (producer, consumer) = RingBuffer::new(CAPACITY);
        let metrics = Arc::new(Metrics::default());
        metrics.active.store(true, Ordering::Relaxed);
        self.send(Command::Attach(producer, metrics.clone()))?;
        Ok(Capture { consumer, metrics })
    }
    pub fn poll(&mut self) -> Option<Update> {
        let mut latest = None;
        for _ in 0..self.updates.slots() {
            latest = self.updates.pop().ok();
        }
        latest
    }
}
impl Drop for Worker {
    fn drop(&mut self) {
        self.stop();
        let _ = self.commands.send(Request {
            id: 0,
            stop_epoch: self.stop_epoch.load(Ordering::Acquire),
            command: Command::Shutdown,
        });
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn settings() -> Settings {
        let mut s = Settings::default();
        for signal in &mut s.signals {
            signal.enabled = true;
            signal.frequency_hz = 750.0;
        }
        s
    }
    fn wait(worker: &mut Worker, predicate: impl Fn(Update) -> bool) -> Update {
        let deadline = Instant::now() + Duration::from_secs(3);
        loop {
            if let Some(update) = worker.poll()
                && predicate(update)
            {
                return update;
            }
            assert!(
                Instant::now() < deadline,
                "output acknowledgement timed out"
            );
            thread::sleep(Duration::from_millis(2));
        }
    }
    #[test]
    fn idle_stop_is_acknowledged_and_start_edit_and_restore_never_restart_implicitly() {
        let mut worker = Worker::new();
        let epoch = worker.stop();
        wait(&mut worker, |u| {
            u.stop_epoch == epoch && u.status.state == State::Stopped
        });
        let mut s = settings();
        let id = worker.configure(s).unwrap();
        let stopped = wait(&mut worker, |u| u.acknowledged_request >= id);
        assert_eq!(stopped.status.state, State::Stopped);
        worker.start(s).unwrap();
        let running = wait(&mut worker, |u| u.status.state == State::Running);
        assert_eq!(running.status.output_generation, 1);
        s.signals[1].phase_degrees = 90.0;
        let id = worker.configure(s).unwrap();
        let applied = wait(&mut worker, |u| {
            u.acknowledged_request >= id && !u.status.transitioning()
        });
        assert_eq!(applied.status.settings, s);
        assert!(applied.status.next_sample > running.status.next_sample);
        let epoch = worker.stop();
        let stopped = wait(&mut worker, |u| {
            u.stop_epoch == epoch && u.status.state == State::Stopped
        });
        assert!(stopped.status.stopped_at.unwrap() > stopped.status.stop_sample.unwrap());
        let id = worker.set_rate(96_000, s).unwrap();
        let restored = wait(&mut worker, |u| u.acknowledged_request >= id);
        assert_eq!(restored.status.state, State::Stopped);
        assert_eq!(restored.status.next_sample, stopped.status.next_sample);
        assert_eq!(restored.status.output_generation, 1);
        worker.start(s).unwrap();
        assert_eq!(
            wait(&mut worker, |u| u.status.state == State::Running)
                .status
                .output_generation,
            2
        );
    }
    #[test]
    fn unconsumed_input_and_feedback_never_stall_output_and_input_restart_keeps_the_clock() {
        let mut worker = Worker::new();
        worker.start(settings()).unwrap();
        let running = wait(&mut worker, |u| u.status.state == State::Running);
        let capture = worker.capture().unwrap();
        let metrics = capture.metrics.clone();
        let deadline = Instant::now() + Duration::from_secs(3);
        while metrics.dropped.load(Ordering::Relaxed) == 0 {
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(5));
        }
        let end = metrics.input_end.load(Ordering::Acquire);
        assert!(end > running.status.next_sample + CAPACITY as u64);
        assert!(!metrics.failed.load(Ordering::Acquire));
        drop(capture);
        let advanced = wait(&mut worker, |u| u.status.next_sample > end + 128);
        assert_eq!(advanced.status.state, State::Running);
        assert_eq!(
            advanced.status.output_generation,
            running.status.output_generation
        );
        let capture = worker.capture().unwrap();
        let deadline = Instant::now() + Duration::from_secs(3);
        while !capture.metrics.ready.load(Ordering::Acquire) {
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(2));
        }
        assert!(capture.metrics.first_sample.load(Ordering::Relaxed) > end);
        let id = worker.set_rate(96_000, settings()).unwrap();
        let rejected = wait(&mut worker, |u| u.acknowledged_request >= id);
        assert_eq!(rejected.error, Some(generator::Error::AlreadyActive));
        assert_eq!(rejected.status.nominal_sample_rate, 48_000);
        worker.stop();
    }
    #[test]
    fn condition_history_is_bounded_and_gaps_or_transitions_are_never_stationary() {
        let mut engine = Engine::new(48_000, 2, settings(), 1u64 << 54).unwrap();
        engine.start(settings(), 1).unwrap();
        let mut timeline = Timeline::default();
        for _ in 0..600 {
            let condition = Condition::from_status(engine.status());
            let f = engine.next_frame().unwrap();
            timeline.push(Frame {
                sequence: f.sequence,
                samples: [f.samples[0], f.samples[1]],
                condition,
                #[cfg(feature = "qa")]
                available_at: Instant::now(),
            });
        }
        let start = 1u64 << 54;
        assert!(timeline.stationary(start..start + 600).is_none());
        assert!(timeline.stationary(start + 480..start + 600).is_some());
        let stable = timeline.spans.last().unwrap().clone();
        for i in 0..CONDITION_CAPACITY + 20 {
            timeline.push(Frame {
                sequence: start + 1000 + i as u64 * 2,
                samples: [0.0; 2],
                condition: stable.condition,
                #[cfg(feature = "qa")]
                available_at: Instant::now(),
            });
        }
        assert_eq!(timeline.spans.len(), CONDITION_CAPACITY);
        assert!(timeline.stationary(start + 1000..start + 1010).is_none());
        timeline.validate(48_000, start + 2000).unwrap();
    }
}
