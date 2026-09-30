//! Bounded, worker-owned history. Reads copy immutable windows; no reader blocks acquisition.
//! This API allocates and must never run in an audio callback.
use crate::{Graph, InvalidSpan, Precision, Rational, Samples, SignalBlock, Source};
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::sync::Arc;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TriggerEvent {
    pub id: String,
    pub stream_id: String,
    pub generation: u64,
    pub timebase_id: String,
    pub sample: Rational,
    pub source: String,
    pub kind: String,
    pub polarity: String,
    pub condition_revision: String,
    pub validity: Vec<InvalidSpan>,
    pub received_host_seconds: Option<Rational>,
}
#[derive(Clone, Copy, Debug)]
pub struct HistoryLimits {
    pub capacity_frames: usize,
    pub max_numeric_bytes: usize,
    pub max_validity_spans: usize,
}
impl HistoryLimits {
    pub fn frames(capacity_frames: usize) -> Self {
        Self {
            capacity_frames,
            max_numeric_bytes: 64 * 1024 * 1024,
            max_validity_spans: 4096,
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ReadReport {
    pub stream_id: String,
    pub generation: u64,
    pub timebase_id: String,
    pub interval: [i64; 2],
    pub status: String,
    pub missing: Vec<[i64; 2]>,
    pub pending: Vec<[i64; 2]>,
    pub reason: Option<String>,
}
pub struct HistoryRead {
    pub report: ReadReport,
    pub trigger: Option<TriggerEvent>,
    pub fractional_residual: Rational,
    pub snapshot: Option<Arc<SignalBlock>>,
}
/// Independent cursor; seeking and successful reads affect only this reader.
pub struct HistoryReader {
    stream_id: String,
    generation: u64,
    timebase_id: String,
    position: i64,
}
impl HistoryReader {
    pub fn position(&self) -> i64 {
        self.position
    }
    pub fn seek(&mut self, position: i64) {
        self.position = position;
    }
}
pub struct History {
    source: Source,
    limits: HistoryLimits,
    high: u64,
    blocks: VecDeque<SignalBlock>,
}
impl History {
    pub fn new(source: Source, limits: HistoryLimits) -> Result<Self, String> {
        let bytes = limits
            .capacity_frames
            .checked_mul(source.channel_ids.len())
            .and_then(|n| {
                n.checked_mul(if source.precision == Precision::F32 {
                    4
                } else {
                    8
                })
            });
        if !source.valid()
            || limits.capacity_frames == 0
            || limits.max_validity_spans == 0
            || limits.capacity_frames > i64::MAX as usize
            || bytes.is_none_or(|n| n > limits.max_numeric_bytes)
        {
            return Err("history_limits".into());
        }
        Ok(Self {
            source,
            limits,
            high: 0,
            blocks: VecDeque::new(),
        })
    }
    pub fn source(&self) -> &Source {
        &self.source
    }
    pub fn acquired_until(&self) -> u64 {
        self.high
    }
    pub fn retained_frames(&self) -> usize {
        self.blocks.iter().map(|b| b.frames).sum()
    }
    pub fn retained_numeric_bytes(&self) -> usize {
        self.retained_frames()
            * self.source.channel_ids.len()
            * if self.source.precision == Precision::F32 {
                4
            } else {
                8
            }
    }
    /// Explicit restart: construct/validate before releasing history. Existing snapshots remain owned.
    /// The caller retires graph demand before admitting blocks from this new generation.
    pub fn restart(&mut self, source: Source) -> Result<(), String> {
        if source.stream_id != self.source.stream_id || source.generation <= self.source.generation
        {
            return Err("stale_generation".into());
        }
        *self = Self::new(source, self.limits)?;
        Ok(())
    }
    /// Validate replacement first, then fence graph publication before switching history.
    /// Call on the sole control/analysis owner with existing stream subscriptions.
    pub fn restart_with_graph(&mut self, source: Source, graph: &Graph) -> Result<(), String> {
        if source.stream_id != self.source.stream_id || source.generation <= self.source.generation
        {
            return Err("stale_generation".into());
        }
        let replacement = Self::new(source, self.limits)?;
        graph.retire_stream_before(&replacement.source.stream_id, replacement.source.generation)?;
        *self = replacement;
        Ok(())
    }
    /// Reject duplicate/reversed/configuration-changed blocks before mutating any history.
    /// Route/filter/calibration revisions can change within a generation; reads cannot cross those boundaries.
    pub fn append(&mut self, block: SignalBlock) -> Result<(), String> {
        if block.source.generation != self.source.generation {
            return Err(if block.source.generation < self.source.generation {
                "stale_generation"
            } else {
                "restart_required"
            }
            .into());
        }
        if block.source.stream_id != self.source.stream_id
            || block.source.channel_ids != self.source.channel_ids
            || block.source.precision != self.source.precision
            || block.source.timebase != self.source.timebase
        {
            return Err("configuration_requires_new_generation".into());
        }
        let end = block.interval().1;
        if end > i64::MAX as u64 {
            return Err("position_overflow".into());
        }
        if block.start < self.high {
            return Err("overlap_or_reverse".into());
        }
        let floor = end.saturating_sub(self.limits.capacity_frames as u64);
        let spans = self
            .blocks
            .iter()
            .flat_map(|b| &b.validity)
            .chain(&block.validity)
            .filter(|v| v.end > floor)
            .count();
        if spans > self.limits.max_validity_spans {
            return Err("validity_capacity".into());
        }
        // Retain only the capacity-sized tail, with fresh vectors so an oversized input allocation
        // cannot remain hidden behind a small logical frame count.
        while self.blocks.front().is_some_and(|b| b.interval().1 <= floor) {
            self.blocks.pop_front();
        }
        if let Some(old) = self.blocks.pop_front_if(|b| b.start < floor) {
            self.blocks
                .push_front(slice(&old, floor, old.interval().1)?);
        }
        self.blocks
            .push_back(slice(&block, block.start.max(floor), end)?);
        self.high = end;
        Ok(())
    }
    pub fn reader(&self, position: i64) -> HistoryReader {
        HistoryReader {
            stream_id: self.source.stream_id.clone(),
            generation: self.source.generation,
            timebase_id: self.source.timebase.id.clone(),
            position,
        }
    }
    pub fn read_next(
        &self,
        reader: &mut HistoryReader,
        frames: usize,
    ) -> Result<HistoryRead, String> {
        self.check_identity(&reader.stream_id, reader.generation, &reader.timebase_id)?;
        let end = reader
            .position
            .checked_add(i64::try_from(frames).map_err(|_| "history_request")?)
            .ok_or("history_request")?;
        let read = self.read_interval(reader.position, end)?;
        if read.snapshot.is_some() {
            reader.position = end;
        }
        Ok(read)
    }
    fn check_identity(&self, stream: &str, generation: u64, timebase: &str) -> Result<(), String> {
        if generation != self.source.generation {
            return Err("stale_generation".into());
        }
        if stream != self.source.stream_id || timebase != self.source.timebase.id {
            return Err("stream_or_timebase_mismatch".into());
        }
        Ok(())
    }
    pub fn query(&self, event: &TriggerEvent, pre: u64, post: u64) -> Result<HistoryRead, String> {
        self.check_identity(&event.stream_id, event.generation, &event.timebase_id)?;
        if event.id.is_empty()
            || !event.sample.valid()
            || event.source.is_empty()
            || event.kind.is_empty()
            || event.condition_revision.is_empty()
            || event
                .received_host_seconds
                .as_ref()
                .is_some_and(|r| !r.valid())
        {
            return Err("trigger_event".into());
        }
        let denominator = i128::from(event.sample.denominator);
        let anchor = i128::from(event.sample.numerator).div_euclid(denominator);
        let start = i64::try_from(anchor - i128::from(pre)).map_err(|_| "history_request")?;
        let end = i64::try_from(anchor + i128::from(post)).map_err(|_| "history_request")?;
        let mut read = self.read_interval(start, end)?;
        read.fractional_residual = Rational {
            numerator: i64::try_from(i128::from(event.sample.numerator).rem_euclid(denominator))
                .map_err(|_| "rational_overflow")?,
            denominator: event.sample.denominator,
        }
        .normalized()?;
        read.trigger = Some(event.clone());
        Ok(read)
    }
    pub fn read_interval(&self, start: i64, end: i64) -> Result<HistoryRead, String> {
        if end <= start {
            return Err("history_request".into());
        }
        let high = self.high as i64;
        let mut cursor = start;
        let mut missing = Vec::new();
        let acquired_end = end.min(high);
        for b in &self.blocks {
            let left = b.start as i64;
            let right = b.interval().1 as i64;
            if right <= cursor || left >= acquired_end {
                continue;
            }
            if left > cursor {
                missing.push([cursor, left.min(acquired_end)]);
            }
            cursor = cursor.max(right.min(acquired_end));
        }
        if cursor < acquired_end {
            missing.push([cursor, acquired_end]);
        }
        let pending = if end > high {
            vec![[start.max(high), end]]
        } else {
            Vec::new()
        };
        let status = if !missing.is_empty() {
            "gap"
        } else if !pending.is_empty() {
            "pending"
        } else {
            "snapshot"
        };
        let snapshot = if status == "snapshot" {
            let parts: Vec<_> = self
                .blocks
                .iter()
                .filter(|b| b.start < end as u64 && b.interval().1 > start as u64)
                .collect();
            let source = &parts[0].source;
            if parts.iter().any(|b| &b.source != source) {
                return Err("mixed_source_conditions".into());
            }
            let mut validity = Vec::new();
            let mut samples = match source.precision {
                Precision::F32 => Samples::F32(Vec::new()),
                Precision::F64 => Samples::F64(Vec::new()),
            };
            for b in parts {
                let part = slice(
                    b,
                    (start as u64).max(b.start),
                    (end as u64).min(b.interval().1),
                )?;
                match (&mut samples, part.samples) {
                    (Samples::F32(v), Samples::F32(p)) => v.extend(p),
                    (Samples::F64(v), Samples::F64(p)) => v.extend(p),
                    _ => unreachable!(),
                }
                validity.extend(part.validity);
            }
            Some(Arc::new(SignalBlock::new(
                source.clone(),
                start as u64,
                samples,
                validity,
            )?))
        } else {
            None
        };
        Ok(HistoryRead {
            report: ReadReport {
                stream_id: self.source.stream_id.clone(),
                generation: self.source.generation,
                timebase_id: self.source.timebase.id.clone(),
                interval: [start, end],
                status: status.into(),
                reason: (!missing.is_empty()).then(|| "missing".into()),
                missing,
                pending,
            },
            trigger: None,
            fractional_residual: Rational {
                numerator: 0,
                denominator: 1,
            },
            snapshot,
        })
    }
}
fn slice(block: &SignalBlock, start: u64, end: u64) -> Result<SignalBlock, String> {
    let channels = block.source.channel_ids.len();
    let from = (start - block.start) as usize * channels;
    let to = (end - block.start) as usize * channels;
    let samples = match &block.samples {
        Samples::F32(v) => Samples::F32(v[from..to].to_vec()),
        Samples::F64(v) => Samples::F64(v[from..to].to_vec()),
    };
    let validity = block
        .validity
        .iter()
        .filter(|v| v.start < end && v.end > start)
        .map(|v| InvalidSpan {
            start: v.start.max(start),
            end: v.end.min(end),
            ..v.clone()
        })
        .collect();
    SignalBlock::new(block.source.clone(), start, samples, validity)
}

#[cfg(test)]
mod tests;
