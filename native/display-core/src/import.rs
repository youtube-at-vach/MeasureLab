//! Independent, bounded file reader. Qt polls receipts and a sampled preview;
//! the full validated product never enters the acquisition/calibration owner.
use super::*;
use graph_core::product::{self, ImportedProduct, ProductFormat};
use serde::Serialize;
use serde_json::Value;
use std::collections::VecDeque;
use std::sync::{Condvar, OnceLock};

const HISTORY: usize = 16;
const MAX_SESSIONS: usize = 8;
static SESSIONS: AtomicUsize = AtomicUsize::new(0);
static REAPERS: OnceLock<Mutex<Vec<JoinHandle<()>>>> = OnceLock::new();
static OPERATIONS: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Submission {
    path: PathBuf,
    format: String,
    #[serde(default)]
    spec: Option<PathBuf>,
}
#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
enum Status {
    Queued,
    Reading,
    Loaded,
    Failed { message: String },
    Cancelled,
}
impl Status {
    fn terminal(&self) -> bool {
        !matches!(self, Self::Queued | Self::Reading)
    }
}
#[derive(Clone, Serialize)]
struct Receipt {
    operation_id: u64,
    #[serde(flatten)]
    submission: Submission,
    status: Status,
}
struct Loaded {
    // Retain every original array, metadata, null/reason and full snapshot.
    // Replacement and destruction occur on the reader/reaper, never in Qt.
    _product: ImportedProduct,
    preview: Arc<String>,
    operation_id: u64,
}
#[derive(Default)]
struct Mailbox {
    queue: VecDeque<u64>,
    receipts: Vec<Receipt>,
    inflight: usize,
    latest: u64,
    closed: bool,
    displayed: Option<Loaded>,
}
struct Worker {
    shared: Arc<(Mutex<Mailbox>, Condvar)>,
    thread: JoinHandle<()>,
}
#[derive(Default)]
pub(super) struct Controller {
    worker: Option<Worker>,
    rejection: Option<String>,
    closed: bool,
}

