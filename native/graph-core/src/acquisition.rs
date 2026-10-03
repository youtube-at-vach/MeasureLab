//! MIG-005 acquisition -> history -> fixed shared FFT worker. Never callback-safe.
//! The caller polls this single owner independently of display notifications.
use crate::history::{History, HistoryLimits, ReadReport};
use crate::{
    Average, FftKey, Graph, InvalidSpan, Limits, Precision, Presentation, Rational, ResultId,
    Samples, SignalBlock, Source, Subscription, Tap, Timebase, WindowSpec,
};
use audio_core::{Consumer, Delivery, IoFormat, MAX_CALLBACK_FRAMES, Sample};
use serde::Serialize;
use std::sync::Arc;

mod trigger;
pub use trigger::{TriggerRead, TriggerRequest};
mod derived;

mod sealed {
    pub trait Sealed {}
    impl Sealed for f32 {}
    impl Sealed for f64 {}
}
pub trait CaptureSample: Sample + sealed::Sealed {
    const PRECISION: Precision;
    fn owned(values: Vec<Self>) -> Samples;
    fn finite(self) -> bool;
}
impl CaptureSample for f32 {
    const PRECISION: Precision = Precision::F32;
    fn owned(values: Vec<Self>) -> Samples {
        Samples::F32(values)
    }
    fn finite(self) -> bool {
        self.is_finite()
    }
}
impl CaptureSample for f64 {
    const PRECISION: Precision = Precision::F64;
    fn owned(values: Vec<Self>) -> Samples {
        Samples::F64(values)
    }
    fn finite(self) -> bool {
        self.is_finite()
    }
}
#[derive(Clone, Debug)]
pub struct CaptureLimits {
    pub history: HistoryLimits,
    pub frames_per_poll: usize,
    pub windows_per_poll: usize,
}
#[derive(Clone, Debug)]
pub struct FftSpec {
    pub n: usize,
    pub hop: usize,
    pub alignment: u64,
    pub window: WindowSpec,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub enum WorkerState {
    Running,
    Stopped,
    Failed(String),
}
/// Backend timestamp remains diagnostic: no inferred clock mapping or uncertainty=0.
#[derive(Debug, Serialize)]
pub struct FrameStamp {
    pub sample: u64,
    pub seconds: Option<f64>,
    pub backend_flags: u32,
}
#[derive(Debug, Serialize)]
pub struct WindowEvent {
    pub history: ReadReport,
    pub result_id: Option<ResultId>,
    pub numeric: bool,
}
#[derive(Debug, Default)]
pub struct PollReport {
    pub deliveries: usize,
    pub blocks: Vec<Arc<SignalBlock>>,
    pub timestamps: Vec<FrameStamp>,
    pub gaps: Vec<[u64; 2]>,
    pub windows: Vec<WindowEvent>,
    pub filtered_blocks: Vec<Arc<SignalBlock>>,
    pub filtered_windows: Vec<WindowEvent>,
}
/// A single input queue, explicit logical-to-physical binding and one FFT specification.
/// Display/save demand is represented only by external graph subscription tokens.
pub struct Acquisition<T: CaptureSample> {
    receiver: Option<Consumer<T>>,
    history: Option<History>,
    format: IoFormat,
    limits: CaptureLimits,
    key: FftKey,
    next_window: u64,
    graph: Graph,
    state: WorkerState,
    // One retained on-demand raw result, independent of continuous view mailboxes.
    trigger_cache: Option<Arc<crate::FftResult>>,
    trigger_evaluations: u64,
    filtered: Option<derived::FilteredStream>,
    input_finished: bool,
}
fn prepare<T: CaptureSample>(
    receiver: &Consumer<T>,
    format: &IoFormat,
    spec: &FftSpec,
    limits: &CaptureLimits,
) -> Result<(History, FftKey), String> {
    // This worker owns input.raw only; device output/tap processing is a separate owner.
    format.validate(receiver.stats().channels, 0)?;
    let rate = i64::try_from(format.rate[0]).map_err(|_| "capture_rate")?;
    let rate_hz = rate as f64 / format.rate[1] as f64;
    if format.input_ids.is_empty()
        || rate_hz != receiver.rate_hz()
        || limits.frames_per_poll == 0
        || limits.frames_per_poll > MAX_CALLBACK_FRAMES
        || limits.windows_per_poll == 0
        || limits.windows_per_poll > 4096
        || spec.n < 3
        || spec.n > limits.history.capacity_frames
        || spec.hop == 0
        || spec
            .alignment
            .checked_add(spec.n as u64)
            .is_none_or(|n| n > i64::MAX as u64)
    {
        return Err("capture_configuration".into());
    }
    let source = Source {
        stream_id: format.stream_id.clone(),
        generation: format.generation,
        channel_ids: format.input_ids.clone(),
        precision: T::PRECISION,
        timebase: Timebase {
            id: format.timebase_id.clone(),
            revision: 0,
            clock_domain: format.clock_domain.clone(),
            generation: format.generation,
            rate: Rational {
                numerator: rate,
                denominator: format.rate[1],
            },
            nominal_rate: Rational {
                numerator: rate,
                denominator: format.rate[1],
            },
            origin_sample: 0,
            origin_seconds: None,
            origin_kind: "backend-unverified".into(),
            uncertainty_seconds: None,
        },
        route_revision: "input-physical-binding".into(),
        tap: Tap::InputRaw,
        filter_state_revision: "none".into(),
        calibration_revision: "none".into(),
    };
    let history = History::new(source.clone(), limits.history)?;
    let key = FftKey {
        source,
        n: spec.n,
        hop: spec.hop,
        alignment: spec.alignment,
        window: spec.window,
        remove_dc: false,
        input_gains: Vec::new(),
    };
    key.validate(&Limits::default())?;
    Ok((history, key))
}
impl<T: CaptureSample> Acquisition<T> {
    pub fn new(
        receiver: Consumer<T>,
        format: IoFormat,
        spec: FftSpec,
        limits: CaptureLimits,
    ) -> Result<Self, String> {
        let (history, key) = prepare(&receiver, &format, &spec, &limits)?;
        Ok(Self {
            receiver: Some(receiver),
            history: Some(history),
            format,
            limits,
            next_window: key.alignment,
            key,
            graph: Graph::new(Limits::default())?,
            state: WorkerState::Running,
            trigger_cache: None,
            trigger_evaluations: 0,
            filtered: None,
            input_finished: false,
        })
    }
    pub fn key(&self) -> &FftKey {
        &self.key
    }
    pub fn format(&self) -> &IoFormat {
        &self.format
    }
    pub fn graph(&self) -> &Graph {
        &self.graph
    }
    pub fn history(&self) -> Option<&History> {
        self.history.as_ref()
    }
    pub fn queue_stats(&self) -> Option<audio_core::QueueStats> {
        self.receiver.as_ref().map(Consumer::stats)
    }
    pub fn state(&self) -> &WorkerState {
        &self.state
    }
    pub fn subscribe(
        &self,
        average: Average,
        presentation: Presentation,
    ) -> Result<Subscription, String> {
        self.graph
            .subscribe(self.key.clone(), average, presentation)
    }
    /// Construct replacement before fencing publication. Old callback queue is never reused.
    /// Existing subscriptions must explicitly reconfigure to key() after success.
    pub fn restart(&mut self, receiver: Consumer<T>, format: IoFormat) -> Result<(), String> {
        if self.state != WorkerState::Running
            || self.input_finished
            || format.stream_id != self.format.stream_id
            || format.generation <= self.format.generation
        {
            return Err("stale_generation_or_state".into());
        }
        let spec = FftSpec {
            n: self.key.n,
            hop: self.key.hop,
            alignment: self.key.alignment,
            window: self.key.window,
        };
        let (history, key) = prepare(&receiver, &format, &spec, &self.limits)?;
        if self.graph.stats().subscriptions > 0 {
            self.graph
                .retire_stream_before(&format.stream_id, format.generation)?;
        }
        self.history = Some(history);
        self.receiver = Some(receiver);
        self.format = format;
        self.next_window = key.alignment;
        self.key = key;
        self.trigger_cache = None;
        self.filtered = None;
        Ok(())
    }
    pub fn stop(&mut self) {
        self.graph.shutdown();
        self.receiver = None;
        self.history = None;
        self.trigger_cache = None;
        self.filtered = None;
        if self.state == WorkerState::Running {
            self.state = WorkerState::Stopped;
        }
    }
    /// Bound both dequeue work and window work. Failure closes demand and releases worker storage.
    pub fn poll(&mut self) -> Result<PollReport, String> {
        if self.state != WorkerState::Running {
            return Err("capture_not_running".into());
        }
        match self.poll_inner() {
            Ok(report) => Ok(report),
            Err(reason) => {
                self.state = WorkerState::Failed(reason.clone());
                self.stop();
                Err(reason)
            }
        }
    }
    fn windows(&mut self, report: &mut PollReport) -> Result<(), String> {
        derived::schedule_windows(
            &self.graph,
            self.history.as_ref().unwrap(),
            &self.key,
            &mut self.next_window,
            self.limits.windows_per_poll,
            &mut report.windows,
        )
    }

