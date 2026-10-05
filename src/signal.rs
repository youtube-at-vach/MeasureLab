use std::ops::Range;

pub const MAX_CHANNELS: usize = 16;
/// Standard precision of the acquisition and measurement core.
pub type Samples = [f64; MAX_CHANNELS];

/// Fixed allocation, with absolute indices so wrapping never changes time ordering.
pub struct History {
    data: Vec<f64>,
    valid: Vec<bool>,
    channels: usize,
    end: u64,
    len: usize,
    contiguous_start: u64,
}

impl History {
    pub fn new(capacity: usize) -> Self {
        Self::with_channels(capacity, 2)
    }

    pub fn with_channels(capacity: usize, channels: usize) -> Self {
        assert!(capacity > 0 && (1..=MAX_CHANNELS).contains(&channels));
        Self {
            data: vec![0.0; capacity * channels],
            valid: vec![false; capacity],
            channels,
            end: 0,
            len: 0,
            contiguous_start: 0,
        }
    }

    pub fn channels(&self) -> usize {
        self.channels
    }

    pub fn push(&mut self, samples: impl AsRef<[f64]>) {
        self.push_at(self.end, samples);
    }

    /// Preserve source sample coordinates and retained frames around gaps.
    /// Incomplete channel frames are discarded; they remain missing if input resumes.
    pub fn push_at(&mut self, sequence: u64, samples: impl AsRef<[f64]>) {
        let samples = samples.as_ref();
        if samples.len() < self.channels {
            return;
        }
        self.advance_to(sequence);
        let capacity = self.valid.len();
        let slot = (sequence % capacity as u64) as usize;
        let index = slot * self.channels;
        for (target, &sample) in self.data[index..index + self.channels]
            .iter_mut()
            .zip(samples)
        {
            *target = if sample.is_finite() { sample } else { 0.0 };
        }
        self.valid[slot] = true;
        self.end = sequence + 1;
        self.len = (self.len + 1).min(capacity);
    }

    /// Advance the source clock through missing frames with bounded work and
    /// no allocation. A restart or gap beyond capacity expires all old frames.
    pub fn advance_to(&mut self, next_sequence: u64) {
        if next_sequence == self.end {
            return;
        }
        let capacity = self.valid.len();
        if self.is_empty()
            || next_sequence < self.end
            || next_sequence - self.end >= capacity as u64
        {
            self.clear_at(next_sequence);
            return;
        }
        let missing = (next_sequence - self.end) as usize;
        self.contiguous_start = next_sequence;
        let start = (self.end % capacity as u64) as usize;
        let first = missing.min(capacity - start);
        self.valid[start..start + first].fill(false);
        self.valid[..missing - first].fill(false);
        self.len = (self.len + missing).min(capacity);
        self.end = next_sequence;
    }

