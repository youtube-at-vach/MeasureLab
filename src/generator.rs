//! Independent generator cards on one integer output clock.
//! This core owns no device, thread, UI, or measurement state. Construction may
//! allocate in the control adapter; rendering and applying settings never do.
use crate::{audio::MAX_SAMPLE_RATE, channel::ChannelId, signal::Samples};
use std::f64::consts::{PI, TAU};

pub mod control;
mod signals;
mod waveform;
pub use signals::Signals;
pub(crate) use signals::clock_array;
pub use waveform::Waveform;
#[cfg(test)]
mod tests;

pub const SIGNALS: usize = 16;
pub const TRANSITION_SECONDS: f64 = 0.010;

#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Signal {
    /// Stable card identity, never an output channel or display position.
    #[serde(default)]
    pub id: u64,
    #[serde(default)]
    pub waveform: Waveform,
    #[serde(default = "default_seed")]
    pub noise_seed: u64,
    pub frequency_hz: f64,
    /// Peak reference: 0 dBFS = 1 FS peak, sine RMS = peak / sqrt(2).
    pub amplitude_dbfs: f64,
    /// Positive phase leads. This offset is independent of the carrier history.
    pub phase_degrees: f64,
    pub enabled: bool,
    /// Zero-based output position, distinct from an input channel identity.
    pub output_channel: Option<ChannelId>,
}

impl Default for Signal {
    fn default() -> Self {
        Self {
            id: 0,
            waveform: Waveform::Sine,
            noise_seed: default_seed(),
            frequency_hz: 1000.0,
            amplitude_dbfs: -20.0,
            phase_degrees: 0.0,
            enabled: false,
            output_channel: None,
        }
    }
}
fn default_seed() -> u64 {
    1
}
fn default_next_id() -> u64 {
    3
}