/// The preview samples original indices without interpolation or recalibration.
/// Bounded numeric/text projection; full metadata stays in ImportedProduct.
fn preview(product: &ImportedProduct) -> Result<String, String> {
    let document = product.document();
    let traces = document["traces"].as_array().unwrap();
    // Never shorten an ID, physical unit or descriptor into another meaning.
    for trace in traces {
        let fields = ["id", "name", "source_module", "timestamp"].map(|key| &trace[key]);
        let axes = ["x_axis", "y_axis", "y2_axis"]
            .into_iter()
            .flat_map(|axis| {
                ["dimension", "base_unit", "display_unit"].map(|key| &trace[axis][key])
            });
        if fields
            .into_iter()
            .chain(axes)
            .any(|v| v.as_str().is_some_and(|s| s.chars().count() > 256))
        {
            return Err("import_preview_text_capacity".into());
        }
    }
    let budget = (8192 / (3 * traces.len().max(1))).clamp(2, 256);
    let text = |value: &Value| -> Value { Value::String(value.as_str().unwrap_or("").into()) };
    let axis = |value: &Value| -> Value {
        if value.is_null() {
            Value::Null
        } else {
            json!({"dimension": text(&value["dimension"]), "base_unit": text(&value["base_unit"]),
                "display_unit": text(&value["display_unit"]), "is_log": value["is_log"]})
        }
    };
    // QML JSON.stringify changes -0 into 0. Display decimal tokens verbatim;
    // the owned product still contains the original finite f64 arrays.
    let numeric = |value: &Value| Value::String(value.to_string());
    let traces: Vec<_> = traces.iter().map(|trace| {
        let n = trace["x_data"].as_array().unwrap().len();
        let count = n.min(budget);
        let indexes: Vec<_> = (0..count).map(|i| if count <= 1 { 0 } else { i * (n - 1) / (count - 1) }).collect();
        json!({"id": text(&trace["id"]), "name": text(&trace["name"]),
            "source_module": text(&trace["source_module"]), "timestamp": text(&trace["timestamp"]),
            "x_axis": axis(&trace["x_axis"]), "y_axis": axis(&trace["y_axis"]), "y2_axis": axis(&trace["y2_axis"]),
            "is_calibrated": trace["calibration"]["is_calibrated"], "original_count": n,
            "rows": indexes.iter().map(|&i| json!({"index": i, "x": numeric(&trace["x_data"][i]),
                "y": numeric(&trace["y_data"][i]), "y2": trace["y2_data"].as_array().map(|a| numeric(&a[i]))})).collect::<Vec<_>>()})
    }).collect();
    let encoded = json!({"has_snapshot": product.snapshot().is_some(), "sample_relation": product.sample_relation(),
        "invalid_spans": product.snapshot().map(|s| s.validity().len()), "error": product.snapshot().and_then(|s| s.error()),
        "traces": traces}).to_string();
    if encoded.len() > 1024 * 1024 {
        return Err("import_preview_byte_capacity".into());
    }
    Ok(encoded)
}
fn load(submission: &Submission, operation_id: u64) -> Result<Loaded, String> {
    let product = match submission.format.as_str() {
        "product_json" => product::load_import(&submission.path, ProductFormat::ProductJson),
        "product_csv" => product::load_import(&submission.path, ProductFormat::ProductCsv),
        "csv_spec" => {
            product::load_csv_with_spec(&submission.path, submission.spec.as_ref().unwrap())
        }
        _ => unreachable!("validated submission"),
    }?;
    let preview = Arc::new(preview(&product)?);
    // Explicit diagnostic output only, on the file worker and outside Qt locks.
    if let Some(directory) = std::env::var_os("MEASURELAB_IMPORT_EVIDENCE") {
        let directory = PathBuf::from(directory);
        std::fs::create_dir_all(&directory).map_err(|e| e.to_string())?;
        use std::io::Write;
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(directory.join(format!("import-{operation_id}.json")))
            .map_err(|e| e.to_string())?;
        serde_json::to_writer(&mut file, &product.to_value()).map_err(|e| e.to_string())?;
        file.flush().map_err(|e| e.to_string())?;
    }
    Ok(Loaded {
        preview,
        _product: product,
        operation_id,
    })
}
impl Controller {
    fn start(
        &mut self,
        loader: impl Fn(&Submission, u64) -> Result<Loaded, String> + Send + 'static,
    ) -> Result<(), String> {
        SESSIONS
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |n| {
                (n < MAX_SESSIONS).then_some(n + 1)
            })
            .map_err(|_| "busy")?;
        let shared = Arc::new((Mutex::new(Mailbox::default()), Condvar::new()));
        let owner = Arc::clone(&shared);
        let thread = thread::spawn(move || {
            loop {
                let (id, submission) = {
                    let (lock, changed) = &*owner;
                    let mut slot = changed
                        .wait_while(lock.lock().unwrap(), |s| s.queue.is_empty() && !s.closed)
                        .unwrap();
                    let Some(id) = slot.queue.pop_front() else {
                        break;
                    };
                    let receipt = slot
                        .receipts
                        .iter_mut()
                        .find(|r| r.operation_id == id)
                        .unwrap();
                    receipt.status = Status::Reading;
                    (id, receipt.submission.clone())
                };
                let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    loader(&submission, id)
                }))
                .unwrap_or_else(|_| Err("import_worker_panic".into()));
                let old = {
                    let mut slot = owner.0.lock().unwrap();
                    slot.inflight -= 1;
                    let receipt = slot
                        .receipts
                        .iter_mut()
                        .find(|r| r.operation_id == id)
                        .unwrap();
                    match &result {
                        Ok(_) => receipt.status = Status::Loaded,
                        Err(message) => {
                            receipt.status = Status::Failed {
                                message: message.chars().take(1024).collect(),
                            }
                        }
                    }
                    if slot.latest == id && !slot.closed {
                        std::mem::replace(&mut slot.displayed, result.ok())
                    } else {
                        None
                    }
                };
                drop(old); // expensive destruction outside the mailbox lock
            }
        });
        self.worker = Some(Worker { shared, thread });
        Ok(())
    }
    fn submit(&mut self, encoded: &str) -> Result<(), String> {
        if self.closed {
            return Err("closed".into());
        }
        if encoded.len() > 16384 {
            return Err("invalid_request".into());
        }
        let submission: Submission =
            serde_json::from_str(encoded).map_err(|_| "invalid_request")?;
        let valid_path = |p: &PathBuf| !p.as_os_str().is_empty() && p.as_os_str().len() <= 4096;
        if !valid_path(&submission.path)
            || submission.spec.as_ref().is_some_and(|p| !valid_path(p))
            || !matches!(
                submission.format.as_str(),
                "product_json" | "product_csv" | "csv_spec"
            )
            || (submission.format == "csv_spec") != submission.spec.is_some()
        {
            return Err("invalid_request".into());
        }
        if self.worker.is_none() {
            self.start(load)?;
        }
        let shared = &self.worker.as_ref().unwrap().shared;
        let mut slot = shared.0.lock().unwrap();
        if slot.inflight == 2 {
            return Err("busy".into());
        }
        let id = OPERATIONS
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |n| n.checked_add(1))
            .map_err(|_| "identity_exhausted")?;
        if slot.receipts.len() == HISTORY {
            let i = slot
                .receipts
                .iter()
                .position(|r| r.status.terminal())
                .unwrap();
            slot.receipts.remove(i);
        }
        slot.latest = id;
        slot.inflight += 1;
        slot.queue.push_back(id);
        slot.receipts.push(Receipt {
            operation_id: id,
            submission,
            status: Status::Queued,
        });
        shared.1.notify_one();
        Ok(())
    }
    fn cancel(slot: &mut Mailbox, id: u64) -> bool {
        let Some(receipt) = slot.receipts.iter_mut().find(|r| r.operation_id == id) else {
            return false;
        };
        if receipt.status != Status::Queued {
            return false;
        }
        receipt.status = Status::Cancelled;
        slot.queue.retain(|&queued| queued != id);
        slot.inflight -= 1;
        true
    }
    fn close(&mut self) {
        self.closed = true;
        if let Some(worker) = &self.worker {
            let mut slot = worker.shared.0.lock().unwrap();
            slot.closed = true;
            slot.latest = 0;
            for id in slot.queue.clone() {
                Self::cancel(&mut slot, id);
            }
            worker.shared.1.notify_one();
        }
    }
}
impl Display {
    pub fn import_product(&mut self, encoded: &str) -> bool {
        match self.imports.submit(encoded) {
            Ok(()) => {
                self.imports.rejection = None;
                true
            }
            Err(error) => {
                self.imports.rejection = Some(error);
                false
            }
        }
    }
    /// Latest admitted request alone may be displayed. A failed/cancelled newest
    /// request cannot expose an older result, including after close or recreation.
    pub fn poll_imports(&self) -> String {
        let (receipts, preview, latest) = match &self.imports.worker {
            None => (Vec::new(), None, 0),
            Some(worker) => {
                let slot = worker.shared.0.lock().unwrap();
                (
                    slot.receipts.clone(),
                    slot.displayed
                        .as_ref()
                        .filter(|d| d.operation_id == slot.latest && !slot.closed)
                        .map(|d| Arc::clone(&d.preview)),
                    slot.latest,
                )
            }
        };
        json!({"schema_version": 1, "closed": self.imports.closed, "rejection": self.imports.rejection,
            "latest": latest, "receipts": receipts, "preview": preview.as_deref()}).to_string()
    }
    pub fn cancel_import(&self, id: u64) -> bool {
        self.imports
            .worker
            .as_ref()
            .is_some_and(|w| Controller::cancel(&mut w.shared.0.lock().unwrap(), id))
    }
    pub fn close_imports(&mut self) {
        self.imports.close();
    }
}
impl Drop for Controller {
    fn drop(&mut self) {
        self.close();
        if let Some(worker) = self.worker.take() {
            let mut reapers = REAPERS.get_or_init(Mutex::default).lock().unwrap();
            reapers.retain(|t| !t.is_finished());
            reapers.push(thread::spawn(move || {
                let error = worker.thread.join().err().map(|_| "import_thread_panic");
                let receipts = worker.shared.0.lock().unwrap().receipts.clone();
                drop(worker.shared); // owns full imported product; GUI never drops it
                println!(
                    "DISPLAY_IMPORT_RETIRED {}",
                    json!({"error": error, "receipts": receipts})
                );
                SESSIONS.fetch_sub(1, Ordering::SeqCst);
            }));
        }
    }
}
pub fn finish_imports() {
    if let Some(reapers) = REAPERS.get() {
        for reaper in std::mem::take(&mut *reapers.lock().unwrap()) {
            reaper.join().expect("import teardown thread");
        }
    }
    assert_eq!(SESSIONS.load(Ordering::SeqCst), 0);
    println!("DISPLAY_IMPORT_TEARDOWN sessions=0");
}

#[cfg(test)]
mod tests;
