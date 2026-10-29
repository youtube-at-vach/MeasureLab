//! Presentation time advances independently of STFT and raster delivery.
use crate::stft::Config;
use std::time::Instant;

/// Keep the incomplete hop and ordinary analysis/raster delivery jitter above
/// the visible edge. The raster retains this same amount of older history.
pub(super) fn live_delay_samples(config: Config) -> u64 {
    config.hop as u64 + config.sample_rate.div_ceil(4) as u64
}

#[derive(Default)]
pub struct ScrollClock {
    origin: Option<(u64, Config, Instant)>,
}

impl ScrollClock {
    pub fn reset(&mut self) {
        self.origin = None;
    }

    /// Advance behind the input clock so complete rows enter from above the
    /// plot. Long delivery stalls still leave unavailable time blank; numerical
    /// reads always require an original, complete STFT frame.
    pub fn anchor(
        &mut self,
        end: u64,
        config: Config,
        observed_at: Instant,
        now: Instant,
        live: bool,
    ) -> u64 {
        if !live {
            self.reset();
            return end;
        }
        let (origin, captured, started) = *self.origin.get_or_insert((end, config, observed_at));
        if captured != config {
            self.origin = None;
            return self.anchor(end, config, observed_at, now, live);
        }
        // Convert only the elapsed interval, preserving integer coordinates
        // even after the input sample counter has passed 2^53.
        origin
            .saturating_add(
                (now.saturating_duration_since(started).as_secs_f64() * config.sample_rate as f64)
                    .round() as u64,
            )
            .saturating_sub(live_delay_samples(config))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    fn config() -> Config {
        Config {
            analysis: crate::stft::Analysis::Spectrogram,
            log_floor_db: crate::cepstrum::DEFAULT_LOG_FLOOR_DB,
            sample_rate: 48000,
            channels: 2,
            channel: 0,
            size: 8192,
            hop: 2048,
            window: crate::spectrum::Window::Hann,
            remove_dc: true,
            precision: crate::spectrum::Precision::F64,
        }
    }

    #[test]
    fn uneven_frames_and_batched_rasters_do_not_change_scroll_speed() {
        let mut clock = ScrollClock::default();
        let now = Instant::now();
        let origin = (1_u64 << 54) + 123;
        // Irregular rendering below 60 FPS, with image deliveries at ~20 Hz
        // and an extended delivery pause. Every position follows elapsed time.
        for ms in [0, 33, 75, 116, 180, 224, 300, 550, 900] {
            let delivered = origin + (ms / 50 * 50).min(200) * 48;
            assert_eq!(
                clock.anchor(
                    delivered,
                    config(),
                    now,
                    now + Duration::from_millis(ms),
                    true
                ),
                origin + ms * 48 - live_delay_samples(config()),
            );
        }
    }

    #[test]
    fn hold_stop_restart_and_rate_changes_reset_the_presentation_origin() {
        let mut clock = ScrollClock::default();
        let now = Instant::now();
        let config = config();
        let delay = live_delay_samples(config);
        assert_eq!(clock.anchor(48000, config, now, now, true), 48000 - delay);
        let later = now + Duration::from_secs(1);
        assert_eq!(clock.anchor(72000, config, later, later, false), 72000);
        assert_eq!(
            clock.anchor(100000, config, later, later, true),
            100000 - delay
        );
        clock.reset();
        assert_eq!(
            clock.anchor(20000, config, later, later, true),
            20000 - delay
        );
        let changed = Config {
            sample_rate: 96000,
            ..config
        };
        assert_eq!(
            clock.anchor(96000, changed, later, later, true),
            96000 - live_delay_samples(changed)
        );
        let changed = Config {
            hop: 1024,
            ..changed
        };
        assert_eq!(
            clock.anchor(97024, changed, later, later, true),
            97024 - live_delay_samples(changed)
        );
    }

    #[test]
    fn initial_raster_latency_is_included_in_presentation_time() {
        let mut clock = ScrollClock::default();
        let observed = Instant::now();
        let received = observed + Duration::from_millis(175);
        assert_eq!(
            clock.anchor(48000, config(), observed, received, true),
            56400 - live_delay_samples(config())
        );
    }

    #[test]
    fn startup_waits_for_buffered_history_without_wrapping_sample_time() {
        let mut clock = ScrollClock::default();
        let now = Instant::now();
        assert_eq!(clock.anchor(8192, config(), now, now, true), 0);
        let later = now + Duration::from_millis(200);
        assert_eq!(
            clock.anchor(16384, config(), later, later, true),
            8192 + 9600 - live_delay_samples(config())
        );
        assert_eq!(clock.anchor(8192, config(), later, later, false), 8192);
    }
}
