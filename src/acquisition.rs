//! Sample-clock Scope capture. UI publication never arms or completes a trigger.
use crate::signal::{Edge, History, Sweep, Trigger};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Mode {
    #[default]
    Auto,
    Normal,
    Single,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum State {
    #[default]
    Waiting,
    Acquiring,
    WaitingWithCapture,
    Complete,
}

pub struct Acquisition {
    pub mode: Mode,
    pub state: State,
    pub capture: History,
    pub sweep: Sweep,
    pending: Option<(u64, f64)>,
}

impl Acquisition {
    pub fn invalidate(&mut self) {
        self.pending = None;
        self.capture.clear();
        self.sweep = Sweep::default();
        self.state = State::Waiting;
    }
    pub fn new(mode: Mode, samples: usize, channels: usize) -> Self {
        Self {
            mode,
            state: State::Waiting,
            capture: History::with_channels(samples.max(2), channels),
            sweep: Sweep::default(),
            pending: None,
        }
    }

    /// Called after each acquired frame, before a shared ring can wrap.
    pub fn push(&mut self, history: &History, samples: usize, trigger: Trigger) {
        if self.mode == Mode::Auto || self.state == State::Complete {
            return;
        }
        let available = history.contiguous_range();
        let count = samples.max(2) as u64;
        let pre = count / 5;
        let index = available.end.saturating_sub(1);
        if self
            .pending
            .is_some_and(|(start, _)| start < available.start)
        {
            self.pending = None;
        }
        // A discontinuity invalidates both the candidate and an older Normal capture.
        if available.start == index {
            self.pending = None;
            self.capture.clear();
            self.sweep = Sweep::default();
        }
        if self.pending.is_none()
            && index >= available.start + pre.max(1)
            && let (Some(a), Some(b)) = (history.get(index - 1), history.get(index))
            && trigger.channel < history.channels()
        {
            let a = a[trigger.channel];
            let b = b[trigger.channel];
            let crossed = match trigger.edge {
                Edge::Rising => a < trigger.level && b >= trigger.level,
                Edge::Falling => a > trigger.level && b <= trigger.level,
                Edge::Free => false,
            };
            if crossed {
                self.pending = Some((index - pre, (b - trigger.level) / (b - a)));
            }
        }
        if let Some((start, offset)) = self.pending
            && available.end >= start + count
        {
            self.capture.clear_at(start);
            for n in start..start + count {
                self.capture
                    .push_at(n, history.get(n).expect("complete trigger window"));
            }
            self.sweep = Sweep {
                range: start..start + count,
                triggered: true,
                sample_offset: offset,
            };
            self.pending = None;
            self.state = if self.mode == Mode::Single {
                State::Complete
            } else {
                State::WaitingWithCapture
            };
        } else {
            self.state = if self.pending.is_some() {
                State::Acquiring
            } else if self.capture.is_empty() {
                State::Waiting
            } else {
                State::WaitingWithCapture
            };
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Autoset {
    pub samples: usize,
    pub fs_per_div: f64,
    pub trigger: Trigger,
    pub frequency_hz: f64,
}

pub fn autoset(history: &History, rate: u32, channel: usize) -> Result<Autoset, String> {
    if channel >= history.channels() {
        return Err("Autoset: source unavailable".into());
    }
    let range = history.range();
    let start = range.end.saturating_sub(rate as u64 / 5).max(range.start);
    if range.end - start < 32 {
        return Err("Autoset: acquire at least 32 samples".into());
    }
    let mut min = f64::INFINITY;
    let mut max = f64::NEG_INFINITY;
    for n in start..range.end {
        let x = history
            .get(n)
            .ok_or("Autoset: input contains missing samples")?[channel];
        if !x.is_finite() {
            return Err("Autoset: nonfinite input".into());
        }
        min = min.min(x);
        max = max.max(x);
    }
    if min <= -0.999 || max >= 0.999 {
        return Err("Autoset: input clips at full scale".into());
    }
    if max - min < 1e-6 {
        return Err("Autoset: DC, no signal or signal below 1 µFS".into());
    }
    let level = (min + max) / 2.0;
    let hysteresis = (max - min) * 0.1;
    let mut armed = false;
    let mut crossings = Vec::new();
    for n in start + 1..range.end {
        let a = history.get(n - 1).unwrap()[channel];
        let b = history.get(n).unwrap()[channel];
        if b < level - hysteresis {
            armed = true;
        }
        if armed && a < level && b >= level {
            crossings.push(n as f64 - (b - level) / (b - a));
            armed = false;
        }
    }
    if crossings.len() < 3 {
        return Err("Autoset: no stable periodic trigger in 200 ms".into());
    }
    let periods: Vec<_> = crossings.windows(2).map(|w| w[1] - w[0]).collect();
    let period = periods.iter().sum::<f64>() / periods.len() as f64;
    if periods
        .iter()
        .any(|p| (p - period).abs() > period * 0.1 + 1.0)
    {
        return Err("Autoset: irregular/noisy signal".into());
    }
    Ok(Autoset {
        samples: (period * 3.0)
            .round()
            .clamp(rate as f64 * 0.0005, rate as f64) as usize,
        fs_per_div: (min.abs().max(max.abs()) / 3.5).clamp(0.001, 0.5),
        trigger: Trigger {
            channel,
            edge: Edge::Rising,
            level,
        },
        frequency_hz: rate as f64 / period,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn single_pulse_is_fixed_without_any_display_and_gap_rearms() {
        let mut h = History::with_channels(20, 16);
        let mut a = Acquisition::new(Mode::Single, 10, 16);
        let t = Trigger {
            channel: 15,
            level: 0.5,
            edge: Edge::Rising,
        };
        for n in 0..100 {
            let mut f = [0.0; 16];
            f[15] = if n == 12 { 1.0 } else { 0.0 };
            h.push_at(n, f);
            a.push(&h, 10, t);
        }
        assert_eq!(a.state, State::Complete);
        assert_eq!(a.sweep.range, 10..20);
        assert_eq!(a.capture.get(12).unwrap()[15], 1.0);
        assert!(h.get(12).is_none());
        let mut a = Acquisition::new(Mode::Single, 10, 16);
        h.clear_at(0);
        for n in 0..14 {
            let mut f = [0.0; 16];
            if n == 12 {
                f[15] = 1.0;
            }
            h.push_at(n, f);
            a.push(&h, 10, t);
        }
        h.push_at(16, [0.0; 16]);
        a.push(&h, 10, t);
        assert_eq!(a.state, State::Waiting);
        assert!(a.capture.is_empty());
    }
    #[test]
    fn normal_does_not_substitute_free_running_samples_and_autoset_has_reasons() {
        let mut h = History::new(48000);
        let mut a = Acquisition::new(Mode::Normal, 100, 2);
        for _ in 0..1000 {
            h.push([0.1, 0.0]);
            a.push(&h, 100, Trigger::default());
        }
        assert!(a.capture.is_empty());
        assert!(autoset(&h, 48000, 0).unwrap_err().contains("DC"));
        for n in 0..9600 {
            h.push([
                0.2 + 0.1 * (std::f64::consts::TAU * n as f64 / 48.0).sin(),
                0.0,
            ]);
        }
        let result = autoset(&h, 48000, 0).unwrap();
        assert!((result.frequency_hz - 1000.0).abs() < 1e-9);
        assert_eq!(result.samples, 144);
        assert!((result.trigger.level - 0.2).abs() < 1e-12);
        h.push_at(h.range().end + 2, [0.0, 0.0]);
        assert!(autoset(&h, 48000, 0).unwrap_err().contains("missing"));
    }

    #[test]
    fn falling_edge_boundaries_and_new_single_arm_keep_exact_sample_counts() {
        for crossing in [2, 19, 40] {
            let mut h = History::new(16);
            let trigger = Trigger {
                channel: 0,
                level: 0.25,
                edge: Edge::Falling,
            };
            let mut a = Acquisition::new(Mode::Single, 10, 2);
            for n in 0..crossing + 8 {
                h.push_at(n, [if n < crossing { 0.5 } else { 0.0 }, 0.0]);
                a.push(&h, 10, trigger);
            }
            assert_eq!(a.state, State::Complete);
            assert_eq!(a.sweep.range, crossing - 2..crossing + 8);
            assert_eq!(a.sweep.sample_offset, 0.5);
            assert_eq!(
                crate::signal::measure(
                    &a.capture,
                    a.sweep.range.clone(),
                    crate::channel::Pair::<2>::default()
                )[0]
                .samples,
                10
            );
            let rearmed = Acquisition::new(Mode::Single, 10, 2);
            assert!(rearmed.capture.is_empty());
            assert_eq!(rearmed.state, State::Waiting);
        }
    }

    #[test]
    fn autoset_rejects_clipping_noise_and_missing_channel() {
        let mut h = History::new(48000);
        for n in 0..9600 {
            h.push([(std::f64::consts::TAU * n as f64 / 48.0).sin(), 0.0]);
        }
        assert!(autoset(&h, 48000, 0).unwrap_err().contains("clips"));
        assert!(autoset(&h, 48000, 15).unwrap_err().contains("unavailable"));
        h.clear();
        let mut random = 17u64;
        for _ in 0..9600 {
            random ^= random << 13;
            random ^= random >> 7;
            random ^= random << 17;
            h.push([(random as f64 / u64::MAX as f64 - 0.5) * 0.2, 0.0]);
        }
        assert!(autoset(&h, 48000, 0).is_err());
    }
}
