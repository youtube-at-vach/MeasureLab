//! MIG-007-A replay/live input through the real acquisition/history/shared FFT.
//! This is an analysis thread, never an audio callback. Qt receives one immutable
//! projection; GUI notification replacement does not discard acquisition data.
#![forbid(unsafe_code)]
use audio_core::backend::Backend;
use audio_core::{IoFormat, Producer, frame_queue, frame_queue_f64};
use graph_core::acquisition::{Acquisition, CaptureLimits, CaptureSample, FftSpec};
use graph_core::history::HistoryLimits;
use graph_core::result::{Capture, Format, MeasurementResult};
use graph_core::{Average, FftResult, Precision, Presentation, Subscription, WindowSpec};
use probe_core::State;
use serde::Deserialize;
use serde_json::json;
use std::collections::{BTreeMap, HashSet};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;

static GENERATION: AtomicU64 = AtomicU64::new(0);
static TOKEN: AtomicU64 = AtomicU64::new(0);
static WORKERS: AtomicUsize = AtomicUsize::new(0);
static MODELS: AtomicUsize = AtomicUsize::new(0);
const MAX_INPUT_BYTES: u64 = 4096 * 16 * 8;
const MAX_DEMAND: usize = 16;

mod calibration;
pub mod locale;
pub use calibration::ChannelCalibration;
mod trigger;
pub use trigger::TriggerResponse;
mod save;
pub use save::finish_saves;
mod import;
pub use import::finish_imports;

#[cfg(feature = "live-audio")]
mod live;

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LiveRequest {
    pub device: String,
    pub device_channels: usize,
    #[serde(default = "cpal_backend")]
    pub backend: Backend,
    /// Required absolute path for the native PortAudio v19 callback evaluation.
    pub library: Option<PathBuf>,
}
fn cpal_backend() -> Backend {
    Backend::Cpal
}
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub format: IoFormat,
    pub precision: Precision,
    pub n: usize,
    pub window: WindowSpec,
    pub input: Option<PathBuf>,
    pub live: Option<LiveRequest>,
    /// Optional directory for each generation's first-result evidence.
    pub evidence: Option<PathBuf>,
    /// Bounded raw-window evidence for the opt-in live save correctness exercise.
    #[serde(default)]
    pub save_input_evidence: bool,
    /// Injected writer latency, not a measured disk or performance result.
    #[serde(default)]
    pub save_diagnostic_delay_ms: u64,
    #[serde(default)]
    pub calibration: Vec<ChannelCalibration>,
}
impl Request {
    fn validate(&self) -> Result<(), String> {
        let channels = self.format.input_ids.len();
        if !(3..=4096).contains(&self.n) || channels == 0 || channels > 16 {
            return Err("display_input_capacity".into());
        }
        if self.save_diagnostic_delay_ms > 500
            || (self.save_input_evidence && (self.live.is_none() || self.evidence.is_none()))
            || (self.save_diagnostic_delay_ms != 0 && !self.save_input_evidence)
        {
            return Err("display_save_diagnostic_configuration".into());
        }
        match (&self.input, &self.live) {
            (Some(_), None) => self.format.validate(channels, 0).map_err(String::from),
            (None, Some(live)) => {
                if self.precision != Precision::F32
                    || self.format.rate != [48000, 1]
                    || live.device.trim().is_empty()
                    || !(1..=16).contains(&live.device_channels)
                    || self.format.clock_domain
                        != format!(
                            "{}.device:{}",
                            match live.backend {
                                Backend::Cpal => "cpal",
                                Backend::PortAudio => "portaudio",
                            },
                            live.device
                        )
                    || match (live.backend, &live.library) {
                        (Backend::Cpal, None) => false,
                        (Backend::PortAudio, Some(path)) => !path.is_absolute(),
                        _ => true,
                    }
                {
                    return Err("display_live_configuration".into());
                }
                self.format
                    .validate(live.device_channels, 0)
                    .map_err(String::from)
            }
            _ => Err("display_input_source".into()),
        }?;
        self.validate_calibration()
    }
    fn bytes(&self) -> Result<Vec<u8>, String> {
        self.validate()?;
        let channels = self.format.input_ids.len();
        let width = if self.precision == Precision::F32 {
            4
        } else {
            8
        };
        let expected = self.n * channels * width;
        let file = std::fs::File::open(self.input.as_ref().ok_or("display_input_source")?)
            .map_err(|e| e.to_string())?;
        if file.metadata().map_err(|e| e.to_string())?.len() != expected as u64 {
            return Err("display_input_shape".into());
        }
        // A changing file cannot cause an unbounded read.
        use std::io::Read;
        let mut bytes = Vec::new();
        file.take(MAX_INPUT_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|e| e.to_string())?;
        if bytes.len() != expected {
            return Err("display_input_shape".into());
        }
        Ok(bytes)
    }
}

