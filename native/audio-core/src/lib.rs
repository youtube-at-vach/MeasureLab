//! Explicit N-channel queue boundary used by graph acquisition.
//! Producer::write is bounded and allocation/lock/free-free after setup.
#![forbid(unsafe_code)]
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
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
    /// Worker-side EOF precondition. The producer must already be stopped by the caller.
    pub fn is_drained(&self) -> bool {
        self.next == self.ring.end.load(SeqCst)
    }
    pub fn rate_hz(&self) -> f64 {
        self.ring.rate
    }
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
}