    pub fn clear(&mut self) {
        self.len = 0;
        self.contiguous_start = self.end;
    }
    pub fn clear_at(&mut self, next_sequence: u64) {
        self.clear();
        self.end = next_sequence;
        self.contiguous_start = next_sequence;
    }
    /// Retained time span in frames, including missing positions.
    pub fn len(&self) -> usize {
        self.len
    }
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }
    pub fn range(&self) -> Range<u64> {
        self.end - self.len as u64..self.end
    }
    /// Latest uninterrupted input, suitable for complete FFT/trigger windows.
    pub fn contiguous_range(&self) -> Range<u64> {
        self.contiguous_start.max(self.range().start)..self.end
    }
    pub fn get(&self, index: u64) -> Option<&[f64]> {
        if !self.range().contains(&index) {
            return None;
        }
        let slot = (index % self.valid.len() as u64) as usize;
        let start = slot * self.channels;
        self.valid[slot].then(|| &self.data[start..start + self.channels])
    }

    /// Caller validates that the complete range is retained. Walk the two
    /// contiguous ring slices without a division or range check per sample.
    /// Missing positions yield None rather than fabricated samples.
    pub(crate) fn samples(&self, range: Range<u64>) -> impl Iterator<Item = Option<&[f64]>> + '_ {
        let count = (range.end - range.start) as usize;
        let capacity = self.data.len() / self.channels;
        let start = (range.start % capacity as u64) as usize;
        let first = count.min(capacity - start);
        let frames = self.data[start * self.channels..(start + first) * self.channels]
            .chunks_exact(self.channels)
            .chain(self.data[..(count - first) * self.channels].chunks_exact(self.channels));
        let valid = self.valid[start..start + first]
            .iter()
            .chain(&self.valid[..count - first]);
        frames
            .zip(valid)
            .map(|(frame, &valid)| valid.then_some(frame))
    }

    /// Latest complete triggered sweep, or latest time span with gaps in auto
    /// mode. Trigger position is 20% from the left edge.
    pub fn sweep(&self, count: usize, trigger: Trigger) -> Sweep {
        let count = count.max(2).min(self.len);
        if count < 2 {
            return Sweep {
                range: self.range(),
                triggered: false,
                sample_offset: 0.0,
            };
        }
        let available = self.range();
        let latest_start = available.end - count as u64;
        if trigger.edge != Edge::Free && trigger.channel < self.channels {
            let pre = (count / 5) as u64;
            let start = self.contiguous_range().start;
            let first = (start + pre).max(start + 1);
            let last = latest_start + pre;
            // A bounded backwards scan; old captures are not searched forever.
            let first = first.max(last.saturating_sub(count as u64 * 2));
            for index in (first..=last).rev() {
                let (Some(a), Some(b)) = (self.get(index - 1), self.get(index)) else {
                    continue;
                };
                let a = a[trigger.channel];
                let b = b[trigger.channel];
                let crossed = match trigger.edge {
                    Edge::Rising => a < trigger.level && b >= trigger.level,
                    Edge::Falling => a > trigger.level && b <= trigger.level,
                    Edge::Free => false,
                };
                if crossed {
                    let start = index - pre;
                    return Sweep {
                        range: start..start + count as u64,
                        triggered: true,
                        // The crossing lies between a and b. Keeping that
                        // fractional position avoids a full-sample jump when
                        // noise changes the sign of a sample near the level.
                        sample_offset: ((b - trigger.level) / (b - a)).clamp(0.0, 1.0),
                    };
                }
            }
        }
        // Auto trigger: keep updating even on silence or without a crossing.
        Sweep {
            range: latest_start..available.end,
            triggered: false,
            sample_offset: 0.0,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Edge {
    Free,
    Rising,
    Falling,
}

#[derive(Clone, Copy)]
pub struct Trigger {
    pub edge: Edge,
    pub level: f64,
    pub channel: usize,
}

impl Default for Trigger {
    fn default() -> Self {
        Self {
            edge: Edge::Rising,
            level: 0.0,
            channel: 0,
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct Sweep {
    pub range: Range<u64>,
    pub triggered: bool,
    /// Horizontal correction in sample units. The trigger crossing is this
    /// far before `range.start + range.len() / 5`; acquired samples stay intact.
    pub sample_offset: f64,
}

#[derive(Clone, Copy, Debug)]
pub struct Line {
    pub a: [f32; 2],
    pub b: [f32; 2],
    pub channel: usize,
}

#[derive(Clone, Copy, Default, Debug)]
pub struct Measurement {
    pub peak: f64,
    pub rms: f64,
    pub peak_to_peak: f64,
}

/// At low density, connect real samples. At high density, retain each pixel's
/// extrema as vertical segments, with a connector between adjacent buckets.
/// Output and GPU transfer remain O(screen width), with no missed narrow peaks.
pub fn build_lines(
    history: &History,
    range: Range<u64>,
    pixels: usize,
    fs_per_div: f32,
    enabled: [bool; 2],
    output: &mut Vec<Line>,
) -> [Measurement; 2] {
    build_sweep_lines(
        history,
        &Sweep {
            range,
            ..Sweep::default()
        },
        pixels,
        fs_per_div,
        enabled,
        output,
    )
}

/// Align real samples to the interpolated trigger time. Only the horizontal
/// display coordinates change; measurements use the original samples.
pub fn build_sweep_lines(
    history: &History,
    sweep: &Sweep,
    pixels: usize,
    fs_per_div: f32,
    enabled: [bool; 2],
    output: &mut Vec<Line>,
) -> [Measurement; 2] {
    output.clear();
    let range = sweep.range.clone();
    let range = range.start.max(history.range().start)..range.end.min(history.range().end);
    if range.end <= range.start + 1 || pixels == 0 {
        return [Measurement::default(); 2];
    }
    let count = (range.end - range.start) as usize;
    let x = |offset: f64| ((offset + sweep.sample_offset) / (count - 1) as f64) as f32;
    let scale = 1.0 / (fs_per_div.max(0.00001) * 8.0);
    let y = |value: f64| (0.5 - value * scale as f64) as f32;
    let mut result = [Measurement::default(); 2];
    for channel in 0..2 {
        if !enabled[channel] || channel >= history.channels() {
            continue;
        }
        let mut min = f64::INFINITY;
        let mut max = f64::NEG_INFINITY;
        let mut square_sum = 0.0_f64;
        let mut valid_count = 0;
        if count <= pixels * 2 {
            let mut previous = None;
            for (offset, frame) in history.samples(range.clone()).enumerate() {
                let Some(frame) = frame else {
                    previous = None;
                    continue;
                };
                let value = frame[channel];
                min = min.min(value);
                max = max.max(value);
                square_sum += value * value;
                valid_count += 1;
                let point = [x(offset as f64), y(value)];
                if let Some(a) = previous {
                    output.push(Line {
                        a,
                        b: point,
                        channel,
                    });
                }
                previous = Some(point);
            }
        } else {
            let mut previous = None;
            let mut samples = history.samples(range.clone());
            for bucket in 0..pixels {
                let begin = bucket * count / pixels;
                let end = (bucket + 1) * count / pixels;
                let mut lo = f64::INFINITY;
                let mut hi = f64::NEG_INFINITY;
                let mut first = 0.0;
                let mut last = 0.0;
                let mut missing = false;
                for offset in begin..end {
                    let Some(frame) = samples.next().unwrap() else {
                        missing = true;
                        continue;
                    };
                    let value = frame[channel];
                    if offset == begin {
                        first = value;
                    }
                    last = value;
                    lo = lo.min(value);
                    hi = hi.max(value);
                    square_sum += value * value;
                    valid_count += 1;
                }
                min = min.min(lo);
                max = max.max(hi);
                // Omit a pixel bucket containing a gap: neither its envelope
                // nor its connector may merge separate acquisition intervals.
                if missing {
                    previous = None;
                    continue;
                }
                let x = x((begin + end - 1) as f64 * 0.5);
                if let Some(a) = previous {
                    output.push(Line {
                        a,
                        b: [x, y(first)],
                        channel,
                    });
                }
                output.push(Line {
                    a: [x, y(lo)],
                    b: [x, y(hi)],
                    channel,
                });
                previous = Some([x, y(last)]);
            }
        }
        if valid_count > 0 {
            result[channel] = Measurement {
                peak: min.abs().max(max.abs()),
                rms: (square_sum / valid_count as f64).sqrt(),
                peak_to_peak: max - min,
            };
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gaps_preserve_retained_frames_and_invalidate_wrapped_slots_without_allocation() {
        let mut history = History::new(8);
        let storage = history.data.as_ptr();
        let validity = history.valid.as_ptr();
        for sequence in 100..108 {
            history.push_at(sequence, [sequence as f64, 0.0]);
        }
        history.advance_to(110);
        assert_eq!(history.range(), 102..110);
        assert_eq!(history.contiguous_range(), 110..110);
        history.push_at(110, [110.0, 0.0]);
        assert_eq!(history.range(), 103..111);
        assert_eq!(history.contiguous_range(), 110..111);
        assert_eq!(
            history
                .samples(history.range())
                .map(|s| s.map(|s| s[0]))
                .collect::<Vec<_>>(),
            [
                Some(103.0),
                Some(104.0),
                Some(105.0),
                Some(106.0),
                Some(107.0),
                None,
                None,
                Some(110.0)
            ]
        );
        assert!(history.get(108).is_none());
        assert!(history.get(109).is_none());
        history.push_at(111, [111.0, 0.0]);
        assert_eq!(history.get(107).unwrap()[0], 107.0);
        for sequence in 112..119 {
            history.push_at(sequence, [sequence as f64, 0.0]);
        }
        // This gap straddles the end of the validity ring.
        history.push_at(122, [122.0, 0.0]);
        assert_eq!(history.range(), 115..123);
        assert_eq!(history.get(117).unwrap()[0], 117.0);
        assert_eq!(history.get(118).unwrap()[0], 118.0);
        for missing in 119..122 {
            assert!(history.get(missing).is_none());
        }
        for sequence in 123..131 {
            history.push_at(sequence, [sequence as f64, 0.0]);
        }
        assert_eq!(history.contiguous_range(), 123..131);
        assert!(
            history
                .samples(history.range())
                .all(|frame| frame.is_some())
        );
        // A jump far beyond capacity must not iterate over all missing frames.
        history.push_at(1_u64 << 54, [0.25, 0.0]);
        assert_eq!(history.len(), 1);
        assert!(history.get(111).is_none());
        history.push_at(3, [0.5, 0.0]);
        assert_eq!(history.range(), 3..4);
        assert_eq!(history.contiguous_range(), 3..4);
        assert_eq!(history.data.as_ptr(), storage);
        assert_eq!(history.valid.as_ptr(), validity);
    }

    #[test]
    fn incomplete_channel_frames_are_discarded_and_become_gaps() {
        let mut history = History::with_channels(8, 16);
        history.push_at(100, [0.25; 16]);
        history.push_at(101, [0.5; 15]);
        assert_eq!(history.range(), 100..101);
        assert_eq!(history.get(100).unwrap(), &[0.25; 16]);
        history.push_at(102, [0.75; 16]);
        assert_eq!(history.range(), 100..103);
        assert!(history.get(101).is_none());
        assert_eq!(history.get(102).unwrap(), &[0.75; 16]);
    }

    #[test]
    fn scope_breaks_lines_at_gaps_and_measures_only_acquired_samples() {
        let mut history = History::new(32);
        for i in 0..16 {
            if i != 7 {
                history.push_at(i, [if i == 9 { 1.0 } else { 0.5 }, 0.0]);
            }
        }
        for pixels in [4, 100] {
            let mut lines = Vec::new();
            let measured = build_lines(&history, 0..16, pixels, 0.25, [true, false], &mut lines);
            assert_eq!(measured[0].peak, 1.0);
            assert_eq!(measured[0].peak_to_peak, 0.5);
            assert!((measured[0].rms - (4.5_f64 / 15.0).sqrt()).abs() < 1e-12);
            let gap = 7.0 / 15.0;
            assert!(
                lines
                    .iter()
                    .all(|line| !(line.a[0] < gap && line.b[0] > gap))
            );
            assert!(lines.iter().any(|line| line.a[0] < gap));
            assert!(lines.iter().any(|line| line.a[0] > gap));
            assert!(lines.len() <= pixels * 2);
            history.advance_to(20);
            let empty = build_lines(&history, 16..20, pixels, 0.25, [true, false], &mut lines);
            assert!(lines.is_empty());
            assert_eq!(empty[0].peak, 0.0);
            assert_eq!(empty[0].rms, 0.0);
            assert_eq!(empty[0].peak_to_peak, 0.0);
        }
    }

    #[test]
    fn trigger_does_not_reuse_pre_gap_crossings_and_recovers_after_a_complete_window() {
        let mut history = History::new(128);
        for i in 0..64 {
            if i != 60 {
                history.push_at(i, [if i % 8 < 4 { -0.5 } else { 0.5 }, 0.0]);
            }
        }
        let sweep = history.sweep(16, Trigger::default());
        assert!(!sweep.triggered);
        assert_eq!(sweep.range, 48..64);
        assert!(history.get(59).is_some());
        assert!(history.get(60).is_none());
        for i in 64..96 {
            history.push_at(i, [if i % 8 < 4 { -0.5 } else { 0.5 }, 0.0]);
        }
        let sweep = history.sweep(16, Trigger::default());
        assert!(sweep.triggered);
        assert!(sweep.range.start >= 61);
        assert!(history.samples(sweep.range).all(|frame| frame.is_some()));
    }

    #[test]
    fn fractional_trigger_alignment_preserves_raw_measurements_and_envelopes() {
        let mut history = History::new(512);
        for i in 0..512 {
            let value = ((i % 16) as f64 - 4.25) * 0.05;
            history.push([value, -value]);
        }
        for channel in 0..2 {
            for edge in [Edge::Rising, Edge::Falling] {
                for level in [0.0, 0.1, -0.1] {
                    let sweep = history.sweep(
                        80,
                        Trigger {
                            edge,
                            level,
                            channel,
                        },
                    );
                    assert!(sweep.triggered);
                    assert!(sweep.sample_offset > 0.0 && sweep.sample_offset < 1.0);
                    let index = sweep.range.start + 16;
                    let a = history.get(index - 1).unwrap()[channel];
                    let b = history.get(index).unwrap()[channel];
                    let crossing = a * sweep.sample_offset + b * (1.0 - sweep.sample_offset);
                    assert!((crossing - level).abs() < 1e-15);
                    for pixels in [8, 100] {
                        let mut raw = Vec::new();
                        let mut aligned = Vec::new();
                        let expected = build_lines(
                            &history,
                            sweep.range.clone(),
                            pixels,
                            0.25,
                            [true; 2],
                            &mut raw,
                        );
                        let measured = build_sweep_lines(
                            &history,
                            &sweep,
                            pixels,
                            0.25,
                            [true; 2],
                            &mut aligned,
                        );
                        assert_eq!(raw.len(), aligned.len());
                        for (raw, aligned) in raw.iter().zip(&aligned) {
                            for (raw, aligned) in [(raw.a, aligned.a), (raw.b, aligned.b)] {
                                assert_eq!(raw[1], aligned[1]);
                                assert!(
                                    ((aligned[0] - raw[0]) as f64 - sweep.sample_offset / 79.0)
                                        .abs()
                                        < 1e-7
                                );
                            }
                        }
                        for channel in 0..2 {
                            assert_eq!(measured[channel].peak, expected[channel].peak);
                            assert_eq!(measured[channel].rms, expected[channel].rms);
                            assert_eq!(
                                measured[channel].peak_to_peak,
                                expected[channel].peak_to_peak
                            );
                        }
                    }
                }
            }
        }
        for edge in [Edge::Free, Edge::Rising] {
            let sweep = history.sweep(
                80,
                Trigger {
                    edge,
                    level: 1.0,
                    channel: 0,
                },
            );
            assert!(!sweep.triggered);
            assert_eq!(sweep.sample_offset, 0.0);
            assert_eq!(sweep.range, 432..512);
        }
    }

    #[test]
    fn history_trigger_and_measurements_preserve_sub_f32_variations() {
        let mut history = History::new(128);
        for i in 0..128 {
            history.push([if i % 16 < 8 { 1.0 - 1e-8 } else { 1.0 + 1e-8 }, 0.0]);
        }
        let sweep = history.sweep(
            32,
            Trigger {
                level: 1.0,
                ..Trigger::default()
            },
        );
        assert!(sweep.triggered);
        let mut lines = Vec::new();
        let measured = build_lines(&history, sweep.range, 100, 0.25, [true, false], &mut lines);
        assert!((measured[0].peak_to_peak - 2e-8).abs() < 1e-15);
        assert!((measured[0].peak - (1.0 + 1e-8)).abs() < 1e-15);
    }

    #[test]
    fn sixteen_channel_history_preserves_absolute_coordinates_and_gaps() {
        let mut h = History::with_channels(4, 16);
        for sequence in 100..107 {
            h.push_at(
                sequence,
                std::array::from_fn::<_, 16, _>(|ch| sequence as f64 + ch as f64),
            );
        }
        assert_eq!(h.range(), 103..107);
        assert_eq!(h.get(103).unwrap()[15], 118.0);
        assert_eq!(
            h.samples(h.range())
                .map(|s| s.unwrap()[15])
                .collect::<Vec<_>>(),
            [118.0, 119.0, 120.0, 121.0]
        );
        h.push_at(200, [0.0; 16]);
        assert_eq!(h.range(), 200..201);
        assert!(h.get(106).is_none());
        for sequence in 201..210 {
            let mut samples = [0.0; 16];
            samples[15] = if sequence < 207 { -0.5 } else { 0.5 };
            h.push_at(sequence, samples);
        }
        let sweep = h.sweep(
            3,
            Trigger {
                channel: 15,
                ..Trigger::default()
            },
        );
        assert!(sweep.triggered);
        assert_eq!(sweep.range, 207..210);
    }

    #[test]
    fn history_wraps_and_clear_invalidates_old_samples() {
        let mut h = History::new(4);
        for i in 0..7 {
            h.push([i as f64, 0.0]);
        }
        assert_eq!(h.range(), 3..7);
        assert_eq!(h.get(2), None);
        assert_eq!(h.get(3), Some([3.0, 0.0].as_slice()));
        assert_eq!(
            h.samples(h.range())
                .map(|v| v.unwrap()[0])
                .collect::<Vec<_>>(),
            vec![3.0, 4.0, 5.0, 6.0]
        );
        h.clear();
        h.push([9.0, 0.0]);
        assert_eq!(h.range(), 7..8);
    }

    #[test]
    fn extrema_preserve_a_single_sample_spike_and_bound_geometry() {
        let mut h = History::new(10_000);
        for i in 0..10_000 {
            h.push([if i == 4321 { 1.0 } else { 0.0 }, 0.0]);
        }
        let mut lines = Vec::new();
        let m = build_lines(&h, h.range(), 100, 0.25, [true, false], &mut lines);
        assert_eq!(m[0].peak, 1.0);
        assert_eq!(m[0].peak_to_peak, 1.0);
        assert!((m[0].rms - 0.01).abs() < 1e-6);
        assert!(lines.iter().any(|l| l.a[1] == 0.0 || l.b[1] == 0.0));
        assert!(lines.len() <= 200);
    }

    #[test]
    fn trigger_requires_post_trigger_samples_and_uses_selected_channel() {
        let mut h = History::new(100);
        for i in 0..100 {
            h.push([0.0, if i % 20 < 10 { -0.5 } else { 0.5 }]);
        }
        let sweep = h.sweep(
            40,
            Trigger {
                channel: 1,
                ..Trigger::default()
            },
        );
        assert!(sweep.triggered);
        assert_eq!(sweep.range, 42..82);
        let falling = h.sweep(
            40,
            Trigger {
                channel: 1,
                edge: Edge::Falling,
                level: 0.0,
            },
        );
        assert_eq!(falling.range, 52..92);
        let free = h.sweep(
            40,
            Trigger {
                edge: Edge::Free,
                ..Trigger::default()
            },
        );
        assert_eq!(free.range, 60..100);
    }

    #[test]
    fn invalid_samples_and_short_captures_are_safe() {
        let mut h = History::new(10);
        h.push([f64::NAN, f64::INFINITY]);
        assert_eq!(h.get(0), Some([0.0, 0.0].as_slice()));
        let mut lines = Vec::new();
        build_lines(
            &h,
            h.sweep(100, Trigger::default()).range,
            100,
            0.25,
            [true; 2],
            &mut lines,
        );
        assert!(lines.is_empty());
    }
}
