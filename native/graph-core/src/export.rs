//! Bounded, non-real-time file worker for immutable snapshots and explicit codecs.
//! Submission shares an Arc, never encodes arrays or performs file I/O. This is
//! an evaluation boundary, not the product schema or a callback-safe API.
use crate::result::{Format, MeasurementResult};
use serde::Serialize;
use std::collections::VecDeque;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Condvar, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;

pub const MAX_SAVE_JOBS: usize = 8;
const MAX_PATH_BYTES: usize = 4096;
const MAX_RESULT_ID_BYTES: usize = 4096;

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum SaveStatus {
    Queued,
    Writing,
    Saved,
    Failed { kind: String, message: String },
    Cancelled,
}
impl SaveStatus {
    pub fn is_terminal(&self) -> bool {
        matches!(self, Self::Saved | Self::Failed { .. } | Self::Cancelled)
    }
}

/// Identity is copied from the submitted snapshot, never from current settings.
#[derive(Clone, Debug, Serialize)]
pub struct SaveReceipt<F = Format> {
    pub operation_id: u64,
    pub result_id: String,
    pub generation: u64,
    pub interval: [u64; 2],
    pub destination: PathBuf,
    pub format: F,
    pub status: SaveStatus,
}
struct Operation<F> {
    receipt: Mutex<SaveReceipt<F>>,
    changed: Condvar,
}
/// A ticket retains only a small receipt, not the numeric snapshot.
#[derive(Clone)]
pub struct SaveTicket<F = Format>(Arc<Operation<F>>);
impl<F: Copy> SaveTicket<F> {
    pub fn receipt(&self) -> SaveReceipt<F> {
        self.0.receipt.lock().unwrap().clone()
    }
    /// Pending-only cancellation. false means writing or completion already won;
    /// a file that may have committed must never be reported as cancelled.
    pub fn cancel(&self) -> bool {
        let mut receipt = self.0.receipt.lock().unwrap();
        if receipt.status != SaveStatus::Queued {
            return false;
        }
        receipt.status = SaveStatus::Cancelled;
        self.0.changed.notify_all();
        true
    }
    /// Control/test thread only; a timeout returns the current, possibly pending receipt.
    pub fn wait(&self, timeout: Duration) -> SaveReceipt<F> {
        self.0
            .changed
            .wait_timeout_while(self.0.receipt.lock().unwrap(), timeout, |receipt| {
                !receipt.status.is_terminal()
            })
            .unwrap()
            .0
            .clone()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SubmitError {
    Busy,
    Closed,
    InvalidDestination,
    IdentityTooLarge,
    OperationIdExhausted,
}
impl std::fmt::Display for SubmitError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "save_{self:?}")
    }
}
impl std::error::Error for SubmitError {}

#[derive(Clone, Copy, Debug)]
pub enum CloseMode {
    Drain,
    CancelPending,
}
struct Request<F> {
    snapshot: Arc<MeasurementResult>,
    path: PathBuf,
    format: F,
    ticket: SaveTicket<F>,
}
struct State<F> {
    queue: VecDeque<Request<F>>,
    outstanding: usize,
    capacity: usize,
    next_id: u64,
    closed: bool,
    worker_panicked: bool,
}
struct Shared<F> {
    state: Mutex<State<F>>,
    ready: Condvar,
}

