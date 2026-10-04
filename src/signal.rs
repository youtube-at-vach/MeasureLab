use std::ops::Range;

pub type Samples = [f32; 2];

/// Fixed allocation, with absolute indices so wrapping never changes time ordering.
pub struct History {
    data: Vec<Samples>,
    end: u64,
    len: usize,
}

impl History {
    pub fn new(capacity: usize) -> Self {
        assert!(capacity > 0);
        Self {
            data: vec![[0.0; 2]; capacity],
            end: 0,
            len: 0,
        }
    }

    pub fn push(&mut self, samples: Samples) {
        let index = self.end as usize % self.data.len();
        self.data[index] = samples.map(|v| if v.is_finite() { v } else { 0.0 });
        self.end += 1;
        self.len = (self.len + 1).min(self.data.len());
    }

    pub fn clear(&mut self) {
        self.len = 0;
    }
    pub fn len(&self) -> usize {
        self.len
    }
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }
    pub fn range(&self) -> Range<u64> {
        self.end - self.len as u64..self.end
    }
    pub fn get(&self, index: u64) -> Option<Samples> {
        self.range()
            .contains(&index)
            .then(|| self.data[index as usize % self.data.len()])
    }

    fn samples(&self, range: Range<u64>) -> impl Iterator<Item = Samples> + '_ {
        let count = (range.end - range.start) as usize;
        let start = range.start as usize % self.data.len();
        let first = count.min(self.data.len() - start);
        self.data[start..start + first]
            .iter()
            .chain(self.data[..count - first].iter())
            .copied()
    }

    /// Latest complete sweep. Trigger position is 20% from the left edge.
    pub fn sweep(&self, count: usize, trigger: Trigger) -> Sweep {
        let count = count.max(2).min(self.len);
        if count < 2 {
            return Sweep {
                range: self.range(),
                triggered: false,
            };
        }
        let available = self.range();
        let latest_start = available.end - count as u64;
        if trigger.edge != Edge::Free {
            let pre = (count / 5) as u64;
            let first = (available.start + pre).max(available.start + 1);
            let last = latest_start + pre;
            // A bounded backwards scan; old captures are not searched forever.
            let first = first.max(last.saturating_sub(count as u64 * 2));
            for index in (first..=last).rev() {
                let a = self.get(index - 1).unwrap()[trigger.channel.min(1)];
                let b = self.get(index).unwrap()[trigger.channel.min(1)];
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
                    };
                }
            }
        }
        // Auto trigger: keep updating even on silence or without a crossing.
        Sweep {
            range: latest_start..available.end,
            triggered: false,
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
    pub level: f32,
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

pub struct Sweep {
    pub range: Range<u64>,
    pub triggered: bool,
}

#[derive(Clone, Copy, Debug)]
pub struct Line {
    pub a: [f32; 2],
    pub b: [f32; 2],
    pub channel: usize,
}

#[derive(Clone, Copy, Default, Debug)]
pub struct Measurement {
    pub peak: f32,
    pub rms: f32,
    pub peak_to_peak: f32,
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
    output.clear();
    let range = range.start.max(history.range().start)..range.end.min(history.range().end);
    if range.end <= range.start + 1 || pixels == 0 {
        return [Measurement::default(); 2];
    }
    let count = (range.end - range.start) as usize;
    let scale = 1.0 / (fs_per_div.max(0.00001) * 8.0);
    let y = |value: f32| 0.5 - value * scale;
    let mut result = [Measurement::default(); 2];
    for channel in 0..2 {
        if !enabled[channel] {
            continue;
        }
        let mut min = f32::INFINITY;
        let mut max = f32::NEG_INFINITY;
        let mut square_sum = 0.0_f64;
        if count <= pixels * 2 {
            let mut previous = None;
            for (offset, frame) in history.samples(range.clone()).enumerate() {
                let value = frame[channel];
                min = min.min(value);
                max = max.max(value);
                square_sum += (value as f64).powi(2);
                let point = [offset as f32 / (count - 1) as f32, y(value)];
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
                let mut lo = f32::INFINITY;
                let mut hi = f32::NEG_INFINITY;
                let mut first = 0.0;
                let mut last = 0.0;
                for offset in begin..end {
                    let value = samples.next().unwrap()[channel];
                    if offset == begin {
                        first = value;
                    }
                    last = value;
                    lo = lo.min(value);
                    hi = hi.max(value);
                    square_sum += (value as f64).powi(2);
                }
                min = min.min(lo);
                max = max.max(hi);
                let x = (begin + end - 1) as f32 * 0.5 / (count - 1) as f32;
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
        result[channel] = Measurement {
            peak: min.abs().max(max.abs()),
            rms: (square_sum / count as f64).sqrt() as f32,
            peak_to_peak: max - min,
        };
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn history_wraps_and_clear_invalidates_old_samples() {
        let mut h = History::new(4);
        for i in 0..7 {
            h.push([i as f32, 0.0]);
        }
        assert_eq!(h.range(), 3..7);
        assert_eq!(h.get(2), None);
        assert_eq!(h.get(3), Some([3.0, 0.0]));
        assert_eq!(
            h.samples(h.range()).map(|v| v[0]).collect::<Vec<_>>(),
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
        h.push([f32::NAN, f32::INFINITY]);
        assert_eq!(h.get(0), Some([0.0, 0.0]));
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
