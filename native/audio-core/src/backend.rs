//! Frozen input binding shared by backend callbacks and worker-side transports.
//! No device discovery, precision conversion, inferred clock mapping or tap aliases.
use super::{Consumer, IoFormat, MAX_CHANNELS, Producer, Sample, queue};
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize, Serialize)]
pub enum Backend {
    Cpal,
    PortAudio,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize, Serialize)]
pub enum SampleFormat {
    F32,
    F64,
}
mod sealed {
    pub trait Sealed {}
    impl Sealed for f32 {}
    impl Sealed for f64 {}
}
pub trait InputSample: Sample + sealed::Sealed {
    const FORMAT: SampleFormat;
}
impl InputSample for f32 {
    const FORMAT: SampleFormat = SampleFormat::F32;
}
impl InputSample for f64 {
    const FORMAT: SampleFormat = SampleFormat::F64;
}

/// `sample_format` is the format actually delivered by the adapter, not a user
/// preference. The adapter must reject an unsupported device format before opening.
#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InputBinding {
    pub backend: Backend,
    pub device: String,
    pub device_channels: usize,
    pub sample_format: SampleFormat,
    pub format: IoFormat,
}
impl InputBinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        let prefix = match self.backend {
            Backend::Cpal => "cpal",
            Backend::PortAudio => "portaudio",
        };
        if self.device.trim().is_empty()
            || !(1..=MAX_CHANNELS).contains(&self.device_channels)
            || self.format.input_ids.is_empty()
            || !self.format.output_ids.is_empty()
            || self.format.clock_domain != format!("{prefix}.device:{}", self.device)
        {
            return Err("backend_input_binding");
        }
        self.format.validate(self.device_channels, 0)
    }
    pub fn queue<T: InputSample>(
        &self,
        capacity_frames: usize,
    ) -> Result<(InputWriter<T>, Consumer<T>), &'static str> {
        self.validate()?;
        if self.sample_format != T::FORMAT {
            return Err("backend_input_precision");
        }
        let rate = self.format.rate[0] as f64 / self.format.rate[1] as f64;
        let (producer, consumer) = queue(capacity_frames, self.device_channels, rate)?;
        Ok((
            InputWriter {
                binding: self.clone(),
                producer,
            },
            consumer,
        ))
    }
}

/// Single producer; all configuration is immutable after control-side setup.
/// `write_next` has the same bounded, allocation/lock-free behavior as Producer.
/// A worker transport also checks generation and position with `write_at`.
pub struct InputWriter<T: InputSample> {
    binding: InputBinding,
    producer: Producer<T>,
}
impl<T: InputSample> InputWriter<T> {
    pub fn binding(&self) -> &InputBinding {
        &self.binding
    }
    pub fn next_sample(&self) -> u64 {
        self.producer.next
    }
    pub fn write_next(
        &mut self,
        data: &[T],
        first_seconds: Option<f64>,
        flags: u32,
    ) -> Result<(), &'static str> {
        self.producer.write(data, first_seconds, flags)
    }
    /// Discontinuous/old transport blocks are rejected before modifying the queue.
    /// Queue overwrites retain their exact gaps; backend loss with unknown position
    /// must be reported as failure, never made into a contiguous normal stream.
    pub fn write_at(
        &mut self,
        generation: u64,
        start: u64,
        data: &[T],
        first_seconds: Option<f64>,
        flags: u32,
    ) -> Result<(), &'static str> {
        if generation != self.binding.format.generation {
            return Err("backend_input_generation");
        }
        if start != self.next_sample() {
            return Err("backend_input_discontinuity");
        }
        self.write_next(data, first_seconds, flags)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Delivery;
    fn binding(backend: Backend, sample_format: SampleFormat) -> InputBinding {
        let prefix = if backend == Backend::Cpal {
            "cpal"
        } else {
            "portaudio"
        };
        InputBinding {
            backend,
            device: "explicit".into(),
            device_channels: 4,
            sample_format,
            format: IoFormat {
                stream_id: "s".into(),
                generation: 7,
                timebase_id: "t".into(),
                clock_domain: format!("{prefix}.device:explicit"),
                rate: [48000, 1],
                input_ids: vec!["z".into(), "a".into()],
                input_ports: vec![3, 0],
                output_ids: vec![],
                output_ports: vec![],
            },
        }
    }
    #[test]
    fn typed_precision_binding_and_unknown_clock_cannot_be_changed_silently() {
        for backend in [Backend::Cpal, Backend::PortAudio] {
            let mut binding = binding(backend, SampleFormat::F64);
            assert!(binding.queue::<f32>(4).is_err());
            let (mut writer, mut reader) = binding.queue::<f64>(4).unwrap();
            let exact = 1. + f64::EPSILON;
            writer
                .write_at(7, 0, &[exact, -0., 0., 2.], None, 3)
                .unwrap();
            assert_eq!(
                reader.take(),
                Some(Delivery::Frame {
                    sample: 0,
                    values: vec![exact, -0., 0., 2.],
                    seconds: None,
                    flags: 3,
                })
            );
            binding.format.input_ports.reverse();
            assert_eq!(writer.binding().format.input_ports, [3, 0]);
            binding.format.clock_domain = "another-clock".into();
            assert!(binding.queue::<f64>(4).is_err());
        }
    }
    #[test]
    fn stale_position_shape_and_time_rejections_do_not_advance_or_publish() {
        let (mut writer, mut reader) = binding(Backend::PortAudio, SampleFormat::F32)
            .queue::<f32>(4)
            .unwrap();
        for (generation, start, data, seconds) in [
            (6, 0, vec![1.; 4], None),
            (7, 1, vec![1.; 4], None),
            (7, 0, vec![1.; 3], None),
            (7, 0, vec![1.; 4], Some(f64::NAN)),
        ] {
            assert!(
                writer
                    .write_at(generation, start, &data, seconds, 0)
                    .is_err()
            );
            assert_eq!(writer.next_sample(), 0);
            assert!(reader.take().is_none());
        }
        writer.write_at(7, 0, &[1.; 4], Some(10.), 0).unwrap();
        assert!(writer.write_at(7, 0, &[2.; 4], None, 0).is_err());
        assert!(matches!(
            reader.take(),
            Some(Delivery::Frame {
                sample: 0,
                seconds: Some(10.),
                ..
            })
        ));
    }
    #[test]
    fn backend_overwrite_keeps_absolute_gap_and_owned_bits() {
        let (mut writer, mut reader) = binding(Backend::Cpal, SampleFormat::F32)
            .queue::<f32>(2)
            .unwrap();
        writer.write_next(&[1.; 4], None, 0).unwrap();
        let held = reader.take().unwrap();
        writer.write_at(7, 1, &[2.; 16], None, 0).unwrap();
        assert_eq!(reader.take(), Some(Delivery::Gap { interval: [1, 3] }));
        assert!(
            matches!(reader.take(), Some(Delivery::Frame { sample: 3, values, .. }) if values == vec![2.; 4])
        );
        assert!(matches!(held, Delivery::Frame { sample: 0, values, .. } if values == vec![1.; 4]));
    }
}
