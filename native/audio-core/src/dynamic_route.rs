//! Single pending control command, copied at an output callback block boundary.
//! Handles are single-owner. Compile/metadata/drop belong on the control thread.
use crate::{CompiledRoute, MAX_CALLBACK_FRAMES, MAX_CHANNELS, Route};
use serde::Serialize;
use std::cell::Cell;
use std::marker::PhantomData;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU8, AtomicU64, Ordering::*};

const EMPTY: u8 = 0;
const PENDING: u8 = 1;
const APPLIED: u8 = 2;
const TERMS: usize = MAX_CHANNELS * MAX_CHANNELS;

#[derive(Clone, Copy, Default)]
struct Term {
    input: usize,
    gain: f64,
}
struct FixedRoute {
    counts: [usize; MAX_CHANNELS],
    terms: [Term; TERMS],
    inputs: usize,
    outputs: usize,
}
impl FixedRoute {
    fn from_compiled(route: &CompiledRoute) -> Self {
        let mut fixed = Self {
            counts: [0; MAX_CHANNELS],
            terms: [Term::default(); TERMS],
            inputs: route.inputs,
            outputs: route.outputs,
        };
        for (row, terms) in route.terms.iter().enumerate() {
            fixed.counts[row] = terms.len();
            for (column, &(input, gain)) in terms.iter().enumerate() {
                fixed.terms[row * MAX_CHANNELS + column] = Term { input, gain };
            }
        }
        fixed
    }
    fn process(&self, input: &[f32], output: &mut [f32]) {
        for (src, dst) in input
            .chunks_exact(self.inputs)
            .zip(output.chunks_exact_mut(self.outputs))
        {
            for (row, value) in dst.iter_mut().enumerate() {
                // Preserve Route's reduction order and exclude zero terms, including NaN * 0.
                *value = self.terms[row * MAX_CHANNELS..row * MAX_CHANNELS + self.counts[row]]
                    .iter()
                    .map(|term| f64::from(src[term.input]) * term.gain)
                    .sum::<f64>() as f32;
            }
        }
    }
}

struct Mailbox {
    state: AtomicU8,
    closed: AtomicBool,
    callback_alive: AtomicBool,
    counts: [AtomicU64; MAX_CHANNELS],
    indices: [AtomicU64; TERMS],
    gains: [AtomicU64; TERMS],
    requested: AtomicU64,
    sequence: AtomicU64,
    applied: AtomicU64,
    rendered_through: AtomicU64,
}

/// Callback metadata contains only numbers; resolve sequence -> revision on control.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct BlockRoute {
    pub generation: u64,
    pub sequence: u64,
    pub interval: [u64; 2],
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RouteStatus {
    Applied,
    Cancelled,
}
#[derive(Debug, PartialEq, Eq, Serialize)]
pub struct RouteEvent {
    pub generation: u64,
    pub sequence: u64,
    pub revision: String,
    pub requested_sample: u64,
    pub applied_sample: Option<u64>,
    pub status: RouteStatus,
}
/// Control-side validation and metadata. A second command is explicitly busy until ack is read.
pub struct RouteController {
    shared: Arc<Mailbox>,
    known: Vec<String>,
    outputs: Vec<String>,
    generation: u64,
    sequence: u64,
    last_requested: u64,
    current_revision: String,
    pending: Option<(u64, String, u64)>,
    _single_owner: PhantomData<Cell<()>>,
}
/// Active coefficients live here, separately from the mailbox. No callback allocation/free/lock.
pub struct RouteCallback {
    shared: Arc<Mailbox>,
    active: FixedRoute,
    generation: u64,
    sequence: u64,
    next_sample: u64,
    _single_owner: PhantomData<Cell<()>>,
}

pub fn route_mailbox(
    known: Vec<String>,
    initial: Route,
    generation: u64,
) -> Result<(RouteController, RouteCallback), &'static str> {
    let active = FixedRoute::from_compiled(&initial.compile(&known)?);
    let shared = Arc::new(Mailbox {
        state: AtomicU8::new(EMPTY),
        closed: AtomicBool::new(false),
        callback_alive: AtomicBool::new(true),
        counts: std::array::from_fn(|_| AtomicU64::new(0)),
        indices: std::array::from_fn(|_| AtomicU64::new(0)),
        gains: std::array::from_fn(|_| AtomicU64::new(0)),
        requested: AtomicU64::new(0),
        sequence: AtomicU64::new(0),
        applied: AtomicU64::new(0),
        rendered_through: AtomicU64::new(0),
    });
    Ok((
        RouteController {
            shared: shared.clone(),
            known,
            outputs: initial.outputs,
            generation,
            sequence: 0,
            last_requested: 0,
            current_revision: initial.revision,
            pending: None,
            _single_owner: PhantomData,
        },
        RouteCallback {
            shared,
            active,
            generation,
            sequence: 0,
            next_sample: 0,
            _single_owner: PhantomData,
        },
    ))
}