/// Capacity counts queued plus writing operations. It is a job-count bound,
/// not a total byte budget; snapshot size limits remain those of MeasurementResult.
pub struct SaveWorker<F: Copy + Send + 'static = Format> {
    shared: Arc<Shared<F>>,
    thread: Option<JoinHandle<()>>,
}
impl SaveWorker {
    pub fn start(capacity: usize) -> io::Result<Self> {
        Self::with_writer(capacity, MeasurementResult::save_new)
    }
}
impl SaveWorker<crate::product::ProductFormat> {
    pub fn start_product(capacity: usize) -> io::Result<Self> {
        Self::with_writer(capacity, crate::product::save_new)
    }
}
impl<F: Copy + Send + 'static> SaveWorker<F> {
    /// Explicit codec seam for non-real-time adapters. A successful writer must
    /// finish sync/no-clobber publication before returning Ok. The default uses
    /// MeasurementResult::save_new; injected writers also enable bounded queue
    /// and slow-I/O ownership checks without timing-dependent filesystem tricks.
    pub fn with_writer(
        capacity: usize,
        writer: impl Fn(&MeasurementResult, &Path, F) -> io::Result<()> + Send + 'static,
    ) -> io::Result<Self> {
        if !(1..=MAX_SAVE_JOBS).contains(&capacity) {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "save_capacity"));
        }
        let shared = Arc::new(Shared {
            state: Mutex::new(State {
                queue: VecDeque::with_capacity(capacity),
                outstanding: 0,
                capacity,
                next_id: 1,
                closed: false,
                worker_panicked: false,
            }),
            ready: Condvar::new(),
        });
        let worker = Arc::clone(&shared);
        let thread = thread::Builder::new()
            .name("measurement-save".into())
            .spawn(move || run(worker, writer))?;
        Ok(Self {
            shared,
            thread: Some(thread),
        })
    }
    /// Nonblocking with respect to disk I/O. Mutex/allocation/Arc operations mean
    /// this API belongs to control threads, never an audio callback.
    pub fn submit(
        &self,
        snapshot: Arc<MeasurementResult>,
        path: PathBuf,
        format: F,
    ) -> Result<SaveTicket<F>, SubmitError> {
        if path.file_name().is_none()
            || path.as_os_str().as_encoded_bytes().len() > MAX_PATH_BYTES
            || path.as_os_str().as_encoded_bytes().contains(&0)
        {
            return Err(SubmitError::InvalidDestination);
        }
        if snapshot.capture().result_id.len() > MAX_RESULT_ID_BYTES {
            return Err(SubmitError::IdentityTooLarge);
        }
        let mut state = self.shared.state.lock().unwrap();
        if state.closed {
            return Err(SubmitError::Closed);
        }
        if state.outstanding == state.capacity {
            return Err(SubmitError::Busy);
        }
        let id = state.next_id;
        state.next_id = id.checked_add(1).ok_or(SubmitError::OperationIdExhausted)?;
        let ticket = SaveTicket(Arc::new(Operation {
            receipt: Mutex::new(SaveReceipt {
                operation_id: id,
                result_id: snapshot.capture().result_id.clone(),
                generation: snapshot.source().generation,
                interval: snapshot.interval(),
                destination: path.clone(),
                format,
                status: SaveStatus::Queued,
            }),
            changed: Condvar::new(),
        }));
        state.queue.push_back(Request {
            snapshot,
            path,
            format,
            ticket: ticket.clone(),
        });
        state.outstanding += 1;
        self.shared.ready.notify_one();
        Ok(ticket)
    }
    /// Stops admission immediately; writing jobs retain their actual outcome.
    /// CancelPending may escalate an earlier Drain. No filesystem waits here.
    pub fn close(&self, mode: CloseMode) {
        let cancelled = {
            let mut state = self.shared.state.lock().unwrap();
            state.closed = true;
            let cancelled = if matches!(mode, CloseMode::CancelPending) {
                let queue = std::mem::take(&mut state.queue);
                for request in &queue {
                    request.ticket.cancel();
                }
                state.outstanding -= queue.len();
                queue
            } else {
                VecDeque::new()
            };
            self.shared.ready.notify_one();
            cancelled
        };
        // Release potentially large snapshots outside the control mutex.
        drop(cancelled);
    }
    /// Blocking shutdown for a teardown/control thread. Slow OS writes cannot
    /// be interrupted safely; Qt must dispatch joining away from its GUI thread.
    pub fn join(&mut self) -> io::Result<()> {
        self.close(CloseMode::Drain);
        if let Some(thread) = self.thread.take() {
            thread
                .join()
                .map_err(|_| io::Error::other("save_worker_panicked"))?;
        }
        if self.shared.state.lock().unwrap().worker_panicked {
            return Err(io::Error::other("save_worker_panicked"));
        }
        Ok(())
    }
}
impl<F: Copy + Send + 'static> Drop for SaveWorker<F> {
    fn drop(&mut self) {
        self.close(CloseMode::CancelPending);
        let _ = self.join();
    }
}

fn run<F: Copy>(
    shared: Arc<Shared<F>>,
    writer: impl Fn(&MeasurementResult, &Path, F) -> io::Result<()>,
) {
    loop {
        let (request, write) = {
            let state = shared.state.lock().unwrap();
            let mut state = shared
                .ready
                .wait_while(state, |s| s.queue.is_empty() && !s.closed)
                .unwrap();
            let Some(request) = state.queue.pop_front() else {
                break;
            };
            let write = {
                let mut receipt = request.ticket.0.receipt.lock().unwrap();
                if receipt.status == SaveStatus::Queued {
                    receipt.status = SaveStatus::Writing;
                    request.ticket.0.changed.notify_all();
                    true
                } else {
                    false
                }
            };
            (request, write)
        };
        let mut panicked = false;
        let outcome = write.then(|| {
            match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                writer(&request.snapshot, &request.path, request.format)
            })) {
                Ok(Ok(())) => SaveStatus::Saved,
                Ok(Err(error)) => SaveStatus::Failed {
                    kind: format!("{:?}", error.kind()),
                    message: error.to_string(),
                },
                Err(_) => {
                    panicked = true;
                    SaveStatus::Failed {
                        kind: "WorkerPanicked".into(),
                        message: "save worker panicked; publication state unknown".into(),
                    }
                }
            }
        });
        // Tickets retain metadata only; release arrays before advertising capacity.
        drop(request.snapshot);
        let mut state = shared.state.lock().unwrap();
        state.outstanding -= 1;
        if let Some(status) = outcome {
            request.ticket.0.receipt.lock().unwrap().status = status;
            request.ticket.0.changed.notify_all();
        }
        if panicked {
            state.closed = true;
            state.worker_panicked = true;
            let cancelled = std::mem::take(&mut state.queue);
            state.outstanding -= cancelled.len();
            for pending in &cancelled {
                pending.ticket.cancel();
            }
            drop(state);
            drop(cancelled);
            break;
        }
    }
}

#[cfg(test)]
pub(crate) mod tests;
