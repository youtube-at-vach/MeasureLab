//! Bounded observations of actual execution reports on the output clock.
//! This journal is serviced by the manager, never by a callback or the UI.
//! Host observation times are not DAC/ADC timestamps or a sample alignment.
use super::{CONDITION_CAPACITY, Saved, Target};
use crate::generator::{Error, State, Status};
use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex};
use std::time::Instant;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ClockRelationship {
    IndependentUncalibrated,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Observation {
    /// Monotonic microseconds from creation of the output manager.
    pub observed_host_micros: u64,
    pub target: Target,
    pub status: Status,
    pub control_or_output_error: Option<Error>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExternalOutput {
    pub input_generation: u64,
    pub clock_relationship: ClockRelationship,
    pub observation_start_host_micros: u64,
    pub observation_end_host_micros: u64,
    /// Last manager observation at input start; it may already be stale.
    pub initial: Option<Observation>,
    /// Changes observed during this input session, at most 128.
    pub changes: Vec<Observation>,
    /// Last available observation at hold, not a completed output barrier.
    pub latest: Option<Observation>,
    pub evicted_changes: u64,
    pub lost_reports_since_output_worker_start: u64,
    pub notifications_since_output_worker_start: u64,
}

impl ExternalOutput {
    pub fn validate(&self, input_generation: u64) -> Result<(), String> {
        if self.input_generation != input_generation
            || self.observation_start_host_micros > self.observation_end_host_micros
            || self.changes.len() > CONDITION_CAPACITY
            || self
                .initial
                .as_ref()
                .is_some_and(|o| o.observed_host_micros > self.observation_start_host_micros)
            || (self.evicted_changes == 0
                && !self
                    .observations()
                    .any(|o| matches!(o.target, Target::Audio { .. })))
        {
            return Err("Invalid external output observation session".into());
        }
        let mut previous = self.observation_start_host_micros;
        for change in &self.changes {
            if change.observed_host_micros < previous {
                return Err("Unordered external output observations".into());
            }
            previous = change.observed_host_micros;
        }
        if self.latest.as_ref().is_some_and(|o| {
            o.observed_host_micros < self.initial.as_ref().map_or(0, |i| i.observed_host_micros)
                || self
                    .changes
                    .last()
                    .is_some_and(|c| o.observed_host_micros < c.observed_host_micros)
        }) {
            return Err("External output endpoint precedes its observations".into());
        }
        for observation in self.observations() {
            let s = observation.status;
            Saved {
                target: observation.target.clone(),
                nominal_sample_rate: s.nominal_sample_rate,
                signals: s.settings,
                use_as_input: false,
            }
            .validate()?;
            if observation.observed_host_micros > self.observation_end_host_micros
                || s.output_channels != observation.target.channels()
                || s.applied_sample > s.next_sample
                || s.stop_sample.is_some_and(|n| n > s.next_sample)
                || s.stopped_at.is_some_and(|n| n > s.next_sample)
                || matches!(s.state, State::Starting | State::Running | State::Stopping)
                    && s.output_generation == 0
                || s.carrier_phase_cycles.iter().any(|p| !p.is_finite() || !(0.0..1.0).contains(p))
                || [observation.control_or_output_error, match s.state { State::Error(e) => Some(e), _ => None }]
                    .into_iter().flatten().any(|e| matches!(e, Error::Frequency(i) | Error::Amplitude(i) | Error::Phase(i) | Error::Routing(i) | Error::Waveform(i) if i >= crate::generator::SIGNALS))
            {
                return Err("Invalid external output execution observation".into());
            }
        }
        Ok(())
    }

    fn observations(&self) -> impl Iterator<Item = &Observation> {
        self.initial
            .iter()
            .chain(&self.changes)
            .chain(self.latest.iter())
    }
}

#[derive(Default)]
struct Journal {
    latest: Option<Observation>,
    changes: Vec<(u64, Observation)>,
    change_count: u64,
    lost_reports: u64,
    notifications: u64,
    audio_changes: u64,
}

#[derive(Clone)]
pub struct Handle {
    origin: Instant,
    journal: Arc<Mutex<Journal>>,
}
impl Default for Handle {
    fn default() -> Self {
        Self {
            origin: Instant::now(),
            journal: Arc::new(Mutex::new(Journal::default())),
        }
    }
}
impl Handle {
    fn now(&self) -> u64 {
        self.origin.elapsed().as_micros().min(u64::MAX as u128) as u64
    }

    pub(super) fn record(&self, target: &Target, status: Status, error: Option<Error>) {
        let mut journal = self.journal.lock().unwrap();
        let observation = Observation {
            observed_host_micros: self.now(),
            target: target.clone(),
            status,
            control_or_output_error: error,
        };
        // next_sample advances in every report; keep its latest value without
        // using identical settings to infer an unobserved output interval.
        let changed = journal.latest.as_ref().is_none_or(|old| {
            let mut previous = old.status;
            previous.next_sample = status.next_sample;
            old.target != observation.target
                || previous != status
                || old.status.transitioning() != status.transitioning()
                || old.control_or_output_error != error
        });
        if changed {
            journal.change_count += 1;
            if matches!(target, Target::Audio { .. }) {
                journal.audio_changes += 1;
            }
            let sequence = journal.change_count;
            if journal.changes.len() == CONDITION_CAPACITY {
                journal.changes.remove(0);
            }
            journal.changes.push((sequence, observation.clone()));
        }
        journal.latest = Some(observation);
    }

    pub(super) fn losses(&self, reports: u64, notifications: u64) {
        let mut journal = self.journal.lock().unwrap();
        journal.lost_reports = journal.lost_reports.saturating_add(reports);
        journal.notifications = journal.notifications.saturating_add(notifications);
    }

    pub fn begin(&self, input_generation: u64) -> Session {
        let journal = self.journal.lock().unwrap();
        Session {
            handle: self.clone(),
            input_generation,
            started: self.now(),
            initial: journal.latest.clone(),
            first_change: journal.change_count,
            first_audio_change: journal.audio_changes,
        }
    }
}

pub struct Session {
    handle: Handle,
    input_generation: u64,
    started: u64,
    initial: Option<Observation>,
    first_change: u64,
    first_audio_change: u64,
}
impl Session {
    /// Called once by the measurement worker at finite Stop/Single/failure.
    /// Later output edits, reset or shutdown cannot change the held evidence.
    pub fn finish(self) -> Option<ExternalOutput> {
        let journal = self.handle.journal.lock().unwrap();
        let changes: Vec<_> = journal
            .changes
            .iter()
            .filter(|(n, _)| *n > self.first_change)
            .map(|(_, o)| o.clone())
            .collect();
        let result = ExternalOutput {
            input_generation: self.input_generation,
            clock_relationship: ClockRelationship::IndependentUncalibrated,
            observation_start_host_micros: self.started,
            observation_end_host_micros: self.handle.now(),
            evicted_changes: journal
                .change_count
                .saturating_sub(self.first_change)
                .saturating_sub(changes.len() as u64),
            initial: self.initial,
            changes,
            latest: journal.latest.clone(),
            lost_reports_since_output_worker_start: journal.lost_reports,
            notifications_since_output_worker_start: journal.notifications,
        };
        let has_audio = journal.audio_changes > self.first_audio_change
            || result
                .observations()
                .any(|o| matches!(o.target, Target::Audio { .. }));
        has_audio.then_some(result)
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use crate::generator::{Engine, Settings};

    pub(crate) fn fixture_handle() -> Handle {
        let handle = Handle::default();
        let target = Target::Audio {
            device_id: "test:output".into(),
            device_name: "Output".into(),
            channels: 2,
            pcm: super::super::device::Pcm::F32,
        };
        let mut settings = Settings::default();
        settings.signals[0].enabled = true;
        let mut engine = Engine::new(96_000, 2, settings, 5_000_000).unwrap();
        handle.record(&target, engine.status(), None);
        engine.start(settings, 1).unwrap();
        handle.record(&target, engine.status(), None);
        for _ in 0..1_024 {
            engine.next_frame().unwrap();
        }
        handle.record(&target, engine.status(), None);
        handle
    }

    pub(crate) fn fixture(generation: u64) -> ExternalOutput {
        fixture_handle().begin(generation).finish().unwrap()
    }

    #[test]
    fn independent_clock_and_held_history_do_not_follow_later_edits_or_reset() {
        let evidence = fixture(7);
        evidence.validate(7).unwrap();
        assert_eq!(
            evidence.clock_relationship,
            ClockRelationship::IndependentUncalibrated
        );
        assert_eq!(
            evidence.latest.as_ref().unwrap().status.next_sample,
            5_001_024
        );
        let decoded: ExternalOutput =
            serde_json::from_slice(&serde_json::to_vec(&evidence).unwrap()).unwrap();
        assert_eq!(decoded, evidence);
        assert!(decoded.validate(8).is_err());
    }

    #[test]
    fn report_loss_notifications_and_history_eviction_survive_error_and_reset() {
        let handle = Handle::default();
        let target = fixture(1).latest.unwrap().target;
        let mut engine = Engine::new(48_000, 2, Settings::default(), 0).unwrap();
        handle.record(&target, engine.status(), None);
        let session = handle.begin(9);
        for rev in 1..=140 {
            engine.configure(Settings::default(), rev).unwrap();
            handle.record(&target, engine.status(), None);
        }
        engine.fail(Error::CallbackStalled);
        handle.record(&target, engine.status(), Some(Error::CallbackStalled));
        handle.losses(5, 2);
        let held = session.finish().unwrap();
        assert_eq!(held.changes.len(), CONDITION_CAPACITY);
        assert_eq!(held.evicted_changes, 13);
        assert_eq!(held.lost_reports_since_output_worker_start, 5);
        assert_eq!(held.notifications_since_output_worker_start, 2);
        assert_eq!(
            held.latest.as_ref().unwrap().status.state,
            State::Error(Error::CallbackStalled)
        );
        handle.record(
            &Target::Internal,
            Engine::new(48_000, 2, Settings::default(), 0)
                .unwrap()
                .status(),
            None,
        );
        assert_eq!(
            held.latest.as_ref().unwrap().status.state,
            State::Error(Error::CallbackStalled)
        );
        held.validate(9).unwrap();
    }

    #[test]
    fn stale_initial_observation_is_not_fabricated_as_a_new_report() {
        let handle = Handle::default();
        let target = fixture(1).latest.unwrap().target;
        let status = Engine::new(48_000, 2, Settings::default(), 0)
            .unwrap()
            .status();
        handle.record(&target, status, None);
        let evidence = handle.begin(1).finish().unwrap();
        assert_eq!(evidence.initial, evidence.latest);
        assert!(evidence.changes.is_empty());
        evidence.validate(1).unwrap();
        assert!(Handle::default().begin(1).finish().is_none());
    }

    #[test]
    fn evicting_all_audio_entries_keeps_unknown_external_excitation() {
        let handle = Handle::default();
        let audio = fixture(1).latest.unwrap().target;
        let mut engine = Engine::new(48_000, 2, Settings::default(), 0).unwrap();
        handle.record(&Target::Internal, engine.status(), None);
        let session = handle.begin(1);
        handle.record(&audio, engine.status(), None);
        for rev in 1..=140 {
            engine.configure(Settings::default(), rev).unwrap();
            handle.record(&Target::Internal, engine.status(), None);
        }
        let result = session.finish().unwrap();
        assert_eq!(result.evicted_changes, 13);
        assert!(result.observations().all(|o| o.target == Target::Internal));
        result.validate(1).unwrap();
    }
}