impl RouteController {
    /// Transactional publication. Source order/physical output binding is fixed for this generation.
    pub fn publish(
        &mut self,
        route: &Route,
        generation: u64,
        requested_sample: u64,
    ) -> Result<u64, &'static str> {
        if self.shared.closed.load(Acquire) || !self.shared.callback_alive.load(Acquire) {
            return Err("route_closed");
        }
        if generation != self.generation {
            return Err("route_generation");
        }
        if self.pending.is_some() {
            return Err("route_busy");
        }
        let compiled = route.compile(&self.known)?;
        if route.outputs != self.outputs {
            return Err("route_output_binding");
        }
        if route.revision == self.current_revision {
            return Err("route_revision_unchanged");
        }
        if requested_sample < self.last_requested {
            return Err("route_request_order");
        }
        let sequence = self
            .sequence
            .checked_add(1)
            .ok_or("route_sequence_overflow")?;
        let fixed = FixedRoute::from_compiled(&compiled);
        // Only this owner writes EMPTY; callback reads PENDING until it releases APPLIED.
        for (index, count) in fixed.counts.iter().enumerate() {
            self.shared.counts[index].store(*count as u64, Relaxed);
        }
        for (index, term) in fixed.terms.iter().enumerate() {
            self.shared.indices[index].store(term.input as u64, Relaxed);
            self.shared.gains[index].store(term.gain.to_bits(), Relaxed);
        }
        self.shared.requested.store(requested_sample, Relaxed);
        self.shared.sequence.store(sequence, Relaxed);
        self.pending = Some((sequence, route.revision.clone(), requested_sample));
        self.sequence = sequence;
        self.last_requested = requested_sample;
        self.shared.state.store(PENDING, Release);
        Ok(sequence)
    }

    pub fn take_event(&mut self) -> Option<RouteEvent> {
        self.pending.as_ref()?;
        let state = self.shared.state.load(Acquire);
        let (status, applied_sample) = if state == APPLIED {
            (
                RouteStatus::Applied,
                Some(self.shared.applied.load(Relaxed)),
            )
        } else if !self.shared.callback_alive.load(Acquire) {
            // Re-read after observing callback destruction: its last ack may have raced the first load.
            if self.shared.state.load(Acquire) == APPLIED {
                (
                    RouteStatus::Applied,
                    Some(self.shared.applied.load(Relaxed)),
                )
            } else {
                (RouteStatus::Cancelled, None)
            }
        } else {
            return None;
        };
        let (sequence, revision, requested_sample) = self.pending.take().unwrap();
        if status == RouteStatus::Applied {
            self.current_revision = revision.clone();
        }
        self.shared.state.store(EMPTY, Release);
        Some(RouteEvent {
            generation: self.generation,
            sequence,
            revision,
            requested_sample,
            applied_sample,
            status,
        })
    }
    pub fn rendered_through(&self) -> u64 {
        self.shared.rendered_through.load(Acquire)
    }
    /// In-flight blocks may finish. Pending cancellation is final after callback destruction.
    pub fn close(&mut self) {
        self.shared.closed.store(true, Release);
    }
}
impl Drop for RouteController {
    fn drop(&mut self) {
        self.close();
    }
}
impl RouteCallback {
    /// Validate the whole block before changing coefficients, output, ack or position.
    pub fn process_block(
        &mut self,
        start: u64,
        input: &[f32],
        output: &mut [f32],
    ) -> Result<BlockRoute, &'static str> {
        if self.shared.closed.load(Acquire) {
            return Err("route_closed");
        }
        let frames = input.len() / self.active.inputs;
        if input.is_empty()
            || !input.len().is_multiple_of(self.active.inputs)
            || frames > MAX_CALLBACK_FRAMES
            || output.len() != frames * self.active.outputs
        {
            return Err("frame_shape");
        }
        let end = start.checked_add(frames as u64).ok_or("sample_overflow")?;
        if start != self.next_sample {
            return Err("output_position");
        }
        if self.shared.state.load(Acquire) == PENDING
            && self.shared.requested.load(Relaxed) <= start
        {
            for (index, count) in self.active.counts.iter_mut().enumerate() {
                *count = self.shared.counts[index].load(Relaxed) as usize;
            }
            for (index, term) in self.active.terms.iter_mut().enumerate() {
                term.input = self.shared.indices[index].load(Relaxed) as usize;
                term.gain = f64::from_bits(self.shared.gains[index].load(Relaxed));
            }
            self.sequence = self.shared.sequence.load(Relaxed);
            self.shared.applied.store(start, Relaxed);
            self.shared.state.store(APPLIED, Release);
        }
        self.active.process(input, output);
        self.next_sample = end;
        self.shared.rendered_through.store(end, Release);
        Ok(BlockRoute {
            generation: self.generation,
            sequence: self.sequence,
            interval: [start, end],
        })
    }
}
impl Drop for RouteCallback {
    fn drop(&mut self) {
        self.shared.callback_alive.store(false, Release);
    }
}

#[cfg(test)]
mod tests;
