//! MIG-005-A explicit N-channel boundary. Control operations allocate; `process_into`
//! and Producer::write are bounded and allocation/lock/free-free after setup.
#![forbid(unsafe_code)]
use serde::{Deserialize, Serialize};
use std::collections::{BTreeSet, HashSet};
use std::marker::PhantomData;
use std::sync::Arc;
use std::sync::atomic::{AtomicU32, AtomicU64, Ordering::SeqCst};

pub const MAX_CHANNELS: usize = 16;
pub const MAX_CALLBACK_FRAMES: usize = 8192;
pub const MAX_QUEUE_FRAMES: usize = 1_048_576;

fn unique(ids: &[String]) -> bool {
    ids.iter().all(|id| !id.is_empty()) && ids.iter().collect::<HashSet<_>>().len() == ids.len()
}

/// Physical bindings are explicit; empty input OR output is allowed, but not both.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IoFormat {
    pub stream_id: String,
    pub generation: u64,
    pub timebase_id: String,
    pub clock_domain: String,
    pub rate: [u64; 2],
    pub input_ids: Vec<String>,
    pub input_ports: Vec<usize>,
    pub output_ids: Vec<String>,
    pub output_ports: Vec<usize>,
}
impl IoFormat {
    pub fn validate(
        &self,
        device_inputs: usize,
        device_outputs: usize,
    ) -> Result<(), &'static str> {
        if self.stream_id.is_empty()
            || self.timebase_id.is_empty()
            || self.clock_domain.is_empty()
            || self.rate.contains(&0)
            || self.input_ids.is_empty() && self.output_ids.is_empty()
        {
            return Err("stream_format");
        }
        for (ids, ports, available) in [
            (&self.input_ids, &self.input_ports, device_inputs),
            (&self.output_ids, &self.output_ports, device_outputs),
        ] {
            if ids.len() > MAX_CHANNELS
                || !unique(ids)
                || ids.len() != ports.len()
                || ports.iter().any(|p| *p >= available)
                || ports.iter().collect::<HashSet<_>>().len() != ports.len()
            {
                return Err("channel_binding");
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Route {
    pub inputs: Vec<String>,
    pub outputs: Vec<String>,
    pub gains: Vec<Vec<f64>>,
    pub revision: String,
}
impl Route {
    pub fn validate(&self, known: &[String]) -> Result<(), &'static str> {
        if !unique(&self.inputs) || self.inputs.iter().any(|id| !known.contains(id)) {
            return Err("unknown_or_duplicate_input");
        }
        if self.outputs.is_empty() || !unique(&self.outputs) {
            return Err("duplicate_or_empty_output");
        }
        if self.gains.len() != self.outputs.len()
            || self.gains.iter().any(|r| r.len() != self.inputs.len())
        {
            return Err("gain_shape");
        }
        if self.gains.iter().flatten().any(|g| !g.is_finite()) {
            return Err("nonfinite_gain");
        }
        if self.inputs.len() > MAX_CHANNELS
            || self.outputs.len() > MAX_CHANNELS
            || self.revision.is_empty()
        {
            return Err("route_limit_or_revision");
        }
        Ok(())
    }
    /// Compiled once on the control thread. No implicit clipping/normalization.
    pub fn compile(&self, known: &[String]) -> Result<CompiledRoute, &'static str> {
        self.validate(known)?;
        if known.is_empty() || known.len() > MAX_CHANNELS || !unique(known) {
            return Err("channel_ids");
        }
        Ok(CompiledRoute {
            inputs: known.len(),
            outputs: self.outputs.len(),
            terms: self
                .gains
                .iter()
                .map(|row| {
                    row.iter()
                        .zip(&self.inputs)
                        .filter(|(gain, _)| **gain != 0.0)
                        .map(|(gain, id)| (known.iter().position(|k| k == id).unwrap(), *gain))
                        .collect()
                })
                .collect(),
        })
    }
}

pub struct CompiledRoute {
    inputs: usize,
    outputs: usize,
    terms: Vec<Vec<(usize, f64)>>,
}
impl CompiledRoute {
    /// Callback-safe f32 interleaved route; reject shape before touching output.
    pub fn process_into(&self, input: &[f32], output: &mut [f32]) -> Result<(), &'static str> {
        if input.is_empty()
            || !input.len().is_multiple_of(self.inputs)
            || input.len() / self.inputs > MAX_CALLBACK_FRAMES
            || output.len() != input.len() / self.inputs * self.outputs
        {
            return Err("frame_shape");
        }
        for (src, dst) in input
            .chunks_exact(self.inputs)
            .zip(output.chunks_exact_mut(self.outputs))
        {
            for (y, terms) in dst.iter_mut().zip(&self.terms) {
                *y = terms
                    .iter()
                    .map(|(index, gain)| f64::from(src[*index]) * gain)
                    .sum::<f64>() as f32;
            }
        }
        Ok(())
    }
}

