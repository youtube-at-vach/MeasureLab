//! Single-owner trigger reads. Never called from an audio callback or a GUI thread.
//! A pending read is retried explicitly; it does not pause acquisition or arm a detector.
use super::*;
use crate::FftResult;
use crate::history::{HistoryRead, TriggerEvent};
use crate::result::{Capture, MeasurementResult, Profile};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::sync::atomic::{AtomicU64, Ordering};

static NEXT_CAPTURE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TriggerRequest {
    pub request_id: String,
    pub event: TriggerEvent,
    pub pre: u64,
    pub post: u64,
}
/// Both views may hold the same raw Arc. Pending/gap reads contain no numeric result.
pub struct TriggerRead {
    pub request_id: String,
    pub history: HistoryRead,
    pub raw: Option<Arc<FftResult>>,
    pub result: Option<Arc<MeasurementResult>>,
    /// continuous-cache, trigger-cache, computed, or none (pending/gap).
    pub fft_origin: &'static str,
}
impl<T: CaptureSample> Acquisition<T> {
    /// Analysis owner releases its extra cache; external captures keep their owned data.
    pub fn release_trigger_cache(&mut self) {
        self.trigger_cache = None;
    }
    pub fn trigger_evaluations(&self) -> u64 {
        self.trigger_evaluations
    }
    /// Read exactly N frames at floor(event.sample)-pre. GUI reception time is never an anchor.
    /// Reading old windows must not publish into continuous views or change their averages.
    pub fn capture_trigger(&mut self, request: &TriggerRequest) -> Result<TriggerRead, String> {
        self.capture_trigger_with_profiles(request, |_| BTreeMap::new())
    }
    /// Resolve session profiles against the actual captured interval and construct one result.
    /// The analysis owner supplies profiles; pending/gap reads never call the provider.
    pub fn capture_trigger_with_profiles(
        &mut self,
        request: &TriggerRequest,
        profiles: impl FnOnce([u64; 2]) -> BTreeMap<String, Profile>,
    ) -> Result<TriggerRead, String> {
        self.capture_selected_trigger(request, profiles, false)
    }
    /// Event and pre/post are explicitly in the derived Stream/Timebase domain.
    /// This never infers a parent-event mapping or compensates signal delay.
    pub fn capture_filtered_trigger_with_profiles(
        &mut self,
        request: &TriggerRequest,
        profiles: impl FnOnce([u64; 2]) -> BTreeMap<String, Profile>,
    ) -> Result<TriggerRead, String> {
        self.capture_selected_trigger(request, profiles, true)
    }
    fn capture_selected_trigger(
        &mut self,
        request: &TriggerRequest,
        profiles: impl FnOnce([u64; 2]) -> BTreeMap<String, Profile>,
        filtered: bool,
    ) -> Result<TriggerRead, String> {
        if self.state != WorkerState::Running {
            return Err("capture_not_running".into());
        }
        let (key, history) = if filtered {
            let stream = self.filtered.as_ref().ok_or("capture_filter_missing")?;
            if self.graph.filter_metadata(&stream.key.source).is_none() {
                return Err("capture_filter_missing".into());
            }
            (&stream.key, &stream.history)
        } else {
            (&self.key, self.history.as_ref().unwrap())
        };
        if request.request_id.is_empty()
            || request.request_id.len() > 256
            || key.n > 4096
            || request.pre.checked_add(request.post) != Some(key.n as u64)
        {
            return Err("trigger_request".into());
        }
        let read = history.query(&request.event, request.pre, request.post)?;
        let mut response = TriggerRead {
            request_id: request.request_id.clone(),
            history: read,
            raw: None,
            result: None,
            fft_origin: "none",
        };
        let Some(block) = response.history.snapshot.as_ref() else {
            return Ok(response);
        };
        let start = block.interval().0;
        let mut key = key.clone();
        // Preserve the continuous key when its hop/alignment also matches this window.
        if start < key.alignment || !(start - key.alignment).is_multiple_of(key.hop as u64) {
            key.alignment = start;
        }
        let (raw, origin) = if let Some(raw) = self.graph.cached(&key, start) {
            (raw, "continuous-cache")
        } else if let Some(raw) = self
            .trigger_cache
            .as_ref()
            .filter(|raw| raw.key() == &key && raw.interval() == block.interval())
        {
            (Arc::clone(raw), "trigger-cache")
        } else {
            // An isolated, bounded one-shot graph uses the existing FFT implementation.
            // Continuous scheduling rejects reverse intervals; bypassing that fence would
            // also regress latest mailboxes and cumulative averages. No such publication here.
            let graph = Graph::new(Limits {
                max_nodes: 1,
                max_subscriptions: 1,
                max_in_flight: 1,
                max_frames: key.n,
                max_channels: self.format.input_ids.len(),
                ..Limits::default()
            })?;
            let subscription = graph.subscribe(
                key,
                Average::None,
                Presentation {
                    color: String::new(),
                    unit: "FS".into(),
                },
            )?;
            let jobs = graph.schedule_history(&response.history)?;
            if jobs.len() != 1 {
                return Err("trigger_job_count".into());
            }
            for job in jobs {
                if !job.run() {
                    return Err("trigger_publication_fenced".into());
                }
            }
            let snapshot = subscription.take_latest().ok_or("trigger_result_missing")?;
            let raw = Arc::clone(snapshot.raw());
            self.trigger_evaluations += graph.stats().fft_evaluations;
            graph.shutdown();
            (raw, "computed")
        };
        let mut result = MeasurementResult::from_fft(
            &raw,
            Capture {
                result_id: format!(
                    "trigger:{}:{}:{}:{}",
                    raw.id().graph,
                    raw.id().serial,
                    request.request_id,
                    NEXT_CAPTURE.fetch_add(1, Ordering::Relaxed)
                ),
                trigger_id: Some(request.event.id.clone()),
                trigger: Some(request.event.clone()),
                acquired_host_seconds: None,
                result_host_seconds: None,
                clock_mapping: None,
            },
            &profiles([raw.interval().0, raw.interval().1]),
            1.,
        )?;
        if filtered {
            result = result
                .with_filter_metadata(&self.filtered_metadata().ok_or("capture_filter_missing")?)?;
        }
        self.trigger_cache = Some(Arc::clone(&raw));
        response.raw = Some(raw);
        response.result = Some(Arc::new(result));
        response.fft_origin = origin;
        Ok(response)
    }
}

#[cfg(test)]
mod tests;
