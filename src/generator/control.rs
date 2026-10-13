//! Fixed-size SPSC snapshots and acknowledgement reports. Only the controller
//! retains a pending edit; Stop has an independent atomic priority path.
use super::{Engine, Error, Settings, Status};
use rtrb::{Consumer, Producer, RingBuffer};
use std::sync::{
    Arc,
    atomic::{AtomicU64, Ordering},
};

pub const CAPACITY: usize = 4;

#[derive(Clone, Copy)]
struct Request {
    revision: u64,
    stop_epoch: u64,
    settings: Settings,
    start: bool,
    align: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Rejection {
    pub revision: u64,
    pub error: Error,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Report {
    pub status: Status,
    /// Priority Stop accepted by the execution side, including an idle Stop.
    pub stop_epoch: u64,
    pub rejected: Option<Rejection>,
    /// Requests from before the most recent Stop that were never applied.
    pub superseded_requests: u64,
    /// Missing reports are observable; a latest report is not a full history.
    pub lost_reports: u64,
}

/// Non-real-time single writer. Call flush/poll periodically from the output
/// manager even when the UI is hidden; no edit is silently lost on saturation.
pub struct Controller {
    requests: Producer<Request>,
    reports: Consumer<Report>,
    pending: Option<Request>,
    stop_epoch: Arc<AtomicU64>,
    revision: u64,
    coalesced: u64,
    rate: u32,
    channels: usize,
    settings: Settings,
}

/// Owned by exactly one output callback or internal generation worker. Keep it
/// alive until the stream is released; dropping it is a non-real-time operation.
pub struct Execution {
    engine: Engine,
    requests: Consumer<Request>,
    reports: Producer<Report>,
    stop_epoch: Arc<AtomicU64>,
    report: Report,
}

pub fn new(
    rate: u32,
    channels: usize,
    settings: Settings,
    first_sample: u64,
) -> Result<(Controller, Execution), Error> {
    let engine = Engine::new(rate, channels, settings, first_sample)?;
    Ok(from_engine(engine))
}

/// Also accepts an engine constructed with a continued output generation.
pub fn from_engine(engine: Engine) -> (Controller, Execution) {
    from_engine_with_stop(engine, Arc::new(AtomicU64::new(0)))
}

/// The output manager and callback share the same Stop fence, including while
/// a device is being opened. No queued Start can cross an intervening Stop.
pub(crate) fn from_engine_with_stop(
    engine: Engine,
    stop_epoch: Arc<AtomicU64>,
) -> (Controller, Execution) {
    let status = engine.status();
    let (requests, receiver) = RingBuffer::new(CAPACITY);
    let (reports, feedback) = RingBuffer::new(CAPACITY);
    let report = Report {
        status: engine.status(),
        stop_epoch: stop_epoch.load(Ordering::Acquire),
        rejected: None,
        superseded_requests: 0,
        lost_reports: 0,
    };
    (
        Controller {
            requests,
            reports: feedback,
            pending: None,
            stop_epoch: stop_epoch.clone(),
            revision: status.revision,
            coalesced: 0,
            rate: status.nominal_sample_rate,
            channels: status.output_channels,
            settings: status.settings,
        },
        Execution {
            engine,
            requests: receiver,
            reports,
            stop_epoch,
            report,
        },
    )
}

impl Controller {
    pub fn configure(&mut self, settings: Settings) -> Result<u64, Error> {
        self.request(settings, false, false)
    }

    pub fn start(&mut self, settings: Settings) -> Result<u64, Error> {
        self.request(settings, true, false)
    }

    pub fn align_phases(&mut self) -> Result<u64, Error> {
        self.request(self.settings, false, true)
    }

    fn request(&mut self, settings: Settings, start: bool, align: bool) -> Result<u64, Error> {
        self.submit(
            settings,
            start,
            align,
            self.stop_epoch.load(Ordering::Acquire),
        )
    }

    pub(crate) fn submit(
        &mut self,
        settings: Settings,
        start: bool,
        align: bool,
        stop_epoch: u64,
    ) -> Result<u64, Error> {
        settings.validate(self.rate, self.channels)?;
        let revision = self
            .revision
            .checked_add(1)
            .ok_or(Error::CounterExhausted)?;
        let mut request = Request {
            revision,
            settings,
            start,
            align,
            stop_epoch,
        };
        if let Some(old) = self.pending.take() {
            // Unsent Start/Align survives a newer edit of its settings.
            if old.stop_epoch == stop_epoch {
                request.start |= old.start;
                request.align |= old.align;
            }
            self.coalesced = self.coalesced.saturating_add(1);
        }
        self.settings = settings;
        self.revision = revision;
        self.pending = self
            .requests
            .push(request)
            .err()
            .map(|rtrb::PushError::Full(value)| value);
        Ok(revision)
    }

    /// True means no unsent snapshot remains, not that it has been applied.
    pub fn flush(&mut self) -> bool {
        if let Some(request) = self.pending.take() {
            self.pending = self
                .requests
                .push(request)
                .err()
                .map(|rtrb::PushError::Full(value)| value);
        }
        self.pending.is_none()
    }

    /// An independent priority fence also cancels all older queued Starts.
    pub fn stop(&mut self) -> Result<u64, Error> {
        let epoch = loop {
            let current = self.stop_epoch.load(Ordering::Acquire);
            let next = current.checked_add(1).ok_or(Error::CounterExhausted)?;
            if self
                .stop_epoch
                .compare_exchange(current, next, Ordering::AcqRel, Ordering::Acquire)
                .is_ok()
            {
                break next;
            }
        };
        self.pending = None;
        Ok(epoch)
    }

    pub fn coalesced_requests(&self) -> u64 {
        self.coalesced
    }

    /// Only execution reports are acknowledgements; a successful enqueue isn't.
    pub fn poll(&mut self) -> Option<Report> {
        let mut latest = None;
        for _ in 0..self.reports.slots().min(CAPACITY) {
            if let Ok(report) = self.reports.pop() {
                latest = Some(report);
            }
        }
        latest
    }
}

impl Execution {
    fn priority_stop(&mut self) {
        let epoch = self.stop_epoch.load(Ordering::Acquire);
        if epoch != self.report.stop_epoch {
            if let Err(error) = self.engine.stop() {
                self.engine.fail(error);
            }
            self.report.stop_epoch = epoch;
        }
    }

    /// Apply at the first frame of a block. The initial slot count bounds work,
    /// even when the producer submits continuously. No callback locks or waits.
    pub fn begin_block(&mut self) {
        self.priority_stop();
        for _ in 0..self.requests.slots().min(CAPACITY) {
            let Ok(request) = self.requests.pop() else {
                break;
            };
            self.priority_stop();
            if request.stop_epoch != self.report.stop_epoch {
                self.report.superseded_requests = self.report.superseded_requests.saturating_add(1);
                continue;
            }
            let result = if request.start {
                // Start already aligns both carriers to the same origin.
                self.engine.start(request.settings, request.revision)
            } else if request.align {
                self.engine
                    .configure_and_align(request.settings, request.revision)
            } else {
                self.engine.configure(request.settings, request.revision)
            };
            self.report.rejected = result.err().map(|error| Rejection {
                revision: request.revision,
                error,
            });
        }
    }

    pub fn next_frame(&mut self) -> Result<super::Frame, Error> {
        self.engine.next_frame()
    }

    pub fn fail(&mut self, error: Error) {
        self.engine.fail(error);
    }

    pub fn status(&self) -> Status {
        self.engine.status()
    }

    /// A missing feedback consumer can never stop generation. Loss is included
    /// in the next report; adapters must not treat these as a complete event log.
    pub fn end_block(&mut self) {
        self.report.status = self.engine.status();
        if self.reports.push(self.report).is_err() {
            self.report.lost_reports = self.report.lost_reports.saturating_add(1);
        }
    }
}