pub struct RouteControl {
    known: Vec<String>,
    current: Route,
    last_boundary: u64,
}
impl RouteControl {
    pub fn new(known: Vec<String>, initial: Route) -> Result<Self, &'static str> {
        if known.len() > MAX_CHANNELS || !unique(&known) {
            return Err("channel_ids");
        }
        initial.validate(&known)?;
        Ok(Self {
            known,
            current: initial,
            last_boundary: 0,
        })
    }
    /// Control/worker boundary only, not a callback queue. Rejection is transactional.
    pub fn apply(
        &mut self,
        route: Route,
        requested: u64,
        boundary: u64,
    ) -> Result<u64, &'static str> {
        route.validate(&self.known)?;
        if requested > boundary || boundary < self.last_boundary {
            return Err("boundary_before_request");
        }
        self.current = route;
        self.last_boundary = boundary;
        Ok(boundary)
    }
    pub fn current(&self) -> &Route {
        &self.current
    }
}

#[derive(Clone, Debug, Deserialize)]
pub struct InvalidRange {
    pub channel_id: String,
    pub interval: [u64; 2],
    pub reason: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RouteInput {
    pub channel_ids: Vec<String>,
    pub values: Vec<Vec<Option<f64>>>,
    pub start: u64,
    pub unit: String,
    pub route: Route,
    pub validity: Vec<InvalidRange>,
}
#[derive(Debug, Serialize)]
pub struct RouteResult {
    pub channel_ids: Vec<String>,
    pub values: Vec<Vec<Option<f64>>>,
    pub validity: Vec<RoutedInvalid>,
    pub unit: String,
    pub revision: String,
    pub input_calibration_ids: Vec<Vec<String>>,
    pub single_v_per_fs: Vec<Option<f64>>,
}
#[derive(Debug, Serialize)]
pub struct RoutedInvalid {
    channel_id: String,
    interval: [u64; 2],
    reasons: BTreeSet<String>,
}
/// Owned immutable-by-interface worker result. Null is accepted only with a reason.
pub fn route_owned(data: &RouteInput) -> Result<RouteResult, &'static str> {
    if data.channel_ids.is_empty() || !unique(&data.channel_ids) {
        return Err("channel_ids");
    }
    if data.values.is_empty()
        || data
            .values
            .iter()
            .any(|r| r.len() != data.channel_ids.len())
        || data.start.checked_add(data.values.len() as u64).is_none()
    {
        return Err("frame_shape");
    }
    data.route.validate(&data.channel_ids)?;
    if data.unit != "FS" {
        return Err("mix_requires_explicit_unit_conversion");
    }
    for row in &data.values {
        if row.iter().flatten().any(|v| !v.is_finite()) {
            return Err("nonfinite_without_encoding");
        }
    }
    let indices: Vec<_> = data
        .route
        .inputs
        .iter()
        .map(|ch| data.channel_ids.iter().position(|id| id == ch).unwrap())
        .collect();
    let mut values = Vec::new();
    let mut validity = Vec::new();
    for (offset, row) in data.values.iter().enumerate() {
        let sample = data.start + offset as u64;
        let mut output = Vec::new();
        for (channel, gains) in data.route.outputs.iter().zip(&data.route.gains) {
            let mut reasons = BTreeSet::new();
            let mut total = 0.0;
            for ((ch, index), gain) in data.route.inputs.iter().zip(&indices).zip(gains) {
                if *gain == 0.0 {
                    continue;
                }
                let input_reasons: BTreeSet<_> = data
                    .validity
                    .iter()
                    .filter(|v| {
                        v.channel_id == *ch && v.interval[0] <= sample && sample < v.interval[1]
                    })
                    .map(|v| v.reason.clone())
                    .collect();
                if row[*index].is_none() && input_reasons.is_empty() {
                    return Err("null_without_reason");
                }
                reasons.extend(input_reasons);
                if let Some(v) = row[*index] {
                    total += gain * v;
                }
            }
            if !total.is_finite() {
                reasons.insert("nonfinite".into());
            }
            output.push(if reasons.is_empty() {
                Some(total)
            } else {
                None
            });
            if !reasons.is_empty() {
                validity.push(RoutedInvalid {
                    channel_id: channel.clone(),
                    interval: [sample, sample + 1],
                    reasons,
                });
            }
        }
        values.push(output);
    }
    Ok(RouteResult {
        channel_ids: data.route.outputs.clone(),
        values,
        validity,
        unit: "FS".into(),
        revision: data.route.revision.clone(),
        input_calibration_ids: data
            .route
            .gains
            .iter()
            .map(|row| {
                data.route
                    .inputs
                    .iter()
                    .zip(row)
                    .filter(|(_, gain)| **gain != 0.0)
                    .map(|(ch, _)| ch.clone())
                    .collect()
            })
            .collect(),
        single_v_per_fs: vec![None; data.route.outputs.len()],
    })
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeviceStage {
    pub mute: bool,
    pub gain: f64,
    pub quantization_step: f64,
    pub mapping: Vec<usize>,
    pub dither: String,
}
impl DeviceStage {
    pub fn validate(&self, inputs: usize) -> Result<(), &'static str> {
        if !self.gain.is_finite()
            || !self.quantization_step.is_finite()
            || self.quantization_step < 0.0
            || self.dither != "none"
            || self.mapping.is_empty()
            || self.mapping.len() > MAX_CHANNELS
            || self.mapping.iter().any(|p| *p >= inputs)
        {
            return Err("device_stage");
        }
        Ok(())
    }
    pub fn sample(&self, value: f64) -> f64 {
        if self.mute {
            return 0.0;
        }
        let value = value * self.gain;
        if self.quantization_step == 0.0 {
            value
        } else {
            (value / self.quantization_step).round_ties_even() * self.quantization_step
        }
    }
}

