//! A single f64 transform on the acquisition owner, with its own bounded history.
//! Raw and derived windows have separate fixed budgets and share the same graph.
use super::*;
use crate::filter::{Filter, FilterMetadata};

pub(super) struct FilteredStream {
    pub(super) key: FftKey,
    pub(super) history: History,
    next_window: u64,
    sos: bool,
}

impl<T: CaptureSample> Acquisition<T> {
    /// Configure before consuming input. Subscribe to the exact output key first.
    /// F32 input requires Filter::new_with_conversion; Filter::new never widens it.
    pub fn attach_filter(
        &mut self,
        filter: Filter,
        spec: FftSpec,
        limits: HistoryLimits,
    ) -> Result<(), String> {
        if self.state != WorkerState::Running
            || self.input_finished
            || self.filtered.is_some()
            || self.history.as_ref().unwrap().acquired_until() != 0
            || filter.input_source() != &self.key.source
            || spec.n > limits.capacity_frames
            || spec
                .alignment
                .checked_add(spec.n as u64)
                .is_none_or(|n| n > i64::MAX as u64)
        {
            return Err("capture_filter_configuration".into());
        }
        let key = FftKey {
            source: filter.output_source().clone(),
            n: spec.n,
            hop: spec.hop,
            alignment: spec.alignment,
            window: spec.window,
            remove_dc: false,
            input_gains: Vec::new(),
        };
        key.validate(&Limits::default())?;
        if !self.graph.has_demand(&key) {
            return Err("capture_filter_without_exact_demand".into());
        }
        let history = History::new(key.source.clone(), limits)?;
        let sos = filter.sos_state().is_some();
        self.graph.attach_filter(filter)?;
        self.filtered = Some(FilteredStream {
            next_window: key.alignment,
            key,
            history,
            sos,
        });
        Ok(())
    }
    pub fn filtered_key(&self) -> Option<&FftKey> {
        self.filtered.as_ref().map(|f| &f.key)
    }
    pub fn filtered_history(&self) -> Option<&History> {
        self.filtered.as_ref().map(|f| &f.history)
    }
    pub fn filtered_metadata(&self) -> Option<FilterMetadata> {
        self.filtered
            .as_ref()
            .and_then(|f| self.graph.filter_metadata(&f.key.source))
    }
    fn prune_filtered(&mut self) {
        if self
            .filtered
            .as_ref()
            .is_some_and(|f| self.graph.filter_metadata(&f.key.source).is_none())
        {
            self.filtered = None;
        }
    }
    pub(super) fn filtered_windows(&mut self, report: &mut PollReport) -> Result<(), String> {
        self.prune_filtered();
        if let Some(f) = &mut self.filtered {
            schedule_windows(
                &self.graph,
                &f.history,
                &f.key,
                &mut f.next_window,
                self.limits.windows_per_poll,
                &mut report.filtered_windows,
            )?;
        }
        Ok(())
    }
    fn append_filtered(
        &mut self,
        block: Option<SignalBlock>,
        report: &mut PollReport,
    ) -> Result<(), String> {
        if let Some(block) = block {
            self.filtered.as_mut().unwrap().history.append_ref(&block)?;
            report.filtered_blocks.push(Arc::new(block));
        }
        self.filtered_windows(report)
    }
    pub(super) fn process_filtered(
        &mut self,
        block: &SignalBlock,
        report: &mut PollReport,
    ) -> Result<(), String> {
        self.prune_filtered();
        let Some(f) = &self.filtered else {
            return Ok(());
        };
        let output = match self.graph.process_filter(&f.key.source, block) {
            Ok(output) => output,
            Err(_) if self.graph.filter_metadata(&f.key.source).is_none() => {
                // A token may be dropped on another thread between prune and processing.
                self.filtered = None;
                return Ok(());
            }
            Err(reason) => return Err(reason),
        };
        self.append_filtered(output, report)
    }
    pub(super) fn filtered_gap(&mut self) -> Result<(), String> {
        self.prune_filtered();
        if let Some(f) = &self.filtered {
            if f.sos {
                return Err("unsupported_iir_gap_or_invalid".into());
            }
            // FIR advances the missing support on the next block or explicit end.
            // Until then discard old mailboxes/averages; do not fabricate samples.
            self.graph.invalidate_source(&f.key.source)?;
        }
        Ok(())
    }
    /// The producer must be stopped and the queue drained before this explicit EOF.
    /// Flushes centered lookahead, preserves trailing gaps, then poll drains remaining windows.
    /// Stop/cancel never calls this: cancellation must not create endpoint output.
    pub fn finish_input(&mut self) -> Result<PollReport, String> {
        if self.state != WorkerState::Running || self.input_finished {
            return Err("capture_input_finished_or_not_running".into());
        }
        if self.receiver.as_ref().is_some_and(|r| !r.is_drained()) {
            return Err("capture_queue_not_drained".into());
        }
        self.prune_filtered();
        let result: Result<PollReport, String> = (|| {
            let mut report = PollReport::default();
            if let Some(f) = &self.filtered {
                let end = self.history.as_ref().unwrap().acquired_until();
                let block = match self.graph.finish_filter(&f.key.source, end) {
                    Ok(block) => block,
                    Err(_) if self.graph.filter_metadata(&f.key.source).is_none() => {
                        self.filtered = None;
                        return Ok(report);
                    }
                    Err(reason) => return Err(reason),
                };
                self.append_filtered(block, &mut report)?;
            }
            Ok(report)
        })();
        match result {
            Ok(report) => {
                self.receiver = None;
                self.input_finished = true;
                Ok(report)
            }
            Err(reason) => {
                self.state = WorkerState::Failed(reason.clone());
                self.stop();
                Err(reason)
            }
        }
    }
}

pub(super) fn schedule_windows(
    graph: &Graph,
    history: &History,
    key: &FftKey,
    next: &mut u64,
    budget: usize,
    events: &mut Vec<WindowEvent>,
) -> Result<(), String> {
    while events.len() < budget {
        let end = next.checked_add(key.n as u64).ok_or("position_overflow")?;
        if end > i64::MAX as u64 {
            return Err("position_overflow".into());
        }
        if end > history.acquired_until() {
            break;
        }
        let read = history.read_interval(*next as i64, end as i64)?;
        let mut event = WindowEvent {
            history: read.report.clone(),
            result_id: None,
            numeric: false,
        };
        if read.snapshot.is_some() {
            for job in graph.schedule_history(&read)? {
                let completion = job.compute();
                event.result_id = Some(completion.result().id());
                event.numeric = completion.result().numeric().is_some();
                let result_key = completion.result().key().clone();
                if !completion.publish() {
                    if graph.has_demand(&result_key) {
                        return Err("publication_fenced".into());
                    }
                    event.result_id = None;
                    event.numeric = false;
                }
            }
        } else {
            graph.invalidate_source(&key.source)?;
        }
        events.push(event);
        *next = next
            .checked_add(key.hop as u64)
            .ok_or("position_overflow")?;
    }
    Ok(())
}

#[cfg(test)]
mod tests;