#[derive(Debug)]
pub struct Frame {
    pub result: Arc<MeasurementResult>,
    pub projection: String,
}
/// All full precision bins survive. Only rasterization maps values to pixels.
pub fn project(raw: &FftResult) -> Result<Frame, String> {
    let id = format!("{}:{}", raw.id().graph, raw.id().serial);
    let result = MeasurementResult::from_fft(
        raw,
        Capture {
            result_id: id.clone(),
            trigger_id: None,
            acquired_host_seconds: None,
            result_host_seconds: None,
            trigger: None,
            clock_mapping: None,
        },
        &BTreeMap::new(),
        1.,
    )?;
    project_result(Arc::new(result))
}
fn project_result(result: Arc<MeasurementResult>) -> Result<Frame, String> {
    let projection = serde_json::to_string(&json!({
        "schema_version": 1, "result_id": result.capture().result_id,
        "source": result.source(), "interval": result.interval(),
        "frequency_hz": result.corrected_frequencies(),
        "peak_fs": result.column_value("peak_fs").ok_or("display_peak_column")?,
        "validity": result.validity(), "error": result.error(),
        "clock_origin": "unknown", "calibration": result.calibration_status(),
        "channel_calibration": result.calibration_value(),
        "rms_v": result.column_value("rms_v").ok_or("display_voltage_column")?,
        "dbv": result.column_value("dbv").ok_or("display_dbv_column")?,
        "capture": result.capture(),
        "raw_result_id": result.raw_result_id(),
    }))
    .map_err(|e| e.to_string())?;
    Ok(Frame { result, projection })
}