impl Signal {
    pub fn amplitude_peak(self) -> f64 {
        10.0_f64.powf(self.amplitude_dbfs / 20.0)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Settings {
    pub signals: Signals,
    #[serde(default = "default_next_id")]
    pub next_id: u64,
}

impl Default for Settings {
    fn default() -> Self {
        Self::for_channels(2)
    }
}

impl Settings {
    /// The second signal stays unassigned on a mono device. Output is OFF.
    pub fn for_channels(channels: usize) -> Self {
        let mut signals = Signals::empty();
        for i in 0..2 {
            signals
                .push(Signal {
                    id: i as u64 + 1,
                    output_channel: (i < channels).then_some(i),
                    ..Signal::default()
                })
                .unwrap();
        }
        Self {
            signals,
            next_id: 3,
        }
    }

    /// New/duplicated cards are OFF and use a free output, or remain unassigned.
    pub fn add(&mut self, duplicate: Option<usize>, channels: usize) -> Result<usize, Error> {
        let next_id = self.next_id.checked_add(1).ok_or(Error::CounterExhausted)?;
        let mut signal = duplicate.map_or_else(Signal::default, |i| self.signals[i]);
        signal.id = self.next_id;
        signal.enabled = false;
        signal.output_channel =
            (0..channels).find(|&ch| !self.signals.iter().any(|s| s.output_channel == Some(ch)));
        self.signals.push(signal)?;
        self.next_id = next_id;
        Ok(self.signals.len() - 1)
    }

    /// Fixed-size errors can also be returned at the real-time boundary.
    pub fn validate(self, rate: u32, channels: usize) -> Result<(), Error> {
        if self.next_id == 0 {
            return Err(Error::SignalIdentity);
        }
        if !(1..=MAX_SAMPLE_RATE).contains(&rate) {
            return Err(Error::SampleRate);
        }
        if !(1..=crate::signal::MAX_CHANNELS).contains(&channels) {
            return Err(Error::ChannelCount);
        }
        for (i, s) in self.signals.iter().enumerate() {
            if s.id == 0
                || s.id >= self.next_id
                || self.signals[..i].iter().any(|old| old.id == s.id)
            {
                return Err(Error::SignalIdentity);
            }
            if !s.frequency_hz.is_finite()
                || s.frequency_hz < 0.1
                || s.frequency_hz >= rate as f64 * 0.45
            {
                return Err(Error::Frequency(i));
            }
            if !s.amplitude_dbfs.is_finite() || !(-120.0..=0.0).contains(&s.amplitude_dbfs) {
                return Err(Error::Amplitude(i));
            }
            if !s.phase_degrees.is_finite() || !(-180.0..=180.0).contains(&s.phase_degrees) {
                return Err(Error::Phase(i));
            }
            if s.noise_seed == 0 {
                return Err(Error::Waveform(i));
            }
            if s.output_channel.is_some_and(|ch| ch >= channels)
                || (s.enabled && s.output_channel.is_none())
            {
                return Err(Error::Routing(i));
            }
            if s.output_channel.is_some()
                && self.signals[..i]
                    .iter()
                    .any(|old| old.output_channel == s.output_channel)
            {
                return Err(Error::DuplicateRouting);
            }
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum Error {
    SignalCount,
    SignalIdentity,
    Waveform(usize),
    SampleRate,
    ChannelCount,
    Frequency(usize),
    Amplitude(usize),
    Phase(usize),
    Routing(usize),
    DuplicateRouting,
    RoutingWhileActive,
    NoEnabledSignals,
    AlreadyActive,
    Stopping,
    Revision,
    CounterExhausted,
    NonFiniteOutput,
    OutputRange,
    ProducerSuspended,
    OutputStream,
    CallbackStalled,
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::SignalCount => write!(f, "Generator supports at most 16 cards"),
            Self::SignalIdentity => write!(
                f,
                "Generator card IDs must be unique and precede the next ID"
            ),
            Self::Waveform(i) => {
                write!(f, "Card at position {}: noise seed must be nonzero", i + 1)
            }
            Self::SampleRate => write!(f, "Unsupported nominal output sample rate"),
            Self::ChannelCount => write!(f, "Output requires 1–16 channels"),
            Self::Frequency(i) => write!(
                f,
                "Card at position {}: frequency must be >= 0.1 Hz and < 0.45 × output Fs",
                i + 1
            ),
            Self::Amplitude(i) => write!(
                f,
                "Card at position {}: amplitude must be finite and within -120–0 dBFS peak",
                i + 1
            ),
            Self::Phase(i) => write!(
                f,
                "Card at position {}: phase must be finite and within -180–180°",
                i + 1
            ),
            Self::Routing(i) => write!(
                f,
                "Card at position {}: output channel is unavailable or unassigned",
                i + 1
            ),
            Self::DuplicateRouting => write!(f, "Two signals cannot use the same output channel"),
            Self::RoutingWhileActive => {
                write!(
                    f,
                    "Stop output before changing cards, waveform details or channel assignments"
                )
            }
            Self::NoEnabledSignals => {
                write!(f, "Select at least one signal before starting output")
            }
            Self::AlreadyActive => write!(f, "Output is already active"),
            Self::Stopping => write!(f, "Wait for the output fade to finish"),
            Self::Revision => write!(f, "Settings revision must increase"),
            Self::CounterExhausted => {
                write!(f, "Output sample, generation or control counter exhausted")
            }
            Self::NonFiniteOutput => write!(f, "Nonfinite output; output stopped"),
            Self::OutputRange => write!(f, "Output exceeds full scale; output stopped"),
            Self::ProducerSuspended => write!(
                f,
                "Internal generation was suspended for more than 250 ms; output stopped"
            ),
            Self::OutputStream => write!(f, "Audio output failed; reset output before restarting"),
            Self::CallbackStalled => write!(f, "Audio output callback timed out; output released"),
        }
    }
}

impl std::error::Error for Error {}

#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum State {
    Stopped,
    Starting,
    Running,
    Stopping,
    Error(Error),
}

#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Status {
    pub state: State,
    pub nominal_sample_rate: u32,
    pub output_channels: usize,
    pub output_generation: u64,
    pub revision: u64,
    /// First frame using this revision, never the UI request time.
    pub applied_sample: u64,
    /// Carrier phases at applied_sample, before advancing that frame. Retained
    /// with the revision to describe independent frequency histories.
    #[serde(deserialize_with = "clock_array")]
    pub carrier_phase_cycles: [f64; SIGNALS],
    /// Exclusive transition endpoints; the sample at each endpoint is stable.
    #[serde(deserialize_with = "clock_array")]
    pub transition_end: [u64; SIGNALS],
    pub next_sample: u64,
    pub stop_sample: Option<u64>,
    /// Includes the final zero frame that acknowledged a completed Stop.
    pub stopped_at: Option<u64>,
    pub settings: Settings,
}

impl Status {
    pub fn transitioning(self) -> bool {
        matches!(
            self.state,
            State::Starting | State::Running | State::Stopping
        ) && self
            .transition_end
            .iter()
            .any(|&end| self.next_sample < end)
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Frame {
    pub sequence: u64,
    pub samples: Samples,
}

#[derive(Clone, Copy)]
struct Ramp {
    from: f64,
    to: f64,
    start: u64,
    end: u64,
}

impl Ramp {
    fn constant(value: f64, n: u64) -> Self {
        Self {
            from: value,
            to: value,
            start: n,
            end: n,
        }
    }
    fn new(from: f64, to: f64, n: u64, length: u64) -> Result<Self, Error> {
        if from == to {
            return Ok(Self::constant(to, n));
        }
        Ok(Self {
            from,
            to,
            start: n,
            end: n.checked_add(length).ok_or(Error::CounterExhausted)?,
        })
    }
    fn at(self, n: u64) -> f64 {
        if n >= self.end {
            return self.to;
        }
        let u = (n - self.start) as f64 / (self.end - self.start) as f64;
        self.from + (self.to - self.from) * (0.5 - 0.5 * (PI * u).cos())
    }
}

#[derive(Clone, Copy)]
struct Oscillator {
    /// Cycles in [0, 1); compensated addition bounds long-run phase drift.
    carrier: f64,
    compensation: f64,
    amplitude: Ramp,
    phase: Ramp,
    noise: u64,
}

impl Oscillator {
    fn advance(&mut self, increment: f64) {
        let y = increment - self.compensation;
        let sum = self.carrier + y;
        self.compensation = (sum - self.carrier) - y;
        self.carrier = if sum >= 1.0 { sum - 1.0 } else { sum };
    }
}

fn phase_delta(from: f64, to: f64) -> f64 {
    let delta = (to - from).rem_euclid(1.0);
    if delta > 0.5 { delta - 1.0 } else { delta }
}

fn phase_ramp(
    from: f64,
    target: f64,
    hz: f64,
    rate: u32,
    n: u64,
    minimum: u64,
) -> Result<Ramp, Error> {
    let from = from.rem_euclid(1.0);
    let delta = phase_delta(from, target);
    // Bound the maximum raised-cosine slope in cycles/sample. The extra
    // sample keeps the instantaneous increment strictly below Nyquist.
    let safe_length = (delta.abs() * PI / (2.0 * (0.5 - hz / rate as f64))).ceil() as u64 + 1;
    Ramp::new(from, from + delta, n, minimum.max(safe_length))
}

pub struct Engine {
    status: Status,
    oscillators: [Oscillator; SIGNALS],
}

impl Engine {
    /// Sequence may continue an existing internal input clock across a new
    /// output stream. A sample index is never converted into a phase.
    pub fn new(
        rate: u32,
        channels: usize,
        settings: Settings,
        first_sample: u64,
    ) -> Result<Self, Error> {
        Self::with_clock(rate, channels, settings, first_sample, 0)
    }

    /// A manager carries the last generation across stream/device recreation.
    /// Neither a new stream nor a new Start may reuse an output identity.
    pub fn with_clock(
        rate: u32,
        channels: usize,
        settings: Settings,
        first_sample: u64,
        previous_generation: u64,
    ) -> Result<Self, Error> {
        settings.validate(rate, channels)?;
        Ok(Self {
            status: Status {
                state: State::Stopped,
                nominal_sample_rate: rate,
                output_channels: channels,
                output_generation: previous_generation,
                revision: 0,
                applied_sample: first_sample,
                carrier_phase_cycles: [0.0; SIGNALS],
                transition_end: [first_sample; SIGNALS],
                next_sample: first_sample,
                stop_sample: None,
                stopped_at: Some(first_sample),
                settings,
            },
            oscillators: std::array::from_fn(|i| Oscillator {
                carrier: 0.0,
                compensation: 0.0,
                amplitude: Ramp::constant(0.0, first_sample),
                phase: Ramp::constant(
                    settings
                        .signals
                        .get(i)
                        .map_or(0.0, |s| s.phase_degrees / 360.0),
                    first_sample,
                ),
                noise: settings.signals.get(i).map_or(1, |s| s.noise_seed),
            }),
        })
    }

    pub fn status(&self) -> Status {
        self.status
    }

    fn length(&self) -> u64 {
        (self.status.nominal_sample_rate as f64 * TRANSITION_SECONDS).ceil() as u64
    }

    fn check_revision(&self, settings: Settings, revision: u64) -> Result<(), Error> {
        settings.validate(self.status.nominal_sample_rate, self.status.output_channels)?;
        if revision <= self.status.revision {
            return Err(Error::Revision);
        }
        match self.status.state {
            State::Error(e) => Err(e),
            State::Stopping => Err(Error::Stopping),
            _ => Ok(()),
        }
    }

    /// An invalid snapshot leaves all applied values and ramps unchanged.
    /// Routing can only change while Stopped; the stream topology is immutable.
    pub fn configure(&mut self, settings: Settings, revision: u64) -> Result<(), Error> {
        self.configure_impl(settings, revision, false)
    }

    /// One atomic settings snapshot and alignment at the same frame boundary.
    pub fn configure_and_align(&mut self, settings: Settings, revision: u64) -> Result<(), Error> {
        self.configure_impl(settings, revision, true)
    }

    fn configure_impl(
        &mut self,
        settings: Settings,
        revision: u64,
        align: bool,
    ) -> Result<(), Error> {
        self.check_revision(settings, revision)?;
        let n = self.status.next_sample;
        let rate = self.status.nominal_sample_rate;
        if self.status.state != State::Stopped
            && (settings.signals.len() != self.status.settings.signals.len()
                || settings
                    .signals
                    .iter()
                    .zip(&self.status.settings.signals)
                    .any(|(s, old)| {
                        s.id != old.id
                            || s.output_channel != old.output_channel
                            || s.waveform != old.waveform
                            || s.noise_seed != old.noise_seed
                    }))
        {
            return Err(Error::RoutingWhileActive);
        }
        let mut next = self.oscillators;
        for (i, (o, &s)) in next.iter_mut().zip(settings.signals.iter()).enumerate() {
            let old = self
                .status
                .settings
                .signals
                .get(i)
                .copied()
                .unwrap_or_default();
            if self.status.state == State::Stopped {
                o.phase = Ramp::constant(s.phase_degrees / 360.0, n);
            } else {
                let target = if s.enabled { s.amplitude_peak() } else { 0.0 };
                if target != o.amplitude.to {
                    o.amplitude = Ramp::new(o.amplitude.at(n), target, n, self.length())?;
                }
                if align {
                    o.phase = phase_ramp(
                        o.carrier + o.phase.at(n),
                        s.phase_degrees / 360.0,
                        s.frequency_hz,
                        rate,
                        n,
                        self.length(),
                    )?;
                } else if s.phase_degrees != old.phase_degrees {
                    o.phase = phase_ramp(
                        o.phase.at(n),
                        s.phase_degrees / 360.0,
                        s.frequency_hz,
                        rate,
                        n,
                        self.length(),
                    )?;
                } else if s.frequency_hz != old.frequency_hz && n < o.phase.end {
                    o.phase = phase_ramp(
                        o.phase.at(n),
                        s.phase_degrees / 360.0,
                        s.frequency_hz,
                        rate,
                        n,
                        o.phase.end - n,
                    )?;
                }
            }
            if align {
                o.carrier = 0.0;
                o.compensation = 0.0;
            }
        }
        self.oscillators = next;
        self.applied(settings, revision);
        Ok(())
    }

    /// Explicit Start resets all carriers at the same integer boundary and
    /// increments the output generation without rewinding the sample clock.
    pub fn start(&mut self, settings: Settings, revision: u64) -> Result<(), Error> {
        self.check_revision(settings, revision)?;
        if self.status.state != State::Stopped {
            return Err(Error::AlreadyActive);
        }
        if !settings.signals.iter().any(|s| s.enabled) {
            return Err(Error::NoEnabledSignals);
        }
        let n = self.status.next_sample;
        let generation = self
            .status
            .output_generation
            .checked_add(1)
            .ok_or(Error::CounterExhausted)?;
        let mut next = self.oscillators;
        for (o, s) in next.iter_mut().zip(&settings.signals) {
            *o = Oscillator {
                carrier: 0.0,
                compensation: 0.0,
                amplitude: Ramp::new(
                    0.0,
                    if s.enabled { s.amplitude_peak() } else { 0.0 },
                    n,
                    self.length(),
                )?,
                phase: Ramp::constant(s.phase_degrees / 360.0, n),
                noise: s.noise_seed,
            };
        }
        self.oscillators = next;
        self.status.output_generation = generation;
        self.status.state = State::Starting;
        self.status.stop_sample = None;
        self.status.stopped_at = None;
        self.applied(settings, revision);
        Ok(())
    }

    /// Align the carrier histories smoothly. The configured phase offsets
    /// remain intact; different frequencies will subsequently diverge again.
    pub fn align_phases(&mut self, revision: u64) -> Result<(), Error> {
        self.configure_and_align(self.status.settings, revision)
    }

    /// Repeated Stop never restarts a fade. Render through the terminal zero
    /// frame before releasing a device; an absent callback needs a manager timeout.
    pub fn stop(&mut self) -> Result<(), Error> {
        match self.status.state {
            State::Stopped | State::Stopping => return Ok(()),
            State::Error(e) => return Err(e),
            _ => {}
        }
        let n = self.status.next_sample;
        let mut next = self.oscillators;
        for o in &mut next {
            o.amplitude = Ramp::new(o.amplitude.at(n), 0.0, n, self.length())?;
            o.phase = Ramp::constant(o.phase.at(n), n);
        }
        self.oscillators = next;
        self.status.stop_sample = Some(n);
        self.status.state = State::Stopping;
        self.update_endpoints();
        Ok(())
    }

    fn applied(&mut self, settings: Settings, revision: u64) {
        self.status.settings = settings;
        self.status.revision = revision;
        self.status.applied_sample = self.status.next_sample;
        self.status.carrier_phase_cycles = self.oscillators.map(|o| o.carrier);
        self.update_endpoints();
    }

    fn update_endpoints(&mut self) {
        self.status.transition_end = self.oscillators.map(|o| o.amplitude.end.max(o.phase.end));
    }

    /// Latch a callback error. Recovery requires a newly constructed output
    /// engine; restoring settings or sending another Start cannot clear it.
    pub fn fail(&mut self, error: Error) {
        self.status.state = State::Error(error);
        for o in &mut self.oscillators {
            o.amplitude = Ramp::constant(0.0, self.status.next_sample);
        }
    }

    /// Exactly one clock tick, including OFF/silent channels. The callback must
    /// fill its remaining PCM buffer with the format's silence on Err.
    pub fn next_frame(&mut self) -> Result<Frame, Error> {
        if let State::Error(e) = self.status.state {
            return Err(e);
        }
        let n = self.status.next_sample;
        let Some(end) = n.checked_add(1) else {
            self.fail(Error::CounterExhausted);
            return Err(Error::CounterExhausted);
        };
        let mut frame = Frame {
            sequence: n,
            samples: [0.0; crate::signal::MAX_CHANNELS],
        };
        for (o, s) in self
            .oscillators
            .iter_mut()
            .zip(&self.status.settings.signals)
        {
            let amplitude = o.amplitude.at(n);
            let rate = self.status.nominal_sample_rate;
            let hz = s.frequency_hz;
            // Noise advances while OFF too; every explicit Start replays the seed.
            let value = if s.waveform == Waveform::Noise {
                waveform::noise(&mut o.noise)
            } else if amplitude != 0.0 {
                s.waveform.periodic(o.carrier + o.phase.at(n), hz, rate)
            } else {
                0.0
            };
            if amplitude != 0.0
                && let Some(ch) = s.output_channel
            {
                frame.samples[ch] = amplitude * value;
            }
            o.advance(hz / rate as f64);
        }
        if frame.samples.iter().any(|x| !x.is_finite()) {
            self.fail(Error::NonFiniteOutput);
            return Err(Error::NonFiniteOutput);
        }
        if frame.samples.iter().any(|x| x.abs() > 1.0) {
            self.fail(Error::OutputRange);
            return Err(Error::OutputRange);
        }
        if self.oscillators.iter().all(|o| n >= o.amplitude.end) {
            match self.status.state {
                State::Starting => self.status.state = State::Running,
                State::Stopping => {
                    self.status.state = State::Stopped;
                    self.status.stopped_at = Some(end);
                }
                _ => {}
            }
        }
        self.status.next_sample = end;
        Ok(frame)
    }
}
