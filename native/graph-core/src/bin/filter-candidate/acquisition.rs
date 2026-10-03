//! Saved coefficients/bytes through the real acquisition queue and persistent owner.
use super::*;
use audio_core::{Consumer, IoFormat, Producer, frame_queue, frame_queue_f64};
use graph_core::acquisition::{Acquisition, CaptureLimits, CaptureSample, FftSpec, PollReport};

#[derive(Default)]
struct Observed {
    values: Vec<f64>,
    raw_f32_as_f64: Vec<f64>,
    validity: Vec<InvalidSpan>,
    proofs: Vec<WindowProof>,
    fft_sample: Option<Vec<f64>>,
    acquired_frames: usize,
    gaps: Vec<[u64; 2]>,
    max_deliveries: usize,
    max_raw_windows: usize,
    max_filtered_windows: usize,
}
impl Observed {
    fn collect(
        &mut self,
        report: PollReport,
        a: &graph_core::Subscription,
        b: &graph_core::Subscription,
        channels: usize,
    ) -> Result<bool, Box<dyn std::error::Error>> {
        let idle = report.deliveries == 0
            && report.windows.is_empty()
            && report.filtered_windows.is_empty();
        self.max_deliveries = self.max_deliveries.max(report.deliveries);
        self.max_raw_windows = self.max_raw_windows.max(report.windows.len());
        self.max_filtered_windows = self.max_filtered_windows.max(report.filtered_windows.len());
        self.acquired_frames += report
            .blocks
            .iter()
            .map(|b| (b.interval().1 - b.interval().0) as usize)
            .sum::<usize>();
        for block in &report.blocks {
            if let Samples::F32(values) = block.samples() {
                self.raw_f32_as_f64
                    .extend(values.iter().copied().map(f64::from));
            }
        }
        self.gaps.extend(report.gaps);
        for block in report.filtered_blocks {
            if block.interval().0 != (self.values.len() / channels) as u64 {
                return Err("output interval/phase".into());
            }
            let Samples::F64(v) = block.samples() else {
                return Err("output precision".into());
            };
            self.values.extend_from_slice(v);
            self.validity.extend_from_slice(block.validity());
        }
        for event in report.filtered_windows {
            let x = a.take_latest().ok_or("first snapshot")?;
            let y = b.take_latest().ok_or("second snapshot")?;
            if !Arc::ptr_eq(x.raw(), y.raw())
                || event.result_id != Some(x.raw().id())
                || event.history.interval
                    != [x.raw().interval().0 as i64, x.raw().interval().1 as i64]
            {
                return Err("acquisition shared publication".into());
            }
            if self.fft_sample.is_none()
                && let Some(graph_core::Numeric::F64(numeric)) = x.raw().numeric()
            {
                self.fft_sample = Some(
                    numeric
                        .fft_over_n
                        .iter()
                        .flat_map(|z| [z.re, z.im])
                        .collect(),
                );
            }
            let (start, end) = x.raw().interval();
            self.proofs.push(WindowProof {
                interval: [start, end],
                result_id: x.raw().id(),
                second_result_id: y.raw().id(),
                shared_allocation: true,
                validity: x.raw().validity().to_vec(),
                numeric: x.raw().numeric().is_some(),
                average_count: x.average_count(),
            });
        }
        Ok(idle)
    }
    fn drain(
        &mut self,
        worker: &mut Acquisition<impl CaptureSample>,
        a: &graph_core::Subscription,
        b: &graph_core::Subscription,
        channels: usize,
    ) -> Result<(), Box<dyn std::error::Error>> {
        for _ in 0..131072 {
            if self.collect(worker.poll()?, a, b, channels)? {
                return Ok(());
            }
        }
        Err("acquisition did not drain".into())
    }
}
type Run = (serde_json::Value, BTreeMap<String, Vec<f64>>);
pub(super) fn run(
    r: &Request,
    pattern: &[usize],
    samples: &Samples,
) -> Result<Run, Box<dyn std::error::Error>> {
    let channels = r.source.channel_ids.len();
    let capacity = if r.gaps.is_empty() { 8192 } else { 128 };
    match samples {
        Samples::F32(values) => {
            let (tx, rx) = frame_queue(capacity, channels, r.source.timebase.rate_hz())?;
            run_typed(r, pattern, values, tx, rx, capacity)
        }
        Samples::F64(values) => {
            let (tx, rx) = frame_queue_f64(capacity, channels, r.source.timebase.rate_hz())?;
            run_typed(r, pattern, values, tx, rx, capacity)
        }
    }
}
fn run_typed<T: CaptureSample>(
    r: &Request,
    pattern: &[usize],
    values: &[T],
    mut tx: Producer<T>,
    rx: Consumer<T>,
    capacity: usize,
) -> Result<Run, Box<dyn std::error::Error>> {
    let channels = r.source.channel_ids.len();
    let format = IoFormat {
        stream_id: r.source.stream_id.clone(),
        generation: r.source.generation,
        timebase_id: r.source.timebase.id.clone(),
        clock_domain: r.source.timebase.clock_domain.clone(),
        rate: [
            r.source.timebase.rate.numerator.try_into()?,
            r.source.timebase.rate.denominator,
        ],
        input_ids: r.source.channel_ids.clone(),
        input_ports: r
            .input_ports
            .clone()
            .unwrap_or_else(|| (0..channels).collect()),
        output_ids: Vec::new(),
        output_ports: Vec::new(),
    };
    let spec = FftSpec {
        n: 64,
        hop: 64,
        alignment: 0,
        window: WindowSpec::Boxcar,
    };
    let mut worker = Acquisition::new(
        rx,
        format,
        spec.clone(),
        CaptureLimits {
            history: HistoryLimits::frames(256),
            frames_per_poll: 8192,
            windows_per_poll: 1,
        },
    )?;
    // The adapter must expose its real Source; no fixture identity is substituted.
    if worker.key().source != r.source {
        return Err("acquisition source metadata".into());
    }
    let filter = Filter::new_with_conversion(
        worker.key().source.clone(),
        r.output_stream.clone(),
        r.output_timebase.clone(),
        r.config.clone(),
        FilterLimits::default(),
        r.input_conversion,
    )?;
    let source = filter.output_source().clone();
    let key = FftKey {
        source: source.clone(),
        n: 64,
        hop: 64,
        alignment: 0,
        window: WindowSpec::Boxcar,
        remove_dc: false,
        input_gains: Vec::new(),
    };
    let subscribe = || {
        worker.graph().subscribe(
            key.clone(),
            Average::CumulativePsd,
            Presentation {
                color: "blue".into(),
                unit: "FS".into(),
            },
        )
    };
    let a = subscribe()?;
    let b = subscribe()?;
    worker.attach_filter(filter, spec, HistoryLimits::frames(512))?;
    let mut observed = Observed::default();
    let (mut cursor, mut index) = (0usize, 0usize);
    while cursor < r.frames {
        let gap = r.gaps.iter().find(|g| g[0] as usize == cursor);
        let end = if let Some(g) = gap {
            // Advance producer with actual bytes, deliberately overwrite precisely the gap.
            let end = g[1] as usize + capacity;
            if end > r.frames
                || r.gaps
                    .iter()
                    .any(|next| next[0] > g[0] && next[0] < end as u64)
            {
                return Err("unsupported saved gap injection".into());
            }
            end
        } else {
            let boundary = r
                .gaps
                .iter()
                .filter(|g| g[0] as usize > cursor)
                .map(|g| g[0] as usize)
                .min()
                .unwrap_or(r.frames);
            (cursor + pattern[index % pattern.len()].min(capacity))
                .min(boundary)
                .min(r.frames)
        };
        tx.write(&values[cursor * channels..end * channels], None, 0)?;
        observed.drain(&mut worker, &a, &b, channels)?;
        cursor = end;
        index += 1;
    }
    drop(tx);
    let report = worker.finish_input()?;
    observed.collect(report, &a, &b, channels)?;
    observed.drain(&mut worker, &a, &b, channels)?;
    let state = worker.graph().filter_state(&source);
    let before = worker.graph().stats();
    let filters_before = worker.graph().filter_count();
    drop(a);
    drop(b);
    let released = worker.graph().stats();
    let filters_released = worker.graph().filter_count();
    // Next owner poll retires its derived history after final demand disappears.
    worker.poll()?;
    let history_released = worker.filtered_history().is_none();
    worker.stop();
    let after = worker.graph().stats();
    let run = json!({"validity": observed.validity, "windows": observed.proofs, "before_release": before,
        "after_release": released, "after_shutdown": after, "filters_before": filters_before,
        "filters_released": filters_released, "filters_after": worker.graph().filter_count(),
        "acquisition": {"acquired_frames": observed.acquired_frames, "gaps": observed.gaps,
            "max_deliveries": observed.max_deliveries, "max_raw_windows": observed.max_raw_windows,
            "max_filtered_windows": observed.max_filtered_windows, "history_released": history_released,
            "state": worker.state(), "queue_released": worker.queue_stats().is_none()}});
    let mut arrays = BTreeMap::from([("output".into(), observed.values)]);
    if !observed.raw_f32_as_f64.is_empty() {
        arrays.insert("raw_f32_as_f64".into(), observed.raw_f32_as_f64);
    }
    if let Some(values) = observed.fft_sample {
        arrays.insert("fft_over_n".into(), values);
    }
    if let Some(state) = state {
        arrays.insert("state".into(), state);
    }
    Ok((run, arrays))
}
