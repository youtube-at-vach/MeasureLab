//! Qt control boundary. Pin the presented result, never reconstruct it from QML.
//! File I/O and writer teardown stay outside Qt and the acquisition owner.
use super::*;
use graph_core::export::{CloseMode, SaveTicket, SaveWorker};
use graph_core::product::{self, ProductFormat};
use serde::Serialize;
use std::sync::OnceLock;

const MAX_SESSIONS: usize = 8;
const HISTORY: usize = 16;
static SESSIONS: AtomicUsize = AtomicUsize::new(0);
static REAPERS: OnceLock<Mutex<Vec<JoinHandle<()>>>> = OnceLock::new();

/// One queue and operation sequence for all formats, including CSV/sidecar pairs.
#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
enum SaveFormat {
    Json,
    Csv,
    ProductJson,
    ProductCsv,
}
impl SaveFormat {
    fn write(
        result: &MeasurementResult,
        path: &std::path::Path,
        format: Self,
    ) -> std::io::Result<()> {
        match format {
            Self::Json => result.save_new(path, Format::Json),
            Self::Csv => result.save_new(path, Format::Csv),
            Self::ProductJson => product::save_new(result, path, ProductFormat::ProductJson),
            Self::ProductCsv => product::save_new(result, path, ProductFormat::ProductCsv),
        }
    }
}

