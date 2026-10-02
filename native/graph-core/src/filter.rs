//! MIG-006-D: bounded f64 worker transforms. Never call from an audio callback.
//! Output positions use the absolute rational phase; centered FIR waits for lookahead.
use crate::{InvalidSpan, Precision, Rational, Samples, SignalBlock, Source};
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "kind", deny_unknown_fields)]
pub enum FilterConfig {
    Fir {
        coefficients: Vec<f64>,
        target_rate: Rational,
        centered: bool,
        revision: String,
    },
    Sos {
        coefficients: Vec<[f64; 6]>,
        revision: String,
    },
}
#[derive(Clone, Copy, Debug)]
pub struct FilterLimits {
    pub max_channels: usize,
    pub max_coefficients: usize,
    pub max_input_frames: usize,
    pub max_output_frames: usize,
    pub max_validity_spans: usize,
}
impl Default for FilterLimits {
    fn default() -> Self {
        Self {
            max_channels: 32,
            max_coefficients: 4097,
            max_input_frames: 65536,
            max_output_frames: 131072,
            max_validity_spans: 4096,
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct FilterMetadata {
    pub parent: Source,
    pub output: Source,
    pub rate_ratio: Rational,
    pub output_m_to_input: Rational,
    pub origin_mapping: [Rational; 2],
    /// Uncompensated linear-phase FIR group delay; SOS delay is frequency dependent.
    pub signal_delay_input_samples: Option<Rational>,
    pub signal_delay_output_samples: Option<Rational>,
    pub signal_delay_seconds: Option<Rational>,
    pub delay_compensated: bool,
    pub processing_latency_seconds: Option<Rational>,
    pub processing_latency_reason: String,
    pub initial_state: String,
    pub tail_flush: bool,
}
fn rat(n: i128, d: u128) -> Result<Rational, String> {
    let mut a = n.unsigned_abs();
    let mut b = d;
    if d == 0 {
        return Err("invalid_rate".into());
    }
    while b != 0 {
        (a, b) = (b, a % b);
    }
    let signed = i128::try_from(n.unsigned_abs() / a).map_err(|_| "rational_overflow")?;
    Ok(Rational {
        numerator: i64::try_from(if n < 0 { -signed } else { signed })
            .map_err(|_| "rational_overflow")?,
        denominator: u64::try_from(d / a).map_err(|_| "rational_overflow")?,
    })
}
pub fn rate_ratio(source: &Rational, target: &Rational) -> Result<Rational, String> {
    if source.numerator <= 0
        || target.numerator <= 0
        || source.denominator == 0
        || target.denominator == 0
    {
        return Err("invalid_rate".into());
    }
    rat(
        i128::from(target.numerator) * i128::from(source.denominator),
        u128::from(target.denominator) * source.numerator as u128,
    )
}
impl FilterMetadata {
    pub fn map_position(&self, position: &Rational) -> Result<Rational, String> {
        rat(
            i128::from(position.numerator) * i128::from(self.rate_ratio.numerator),
            u128::from(position.denominator) * u128::from(self.rate_ratio.denominator),
        )
    }
}
struct OutputBuffer {
    start: Option<u64>,
    values: Vec<f64>,
    spans: Vec<InvalidSpan>,
}
impl OutputBuffer {
    fn new() -> Self {
        Self {
            start: None,
            values: Vec::new(),
            spans: Vec::new(),
        }
    }
    fn push(&mut self, block: Option<SignalBlock>, limits: FilterLimits) -> Result<(), String> {
        let Some(block) = block else { return Ok(()) };
        self.start.get_or_insert(block.start);
        let Samples::F64(values) = block.samples else {
            unreachable!()
        };
        if (self.values.len() + values.len()) / block.source.channel_ids.len()
            > limits.max_output_frames
        {
            return Err("filter_capacity".into());
        }
        self.values.extend(values);
        for span in block.validity {
            push_span(&mut self.spans, span, limits.max_validity_spans)?;
        }
        Ok(())
    }
    fn finish(self, source: Source, limits: FilterLimits) -> Result<Option<SignalBlock>, String> {
        let Some(start) = self.start else {
            return Ok(None);
        };
        let spans = merge_spans(self.spans);
        if spans.len() > limits.max_validity_spans {
            return Err("filter_capacity".into());
        }
        SignalBlock::new(source, start, Samples::F64(self.values), spans).map(Some)
    }
}
fn push_span(spans: &mut Vec<InvalidSpan>, span: InvalidSpan, limit: usize) -> Result<(), String> {
    if spans.len() >= limit {
        *spans = merge_spans(std::mem::take(spans));
    }
    // Allow a duplicate/adjacent last span without using an extra slot.
    if let Some(last) = spans.iter_mut().find(|s| {
        s.channel_id == span.channel_id
            && s.reason == span.reason
            && s.origin == span.origin
            && s.start <= span.end
            && span.start <= s.end
    }) {
        last.start = last.start.min(span.start);
        last.end = last.end.max(span.end);
        return Ok(());
    }
    if spans.len() >= limit {
        return Err("filter_capacity".into());
    }
    spans.push(span);
    Ok(())
}
#[derive(Clone)]
struct Frame {
    values: Vec<f64>,
    // Reasons retain the affected channel and original provenance through the FIR support.
    invalid: Vec<(Option<String>, String, String)>,
}
#[derive(Clone)]
struct FirState {
    h: Vec<f64>,
    up: u64,
    down: u64,
    shift: u64,
    base: u64,
    rows: VecDeque<Frame>,
    next: u64,
}
#[derive(Clone)]
pub struct SosState {
    coefficients: Vec<[f64; 6]>,
    channels: usize,
    state: Vec<f64>,
}
impl SosState {
    pub fn new(coefficients: Vec<[f64; 6]>, channels: usize) -> Result<Self, String> {
        if channels == 0
            || channels > 32
            || coefficients.is_empty()
            || coefficients.len() > 16
            || coefficients.iter().any(|h| {
                h[3] != 1.0 || h.iter().any(|x| !x.is_finite()) || (1.0 + h[4] + h[5]) == 0.0
            })
        {
            return Err("unsupported_sos".into());
        }
        let state = vec![0.0; coefficients.len() * 2 * channels];
        Ok(Self {
            coefficients,
            channels,
            state,
        })
    }
    pub fn final_state(&self) -> &[f64] {
        &self.state
    }
    pub fn process(&mut self, input: &[f64]) -> Result<Vec<f64>, String> {
        if !input.len().is_multiple_of(self.channels) || input.iter().any(|x| !x.is_finite()) {
            return Err("invalid_block".into());
        }
        // Rejection of arithmetic overflow is atomic, including the complete cascade state.
        let mut state = self.state.clone();
        let mut output = Vec::with_capacity(input.len());
        for frame in input.chunks_exact(self.channels) {
            for (c, &sample) in frame.iter().enumerate() {
                let mut x = sample;
                for (s, h) in self.coefficients.iter().enumerate() {
                    let i = s * 2 * self.channels + c;
                    let y = h[0] * x + state[i];
                    state[i] = h[1] * x - h[4] * y + state[i + self.channels];
                    state[i + self.channels] = h[2] * x - h[5] * y;
                    x = y;
                }
                output.push(x);
            }
        }
        if output.iter().chain(&state).any(|x| !x.is_finite()) {
            return Err("nonfinite".into());
        }
        self.state = state;
        Ok(output)
    }
    fn steady(&mut self, endpoint: &[f64]) {
        for (c, &sample) in endpoint.iter().enumerate() {
            let mut x = sample;
            for (s, h) in self.coefficients.iter().enumerate() {
                let y = x * (h[0] + h[1] + h[2]) / (1.0 + h[4] + h[5]);
                let i = s * 2 * self.channels + c;
                self.state[i] = y - h[0] * x;
                self.state[i + self.channels] = h[2] * x - h[5] * y;
                x = y;
            }
        }
    }
    /// Explicit complete-array adapter. Odd padding and two passes cannot be restarted per chunk.
    pub fn forward_backward(&self, input: &[f64], pad: usize) -> Result<Vec<f64>, String> {
        let n = input.len() / self.channels;
        if n <= pad || n > 65536 || pad > 1024 || !input.len().is_multiple_of(self.channels) {
            return Err("unsupported_offline_interval".into());
        }
        let mut extended = Vec::with_capacity(input.len() + 2 * pad * self.channels);
        for i in (1..=pad).rev() {
            for c in 0..self.channels {
                extended.push(2.0 * input[c] - input[i * self.channels + c]);
            }
        }
        extended.extend_from_slice(input);
        for i in 1..=pad {
            for c in 0..self.channels {
                extended.push(
                    2.0 * input[(n - 1) * self.channels + c]
                        - input[(n - 1 - i) * self.channels + c],
                );
            }
        }
        let mut forward = self.clone();
        forward.steady(&extended[..self.channels]);
        let values = forward.process(&extended)?;
        let reversed: Vec<_> = values
            .chunks_exact(self.channels)
            .rev()
            .flatten()
            .copied()
            .collect();
        let mut backward = self.clone();
        backward.steady(&reversed[..self.channels]);
        let values = backward.process(&reversed)?;
        let reversed: Vec<_> = values
            .chunks_exact(self.channels)
            .rev()
            .flatten()
            .copied()
            .collect();
        Ok(reversed[pad * self.channels..(pad + n) * self.channels].to_vec())
    }
    pub fn response(&self, frequencies: &[f64], rate: f64) -> Result<Vec<f64>, String> {
        if !rate.is_finite()
            || rate <= 0.0
            || frequencies
                .iter()
                .any(|f| !f.is_finite() || *f < 0.0 || *f > rate / 2.0)
        {
            return Err("invalid_frequency".into());
        }
        let mut output = Vec::new();
        for f in frequencies {
            let angle = std::f64::consts::TAU * f / rate;
            let (s, c) = angle.sin_cos();
            let (s2, c2) = (2.0 * angle).sin_cos();
            let (mut real, mut imag) = (1.0, 0.0);
            for h in &self.coefficients {
                let (nr, ni) = (h[0] + h[1] * c + h[2] * c2, -h[1] * s - h[2] * s2);
                let (dr, di) = (1.0 + h[4] * c + h[5] * c2, -h[4] * s - h[5] * s2);
                let norm = dr * dr + di * di;
                let (r, i) = ((nr * dr + ni * di) / norm, (ni * dr - nr * di) / norm);
                (real, imag) = (real * r - imag * i, real * i + imag * r);
            }
            output.extend([real, imag]);
        }
        if output.iter().any(|x| !x.is_finite()) {
            return Err("nonfinite".into());
        }
        Ok(output)
    }
}
#[derive(Clone)]
enum State {
    Fir(FirState),
    Sos(SosState),
}
/// One state per graph transform, shared by all consumers of the resulting Source.
#[derive(Clone)]
pub struct Filter {
    metadata: FilterMetadata,
    limits: FilterLimits,
    state: State,
    cursor: u64,
    finished: bool,
}
impl Filter {
    pub fn new(
        input: Source,
        output_stream: String,
        output_timebase: String,
        config: FilterConfig,
        limits: FilterLimits,
    ) -> Result<Self, String> {
        if !input.valid()
            || input.precision != Precision::F64
            || input.channel_ids.len() > limits.max_channels
            || output_stream.is_empty()
            || output_timebase.is_empty()
            || output_stream == input.stream_id
            || output_timebase == input.timebase.id
            || limits.max_input_frames == 0
            || limits.max_output_frames == 0
            || limits.max_validity_spans == 0
        {
            return Err("unsupported_filter_source".into());
        }
        let (state, target, revision, centered, initial, bits, delay) = match config {
            FilterConfig::Fir {
                coefficients,
                target_rate,
                centered,
                revision,
            } => {
                let ratio = rate_ratio(&input.timebase.rate, &target_rate)?;
                if coefficients.is_empty()
                    || coefficients.len() > limits.max_coefficients
                    || coefficients.len() % 2 != 1
                    || coefficients.iter().any(|x| !x.is_finite())
                    || ratio.numerator > 512
                    || ratio.denominator > 512
                {
                    return Err("unsupported_fir".into());
                }
                // Group-delay metadata is valid only for the symmetric linear-phase kernels in this probe.
                if !coefficients
                    .iter()
                    .zip(coefficients.iter().rev())
                    .all(|(a, b)| a == b)
                {
                    return Err("unsupported_asymmetric_fir".into());
                }
                let half = (coefficients.len() as u64 - 1) / 2;
                let bits = coefficients
                    .iter()
                    .map(|v| format!("{:016x}", v.to_bits()))
                    .collect::<String>();
                let state = FirState {
                    h: coefficients,
                    up: ratio.numerator as u64,
                    down: ratio.denominator,
                    shift: if centered { half } else { 0 },
                    base: 0,
                    rows: VecDeque::new(),
                    next: 0,
                };
                let delay = Some(rat(i128::from(half), ratio.numerator as u128)?);
                (
                    State::Fir(state),
                    target_rate,
                    revision,
                    centered,
                    "zero-padding-with-validity",
                    bits,
                    delay,
                )
            }
            FilterConfig::Sos {
                coefficients,
                revision,
            } => {
                if coefficients.len() * 6 > limits.max_coefficients {
                    return Err("unsupported_sos".into());
                }
                let bits = coefficients
                    .iter()
                    .flatten()
                    .map(|v| format!("{:016x}", v.to_bits()))
                    .collect::<String>();
                let state = SosState::new(coefficients, input.channel_ids.len())?;
                (
                    State::Sos(state),
                    input.timebase.rate.clone(),
                    revision,
                    false,
                    "zero-state-transient-no-valid-after-cutoff",
                    bits,
                    None,
                )
            }
        };
        if revision.is_empty() {
            return Err("invalid_filter_revision".into());
        }
        let ratio = rate_ratio(&input.timebase.rate, &target)?;
        let mut output = input.clone();
        output.stream_id = output_stream;
        output.timebase.id = output_timebase;
        output.timebase.rate = target.normalized()?;
        output.timebase.nominal_rate = rat(
            i128::from(input.timebase.nominal_rate.numerator) * i128::from(ratio.numerator),
            u128::from(input.timebase.nominal_rate.denominator) * u128::from(ratio.denominator),
        )?;
        output.timebase.origin_seconds =
            crate::time::relation(&input.timebase, &input.timebase, None, 0)?.value;
        output.timebase.origin_sample = 0;
        // Exact coefficient bits are part of identity: revision labels alone cannot alias different kernels.
        output.filter_state_revision = format!(
            "{}/{}:{revision}:{}:{}:{centered}:{bits}",
            input.filter_state_revision,
            if matches!(state, State::Fir(_)) {
                "fir"
            } else {
                "sos"
            },
            ratio.numerator,
            ratio.denominator
        );
        let metadata = FilterMetadata {
            parent: input,
            output,
            output_m_to_input: rat(i128::from(ratio.denominator), ratio.numerator as u128)?,
            origin_mapping: [rat(0, 1)?, rat(0, 1)?],
            signal_delay_output_samples: delay
                .as_ref()
                .map(|d| {
                    rat(
                        i128::from(d.numerator) * i128::from(ratio.numerator),
                        u128::from(d.denominator) * u128::from(ratio.denominator),
                    )
                })
                .transpose()?,
            signal_delay_input_samples: delay,
            signal_delay_seconds: None,
            rate_ratio: ratio,
            delay_compensated: centered,
            processing_latency_seconds: None,
            processing_latency_reason: "not_measured".into(),
            initial_state: initial.into(),
            tail_flush: false,
        };
        let mut filter = Self {
            metadata,
            limits,
            state,
            cursor: 0,
            finished: false,
        };
        if let Some(delay) = &filter.metadata.signal_delay_input_samples {
            let rate = &filter.metadata.parent.timebase.rate;
            filter.metadata.signal_delay_seconds = Some(rat(
                i128::from(delay.numerator) * i128::from(rate.denominator),
                u128::from(delay.denominator) * rate.numerator as u128,
            )?);
        }
        Ok(filter)
    }
    pub fn metadata(&self) -> &FilterMetadata {
        &self.metadata
    }
    pub fn output_source(&self) -> &Source {
        &self.metadata.output
    }
    pub fn input_source(&self) -> &Source {
        &self.metadata.parent
    }
    pub fn retained_frames(&self) -> usize {
        match &self.state {
            State::Fir(s) => s.rows.len(),
            State::Sos(_) => 0,
        }
    }
    pub fn sos_state(&self) -> Option<&[f64]> {
        match &self.state {
            State::Sos(s) => Some(s.final_state()),
            _ => None,
        }
    }
    /// Transactional rejection. Fixed input/output identity must be explicitly replaced on revision/restart.
    pub fn process(&mut self, block: &SignalBlock) -> Result<Option<SignalBlock>, String> {
        if self.finished || block.source() != self.input_source() {
            return Err("filter_source_or_generation".into());
        }
        let (start, end) = block.interval();
        if start < self.cursor {
            return Err("overlap_or_reorder".into());
        }
        if end - self.cursor > self.limits.max_input_frames as u64
            || block.validity().len() > self.limits.max_validity_spans
        {
            return Err("filter_capacity".into());
        }
        if let State::Fir(s) = &self.state {
            let total = end
                .checked_mul(s.up)
                .ok_or("sample_overflow")?
                .div_ceil(s.down);
            if total.saturating_sub(s.next) > self.limits.max_output_frames as u64 {
                return Err("filter_capacity".into());
            }
        }
        if matches!(self.state, State::Sos(_)) && block.frames > self.limits.max_output_frames {
            return Err("filter_capacity".into());
        }
        let Samples::F64(values) = block.samples() else {
            return Err("unsupported_precision".into());
        };
        if matches!(self.state, State::Sos(_))
            && (start != self.cursor
                || !block.validity().is_empty()
                || values.iter().any(|v| !v.is_finite()))
        {
            return Err("unsupported_iir_gap_or_invalid".into());
        }
        let mut next = self.clone();
        let result = next.process_inner(block)?;
        *self = next;
        Ok(result)
    }
    fn process_inner(&mut self, block: &SignalBlock) -> Result<Option<SignalBlock>, String> {
        let (start, end) = block.interval();
        let channels = self.input_source().channel_ids.len();
        let Samples::F64(values) = block.samples() else {
            unreachable!()
        };
        if let State::Sos(state) = &mut self.state {
            let output = state.process(values)?;
            self.cursor = end;
            return Ok(Some(SignalBlock::new(
                self.metadata.output.clone(),
                start,
                Samples::F64(output),
                vec![InvalidSpan {
                    start,
                    end,
                    channel_id: None,
                    reason: "warmup".into(),
                    origin: "sos.zero-state-transient".into(),
                }],
            )?));
        }
        let mut outputs = OutputBuffer::new();
        for position in self.cursor..end {
            let mut row = Frame {
                values: vec![0.0; channels],
                invalid: Vec::new(),
            };
            if position < start {
                row.invalid
                    .push((None, "gap".into(), "filter.input-missing".into()));
            } else {
                row.values.copy_from_slice(
                    &values[(position - start) as usize * channels
                        ..(position - start + 1) as usize * channels],
                );
                for v in block
                    .validity()
                    .iter()
                    .filter(|v| v.start <= position && position < v.end)
                {
                    row.invalid
                        .push((v.channel_id.clone(), v.reason.clone(), v.origin.clone()));
                }
                for (c, value) in row.values.iter_mut().enumerate() {
                    if !value.is_finite() {
                        *value = 0.0;
                        row.invalid.push((
                            Some(self.metadata.parent.channel_ids[c].clone()),
                            "nonfinite".into(),
                            "filter.input".into(),
                        ));
                    }
                }
            }
            let State::Fir(state) = &mut self.state else {
                unreachable!()
            };
            state.rows.push_back(row);
            self.cursor = position + 1;
            outputs.push(self.drain(false)?, self.limits)?;
        }
        outputs.finish(self.metadata.output.clone(), self.limits)
    }
    /// Explicit end-of-stream, including a trailing acquisition gap. No inferred end from chunk size.
    pub fn finish(&mut self, end: u64) -> Result<Option<SignalBlock>, String> {
        if self.finished
            || end < self.cursor
            || end - self.cursor > self.limits.max_input_frames as u64
        {
            return Err("invalid_filter_end".into());
        }
        if matches!(self.state, State::Sos(_)) && end != self.cursor {
            return Err("unsupported_iir_gap_or_invalid".into());
        }
        if let State::Fir(s) = &self.state {
            let total = end
                .checked_mul(s.up)
                .ok_or("sample_overflow")?
                .div_ceil(s.down);
            if total.saturating_sub(s.next) > self.limits.max_output_frames as u64 {
                return Err("filter_capacity".into());
            }
        }
        let mut next = self.clone();
        let mut outputs = OutputBuffer::new();
        while next.cursor < end {
            let State::Fir(state) = &mut next.state else {
                unreachable!()
            };
            state.rows.push_back(Frame {
                values: vec![0.0; next.metadata.parent.channel_ids.len()],
                invalid: vec![(None, "gap".into(), "filter.input-missing".into())],
            });
            next.cursor += 1;
            outputs.push(next.drain(false)?, next.limits)?;
        }
        outputs.push(next.drain(true)?, next.limits)?;
        let result = outputs.finish(next.metadata.output.clone(), next.limits)?;
        next.finished = true;
        *self = next;
        Ok(result)
    }
    fn drain(&mut self, eof: bool) -> Result<Option<SignalBlock>, String> {
        let State::Fir(s) = &mut self.state else {
            return Ok(None);
        };
        let channels = self.metadata.parent.channel_ids.len();
        let start = s.next;
        let mut values = Vec::new();
        let mut spans = Vec::new();
        let total = self
            .cursor
            .checked_mul(s.up)
            .ok_or("sample_overflow")?
            .div_ceil(s.down);
        while s.next < total {
            let center = s
                .next
                .checked_mul(s.down)
                .and_then(|n| n.checked_add(s.shift))
                .ok_or("sample_overflow")?;
            if !eof && center / s.up >= self.cursor {
                break;
            }
            let mut output = vec![0.0; channels];
            let first = (i128::from(center) - s.h.len() as i128 + 1).div_euclid(i128::from(s.up));
            let last = center / s.up;
            for index in first..=i128::from(last) {
                let tap = i128::from(center) - index * i128::from(s.up);
                if tap < 0 || tap >= s.h.len() as i128 {
                    continue;
                }
                if index < 0 || index >= i128::from(self.cursor) {
                    push_span(
                        &mut spans,
                        InvalidSpan {
                            start: s.next,
                            end: s.next + 1,
                            channel_id: None,
                            reason: "warmup".into(),
                            origin: "filter.endpoint-padding".into(),
                        },
                        self.limits.max_validity_spans,
                    )?;
                    continue;
                }
                let at = (index as u64)
                    .checked_sub(s.base)
                    .ok_or("filter_state_underflow")? as usize;
                let frame = s.rows.get(at).ok_or("filter_state_underflow")?;
                for (c, y) in output.iter_mut().enumerate() {
                    *y += s.h[tap as usize] * s.up as f64 * frame.values[c];
                }
                for (channel_id, reason, origin) in &frame.invalid {
                    push_span(
                        &mut spans,
                        InvalidSpan {
                            start: s.next,
                            end: s.next + 1,
                            channel_id: channel_id.clone(),
                            reason: reason.clone(),
                            origin: origin.clone(),
                        },
                        self.limits.max_validity_spans,
                    )?;
                }
            }
            if output.iter().any(|v| !v.is_finite()) {
                return Err("nonfinite".into());
            }
            values.extend(output);
            s.next += 1;
            if values.len() / channels > self.limits.max_output_frames {
                return Err("filter_capacity".into());
            }
        }
        let next_center = s
            .next
            .checked_mul(s.down)
            .and_then(|n| n.checked_add(s.shift))
            .ok_or("sample_overflow")?;
        let keep = (i128::from(next_center) - s.h.len() as i128 + 1)
            .div_euclid(i128::from(s.up))
            .max(0) as u64;
        while s.base < keep.min(self.cursor) {
            s.rows.pop_front();
            s.base += 1;
        }
        if values.is_empty() {
            return Ok(None);
        }
        let spans = merge_spans(spans);
        if spans.len() > self.limits.max_validity_spans {
            return Err("filter_capacity".into());
        }
        SignalBlock::new(
            self.metadata.output.clone(),
            start,
            Samples::F64(values),
            spans,
        )
        .map(Some)
    }
}
fn merge_spans(mut spans: Vec<InvalidSpan>) -> Vec<InvalidSpan> {
    spans.sort_by(|a, b| {
        (&a.channel_id, &a.reason, &a.origin, a.start, a.end).cmp(&(
            &b.channel_id,
            &b.reason,
            &b.origin,
            b.start,
            b.end,
        ))
    });
    let mut result: Vec<InvalidSpan> = Vec::new();
    for s in spans {
        if let Some(last) = result.last_mut()
            && last.channel_id == s.channel_id
            && last.reason == s.reason
            && last.origin == s.origin
            && last.end >= s.start
        {
            last.end = last.end.max(s.end);
        } else {
            result.push(s);
        }
    }
    result
}
#[cfg(test)]
mod tests;