#[derive(Clone, Debug, Default)]
pub struct Snapshot {
    pub state: State,
    pub outcome: i32,
    pub generation: u64,
    pub produced: u64,
    pub coalesced: u64,
    pub shared: bool,
    pub reclaimed: bool,
    pub error: String,
    pub frame: Option<Arc<Frame>>,
    pub trigger: Option<Arc<TriggerResponse>>,
    pub calibration: String,
}
#[derive(Default)]
struct Mailbox {
    snapshot: Snapshot,
    pending: bool,
    demand: HashSet<u64>,
    trigger: trigger::Controller,
    calibration: calibration::Controller,
}
pub struct Display {
    mailbox: Arc<Mutex<Mailbox>>,
    stop: Arc<AtomicBool>,
    worker: Option<JoinHandle<()>>,
    request: Option<Request>,
    saves: save::Controller,
    imports: import::Controller,
}
impl Default for Display {
    fn default() -> Self {
        MODELS.fetch_add(1, Ordering::SeqCst);
        Self {
            mailbox: Arc::default(),
            stop: Arc::default(),
            worker: None,
            request: None,
            saves: save::Controller::default(),
            imports: import::Controller::default(),
        }
    }
}
impl Display {
    pub fn with_request(request: Request) -> Self {
        let mut display = Self::default();
        display.request = Some(request);
        display
    }
    pub fn subscribe(&mut self) -> u64 {
        let mut slot = self.mailbox.lock().unwrap();
        if slot.demand.len() == MAX_DEMAND {
            return 0;
        }
        let token = TOKEN.fetch_add(1, Ordering::SeqCst) + 1;
        slot.demand.insert(token);
        token
    }
    pub fn unsubscribe(&mut self, token: u64) -> bool {
        let mut slot = self.mailbox.lock().unwrap();
        if !slot.demand.remove(&token) {
            return false;
        }
        if slot.demand.is_empty() {
            self.stop.store(true, Ordering::Release);
        }
        true
    }
    pub fn subscribers(&self) -> usize {
        self.mailbox.lock().unwrap().demand.len()
    }
    pub fn start(
        &mut self,
        fail: bool,
        notify: impl Fn(u64) -> bool + Send + 'static,
    ) -> Option<u64> {
        if self.subscribers() == 0 || self.worker.as_ref().is_some_and(|w| !w.is_finished()) {
            return None;
        }
        self.join();
        let generation = GENERATION.fetch_add(1, Ordering::SeqCst) + 1;
        self.stop.store(false, Ordering::Release);
        {
            let mut slot = self.mailbox.lock().unwrap();
            slot.snapshot = Snapshot {
                generation,
                state: State::Preparing,
                ..Snapshot::default()
            };
            slot.pending = false;
            slot.trigger = trigger::Controller::default();
            slot.calibration = calibration::Controller::default();
        }
        let request = self.request.clone();
        let owner = Owner {
            mailbox: self.mailbox.clone(),
            stop: self.stop.clone(),
        };
        self.worker = Some(thread::spawn(move || {
            WORKERS.fetch_add(1, Ordering::SeqCst);
            let result =
                std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| -> Result<(), String> {
                    // Preparation is cancellable; configuration/file parsing is worker-owned.
                    for _ in 0..12 {
                        if owner.stop.load(Ordering::Acquire) {
                            return Ok(());
                        }
                        thread::sleep(Duration::from_millis(5));
                    }
                    if fail {
                        return Err("injected_start_failure".into());
                    }
                    let mut request = match request {
                        Some(request) => request,
                        None => {
                            let path = std::env::var_os("MEASURELAB_DISPLAY_REQUEST")
                                .ok_or("display_request_missing")?;
                            let file = std::fs::File::open(path).map_err(|e| e.to_string())?;
                            use std::io::Read;
                            serde_json::from_reader(file.take(65537)).map_err(|e| e.to_string())?
                        }
                    };
                    request.validate()?;
                    request.format.generation = generation;
                    calibration::initialize(&owner, &request);
                    if request.live.is_some() {
                        #[cfg(feature = "live-audio")]
                        return live::run(&owner, &notify, &request);
                        #[cfg(not(feature = "live-audio"))]
                        return Err("display_live_feature_disabled".into());
                    }
                    let bytes = request.bytes()?;
                    match request.precision {
                        Precision::F32 => {
                            let samples: Vec<f32> = bytes
                                .as_chunks::<4>()
                                .0
                                .iter()
                                .map(|v| f32::from_le_bytes(*v))
                                .collect();
                            let (tx, rx) = frame_queue(
                                2048,
                                request.format.input_ids.len(),
                                request.format.rate[0] as f64 / request.format.rate[1] as f64,
                            )?;
                            replay(&owner, &notify, &request, &samples, tx, rx)
                        }
                        Precision::F64 => {
                            let samples: Vec<f64> = bytes
                                .as_chunks::<8>()
                                .0
                                .iter()
                                .map(|v| f64::from_le_bytes(*v))
                                .collect();
                            let (tx, rx) = frame_queue_f64(
                                2048,
                                request.format.input_ids.len(),
                                request.format.rate[0] as f64 / request.format.rate[1] as f64,
                            )?;
                            replay(&owner, &notify, &request, &samples, tx, rx)
                        }
                    }
                }))
                .unwrap_or_else(|_| Err("display_worker_panic".into()));
            {
                let mut slot = owner.mailbox.lock().unwrap();
                slot.snapshot.reclaimed = true; // acquisition, subscriptions and stream have dropped
                trigger::cancel(&mut slot, result.as_ref().err().map(String::as_str));
                calibration::cancel(&mut slot);
                match result {
                    Err(error) => {
                        slot.snapshot.state = State::Failed;
                        slot.snapshot.outcome = 3;
                        slot.snapshot.error = error;
                    }
                    Ok(()) => {
                        slot.snapshot.state = State::Idle;
                        slot.snapshot.outcome = if slot.snapshot.produced == 0 { 2 } else { 1 };
                    }
                }
            }
            owner.notify(&notify);
            WORKERS.fetch_sub(1, Ordering::SeqCst);
        }));
        Some(generation)
    }
    pub fn peek(&self) -> Snapshot {
        self.mailbox.lock().unwrap().snapshot.clone()
    }
    pub fn take(&self, generation: u64) -> Option<Snapshot> {
        let mut slot = self.mailbox.lock().unwrap();
        if slot.snapshot.generation != generation {
            return None;
        }
        slot.pending = false;
        Some(slot.snapshot.clone())
    }
    pub fn stop(&mut self) {
        self.stop.store(true, Ordering::Release);
        let mut slot = self.mailbox.lock().unwrap();
        if matches!(slot.snapshot.state, State::Preparing | State::Running) {
            slot.snapshot.state = State::Stopping;
        }
        trigger::cancel(&mut slot, None);
        calibration::cancel(&mut slot);
    }
    fn join(&mut self) {
        if let Some(worker) = self.worker.take() {
            worker.join().expect("guarded display worker");
        }
    }
    pub fn shutdown(&mut self) {
        self.stop();
        self.join();
    }
}
impl Drop for Display {
    fn drop(&mut self) {
        self.shutdown();
        MODELS.fetch_sub(1, Ordering::SeqCst);
    }
}
struct Owner {
    mailbox: Arc<Mutex<Mailbox>>,
    stop: Arc<AtomicBool>,
}
impl Owner {
    fn notify(&self, notify: &impl Fn(u64) -> bool) -> bool {
        let generation = {
            let mut slot = self.mailbox.lock().unwrap();
            if slot.pending {
                slot.snapshot.coalesced += 1;
                return true;
            }
            slot.pending = true;
            slot.snapshot.generation
        };
        notify(generation) // Qt call without the mailbox lock
    }
}
fn replay<T: CaptureSample>(
    owner: &Owner,
    notify: &impl Fn(u64) -> bool,
    request: &Request,
    samples: &[T],
    mut tx: Producer<T>,
    rx: audio_core::Consumer<T>,
) -> Result<(), String> {
    let mut request = request.clone();
    let request = &mut request;
    let mut acquisition = Acquisition::new(
        rx,
        request.format.clone(),
        FftSpec {
            n: request.n,
            hop: request.n,
            alignment: 0,
            window: request.window,
        },
        CaptureLimits {
            history: HistoryLimits::frames(request.n * 8),
            frames_per_poll: 1024,
            windows_per_poll: 1,
        },
    )?;
    let mut subscriptions: BTreeMap<u64, Subscription> = BTreeMap::new();
    let mut evidence_written = false;
    while !owner.stop.load(Ordering::Acquire) {
        if !sync_demand(owner, &acquisition, &mut subscriptions)? {
            break;
        }
        calibration::process(owner, notify, request)?;
        trigger::process(owner, notify, request, &mut acquisition)?;
        for chunk in samples.chunks(256 * request.format.input_ids.len()) {
            tx.write(chunk, None, 0)?;
            let report = acquisition.poll()?;
            if !report.gaps.is_empty() {
                return Err("replay_gap".into());
            }
        }
        let frame = shared_frame(&subscriptions, request)?.ok_or("display_result_missing")?;
        if let Some(revision) = calibration::evidence_revision(owner)
            && let Some(path) = &request.evidence
        {
            calibration::save_result(
                &frame.result,
                &path.join(format!(
                    "calibration-{}-{revision}.result.json",
                    request.format.generation
                )),
                request,
            )?;
        }
        if !evidence_written {
            if let Some(path) = &request.evidence {
                calibration::save_result(
                    &frame.result,
                    &path.join(format!("generation-{}.json", request.format.generation)),
                    request,
                )?;
            }
            evidence_written = true;
        }
        if !publish(owner, notify, &acquisition, frame) {
            break;
        }
        trigger::process(owner, notify, request, &mut acquisition)?;
        for _ in 0..8 {
            if owner.stop.load(Ordering::Acquire) {
                break;
            }
            thread::sleep(Duration::from_millis(5));
        }
    }
    reclaim(&mut acquisition)?;
    trigger::finish_evidence(owner, request)
}
fn sync_demand<T: CaptureSample>(
    owner: &Owner,
    acquisition: &Acquisition<T>,
    subscriptions: &mut BTreeMap<u64, Subscription>,
) -> Result<bool, String> {
    let demand = owner.mailbox.lock().unwrap().demand.clone();
    subscriptions.retain(|id, _| demand.contains(id));
    for id in demand {
        if let std::collections::btree_map::Entry::Vacant(entry) = subscriptions.entry(id) {
            entry.insert(acquisition.subscribe(
                Average::None,
                Presentation {
                    color: "cyan".into(),
                    unit: "FS_peak".into(),
                },
            )?);
        }
    }
    Ok(!subscriptions.is_empty())
}
fn shared_frame(
    subscriptions: &BTreeMap<u64, Subscription>,
    request: &Request,
) -> Result<Option<Arc<Frame>>, String> {
    let latest: Vec<_> = subscriptions
        .values()
        .filter_map(Subscription::take_latest)
        .collect();
    if latest.is_empty() {
        return Ok(None);
    }
    if latest.len() != subscriptions.len() {
        return Err("display_result_missing".into());
    }
    let raw = latest[0].raw();
    if latest.iter().any(|s| !Arc::ptr_eq(raw, s.raw())) {
        return Err("display_result_not_shared".into());
    }
    let result = calibration::calibrated_result(
        raw,
        Capture {
            result_id: format!("{}:{}", raw.id().graph, raw.id().serial),
            trigger_id: None,
            acquired_host_seconds: None,
            result_host_seconds: None,
            trigger: None,
            clock_mapping: None,
        },
        request,
    )?;
    Ok(Some(Arc::new(project_result(Arc::new(result))?)))
}
fn publish<T: CaptureSample>(
    owner: &Owner,
    notify: &impl Fn(u64) -> bool,
    acquisition: &Acquisition<T>,
    frame: Arc<Frame>,
) -> bool {
    {
        let mut slot = owner.mailbox.lock().unwrap();
        if owner.stop.load(Ordering::Acquire) {
            return false;
        }
        slot.snapshot.state = State::Running;
        slot.snapshot.produced = acquisition.graph().stats().fft_evaluations;
        slot.snapshot.shared = true;
        slot.snapshot.frame = Some(frame);
    }
    owner.notify(notify)
}
fn reclaim<T: CaptureSample>(acquisition: &mut Acquisition<T>) -> Result<(), String> {
    acquisition.stop();
    let stats = acquisition.graph().stats();
    if stats.nodes != 0
        || stats.subscriptions != 0
        || stats.cache_results != 0
        || stats.in_flight != 0
    {
        return Err("display_graph_leak".into());
    }
    Ok(())
}
pub fn live_workers() -> usize {
    WORKERS.load(Ordering::SeqCst)
}
pub fn live_models() -> usize {
    MODELS.load(Ordering::SeqCst)
}
pub fn qml_path() -> PathBuf {
    std::env::var_os("MEASURELAB_DISPLAY_QML")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../qml/Display.qml"))
        .canonicalize()
        .expect("display QML file")
}

#[cfg(test)]
mod tests;
