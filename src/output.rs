//! Normal-build output. Internal generation and device callbacks never wait
//! for measurement or UI consumers; device management runs off the UI thread.
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
pub mod device;
pub mod history;
mod runtime;

#[derive(Clone, Debug, Default, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(tag = "kind", deny_unknown_fields)]
pub enum Target {
    #[default]
    Internal,
    Audio {
        device_id: String,
        device_name: String,
        channels: u16,
        pcm: device::Pcm,
    },
}
impl Target {
    pub fn channels(&self) -> usize {
        match self {
            Self::Internal => 2,
            Self::Audio { channels, .. } => *channels as usize,
        }
    }
    pub fn label(&self) -> &str {
        match self {
            Self::Internal => "Internal loopback",
            Self::Audio { device_name, .. } => device_name,
        }
    }
    pub fn pcm_label(&self) -> &str {
        match self {
            Self::Internal => "f64",
            Self::Audio { pcm, .. } => pcm.label(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Saved {
    #[serde(default)]
    pub target: Target,
    pub nominal_sample_rate: u32,
    pub signals: Settings,
    pub use_as_input: bool,
}
impl Saved {
    pub fn validate(&self) -> Result<(), String> {
        match &self.target {
            Target::Internal if !RATES.contains(&self.nominal_sample_rate) => {
                return Err("Unsupported internal output rate".into());
            }
            Target::Audio {
                device_id,
                device_name,
                ..
            } if device_id.trim().is_empty()
                || device_name.trim().is_empty()
                || self.use_as_input =>
            {
                return Err("Invalid audio output identity or internal input selection".into());
            }
            _ => {}
        }
        self.signals
            .validate(self.nominal_sample_rate, self.target.channels())
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
    #[serde(deserialize_with = "crate::generator::clock_array")]
    pub carrier_phase_cycles: [f64; crate::generator::SIGNALS],
    #[serde(deserialize_with = "crate::generator::clock_array")]
    pub transition_end: [u64; crate::generator::SIGNALS],
}
impl Condition {
    /// Compare relative phase only for equal frequencies and carrier histories.
    pub fn same_excitation(self, other: Self) -> bool {
        if self.settings.signals.len() != 2
            || self.settings != other.settings
            || self
                .settings
                .signals
                .iter()
                .any(|s| s.waveform != crate::generator::Waveform::Sine)
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
    Select(Target, u32, Settings),
    Refresh,
    Attach(Producer<Frame>, Arc<Metrics>),
    Shutdown,
}
struct Request {
    id: u64,
    stop_epoch: u64,
    command: Command,
}

#[derive(Clone, Debug)]
pub struct Update {
    pub acknowledged_request: u64,
    pub stop_epoch: u64,
    pub status: Status,
    pub error: Option<generator::Error>,
    pub target: Target,
    #[cfg(feature = "qa")]
    pub device_metrics: Option<Arc<device::Metrics>>,
}

/// Non-real-time command adapter. Stop bypasses both queues and fences older
/// Start/edit requests. A successful send is never an execution acknowledgement.
pub struct Worker {
    next_request: AtomicU64,
    commands: mpsc::SyncSender<Request>,
    stop_epoch: Arc<AtomicU64>,
    updates: Consumer<Update>,
    handle: Option<JoinHandle<()>>,
    pub events: mpsc::Receiver<Event>,
    pub history: history::Handle,
}

pub enum Event {
    Devices(Vec<device::DeviceInfo>),
    Error(String),
}

impl Default for Worker {
    fn default() -> Self {
        Self::new()
    }
}
impl Worker {
    pub fn new() -> Self {
        let (commands, requests) = mpsc::sync_channel::<Request>(16);
        let (feedback, updates) = RingBuffer::new(4);
        let stop_epoch = Arc::new(AtomicU64::new(0));
        let stop = stop_epoch.clone();
        let (events, receiver) = mpsc::sync_channel(4);
        let history = history::Handle::default();
        let journal = history.clone();
        let handle = thread::Builder::new()
            .name("measurelab-generator".into())
            .spawn(move || runtime::run(requests, feedback, stop, events, journal))
            .expect("generator worker");
        Self {
            next_request: AtomicU64::new(0),
            commands,
            stop_epoch,
            updates,
            handle: Some(handle),
            events: receiver,
            history,
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
        self.select(Target::Internal, rate, settings)
    }
    pub fn select(&self, target: Target, rate: u32, settings: Settings) -> Result<u64, String> {
        Saved {
            target: target.clone(),
            nominal_sample_rate: rate,
            signals: settings,
            use_as_input: false,
        }
        .validate()?;
        self.send(Command::Select(target, rate, settings))
    }
    pub fn refresh(&self) -> Result<u64, String> {
        self.send(Command::Refresh)
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
    /// Terminal QA only. Counters retained by the caller remain readable after
    /// the stream and all backend listeners have been released.
    #[cfg(feature = "qa")]
    pub fn finish_device_profile(&mut self) {
        self.shutdown();
    }

    fn shutdown(&mut self) {
        if let Some(handle) = self.handle.take() {
            self.stop();
            let _ = self.commands.send(Request {
                id: 0,
                stop_epoch: self.stop_epoch.load(Ordering::Acquire),
                command: Command::Shutdown,
            });
            let _ = handle.join();
        }
    }
}
impl Drop for Worker {
    fn drop(&mut self) {
        self.shutdown();
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
    #[test]
    fn manager_records_device_start_failure_while_ui_feedback_is_unconsumed() {
        let worker = Worker::new();
        let session = worker.history.begin(31);
        let target = Target::Audio {
            device_id: "measurelab:test:nonexistent-output-device".into(),
            device_name: "Missing test output".into(),
            channels: 2,
            pcm: device::Pcm::F32,
        };
        worker.select(target, 48_000, settings()).unwrap();
        worker.start(settings()).unwrap();
        // No poll of Worker feedback: its four UI slots saturate. The manager
        // still records the failed open without ever creating an output stream.
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            if worker.history.begin(31).finish().is_some_and(|h| {
                h.latest
                    .is_some_and(|o| o.status.state == State::Error(generator::Error::OutputStream))
            }) {
                break;
            }
            assert!(
                Instant::now() < deadline,
                "output open did not report failure"
            );
            thread::sleep(Duration::from_millis(2));
        }
        let held = session.finish().unwrap();
        held.validate(31).unwrap();
        assert!(
            held.changes
                .iter()
                .any(|o| o.status.state == State::Error(generator::Error::OutputStream))
        );
        assert_eq!(held.latest.unwrap().status.output_generation, 0);
    }
    #[test]
    fn saved_outputs_preserve_exact_device_config_and_old_internal_defaults() {
        let old = serde_json::json!({"nominal_sample_rate":48000, "signals":settings(), "use_as_input":true});
        let saved: Saved = serde_json::from_value(old).unwrap();
        assert_eq!(saved.target, Target::Internal);
        saved.validate().unwrap();
        let audio = Saved {
            target: Target::Audio {
                device_id: "backend:stable-output".into(),
                device_name: "Output".into(),
                channels: 16,
                pcm: device::Pcm::F32,
            },
            nominal_sample_rate: 96000,
            signals: settings(),
            use_as_input: false,
        };
        let decoded: Saved = serde_json::from_slice(&serde_json::to_vec(&audio).unwrap()).unwrap();
        assert_eq!(decoded, audio);
        decoded.validate().unwrap();
        assert!(
            Saved {
                use_as_input: true,
                ..audio.clone()
            }
            .validate()
            .is_err()
        );
        assert!(
            Saved {
                target: Target::Internal,
                nominal_sample_rate: 48001,
                ..audio
            }
            .validate()
            .is_err()
        );
    }
    #[test]
    fn shared_stop_fences_opening_and_pending_start_even_after_a_new_edit() {
        let stop = Arc::new(AtomicU64::new(0));
        let engine = Engine::new(48000, 2, settings(), 0).unwrap();
        let (mut controller, mut execution) = control::from_engine_with_stop(engine, stop.clone());
        for _ in 0..8 {
            controller.start(settings()).unwrap();
        }
        stop.store(1, Ordering::Release);
        // An edit after Stop must not inherit an older unsent Start.
        controller.configure(settings()).unwrap();
        execution.begin_block();
        controller.flush();
        execution.begin_block();
        assert_eq!(execution.status().state, State::Stopped);
        assert_eq!(execution.status().output_generation, 0);
        controller.submit(settings(), true, false, 0).unwrap();
        execution.begin_block();
        assert_eq!(execution.status().state, State::Stopped);
    }
    fn wait(worker: &mut Worker, predicate: impl Fn(Update) -> bool) -> Update {
        let deadline = Instant::now() + Duration::from_secs(3);
        loop {
            if let Some(update) = worker.poll()
                && predicate(update.clone())
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