#[derive(Default)]
pub(super) struct Controller {
    presented: Vec<Arc<Frame>>,
    pinned: Option<Arc<MeasurementResult>>,
    worker: Option<SaveWorker<SaveFormat>>,
    tickets: Vec<SaveTicket<SaveFormat>>,
    rejection: Option<String>,
    closed: bool,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Submission {
    generation: u64,
    result_id: String,
    destination: PathBuf,
    format: String,
}
impl Controller {
    fn submit(&mut self, encoded: &str, delay_ms: u64) -> Result<(), String> {
        if self.closed {
            return Err("closed".into());
        }
        if encoded.len() > 16384 {
            return Err("invalid_request".into());
        }
        let submission: Submission =
            serde_json::from_str(encoded).map_err(|_| "invalid_request")?;
        let format = match submission.format.as_str() {
            "json" => SaveFormat::Json,
            "csv" => SaveFormat::Csv,
            "product_json" => SaveFormat::ProductJson,
            "product_csv" => SaveFormat::ProductCsv,
            _ => return Err("invalid_format".into()),
        };
        let snapshot = self.pinned.as_ref().ok_or("no_result")?;
        if snapshot.source().generation != submission.generation
            || snapshot.capture().result_id != submission.result_id
        {
            return Err("stale_result".into());
        }
        if self.worker.is_none() {
            SESSIONS
                .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |n| {
                    (n < MAX_SESSIONS).then_some(n + 1)
                })
                .map_err(|_| "busy")?;
            match SaveWorker::with_writer(2, move |result, path, format| {
                if delay_ms != 0 {
                    thread::sleep(Duration::from_millis(delay_ms));
                }
                SaveFormat::write(result, path, format)
            }) {
                Ok(worker) => self.worker = Some(worker),
                Err(error) => {
                    SESSIONS.fetch_sub(1, Ordering::SeqCst);
                    return Err(error.to_string());
                }
            }
        }
        let ticket = self
            .worker
            .as_ref()
            .unwrap()
            .submit(Arc::clone(snapshot), submission.destination, format)
            .map_err(|e| match e {
                graph_core::export::SubmitError::Busy => "busy".to_string(),
                graph_core::export::SubmitError::Closed => "closed".to_string(),
                _ => e.to_string(),
            })?;
        if self.tickets.len() == HISTORY {
            let index = self
                .tickets
                .iter()
                .position(|t| t.receipt().status.is_terminal())
                .expect("only two jobs can be outstanding");
            self.tickets.remove(index);
        }
        self.tickets.push(ticket);
        Ok(())
    }
}
impl Display {
    /// Called before publishing Qt properties. Keeps the full result that produced
    /// those properties, even if the analysis mailbox advances before the click.
    pub fn present(&mut self, snapshot: &Snapshot) {
        self.saves.presented.clear();
        if let Some(frame) = &snapshot.frame {
            self.saves.presented.push(Arc::clone(frame));
        }
        if let Some(frame) = snapshot.trigger.as_ref().and_then(|r| r.frame.as_ref()) {
            self.saves.presented.push(Arc::clone(frame));
        }
    }
    /// Dialog entry: pending/gap/error have no result to pin. No numeric copies.
    pub fn pin_result(&mut self, generation: u64, result_id: &str) -> bool {
        let frame = self.saves.presented.iter().find(|f| {
            f.result.source().generation == generation && f.result.capture().result_id == result_id
        });
        self.saves.pinned = frame.map(|f| Arc::clone(&f.result));
        self.saves.pinned.is_some()
    }
    pub fn release_save_result(&mut self) {
        self.saves.pinned = None;
    }
    /// true is admission, not completion. An accepted job owns the pinned Arc.
    pub fn save_result(&mut self, encoded: &str) -> bool {
        let delay = self
            .request
            .as_ref()
            .map_or(0, |r| r.save_diagnostic_delay_ms);
        if delay != 0 && self.request.as_ref().is_some_and(|r| r.validate().is_err()) {
            self.saves.rejection = Some("invalid_request".into());
            return false;
        }
        match self.saves.submit(encoded, delay) {
            Ok(()) => {
                self.saves.rejection = None;
                true
            }
            Err(reason) => {
                self.saves.rejection = Some(reason);
                false
            }
        }
    }
    /// Small receipts only. Polling works while acquisition is stopped or held.
    pub fn poll_saves(&self) -> String {
        json!({"schema_version": 1, "closed": self.saves.closed,
            "rejection": self.saves.rejection,
            "receipts": self.saves.tickets.iter().map(SaveTicket::receipt).collect::<Vec<_>>()})
        .to_string()
    }
    pub fn cancel_save(&self, operation_id: u64) -> bool {
        self.saves
            .tickets
            .iter()
            .find(|t| t.receipt().operation_id == operation_id)
            .is_some_and(SaveTicket::cancel)
    }
    pub fn close_saves(&mut self) {
        self.saves.closed = true;
        if let Some(worker) = &self.saves.worker {
            worker.close(CloseMode::CancelPending);
        }
    }
}
impl Drop for Controller {
    fn drop(&mut self) {
        if let Some(mut worker) = self.worker.take() {
            worker.close(CloseMode::CancelPending);
            let tickets = std::mem::take(&mut self.tickets);
            // Bounded by MAX_SESSIONS, including retired workers still writing.
            let mut reapers = REAPERS.get_or_init(Mutex::default).lock().unwrap();
            reapers.retain(|thread| !thread.is_finished());
            reapers.push(thread::spawn(move || {
                let outcome = worker.join().err().map(|e| e.to_string());
                drop(worker);
                println!(
                    "DISPLAY_SAVE_RETIRED {}",
                    json!({"error": outcome,
                    "receipts": tickets.iter().map(SaveTicket::receipt).collect::<Vec<_>>() })
                );
                SESSIONS.fetch_sub(1, Ordering::SeqCst);
            }));
        }
    }
}
/// Application entry points call this only after the Qt event loop and QObjects
/// have ended. Every accepted writing operation retains its real final outcome.
pub fn finish_saves() {
    if let Some(reapers) = REAPERS.get() {
        for thread in std::mem::take(&mut *reapers.lock().unwrap()) {
            thread.join().expect("save teardown thread");
        }
    }
    assert_eq!(SESSIONS.load(Ordering::SeqCst), 0);
    println!("DISPLAY_SAVE_TEARDOWN sessions=0");
}

#[cfg(test)]
mod tests;
