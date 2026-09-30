//! MIG-006-B fixed DAG: owned input -> shared FFT -> independent PSD average/latest view.
//! Control/analysis-worker API only. Scheduling, allocation and locks are not callback safe.
use dsp_core::{Analysis, Analyzer, Window};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::time::Duration;

static NEXT_GRAPH: AtomicU64 = AtomicU64::new(1);
pub const TRANSFORM_REVISION: &str = "realfft-3.5.0-x-over-n-v1";
pub mod acquisition;
pub mod filter;
pub mod history;
pub mod result;
pub mod time;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Precision {
    F32,
    F64,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum WindowSpec {
    Boxcar,
    SymmetricHann,
}
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Rational {
    pub numerator: i64,
    pub denominator: u64,
}
impl Rational {
    fn valid(&self) -> bool {
        self.denominator > 0
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Timebase {
    pub id: String,
    pub revision: u64,
    pub clock_domain: String,
    pub generation: u64,
    pub rate: Rational,
    pub nominal_rate: Rational,
    pub origin_sample: u64,
    pub origin_seconds: Option<Rational>,
    pub origin_kind: String,
    pub uncertainty_seconds: Option<Rational>,
}
impl Timebase {
    pub fn rate_hz(&self) -> f64 {
        self.rate.numerator as f64 / self.rate.denominator as f64
    }
    fn valid(&self) -> bool {
        !self.id.is_empty()
            && !self.clock_domain.is_empty()
            && !self.origin_kind.is_empty()
            && self.rate.valid()
            && self.rate.numerator > 0
            && self.nominal_rate.valid()
            && self.nominal_rate.numerator > 0
            && self.origin_seconds.as_ref().is_none_or(Rational::valid)
            && self
                .uncertainty_seconds
                .as_ref()
                .is_none_or(|r| r.valid() && r.numerator >= 0)
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Tap {
    InputRaw,
    InputCalibrated,
    OutputMixed,
    OutputPostDut,
    OutputDeviceBuffer,
}
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Source {
    pub stream_id: String,
    pub generation: u64,
    pub channel_ids: Vec<String>,
    pub precision: Precision,
    pub timebase: Timebase,
    pub route_revision: String,
    pub tap: Tap,
    pub filter_state_revision: String,
    pub calibration_revision: String,
}
impl Source {
    fn valid(&self) -> bool {
        !self.stream_id.is_empty()
            && !self.channel_ids.is_empty()
            && self.channel_ids.iter().all(|id| !id.is_empty())
            && self.channel_ids.iter().collect::<HashSet<_>>().len() == self.channel_ids.len()
            && self.timebase.valid()
            && self.generation == self.timebase.generation
    }
}
/// Dimensionless input correction. Absolute V/SPL calibration/export belongs to MIG-006-E.
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize)]
pub struct InputGain {
    channel_id: String,
    revision: String,
    bits: u64,
}
impl InputGain {
    pub fn new(channel_id: String, revision: String, gain: f64) -> Result<Self, String> {
        if channel_id.is_empty() || revision.is_empty() || !gain.is_finite() {
            return Err("Invalid input correction".into());
        }
        Ok(Self {
            channel_id,
            revision,
            bits: gain.to_bits(),
        })
    }
    pub fn gain(&self) -> f64 {
        f64::from_bits(self.bits)
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize)]
pub struct FftKey {
    pub source: Source,
    pub n: usize,
    pub hop: usize,
    pub alignment: u64,
    pub window: WindowSpec,
    pub remove_dc: bool,
    pub input_gains: Vec<InputGain>,
    // WindowSpec fixes all coefficients and symmetry; invalid windows are rejected as a whole.
    // Transform/normalization and validity policy have one supported version in this DAG.
}
impl FftKey {
    fn validate(&self, limits: &Limits) -> Result<(), String> {
        if !self.source.valid()
            || self.n < 3
            || self.n > limits.max_frames
            || self.hop == 0
            || self.source.channel_ids.len() > limits.max_channels
            || (!self.input_gains.is_empty()
                && (self.input_gains.len() != self.source.channel_ids.len()
                    || self
                        .input_gains
                        .iter()
                        .zip(&self.source.channel_ids)
                        .any(|(g, id)| &g.channel_id != id)))
        {
            return Err("Invalid or unsupported FFT key".into());
        }
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct InvalidSpan {
    pub start: u64,
    pub end: u64,
    pub channel_id: Option<String>,
    pub reason: String,
    pub origin: String,
}
#[derive(Debug)]
pub enum Samples {
    F32(Vec<f32>),
    F64(Vec<f64>),
}
impl Samples {
    fn len(&self) -> usize {
        match self {
            Self::F32(v) => v.len(),
            Self::F64(v) => v.len(),
        }
    }
    fn precision(&self) -> Precision {
        match self {
            Self::F32(_) => Precision::F32,
            Self::F64(_) => Precision::F64,
        }
    }
}
#[derive(Debug)]
pub struct SignalBlock {
    source: Source,
    start: u64,
    frames: usize,
    samples: Samples,
    validity: Vec<InvalidSpan>,
}
impl SignalBlock {
    pub fn new(
        source: Source,
        start: u64,
        samples: Samples,
        validity: Vec<InvalidSpan>,
    ) -> Result<Self, String> {
        if !source.valid()
            || samples.precision() != source.precision
            || samples.len() == 0
            || !samples.len().is_multiple_of(source.channel_ids.len())
        {
            return Err("Invalid block source, precision or dimensions".into());
        }
        let frames = samples.len() / source.channel_ids.len();
        let end = start
            .checked_add(frames as u64)
            .ok_or("Sample interval overflow")?;
        if validity.iter().any(|v| {
            v.start >= v.end
                || v.start < start
                || v.end > end
                || v.reason.is_empty()
                || v.origin.is_empty()
                || v.channel_id
                    .as_ref()
                    .is_some_and(|id| !source.channel_ids.contains(id))
        }) {
            return Err("Invalid validity span".into());
        }
        Ok(Self {
            source,
            start,
            frames,
            samples,
            validity,
        })
    }
    pub fn source(&self) -> &Source {
        &self.source
    }
    pub fn interval(&self) -> (u64, u64) {
        (self.start, self.start + self.frames as u64)
    }
    pub fn samples(&self) -> &Samples {
        &self.samples
    }
    pub fn validity(&self) -> &[InvalidSpan] {
        &self.validity
    }
}
#[derive(Debug)]
pub enum Numeric {
    F32(Analysis<f32>),
    F64(Analysis<f64>),
}
impl Numeric {
    pub fn psd(&self) -> &[f64] {
        match self {
            Self::F32(a) => &a.psd_fs2_hz,
            Self::F64(a) => &a.psd_fs2_hz,
        }
    }
    fn bytes(&self) -> usize {
        fn size<T>(a: &Analysis<T>) -> usize {
            (a.window.len()
                + a.frequency_hz.len()
                + a.peak_fs.len()
                + a.tone_rms_fs.len()
                + a.psd_fs2_hz.len()
                + a.asd_fs_sqrt_hz.len()
                + a.rms_fs.len()
                + a.integrated_power_fs2.len()
                + a.time_window_power_fs2.len())
                * 8
                + a.fft_over_n.len() * 16
                + a.inverse_windowed.len() * std::mem::size_of::<T>()
        }
        match self {
            Self::F32(a) => size(a),
            Self::F64(a) => size(a),
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct ResultId {
    pub graph: u64,
    pub serial: u64,
}
#[derive(Debug)]
pub struct FftResult {
    id: ResultId,
    key: FftKey,
    start: u64,
    numeric: Option<Numeric>,
    validity: Vec<InvalidSpan>,
    error: Option<String>,
}
impl FftResult {
    pub fn id(&self) -> ResultId {
        self.id
    }
    pub fn key(&self) -> &FftKey {
        &self.key
    }
    pub fn interval(&self) -> (u64, u64) {
        (self.start, self.start + self.key.n as u64)
    }
    pub fn numeric(&self) -> Option<&Numeric> {
        self.numeric.as_ref()
    }
    pub fn validity(&self) -> &[InvalidSpan] {
        &self.validity
    }
    pub fn error(&self) -> Option<&str> {
        self.error.as_deref()
    }
    fn bytes(&self) -> usize {
        self.numeric.as_ref().map_or(0, Numeric::bytes)
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Presentation {
    pub color: String,
    pub unit: String,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Average {
    None,
    CumulativePsd,
}
#[derive(Debug)]
pub struct Snapshot {
    raw: Arc<FftResult>,
    mean_psd: Option<Vec<f64>>,
    average_count: u64,
    presentation: Presentation,
}
impl Snapshot {
    pub fn raw(&self) -> &Arc<FftResult> {
        &self.raw
    }
    pub fn mean_psd(&self) -> Option<&[f64]> {
        self.mean_psd.as_deref()
    }
    pub fn average_count(&self) -> u64 {
        self.average_count
    }
    pub fn presentation(&self) -> &Presentation {
        &self.presentation
    }
}
#[derive(Clone, Debug)]
pub struct Limits {
    pub max_nodes: usize,
    pub max_subscriptions: usize,
    pub max_in_flight: usize,
    pub cache_results: usize,
    pub cache_numeric_bytes: usize,
    pub max_frames: usize,
    pub max_channels: usize,
}
impl Default for Limits {
    fn default() -> Self {
        Self {
            max_nodes: 16,
            max_subscriptions: 64,
            max_in_flight: 16,
            cache_results: 8,
            cache_numeric_bytes: 64 * 1024 * 1024,
            max_frames: 4_194_304,
            max_channels: 32,
        }
    }
}
#[derive(Clone, Copy, Debug, Default, Serialize)]
pub struct Stats {
    pub nodes: usize,
    pub subscriptions: usize,
    pub in_flight: usize,
    pub cache_results: usize,
    pub cache_numeric_bytes: usize,
    pub fft_evaluations: u64,
    pub display_replacements: u64,
}
struct Node {
    incarnation: u64,
    last_start: Option<u64>,
    pending: bool,
}
struct Consumer {
    key: FftKey,
    average: Average,
    mean: Vec<f64>,
    count: u64,
    last_start: Option<u64>,
    presentation: Presentation,
    latest: Option<Arc<Snapshot>>,
}
impl Consumer {
    fn reset(&mut self) {
        self.mean.clear();
        self.count = 0;
        self.last_start = None;
    }
    fn deliver(&mut self, result: Arc<FftResult>) -> bool {
        if self
            .last_start
            .is_some_and(|n| n.checked_add(self.key.hop as u64) != Some(result.start))
        {
            self.reset();
        }
        if let Some(numeric) = &result.numeric {
            if self.average == Average::CumulativePsd {
                self.count += 1;
                if self.count == 1 {
                    self.mean = numeric.psd().to_vec();
                } else {
                    for (m, x) in self.mean.iter_mut().zip(numeric.psd()) {
                        *m += (x - *m) / self.count as f64;
                    }
                }
            }
        } else {
            self.reset();
        }
        self.last_start = Some(result.start);
        let snapshot = Arc::new(Snapshot {
            raw: result,
            mean_psd: (self.count > 0).then(|| self.mean.clone()),
            average_count: self.count,
            presentation: self.presentation.clone(),
        });
        self.latest.replace(snapshot).is_some()
    }
}
struct State {
    closed: bool,
    next_id: u64,
    nodes: HashMap<FftKey, Node>,
    consumers: HashMap<u64, Consumer>,
    cache: VecDeque<Arc<FftResult>>,
    in_flight: usize,
    evaluations: u64,
    display_replacements: u64,
    minimum_generations: HashMap<String, u64>,
    filters: HashMap<Source, filter::Filter>,
}
impl State {
    fn accepts(&self, source: &Source) -> bool {
        self.minimum_generations
            .get(&source.stream_id)
            .is_none_or(|minimum| source.generation >= *minimum)
    }
}
struct Core {
    id: u64,
    limits: Limits,
    state: Mutex<State>,
    idle: Condvar,
}
impl Core {
    fn prune(&self, state: &mut State) {
        state
            .nodes
            .retain(|key, _| state.consumers.values().any(|c| &c.key == key));
        state.cache.retain(|r| state.nodes.contains_key(&r.key));
        state
            .filters
            .retain(|source, _| state.consumers.values().any(|c| &c.key.source == source));
    }
    fn trim(&self, state: &mut State) {
        while state.cache.len() > self.limits.cache_results
            || state.cache.iter().map(|r| r.bytes()).sum::<usize>()
                > self.limits.cache_numeric_bytes
        {
            let index = state
                .cache
                .iter()
                .position(|r| Arc::strong_count(r) == 1)
                .unwrap_or(0);
            state.cache.remove(index);
        }
    }
}
/// Sole graph owner. Tokens cannot keep a dropped graph open; shutdown is idempotent.
pub struct Graph {
    core: Arc<Core>,
}
impl Graph {
    pub fn new(limits: Limits) -> Result<Self, String> {
        if limits.max_nodes == 0
            || limits.max_subscriptions == 0
            || limits.max_in_flight == 0
            || limits.max_frames < 3
            || limits.max_channels == 0
        {
            return Err("Invalid graph limits".into());
        }
        Ok(Self {
            core: Arc::new(Core {
                id: NEXT_GRAPH.fetch_add(1, Ordering::Relaxed),
                limits,
                state: Mutex::new(State {
                    closed: false,
                    next_id: 1,
                    nodes: HashMap::new(),
                    consumers: HashMap::new(),
                    cache: VecDeque::new(),
                    in_flight: 0,
                    evaluations: 0,
                    display_replacements: 0,
                    minimum_generations: HashMap::new(),
                    filters: HashMap::new(),
                }),
                idle: Condvar::new(),
            }),
        })
    }
    pub fn subscribe(
        &self,
        key: FftKey,
        average: Average,
        presentation: Presentation,
    ) -> Result<Subscription, String> {
        key.validate(&self.core.limits)?;
        let mut state = self.core.state.lock().unwrap();
        if state.closed
            || !state.accepts(&key.source)
            || state.consumers.len() >= self.core.limits.max_subscriptions
            || (!state.nodes.contains_key(&key) && state.nodes.len() >= self.core.limits.max_nodes)
        {
            return Err("Graph closed or demand capacity exceeded".into());
        }
        let id = state.next_id;
        state.next_id += 1;
        state.nodes.entry(key.clone()).or_insert(Node {
            incarnation: id,
            last_start: None,
            pending: false,
        });
        state.consumers.insert(
            id,
            Consumer {
                key,
                average,
                mean: Vec::new(),
                count: 0,
                last_start: None,
                presentation,
                latest: None,
            },
        );
        Ok(Subscription {
            core: Arc::downgrade(&self.core),
            id,
        })
    }
    /// Reserve at most one interval per node. Busy/capacity errors reject the whole request.
    /// Complete windows only; history::History supplies owned windows from arbitrary input chunks.
    pub fn schedule(&self, block: Arc<SignalBlock>) -> Result<Vec<Job>, String> {
        let mut state = self.core.state.lock().unwrap();
        if state.closed {
            return Err("Graph closed".into());
        }
        if !state.accepts(&block.source) {
            return Err("stale_generation".into());
        }
        if block.frames > self.core.limits.max_frames
            || block.source.channel_ids.len() > self.core.limits.max_channels
        {
            return Err("Block exceeds evaluation limits".into());
        }
        let keys: Vec<_> = state
            .nodes
            .keys()
            .filter(|key| {
                key.source == block.source
                    && block.frames >= key.n
                    && block.start >= key.alignment
                    && (block.start - key.alignment).is_multiple_of(key.hop as u64)
            })
            .cloned()
            .collect();
        if state.in_flight + keys.len() > self.core.limits.max_in_flight
            || keys.iter().any(|key| {
                let node = &state.nodes[key];
                node.pending || node.last_start.is_some_and(|n| block.start <= n)
            })
        {
            return Err(
                "Busy, duplicate/out-of-order interval or in-flight capacity exceeded".into(),
            );
        }
        let mut jobs = Vec::with_capacity(keys.len());
        for key in keys {
            let node = state.nodes.get_mut(&key).unwrap();
            node.pending = true;
            node.last_start = Some(block.start);
            let incarnation = node.incarnation;
            let serial = state.next_id;
            state.next_id += 1;
            state.in_flight += 1;
            jobs.push(Job {
                lease: Some(Lease {
                    core: Arc::clone(&self.core),
                    key,
                    incarnation,
                }),
                block: Arc::clone(&block),
                id: ResultId {
                    graph: self.core.id,
                    serial,
                },
            });
        }
        Ok(jobs)
    }
    /// Only complete acquired history windows can enter the DAG. Gaps/pending are diagnostic
    /// outcomes, with no invented zero samples and no FFT evaluation.
    pub fn schedule_history(&self, read: &history::HistoryRead) -> Result<Vec<Job>, String> {
        let block = read
            .snapshot
            .as_ref()
            .ok_or_else(|| read.report.status.clone())?;
        self.schedule(Arc::clone(block))
    }
    /// Worker-side discontinuity. Fence already reserved jobs, discard unread display
    /// snapshots and reset independent averages without inventing numeric gap samples.
    pub fn invalidate_source(&self, source: &Source) -> Result<(), String> {
        let mut s = self.core.state.lock().unwrap();
        if s.closed || !s.accepts(source) {
            return Err("Graph closed or stale_generation".into());
        }
        let mut incarnation = s.next_id;
        for (_, node) in s.nodes.iter_mut().filter(|(key, _)| &key.source == source) {
            node.incarnation = incarnation;
            incarnation += 1;
            node.pending = false;
        }
        s.next_id = incarnation;
        s.cache.retain(|r| &r.key.source != source);
        for c in s.consumers.values_mut().filter(|c| &c.key.source == source) {
            c.reset();
            c.latest = None;
        }
        Ok(())
    }
    /// Register one worker transform after subscribing to its exact output Source.
    /// All output consumers share this state; the final token removes it through prune().
    pub fn attach_filter(&self, filter: filter::Filter) -> Result<(), String> {
        let mut s = self.core.state.lock().unwrap();
        let source = filter.output_source().clone();
        if s.closed
            || !s.accepts(filter.input_source())
            || !s.accepts(&source)
            || s.filters.len() >= self.core.limits.max_nodes
            || s.filters.contains_key(&source)
            || !s.consumers.values().any(|c| c.key.source == source)
            || s.filters
                .values()
                .any(|f| f.output_source().stream_id == source.stream_id)
            || s.filters
                .keys()
                .any(|p| p.stream_id == filter.input_source().stream_id)
            || s.filters
                .values()
                .any(|f| f.input_source().stream_id == source.stream_id)
        {
            return Err("Filter closed, duplicate, chained or without demand".into());
        }
        s.filters.insert(source, filter);
        Ok(())
    }
    /// Single control/analysis worker entry point. FFT windows come from output history.
    pub fn process_filter(
        &self,
        source: &Source,
        block: &SignalBlock,
    ) -> Result<Option<SignalBlock>, String> {
        let mut s = self.core.state.lock().unwrap();
        if s.closed || !s.accepts(source) || !s.accepts(block.source()) {
            return Err("Graph closed or stale_generation".into());
        }
        s.filters
            .get_mut(source)
            .ok_or("Unknown filter")?
            .process(block)
    }
    pub fn finish_filter(&self, source: &Source, end: u64) -> Result<Option<SignalBlock>, String> {
        let mut s = self.core.state.lock().unwrap();
        if s.closed || !s.accepts(source) {
            return Err("Graph closed or stale_generation".into());
        }
        s.filters
            .get_mut(source)
            .ok_or("Unknown filter")?
            .finish(end)
    }
    pub fn filter_metadata(&self, source: &Source) -> Option<filter::FilterMetadata> {
        self.core
            .state
            .lock()
            .unwrap()
            .filters
            .get(source)
            .map(|f| f.metadata().clone())
    }
    pub fn filter_state(&self, source: &Source) -> Option<Vec<f64>> {
        self.core
            .state
            .lock()
            .unwrap()
            .filters
            .get(source)?
            .sos_state()
            .map(<[f64]>::to_vec)
    }
    pub fn filter_count(&self) -> usize {
        self.core.state.lock().unwrap().filters.len()
    }
    pub fn cached(&self, key: &FftKey, start: u64) -> Option<Arc<FftResult>> {
        let mut state = self.core.state.lock().unwrap();
        if !state.accepts(&key.source) {
            return None;
        }
        let at = state
            .cache
            .iter()
            .position(|r| &r.key == key && r.start == start)?;
        let result = state.cache.remove(at).unwrap();
        state.cache.push_back(Arc::clone(&result));
        Some(result)
    }
    pub fn stats(&self) -> Stats {
        let s = self.core.state.lock().unwrap();
        Stats {
            nodes: s.nodes.len(),
            subscriptions: s.consumers.len(),
            in_flight: s.in_flight,
            cache_results: s.cache.len(),
            cache_numeric_bytes: s.cache.iter().map(|r| r.bytes()).sum(),
            fft_evaluations: s.evaluations,
            display_replacements: s.display_replacements,
        }
    }
    /// Retire a stream before restart. Old leases remain owned but can no longer publish.
    /// Existing tokens survive and can be reconfigured explicitly to the new generation.
    pub fn retire_stream_before(&self, stream_id: &str, generation: u64) -> Result<(), String> {
        let mut s = self.core.state.lock().unwrap();
        if s.closed || stream_id.is_empty() {
            return Err("Graph closed or invalid stream".into());
        }
        // Only a known demand may introduce a fence, bounding this table by subscription count.
        if !s
            .consumers
            .values()
            .any(|c| c.key.source.stream_id == stream_id)
            && !s
                .filters
                .values()
                .any(|f| f.input_source().stream_id == stream_id)
        {
            return Err("Unknown stream".into());
        }
        let current = s.minimum_generations.get(stream_id).copied().unwrap_or(0);
        if generation < current {
            return Err("stale_generation".into());
        }
        if !s.minimum_generations.contains_key(stream_id)
            && s.minimum_generations.len() >= self.core.limits.max_subscriptions
        {
            return Err("Generation fence capacity exceeded".into());
        }
        let derived: HashSet<_> = s
            .filters
            .values()
            .filter(|f| {
                f.input_source().stream_id == stream_id && f.input_source().generation < generation
            })
            .map(|f| f.output_source().clone())
            .collect();
        // Derived fences reject old external blocks and reconfiguration after state has been removed.
        // One transform per distinct output stream; the table has an explicit bounded budget.
        if s.minimum_generations.len()
            + usize::from(!s.minimum_generations.contains_key(stream_id))
            + derived
                .iter()
                .filter(|p| !s.minimum_generations.contains_key(&p.stream_id))
                .count()
            > self.core.limits.max_subscriptions
        {
            return Err("Generation fence capacity exceeded".into());
        }
        s.minimum_generations.insert(stream_id.into(), generation);
        for source in &derived {
            s.minimum_generations
                .insert(source.stream_id.clone(), generation);
        }
        s.filters.retain(|source, _| {
            !derived.contains(source)
                && (source.stream_id != stream_id || source.generation >= generation)
        });
        s.nodes.retain(|key, _| {
            !derived.contains(&key.source)
                && (key.source.stream_id != stream_id || key.source.generation >= generation)
        });
        s.cache.retain(|r| {
            !derived.contains(&r.key.source)
                && (r.key.source.stream_id != stream_id || r.key.source.generation >= generation)
        });
        for c in s.consumers.values_mut().filter(|c| {
            derived.contains(&c.key.source)
                || (c.key.source.stream_id == stream_id && c.key.source.generation < generation)
        }) {
            c.reset();
            c.latest = None;
        }
        Ok(())
    }
    pub fn shutdown(&self) {
        let mut s = self.core.state.lock().unwrap();
        s.closed = true;
        s.consumers.clear();
        s.nodes.clear();
        s.cache.clear();
        s.minimum_generations.clear();
        s.filters.clear();
    }
    /// Wait for caller-owned jobs/completions to finish or be dropped. This does not run or cancel a thread.
    pub fn wait_idle(&self, timeout: Duration) -> bool {
        let s = self.core.state.lock().unwrap();
        let (s, _) = self
            .core
            .idle
            .wait_timeout_while(s, timeout, |s| s.in_flight != 0)
            .unwrap();
        s.in_flight == 0
    }
}
impl Drop for Graph {
    fn drop(&mut self) {
        self.shutdown();
    }
}
pub struct Subscription {
    core: std::sync::Weak<Core>,
    id: u64,
}
impl Subscription {
    pub fn take_latest(&self) -> Option<Arc<Snapshot>> {
        self.core
            .upgrade()?
            .state
            .lock()
            .unwrap()
            .consumers
            .get_mut(&self.id)?
            .latest
            .take()
    }
    pub fn set_presentation(&self, presentation: Presentation) -> Result<(), String> {
        let core = self.core.upgrade().ok_or("Graph dropped")?;
        let mut s = core.state.lock().unwrap();
        let c = s.consumers.get_mut(&self.id).ok_or("Subscription closed")?;
        c.presentation = presentation;
        Ok(())
    }
    pub fn reset_average(&self) -> Result<(), String> {
        let core = self.core.upgrade().ok_or("Graph dropped")?;
        let mut s = core.state.lock().unwrap();
        s.consumers
            .get_mut(&self.id)
            .ok_or("Subscription closed")?
            .reset();
        Ok(())
    }
    /// Atomic reconfiguration; failed validation leaves existing demand/snapshot unchanged.
    pub fn reconfigure(&self, key: FftKey) -> Result<(), String> {
        let core = self.core.upgrade().ok_or("Graph dropped")?;
        key.validate(&core.limits)?;
        let mut s = core.state.lock().unwrap();
        if !s.accepts(&key.source) {
            return Err("stale_generation".into());
        }
        let old = &s.consumers.get(&self.id).ok_or("Subscription closed")?.key;
        if old == &key {
            return Ok(());
        }
        // Removing the old sole demand frees its node slot in this transaction.
        let old_shared = s
            .consumers
            .iter()
            .any(|(id, c)| *id != self.id && &c.key == old);
        if !s.nodes.contains_key(&key)
            && s.nodes.len() - usize::from(!old_shared && s.nodes.contains_key(old))
                >= core.limits.max_nodes
        {
            return Err("Node capacity exceeded".into());
        }
        let incarnation = s.next_id;
        s.next_id += 1;
        s.nodes.entry(key.clone()).or_insert(Node {
            incarnation,
            last_start: None,
            pending: false,
        });
        let c = s.consumers.get_mut(&self.id).unwrap();
        c.key = key;
        c.reset();
        c.latest = None;
        core.prune(&mut s);
        Ok(())
    }
}
impl Drop for Subscription {
    fn drop(&mut self) {
        if let Some(core) = self.core.upgrade() {
            let mut s = core.state.lock().unwrap();
            s.consumers.remove(&self.id);
            core.prune(&mut s);
        }
    }
}
struct Lease {
    core: Arc<Core>,
    key: FftKey,
    incarnation: u64,
}
impl Lease {
    fn active(&self, s: &State) -> bool {
        !s.closed
            && s.accepts(&self.key.source)
            && s.nodes
                .get(&self.key)
                .is_some_and(|n| n.incarnation == self.incarnation)
    }
}
impl Drop for Lease {
    fn drop(&mut self) {
        let mut s = self.core.state.lock().unwrap();
        if let Some(n) = s
            .nodes
            .get_mut(&self.key)
            .filter(|n| n.incarnation == self.incarnation)
        {
            n.pending = false;
        }
        s.in_flight -= 1;
        self.core.idle.notify_all();
    }
}
/// Sendable reservation. Drop releases in-flight ownership even if execution is cancelled/panics.
pub struct Job {
    lease: Option<Lease>,
    block: Arc<SignalBlock>,
    id: ResultId,
}
impl Job {
    pub fn compute(mut self) -> Completion {
        let lease = self.lease.take().unwrap();
        let key = lease.key.clone();
        let end = self.block.start + key.n as u64;
        let mut validity: Vec<_> = self
            .block
            .validity
            .iter()
            .filter(|v| v.start < end && v.end > self.block.start)
            .map(|v| InvalidSpan {
                start: v.start.max(self.block.start),
                end: v.end.min(end),
                ..v.clone()
            })
            .collect();
        let mut error = None;
        let numeric = if !validity.is_empty() {
            None
        } else {
            let active = {
                let mut s = lease.core.state.lock().unwrap();
                let active = lease.active(&s);
                if active {
                    s.evaluations += 1;
                }
                active
            };
            if active {
                match analyze(&self.block, &key) {
                    Ok(n) => Some(n),
                    Err(e) => {
                        validity.push(InvalidSpan {
                            start: self.block.start,
                            end,
                            channel_id: None,
                            reason: "nonfinite".into(),
                            origin: TRANSFORM_REVISION.into(),
                        });
                        error = Some(e);
                        None
                    }
                }
            } else {
                error = Some("cancelled".into());
                None
            }
        };
        Completion {
            lease: Some(lease),
            result: Arc::new(FftResult {
                id: self.id,
                key,
                start: self.block.start,
                numeric,
                validity,
                error,
            }),
        }
    }
    pub fn run(self) -> bool {
        self.compute().publish()
    }
}
/// Keeps a computed result alive until publication/drop, with no graph lock held during FFT.
pub struct Completion {
    lease: Option<Lease>,
    result: Arc<FftResult>,
}
impl Completion {
    pub fn result(&self) -> &Arc<FftResult> {
        &self.result
    }
    pub fn publish(mut self) -> bool {
        let lease = self.lease.take().unwrap();
        let published = {
            let mut s = lease.core.state.lock().unwrap();
            if !lease.active(&s) {
                false
            } else {
                let mut replacements = 0;
                for c in s.consumers.values_mut().filter(|c| c.key == lease.key) {
                    replacements += u64::from(c.deliver(Arc::clone(&self.result)));
                }
                s.display_replacements += replacements;
                s.cache.push_back(Arc::clone(&self.result));
                lease.core.trim(&mut s);
                true
            }
        };
        drop(lease);
        published
    }
}
fn analyze(block: &SignalBlock, key: &FftKey) -> Result<Numeric, String> {
    let window = match key.window {
        WindowSpec::Boxcar => Window::Boxcar,
        WindowSpec::SymmetricHann => Window::SymmetricHann,
    };
    let channels = key.source.channel_ids.len();
    let length = key.n * channels;
    let gains: Vec<_> = if key.input_gains.is_empty() {
        vec![1.0; channels]
    } else {
        key.input_gains.iter().map(InputGain::gain).collect()
    };
    // Cast corrections before multiplication in f32. Reduction/DC estimate uses f64.
    macro_rules! evaluate {
        ($input:expr, $t:ty, $variant:ident) => {{
            let mut values: Vec<$t> = $input[..length]
                .iter()
                .enumerate()
                .map(|(i, x)| *x * gains[i % channels] as $t)
                .collect();
            if key.remove_dc {
                for c in 0..channels {
                    let mean = (0..key.n)
                        .map(|i| values[i * channels + c] as f64)
                        .sum::<f64>()
                        / key.n as f64;
                    for i in 0..key.n {
                        values[i * channels + c] -= mean as $t;
                    }
                }
            }
            Analyzer::<$t>::new(key.n, key.source.timebase.rate_hz(), window)?
                .analyze(&values, &key.source.channel_ids)
                .map(Numeric::$variant)
        }};
    }
    match &block.samples {
        Samples::F32(v) => evaluate!(v, f32, F32),
        Samples::F64(v) => evaluate!(v, f64, F64),
    }
}

#[cfg(test)]
mod tests;
