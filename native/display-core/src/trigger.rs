//! One bounded control mailbox, consumed only by the analysis owner.
//! Pending reads need an explicit retry; a held capture never stops acquisition.
use super::*;
use graph_core::Samples;
use graph_core::acquisition::TriggerRequest;
use serde_json::Value;

const MAX_REQUEST_BYTES: usize = 8192;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Submission {
    revision: u64,
    request: TriggerRequest,
}
#[derive(Default)]
pub(super) struct Controller {
    revision: u64,
    active: Option<Arc<Submission>>,
    command: Option<Command>,
    evidence: Vec<DeferredEvidence>,
}
struct DeferredEvidence {
    directory: PathBuf,
    generation: u64,
    submission: Arc<Submission>,
    receipt: Arc<TriggerResponse>,
    bytes: Option<Vec<u8>>,
    parent: Option<filter::ParentEvidence>,
}
fn defer_evidence(controller: &mut Controller, evidence: DeferredEvidence) -> Result<(), String> {
    if controller.evidence.iter().any(|old| {
        old.generation == evidence.generation
            && old.submission.revision == evidence.submission.revision
            && old.receipt.status == evidence.receipt.status
    }) {
        return Ok(()); // retain the first pending/retry diagnostic, as with create_new
    }
    if controller.evidence.len() == 8 {
        return Err("live_trigger_evidence_capacity".into());
    }
    controller.evidence.push(evidence);
    Ok(())
}
pub(super) fn finish_evidence(owner: &Owner, request: &Request) -> Result<(), String> {
    let evidence = std::mem::take(&mut owner.mailbox.lock().unwrap().trigger.evidence);
    for entry in evidence {
        save_evidence(
            &entry.directory,
            entry.generation,
            &entry.submission,
            &entry.receipt,
            entry.bytes,
            entry.parent,
            request,
        )?;
    }
    Ok(())
}
enum Command {
    Read(Arc<Submission>),
    Release,
}
#[derive(Debug)]
pub struct TriggerResponse {
    pub encoded: String,
    pub frame: Option<Arc<Frame>>,
    status: String,
}
fn response(submission: &Submission, status: &str, reason: Option<&str>) -> Arc<TriggerResponse> {
    Arc::new(TriggerResponse {
        encoded: json!({"schema_version": 1, "revision": submission.revision,
            "request": submission.request, "status": status, "reason": reason,
            "history": null, "fractional_residual": null, "fft_origin": "none", "frame": null})
        .to_string(),
        frame: None,
        status: status.into(),
    })
}
impl Display {
    /// Control/Qt thread: validate size and ordering, then enqueue. Never calls the graph.
    pub fn request_trigger(&mut self, encoded: &str) -> bool {
        if encoded.len() > MAX_REQUEST_BYTES {
            return false;
        }
        let Ok(submission) = serde_json::from_str::<Submission>(encoded) else {
            return false;
        };
        let submission = Arc::new(submission);
        let mut slot = self.mailbox.lock().unwrap();
        if !matches!(slot.snapshot.state, State::Preparing | State::Running)
            || self.stop.load(Ordering::Acquire)
            || submission.request.event.generation != slot.snapshot.generation
            || submission.revision <= slot.trigger.revision
            || slot.trigger.command.is_some()
        {
            return false;
        }
        slot.trigger.revision = submission.revision;
        slot.trigger.active = Some(submission.clone());
        slot.snapshot.trigger = Some(response(&submission, "queued", None));
        slot.trigger.command = Some(Command::Read(submission));
        true
    }
    pub fn retry_trigger(&mut self, generation: u64, revision: u64) -> bool {
        let mut slot = self.mailbox.lock().unwrap();
        if !matches!(slot.snapshot.state, State::Preparing | State::Running)
            || self.stop.load(Ordering::Acquire)
            || generation != slot.snapshot.generation
            || revision != slot.trigger.revision
            || slot.trigger.command.is_some()
            || slot
                .snapshot
                .trigger
                .as_ref()
                .is_none_or(|r| !matches!(r.status.as_str(), "pending" | "gap"))
        {
            return false;
        }
        let Some(submission) = slot.trigger.active.clone() else {
            return false;
        };
        slot.snapshot.trigger = Some(response(&submission, "queued", None));
        slot.trigger.command = Some(Command::Read(submission));
        true
    }
    pub fn release_trigger(&mut self, generation: u64, revision: u64) -> bool {
        let mut slot = self.mailbox.lock().unwrap();
        if generation != slot.snapshot.generation || revision != slot.trigger.revision {
            return false;
        }
        let Some(submission) = slot.trigger.active.take() else {
            return false;
        };
        // Release supersedes a queued/in-flight read and fences its later publication.
        slot.trigger.command = Some(Command::Release);
        slot.snapshot.trigger = Some(response(&submission, "released", None));
        true
    }
}
pub(super) fn cancel(slot: &mut Mailbox, reason: Option<&str>) {
    slot.trigger.command = None;
    if slot
        .snapshot
        .trigger
        .as_ref()
        .is_none_or(|r| r.frame.is_none())
        && let Some(submission) = slot.trigger.active.take()
    {
        slot.snapshot.trigger = Some(response(&submission, "cancelled", reason));
    }
}
pub(super) fn process<T: CaptureSample>(
    owner: &Owner,
    notify: &impl Fn(u64) -> bool,
    request: &Request,
    acquisition: &mut Acquisition<T>,
) -> Result<(), String> {
    let command = owner.mailbox.lock().unwrap().trigger.command.take();
    let Some(command) = command else {
        return Ok(());
    };
    let Command::Read(submission) = command else {
        acquisition.release_trigger_cache();
        return Ok(());
    };
    let read = if request.filter.is_some() {
        acquisition.capture_filtered_trigger_with_profiles(&submission.request, |interval| {
            request.profiles(interval)
        })
    } else {
        acquisition.capture_trigger_with_profiles(&submission.request, |interval| {
            request.profiles(interval)
        })
    };
    let (receipt, evidence) = match read {
        Err(reason) => (response(&submission, "error", Some(&reason)), None),
        Ok(read) => {
            let frame = read
                .result
                .as_ref()
                .map(|result| project_result(Arc::clone(result)).map(Arc::new))
                .transpose()?;
            let projection: Option<Value> = frame
                .as_ref()
                .map(|f| serde_json::from_str(&f.projection))
                .transpose()
                .map_err(|e| e.to_string())?;
            let status = if frame.is_some() {
                "complete"
            } else {
                read.history.report.status.as_str()
            };
            let encoded = json!({"schema_version": 1, "revision": submission.revision,
                "request": submission.request, "status": status, "reason": read.history.report.reason,
                "history": read.history.report, "fractional_residual": read.history.fractional_residual,
                "fft_origin": read.fft_origin, "frame": projection,
                "acquired_until": acquisition.filtered_history().or_else(|| acquisition.history()).unwrap().acquired_until(),
                "trigger_evaluations": acquisition.trigger_evaluations(),
                "continuous_evaluations": acquisition.graph().stats().fft_evaluations}).to_string();
            let evidence = read
                .history
                .snapshot
                .filter(|_| request.evidence.is_some())
                .map(|block| {
                    let bytes: Vec<u8> = match block.samples() {
                        Samples::F32(v) => v.iter().flat_map(|s| s.to_le_bytes()).collect(),
                        Samples::F64(v) => v.iter().flat_map(|s| s.to_le_bytes()).collect(),
                    };
                    bytes
                });
            (
                Arc::new(TriggerResponse {
                    encoded,
                    frame,
                    status: status.into(),
                }),
                evidence,
            )
        }
    };
    {
        let mut slot = owner.mailbox.lock().unwrap();
        if owner.stop.load(Ordering::Acquire)
            || slot
                .trigger
                .active
                .as_ref()
                .is_none_or(|a| a.revision != submission.revision)
        {
            return Ok(());
        }
        slot.snapshot.trigger = Some(receipt.clone());
    }
    // Evidence I/O runs on the analysis owner, outside the control lock and audio callback.
    if let Some(path) = &request.evidence {
        if request.live.is_some() {
            let parent = receipt
                .frame
                .as_ref()
                .map(|frame| filter::parent_evidence(acquisition, frame.result.interval()))
                .transpose()?
                .flatten();
            defer_evidence(
                &mut owner.mailbox.lock().unwrap().trigger,
                DeferredEvidence {
                    directory: path.clone(),
                    generation: acquisition.format().generation,
                    submission: submission.clone(),
                    receipt: receipt.clone(),
                    bytes: evidence,
                    parent,
                },
            )?;
        } else {
            save_evidence(
                path,
                acquisition.format().generation,
                &submission,
                &receipt,
                evidence,
                None,
                request,
            )?;
        }
    }
    if !owner.notify(notify) {
        owner.stop.store(true, Ordering::Release);
    }
    Ok(())
}
fn save_evidence(
    path: &std::path::Path,
    generation: u64,
    submission: &Submission,
    receipt: &TriggerResponse,
    bytes: Option<Vec<u8>>,
    parent: Option<filter::ParentEvidence>,
    request: &Request,
) -> Result<(), String> {
    let stem = format!(
        "trigger-{generation}-{}-{}",
        submission.revision, receipt.status
    );
    // Retrying a still-pending read may repeat the status; keep the first diagnostic.
    let path = path.join(stem);
    use std::io::Write;
    match std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path.with_extension("json"))
    {
        Ok(mut file) => file
            .write_all(receipt.encoded.as_bytes())
            .map_err(|e| e.to_string())?,
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => return Ok(()),
        Err(e) => return Err(e.to_string()),
    }
    if let Some(frame) = &receipt.frame {
        calibration::save_result(&frame.result, &path.with_extension("result.json"), request)?;
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path.with_extension("bin"))
            .map_err(|e| e.to_string())?;
        file.write_all(&bytes.ok_or("trigger_evidence_bytes")?)
            .map_err(|e| e.to_string())?;
        if let Some(parent) = parent {
            parent.write(&path)?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests;
