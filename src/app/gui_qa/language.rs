//! I5: real menu events during live/held measurements, with warm frame timings.
use super::*;

impl ScopeApp {
    pub(super) fn check_language_interactions(
        &mut self,
        driver: &mut Driver,
    ) -> Result<(), String> {
        let selected = i18n::locale();
        let screen = self.presentation.screen;
        let generation = self.input_generation;
        let running = self.running();
        let command = self.generator.command_marker();
        let conditions = self.core_config();
        let held = (!running)
            .then(|| self.capture_scope_results().ok())
            .flatten();
        let progress = running.then(|| {
            let core = self.core.as_ref().unwrap();
            (
                core.metrics.input_frames.load(Ordering::Relaxed),
                core.spectrum.metrics.windows.load(Ordering::Relaxed),
            )
        });
        i18n::initialize(&driver.ctx, None);
        for (width, zoom, native) in [(1440.0, 1.0, 1.0), (900.0, 1.25, 2.0)] {
            driver.resize(self, vec2(width, 1000.0), zoom, native);
            let mut english_p95 = None;
            for locale in i18n::Locale::ALL {
                let switching = Instant::now();
                if width < 1180.0 {
                    driver.click(self, i18n::text("shell.menu"))?;
                }
                driver.click(self, i18n::text("shell.view"))?;
                driver.click(self, i18n::text("shell.language"))?;
                driver.visible_text_rect(locale.native_name())?;
                driver.click(self, locale.native_name())?;
                let switch_ms = switching.elapsed().as_secs_f64() * 1000.0;
                assert_eq!(i18n::locale(), locale);
                assert_eq!(self.presentation.screen, screen);
                assert_eq!(self.input_generation, generation);
                assert_eq!(self.running(), running);
                assert_eq!(self.generator.command_marker(), command);
                let after = self.core_config();
                assert_eq!(after.scope, conditions.scope);
                assert_eq!(after.spectrum, conditions.spectrum);
                assert_eq!(after.lockin, conditions.lockin);
                assert_eq!(after.comparison, conditions.comparison);
                assert_eq!(after.calibrations, conditions.calibrations);
                assert!(!egui::Popup::is_any_open(&driver.ctx));
                driver.visible_text_rect(i18n::text("generator.stop_output_2"))?;
                let input_action = if self.running() {
                    i18n::text("io.stop_input")
                } else if self.source.is_demo() {
                    i18n::text("io.start_input_demo")
                } else {
                    i18n::text("io.start_input")
                };
                driver.visible_text_rect(input_action)?;
                // Warm glyph/layout caches before comparing ordinary frame CPU time.
                for _ in 0..2 {
                    driver.frame(self, vec![]);
                }
                let mut frames = Vec::with_capacity(20);
                for _ in 0..20 {
                    let start = Instant::now();
                    driver.frame(self, vec![]);
                    frames.push(start.elapsed().as_secs_f64() * 1000.0);
                }
                frames.sort_by(f64::total_cmp);
                let p95 = frames[18];
                let baseline = *english_p95.get_or_insert(p95);
                // Broad release-QA regression guard, not a display/scanout SLA.
                assert!(
                    p95 <= baseline * 5.0 + 20.0,
                    "locale frame regression: {locale:?}: {p95} ms vs English {baseline} ms"
                );
                println!(
                    "Language frame CPU: running={running}, width={width}, locale={}, p95_ms={p95:.3}, english_p95_ms={baseline:.3}, menu_switch_ms={switch_ms:.3}",
                    locale.id()
                );
                if running {
                    self.poll_measurement();
                    self.generator.poll();
                }
                if let Some(held) = &held {
                    let after = self.capture_scope_results()?;
                    assert_eq!(after.input, held.input);
                    assert_eq!(after.scope, held.scope);
                    assert_eq!(after.loss, held.loss);
                }
            }
        }
        if let Some((frames, windows)) = progress {
            let core = self.core.as_ref().unwrap();
            assert!(core.metrics.input_frames.load(Ordering::Relaxed) > frames);
            assert!(core.spectrum.metrics.windows.load(Ordering::Relaxed) > windows);
        }
        i18n::set_locale(&driver.ctx, selected.id());
        driver.resize(self, vec2(1440.0, 1000.0), 1.0, 1.0);
        println!(
            "Language UI OK: nine locales, English fallback, wide/narrow/zoom/native scale; selection, measurement conditions, held samples, input generation and output commands unchanged; running={running}"
        );
        Ok(())
    }
}
