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
    let (receipt, evidence) = match acquisition.capture_trigger(&submission.request) {
        Err(reason) => (response(&submission, "error", Some(&reason)), None),
        Ok(mut read) => {
            if !request.calibration.is_empty()
                && let (Some(raw), Some(result)) = (&read.raw, &read.result)
            {
                read.result = Some(Arc::new(calibration::calibrated_result(
                    raw,
                    result.capture().clone(),
                    request,
                )?));
            }
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
                "acquired_until": acquisition.history().unwrap().acquired_until(),
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
        save_evidence(
            path,
            acquisition.format().generation,
            &submission,
            &receipt,
            evidence,
            request,
        )?;
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
    }
    Ok(())
}

#[cfg(test)]
mod tests;
