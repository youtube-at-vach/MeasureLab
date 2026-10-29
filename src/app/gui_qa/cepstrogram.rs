//! Actual egui mode selection, stopped reservation, typed cursors and layout.
use super::*;
impl ScopeApp {
    pub(in crate::app) fn check_cepstrogram_interactions(&mut self) -> Result<(), String> {
        let saved_presentation = self.presentation.clone();
        let saved_mode = self.spectrogram_mode;
        let saved_settings = self.spectrogram_settings;
        let saved_demo = self.demo_running;
        let saved_snapshot = self.spectrogram_snapshot.clone();
        let saved_history = std::mem::replace(
            &mut self.spectrogram_history,
            Arc::new(Mutex::new(spectrogram::History::default())),
        );
        let saved_last = self.last_stft;
        let saved_hold = self.spectrogram_hold.take();
        let saved_hold_anchor = self.spectrogram_hold_anchor;
        let saved_anchor = self.spectrogram_anchor;
        let saved_selected = std::mem::take(&mut self.spectrogram_selected);
        let saved_auto = self.spectrogram_auto_result;
        let saved_scroll = std::mem::take(&mut self.spectrogram_scroll);
        let saved_generation = self.stft_generation;
        let saved_applied = self.stft_applied;
        let saved_cursors = std::mem::take(&mut self.cursors);
        let mut driver = Driver::new();
        driver.size = vec2(1440.0, 1800.0);
        self.stft_history.freeze();
        self.presentation.screen = Screen::Single(Instrument::Spectrogram);
        self.presentation.details_visible = true;
        self.shell.io = None;
        self.demo_running = false;
        self.spectrogram_mode = stft::Analysis::Spectrogram;
        self.spectrogram_settings.precision = Precision::F32;
        let spectral = self.stft_config();
        let snapshot = spectrogram::history::fixture(
            self.input_generation,
            self.stft_generation,
            spectral,
            [(
                RowInfo {
                    generation: self.stft_generation,
                    config: spectral,
                    start: 0,
                    end: spectral.size as u64,
                    gap: Default::default(),
                    cepstrum: None,
                },
                vec![0.25; spectral.size / 2 + 1],
            )],
        );
        self.spectrogram_snapshot = snapshot.clone();
        let previous = self.stft_history.replace_frozen_snapshot(snapshot);
        driver.frame(self, vec![]);
        let mode_rect = driver
            .ctx
            .data(|data| data.get_temp::<egui::Rect>(egui::Id::unique("qa_stft_mode")))
            .ok_or("Mode control not rendered")?;
        driver.click_at(self, mode_rect.center());
        driver.click(self, i18n::text("spectrogram.cepstrogram"))?;
        assert_eq!(self.spectrogram_mode, stft::Analysis::Cepstrogram);
        assert!(
            !self.cepstrogram_applied(),
            "stopped reservation relabeled captured spectrum"
        );
        assert_eq!(self.spectrogram_settings.precision, Precision::F32);
        assert_eq!(self.stft_config().precision, Precision::F64);
        // Apply through the running widget path. Old frequency and Scope time
        // remain independent; time from this history and quefrency must clear.
        self.spectrogram_mode = stft::Analysis::Spectrogram;
        self.demo_running = true;
        self.cursors.set_scope_time(0, 0.25);
        self.cursors.set_spectrogram_sample(1, 1000);
        self.cursors.set_frequency(0, 1234.0);
        self.cursors.quefrency_seconds[0] = Some(0.001);
        driver.frame(self, vec![]);
        let mode_rect = driver
            .ctx
            .data(|data| data.get_temp::<egui::Rect>(egui::Id::unique("qa_stft_mode")))
            .unwrap();
        driver.click_at(self, mode_rect.center());
        driver.click(self, i18n::text("spectrogram.cepstrogram"))?;
        assert!(self.cepstrogram_applied());
        assert_eq!(self.cursors.times[0].unwrap().scope_x(), Some(0.25));
        assert!(self.cursors.times[1].is_none());
        assert_eq!(self.cursors.frequency_hz, Some(1234.0));
        assert!(self.cursors.quefrency_seconds.iter().all(Option::is_none));
        self.demo_running = false;
        let c = self.stft_config();
        let mut coefficients = vec![0.01; c.size / 2 + 1];
        coefficients[13] = -0.4;
        self.spectrogram_snapshot = spectrogram::history::fixture(
            self.input_generation,
            self.stft_generation,
            c,
            [(
                RowInfo {
                    generation: self.stft_generation,
                    config: c,
                    start: 0,
                    end: c.size as u64,
                    gap: Default::default(),
                    cepstrum: Some(crate::cepstrum::Info {
                        algorithm: crate::cepstrum::ALGORITHM,
                        status: crate::cepstrum::Status::Valid,
                        floored_bins: 2,
                    }),
                },
                coefficients,
            )],
        );
        self.stft_history.freeze();
        self.stft_history
            .replace_frozen_snapshot(self.spectrogram_snapshot.clone());
        self.spectrogram_anchor = c.size as u64;
        self.cursors.clear();
        self.hold_spectrogram();
        self.select_spectrogram_sample(0, c.size as u64 - 1);
        self.cursors.quefrency_seconds[0] = Some(13.0 / c.sample_rate as f64);
        self.cursors.set_frequency(0, 1234.0);
        self.link_spectrum_history();
        assert!(!self.spectrum_history.linked);
        self.navigate(Action::OpenSingle(Instrument::Spectrogram));
        self.navigate(Action::PairWith(Instrument::Spectrum));
        assert!(!self.spectrum_history.linked);
        self.presentation.screen = Screen::Single(Instrument::Spectrogram);
        for size in [vec2(1440.0, 1000.0), vec2(760.0, 850.0)] {
            driver.size = size;
            self.shell.narrow_details = false;
            driver.frame(self, vec![]);
            driver.visible_text_rect(i18n::text("spectrogram.quefrency_ms"))?;
            driver.visible_text_rect(i18n::text("spectrogram.cepstrogram"))?;
            assert_eq!(self.cursors.frequency_hz, Some(1234.0));
        }
        self.spectrogram_mode = stft::Analysis::Spectrogram;
        assert!(
            self.cepstrogram_applied(),
            "stopped reservation relabeled cepstrum"
        );
        self.cursors.clear();
        assert_eq!(self.cursors.quefrency_seconds, [None; 2]);
        self.clear_spectrogram_view();
        self.stft_history.replace_frozen_snapshot(previous);
        self.spectrogram_snapshot = saved_snapshot;
        self.spectrogram_history = saved_history;
        self.last_stft = saved_last;
        self.spectrogram_hold = saved_hold;
        self.spectrogram_hold_anchor = saved_hold_anchor;
        self.spectrogram_anchor = saved_anchor;
        self.spectrogram_selected = saved_selected;
        self.spectrogram_auto_result = saved_auto;
        self.spectrogram_scroll = saved_scroll;
        self.stft_generation = saved_generation;
        self.stft_applied = saved_applied;
        self.spectrogram_mode = saved_mode;
        self.spectrogram_settings = saved_settings;
        self.demo_running = saved_demo;
        self.cursors = saved_cursors;
        self.presentation = saved_presentation;
        println!(
            "Cepstrogram GUI QA OK: real mode widgets, stopped reservation, fixed f64, independent cursors, Spectrum guards, wide/compact layouts"
        );
        Ok(())
    }
}