// Every slot and payload is atomic. Sequential consistency makes the before/after
// sequence checks sound even during overwrite; there is no unsafe access or torn
// snapshot. Producer never waits for reader. A slow reader loses oldest frames.
struct Slot {
    sequence: AtomicU64,
    samples: Box<[AtomicU64]>,
    seconds: AtomicU64,
    flags: AtomicU32,
}
struct Ring {
    slots: Box<[Slot]>,
    channels: usize,
    rate: f64,
    end: AtomicU64,
    reader: AtomicU64,
    max_depth: AtomicU64,
}
pub struct Producer<T = f32> {
    ring: Arc<Ring>,
    next: u64,
    precision: PhantomData<T>,
}
pub struct Consumer<T = f32> {
    ring: Arc<Ring>,
    next: u64,
    precision: PhantomData<T>,
}
#[derive(Debug, PartialEq)]
pub enum Delivery<T = f32> {
    Frame {
        sample: u64,
        values: Vec<T>,
        seconds: Option<f64>,
        flags: u32,
    },
    Gap {
        interval: [u64; 2],
    },
}
pub trait Sample: Copy + Send + Sync {
    fn bits(self) -> u64;
    fn from_bits(bits: u64) -> Self;
}
impl Sample for f32 {
    fn bits(self) -> u64 {
        self.to_bits() as u64
    }
    fn from_bits(bits: u64) -> Self {
        f32::from_bits(bits as u32)
    }
}
impl Sample for f64 {
    fn bits(self) -> u64 {
        self.to_bits()
    }
    fn from_bits(bits: u64) -> Self {
        f64::from_bits(bits)
    }
}
pub fn frame_queue(
    capacity: usize,
    channels: usize,
    rate: f64,
) -> Result<(Producer, Consumer), &'static str> {
    queue(capacity, channels, rate)
}
pub fn frame_queue_f64(
    capacity: usize,
    channels: usize,
    rate: f64,
) -> Result<(Producer<f64>, Consumer<f64>), &'static str> {
    queue(capacity, channels, rate)
}
fn queue<T: Sample>(
    capacity: usize,
    channels: usize,
    rate: f64,
) -> Result<(Producer<T>, Consumer<T>), &'static str> {
    if capacity == 0
        || capacity > MAX_QUEUE_FRAMES
        || channels == 0
        || channels > MAX_CHANNELS
        || !rate.is_finite()
        || rate <= 0.0
    {
        return Err("queue_format");
    }
    let ring = Arc::new(Ring {
        slots: (0..capacity)
            .map(|_| Slot {
                sequence: AtomicU64::new(0),
                samples: (0..channels).map(|_| AtomicU64::new(0)).collect(),
                seconds: AtomicU64::new(f64::NAN.to_bits()),
                flags: AtomicU32::new(0),
            })
            .collect(),
        channels,
        rate,
        end: AtomicU64::new(0),
        reader: AtomicU64::new(0),
        max_depth: AtomicU64::new(0),
    });
    Ok((
        Producer {
            ring: ring.clone(),
            next: 0,
            precision: PhantomData,
        },
        Consumer {
            ring,
            next: 0,
            precision: PhantomData,
        },
    ))
}
impl<T: Sample> Producer<T> {
    /// Whole callback block validation happens first; invalid buffers never advance position.
    pub fn write(
        &mut self,
        data: &[T],
        first_seconds: Option<f64>,
        flags: u32,
    ) -> Result<(), &'static str> {
        let frames = data.len() / self.ring.channels;
        if data.is_empty()
            || !data.len().is_multiple_of(self.ring.channels)
            || frames > MAX_CALLBACK_FRAMES
            || first_seconds.is_some_and(|v| !v.is_finite())
            || self
                .next
                .checked_add(frames as u64)
                .is_none_or(|v| v >= u64::MAX / 2)
        {
            return Err("frame_shape");
        }
        for (offset, frame) in data.chunks_exact(self.ring.channels).enumerate() {
            let sample = self.next + offset as u64;
            let slot = &self.ring.slots[sample as usize % self.ring.slots.len()];
            slot.sequence.store(sample * 2 + 1, SeqCst);
            for (value, dest) in frame.iter().zip(&slot.samples) {
                dest.store(value.bits(), SeqCst);
            }
            slot.seconds.store(
                first_seconds
                    .map_or(f64::NAN, |t| t + offset as f64 / self.ring.rate)
                    .to_bits(),
                SeqCst,
            );
            slot.flags.store(flags, SeqCst);
            slot.sequence.store(sample * 2 + 2, SeqCst);
        }
        self.next += frames as u64;
        self.ring.end.store(self.next, SeqCst);
        self.ring.max_depth.fetch_max(
            self.next
                .saturating_sub(self.ring.reader.load(SeqCst))
                .min(self.ring.slots.len() as u64),
            SeqCst,
        );
        Ok(())
    }
}
#[derive(Debug, Serialize)]
pub struct QueueStats {
    pub capacity_frames: usize,
    pub channels: usize,
    pub max_depth_frames: u64,
    pub numeric_bytes: usize,
}
impl<T: Sample> Consumer<T> {
    pub fn stats(&self) -> QueueStats {
        QueueStats {
            capacity_frames: self.ring.slots.len(),
            channels: self.ring.channels,
            max_depth_frames: self.ring.max_depth.load(SeqCst),
            numeric_bytes: self.ring.slots.len() * self.ring.channels * 8,
        }
    }
    /// Worker only. Bounded retry; caller may poll later if producer is overwriting.
    pub fn take(&mut self) -> Option<Delivery<T>> {
        let end = self.ring.end.load(SeqCst);
        let floor = end.saturating_sub(self.ring.slots.len() as u64);
        if self.next < floor {
            let interval = [self.next, floor];
            self.next = floor;
            self.ring.reader.store(self.next, SeqCst);
            return Some(Delivery::Gap { interval });
        }
        if self.next >= end {
            return None;
        }
        let slot = &self.ring.slots[self.next as usize % self.ring.slots.len()];
        let expected = self.next * 2 + 2;
        if slot.sequence.load(SeqCst) != expected {
            return None;
        }
        let values = slot
            .samples
            .iter()
            .map(|a| T::from_bits(a.load(SeqCst)))
            .collect();
        let seconds = f64::from_bits(slot.seconds.load(SeqCst));
        let flags = slot.flags.load(SeqCst);
        if slot.sequence.load(SeqCst) != expected {
            return None;
        }
        let sample = self.next;
        self.next += 1;
        self.ring.reader.store(self.next, SeqCst);
        Some(Delivery::Frame {
            sample,
            values,
            seconds: seconds.is_finite().then_some(seconds),
            flags,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn route() -> Route {
        Route {
            inputs: vec!["a".into(), "b".into()],
            outputs: vec!["out".into()],
            gains: vec![vec![0.5, -1.0]],
            revision: "r1".into(),
        }
    }
    #[test]
    fn explicit_asymmetric_bindings() {
        let mut format = IoFormat {
            stream_id: "s".into(),
            generation: 1,
            timebase_id: "t".into(),
            clock_domain: "c".into(),
            rate: [48000, 1],
            input_ids: vec!["a".into(), "b".into()],
            input_ports: vec![1, 0],
            output_ids: vec![],
            output_ports: vec![],
        };
        assert!(format.validate(2, 0).is_ok());
        format.input_ports = vec![0, 0];
        assert_eq!(format.validate(2, 0), Err("channel_binding"));
        format.input_ports = vec![0, 2];
        assert!(format.validate(2, 0).is_err());
        format.input_ids.clear();
        format.input_ports.clear();
        assert!(format.validate(2, 0).is_err());
        format.output_ids = vec!["o".into()];
        format.output_ports = vec![0];
        assert!(format.validate(0, 1).is_ok());
    }
    #[test]
    fn compiled_route_shape_transaction_and_no_clipping() {
        let r = route().compile(&["b".into(), "a".into()]).unwrap();
        let mut out = [99.0; 2];
        assert!(r.process_into(&[1.0], &mut out).is_err());
        assert_eq!(out, [99.0; 2]);
        r.process_into(&[2.0, 10.0, 4.0, 6.0], &mut out).unwrap();
        assert_eq!(out, [3.0, -1.0]);
    }
    #[test]
    fn invalid_route_cannot_change_current_or_published_snapshot() {
        let mut ctl = RouteControl::new(vec!["a".into(), "b".into()], route()).unwrap();
        let snapshot = ctl.current().clone();
        let mut next = route();
        next.gains[0][0] = 1.0;
        next.revision = "r2".into();
        assert_eq!(ctl.apply(next.clone(), 101, 128), Ok(128));
        next.gains[0][0] = f64::NAN;
        assert!(ctl.apply(next, 150, 256).is_err());
        assert_eq!(ctl.current().revision, "r2");
        assert_eq!(snapshot.revision, "r1");
        assert!(ctl.apply(route(), 129, 128).is_err());
    }
    #[test]
    fn overwrite_drops_oldest_with_absolute_gap_and_owned_snapshot() {
        let (mut tx, mut rx) = frame_queue(3, 2, 48000.0).unwrap();
        tx.write(&[1., 2., 3., 4.], None, 7).unwrap();
        let saved = rx.take().unwrap();
        tx.write(&[5., 6., 7., 8., 9., 10., 11., 12.], Some(10.), 0)
            .unwrap();
        assert_eq!(rx.take(), Some(Delivery::Gap { interval: [1, 3] }));
        if let Some(Delivery::Frame {
            sample,
            values,
            seconds,
            ..
        }) = rx.take()
        {
            assert_eq!(sample, 3);
            assert_eq!(values, [7., 8.]);
            assert_eq!(seconds, Some(10. + 1. / 48000.));
        } else {
            panic!()
        }
        assert_eq!(
            saved,
            Delivery::Frame {
                sample: 0,
                values: vec![1., 2.],
                seconds: None,
                flags: 7
            }
        );
    }
    #[test]
    fn queue_rejects_invalid_shape_without_advancing() {
        let (mut tx, mut rx) = frame_queue(4, 2, 1.).unwrap();
        assert!(tx.write(&[1.], None, 0).is_err());
        assert!(tx.write(&[1., 2.], Some(f64::NAN), 0).is_err());
        assert!(rx.take().is_none());
        tx.write(&[1., 2.], None, 0).unwrap();
        assert!(matches!(rx.take(), Some(Delivery::Frame { sample: 0, .. })));
        assert!(frame_queue(0, 2, 1.).is_err());
        assert!(frame_queue(4, 17, 1.).is_err());
    }
    #[test]
    fn concurrent_overwrite_never_tears_channels_or_compresses_positions() {
        let (mut tx, mut rx) = frame_queue(17, 2, 48000.).unwrap();
        let writer = std::thread::spawn(move || {
            for n in 0..20000 {
                tx.write(&[n as f32, -(n as f32)], None, 0).unwrap();
            }
        });
        let mut cursor = 0;
        while cursor < 20000 {
            match rx.take() {
                Some(Delivery::Frame { sample, values, .. }) => {
                    assert_eq!(sample, cursor);
                    assert_eq!(values, [sample as f32, -(sample as f32)]);
                    cursor += 1
                }
                Some(Delivery::Gap { interval }) => {
                    assert_eq!(interval[0], cursor);
                    cursor = interval[1]
                }
                None => std::thread::yield_now(),
            }
        }
        writer.join().unwrap();
    }
    #[test]
    fn mute_and_ties_even_quantization() {
        let mut stage = DeviceStage {
            mute: false,
            gain: 0.5,
            quantization_step: 0.25,
            mapping: vec![1, 0],
            dither: "none".into(),
        };
        stage.validate(2).unwrap();
        assert_eq!(stage.sample(0.3), 0.25);
        assert_eq!(stage.sample(0.1), 0.0);
        assert_eq!(stage.sample(0.25), 0.0);
        stage.mute = true;
        assert_eq!(stage.sample(0.8), 0.0);
    }
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BlockHeader {
    pub generation: i64,
    pub start: i64,
    pub frames: usize,
    pub channel_ids: Vec<String>,
    pub values: Vec<Vec<f64>>,
    pub dtype: String,
    pub rate: [u64; 2],
    pub clock_domain: String,
    pub binding: Vec<usize>,
}
#[derive(Default)]
pub struct BlockValidator {
    previous: Option<BlockHeader>,
}
impl BlockValidator {
    pub fn accept(&mut self, block: &BlockHeader) -> Result<Vec<[i64; 2]>, &'static str> {
        if block.channel_ids.is_empty()
            || block.channel_ids.len() > MAX_CHANNELS
            || !unique(&block.channel_ids)
        {
            return Err("channel_ids");
        }
        if block.frames == 0
            || block.frames != block.values.len()
            || block
                .values
                .iter()
                .any(|row| row.len() != block.channel_ids.len())
            || i64::try_from(block.frames)
                .ok()
                .and_then(|f| block.start.checked_add(f))
                .is_none()
        {
            return Err("frame_shape");
        }
        if block.start < 0 || block.generation < 0 {
            return Err("negative_position_or_generation");
        }
        if !["<f4", "<f8"].contains(&block.dtype.as_str())
            || block.rate.contains(&0)
            || block.clock_domain.is_empty()
            || block.binding.len() != block.channel_ids.len()
            || block.binding.iter().collect::<HashSet<_>>().len() != block.binding.len()
        {
            return Err("stream_format");
        }
        if block.values.iter().flatten().any(|v| !v.is_finite()) {
            return Err("nonfinite_without_encoding");
        }
        let mut end = 0;
        if let Some(previous) = &self.previous {
            if block.generation < previous.generation {
                return Err("stale_generation");
            }
            if block.generation == previous.generation {
                if block.channel_ids != previous.channel_ids
                    || block.rate != previous.rate
                    || block.dtype != previous.dtype
                    || block.clock_domain != previous.clock_domain
                    || block.binding != previous.binding
                {
                    return Err("configuration_requires_new_generation");
                }
                end = previous.start + previous.frames as i64;
                if block.start < end {
                    return Err("overlap_or_reverse");
                }
            }
        }
        // Retain header only; waveform belongs to the worker/snapshot, not validation state.
        let mut header = block.clone();
        header.values.clear();
        self.previous = Some(header);
        Ok(if block.start > end {
            vec![[end, block.start]]
        } else {
            vec![]
        })
    }
}

#[cfg(test)]
mod precision_tests {
    use super::*;
    #[test]
    fn f64_queue_retains_sub_f32_precision_and_nonfinite_flag() {
        let (mut tx, mut rx) = frame_queue_f64(2, 1, 48000.).unwrap();
        let exact = 1. + f64::EPSILON;
        tx.write(&[exact, f64::NAN], None, 16).unwrap();
        if let Some(Delivery::Frame { values, flags, .. }) = rx.take() {
            assert_eq!(values, [exact]);
            assert_ne!(values[0], f64::from(exact as f32));
            assert_eq!(flags, 16)
        } else {
            panic!()
        }
        if let Some(Delivery::Frame { values, flags, .. }) = rx.take() {
            assert!(values[0].is_nan());
            assert_eq!(flags, 16)
        } else {
            panic!()
        }
        assert_eq!(rx.stats().max_depth_frames, 2);
    }
    #[test]
    fn zero_coefficient_cannot_spread_nonfinite_input() {
        let route = Route {
            inputs: vec!["a".into(), "b".into()],
            outputs: vec!["o".into()],
            gains: vec![vec![0., 1.]],
            revision: "r".into(),
        };
        let compiled = route.compile(&route.inputs).unwrap();
        let mut output = [99.];
        compiled.process_into(&[f32::NAN, 2.], &mut output).unwrap();
        assert_eq!(output, [2.]);
    }
}