    fn commit(
        &mut self,
        values: &mut Vec<T>,
        validity: &mut Vec<InvalidSpan>,
        report: &mut PollReport,
    ) -> Result<(), String> {
        if values.is_empty() {
            return Ok(());
        }
        let history = self.history.as_mut().unwrap();
        let block = Arc::new(SignalBlock::new(
            self.key.source.clone(),
            history.acquired_until(),
            T::owned(std::mem::take(values)),
            std::mem::take(validity),
        )?);
        history.append_ref(&block)?;
        self.process_filtered(&block, report)?;
        report.blocks.push(block);
        self.windows(report)
    }
    fn poll_inner(&mut self) -> Result<PollReport, String> {
        let mut report = PollReport::default();
        self.filtered_windows(&mut report)?;
        self.windows(&mut report)?;
        let mut values = Vec::new();
        let mut validity = Vec::new();
        while report.deliveries < self.limits.frames_per_poll
            && report.windows.len() < self.limits.windows_per_poll
            && report.filtered_windows.len() < self.limits.windows_per_poll
        {
            let Some(delivery) = self.receiver.as_mut().and_then(Consumer::take) else {
                break;
            };
            report.deliveries += 1;
            match delivery {
                Delivery::Gap { interval } => {
                    self.commit(&mut values, &mut validity, &mut report)?;
                    self.history.as_mut().unwrap().append_gap(interval)?;
                    self.graph.invalidate_source(&self.key.source)?;
                    self.filtered_gap()?;
                    report.gaps.push(interval);
                    self.windows(&mut report)?;
                }
                Delivery::Frame {
                    sample,
                    values: frame,
                    seconds,
                    flags,
                } => {
                    let position = self.history.as_ref().unwrap().acquired_until()
                        + (values.len() / self.format.input_ids.len()) as u64;
                    if sample != position {
                        return Err("capture_position".into());
                    }
                    for (id, port) in self.format.input_ids.iter().zip(&self.format.input_ports) {
                        let value = frame[*port];
                        if !value.finite() {
                            span(
                                &mut validity,
                                sample,
                                Some(id.clone()),
                                "nonfinite",
                                "acquisition.input.raw",
                            );
                        }
                        values.push(value);
                    }
                    if flags != 0 {
                        span(
                            &mut validity,
                            sample,
                            None,
                            "unsupported",
                            &format!("backend.flags:{flags}"),
                        );
                    }
                    report.timestamps.push(FrameStamp {
                        sample,
                        seconds,
                        backend_flags: flags,
                    });
                    let end = sample + 1;
                    if end >= self.next_window + self.key.n as u64 {
                        self.commit(&mut values, &mut validity, &mut report)?;
                    }
                }
            }
        }
        self.commit(&mut values, &mut validity, &mut report)?;
        Ok(report)
    }
}
impl<T: CaptureSample> Drop for Acquisition<T> {
    fn drop(&mut self) {
        self.stop();
    }
}
fn span(
    spans: &mut Vec<InvalidSpan>,
    sample: u64,
    channel_id: Option<String>,
    reason: &str,
    origin: &str,
) {
    if let Some(last) = spans
        .iter_mut()
        .rev()
        .find(|v| v.channel_id == channel_id && v.reason == reason && v.origin == origin)
        && last.end == sample
    {
        last.end += 1;
        return;
    }
    spans.push(InvalidSpan {
        start: sample,
        end: sample + 1,
        channel_id,
        reason: reason.into(),
        origin: origin.into(),
    });
}

#[cfg(test)]
mod tests;
