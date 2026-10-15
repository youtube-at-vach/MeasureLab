//! Spectrogram display controls are independent of analysis configuration.
use super::*;
use spectrogram::{ColorRange, FrequencyRange};

pub(super) const GESTURES: &str = "Spectrogram: wheel to zoom frequency; drag to pan frequency/time; Shift+wheel or wheel on time axis to scroll history; click to Hold and select a frame; drag a cursor line to move it; Live releases history; double-click resets frequency/time position.";

pub(super) struct PendingClick {
    pub snapshot: Arc<spectrogram::history::Snapshot>,
    pub anchor: u64,
    pub sample: Option<u64>,
    pub frequency: f64,
    pub index: usize,
    pub time: f64,
}

impl ScopeApp {
    pub(super) fn spectrogram_controls(&mut self, ui: &mut egui::Ui) {
        egui::CollapsingHeader::new("Display")
            .default_open(true)
            .show(ui, |ui| self.spectrogram_display_controls(ui));
        egui::CollapsingHeader::new("Analysis")
            .default_open(true)
            .show(ui, |ui| self.spectrogram_analysis_controls(ui));
    }

    fn spectrogram_display_controls(&mut self, ui: &mut egui::Ui) {
        setting_label(ui, "COLOR MAP");
        egui::ComboBox::from_id_salt("spectrogram_color_map")
            .width(ui.available_width())
            .selected_text(self.spectrogram_color_map.name())
            .show_ui(ui, |ui| {
                for map in spectrogram::ColorMap::ALL {
                    ui.selectable_value(&mut self.spectrogram_color_map, map, map.name());
                }
            });
        setting_label(ui, "COLOR RANGE · dBFS");
        if ui
            .checkbox(&mut self.spectrogram_auto_color, "Auto color range")
            .changed()
        {
            self.spectrogram_auto_result = ColorRange::default();
        }
        let before = (self.spectrogram_floor, self.spectrogram_ceiling);
        let mut changed = false;
        ui.horizontal(|ui| {
            ui.label("Min");
            changed |= ui
                .add(egui::DragValue::new(&mut self.spectrogram_floor).speed(0.5))
                .changed();
            ui.label("Max");
            changed |= ui
                .add(egui::DragValue::new(&mut self.spectrogram_ceiling).speed(0.5))
                .changed();
        });
        if changed {
            if ColorRange::new(self.spectrogram_floor, self.spectrogram_ceiling).is_some() {
                self.spectrogram_auto_color = false;
                self.spectrogram_color_error = false;
            } else {
                (self.spectrogram_floor, self.spectrogram_ceiling) = before;
                self.spectrogram_color_error = true;
            }
        }
        if self.spectrogram_color_error {
            ui.colored_label(
                YELLOW,
                "Min and Max must be finite, with Min < Max. Previous range retained.",
            );
        }
        setting_label(ui, "FREQUENCY SCALE");
        ui.horizontal(|ui| {
            if ui
                .selectable_value(&mut self.spectrogram_scale, FrequencyScale::Log, "Log Hz")
                .changed()
            {
                self.reset_spectrogram_frequency();
            }
            if ui
                .selectable_value(
                    &mut self.spectrogram_scale,
                    FrequencyScale::Linear,
                    "Linear Hz",
                )
                .changed()
            {
                self.reset_spectrogram_frequency();
            }
        });
        let axis = self.spectrogram_frequency_range();
        ui.horizontal(|ui| {
            ui.label("From");
            ui.add(
                egui::DragValue::new(&mut self.spectrogram_min_hz)
                    .range(0.0..=axis.max)
                    .suffix(" Hz"),
            );
        });
        let nyquist = self.spectrogram_sample_rate() as f64 * 0.5;
        ui.horizontal(|ui| {
            ui.label("To");
            ui.add(
                egui::DragValue::new(&mut self.spectrogram_max_hz)
                    .range(0.0..=nyquist)
                    .suffix(" Hz"),
            );
        });
        ui.label(
            RichText::new("To = 0 uses Nyquist. Log excludes DC.")
                .small()
                .color(MUTED),
        );
        setting_label(ui, "TIME RANGE");
        egui::ComboBox::from_id_salt("spectrogram_time")
            .width(ui.available_width())
            .selected_text(format!("{} s", self.spectrogram_seconds))
            .show_ui(ui, |ui| {
                for seconds in [5.0, 10.0, 30.0, 60.0] {
                    ui.selectable_value(
                        &mut self.spectrogram_seconds,
                        seconds,
                        format!("{seconds} s"),
                    );
                }
            });
        ui.label(RichText::new(GESTURES).small().color(MUTED));
    }

    fn spectrogram_sample_rate(&self) -> u32 {
        self.spectrogram_snapshot
            .config
            .or(self.stft_history.snapshot().config)
            .map_or(self.sample_rate, |c| c.sample_rate)
    }

    fn spectrogram_frequency_range(&self) -> FrequencyRange {
        let config = self
            .spectrogram_snapshot
            .config
            .or(self.stft_history.snapshot().config)
            .or(self.spectrogram_history.lock().unwrap().config());
        FrequencyRange::new(
            config.map_or(self.sample_rate, |c| c.sample_rate),
            config.map_or(self.spectrogram_settings.size, |c| c.size),
            self.spectrogram_scale,
            self.spectrogram_min_hz,
            self.spectrogram_max_hz,
        )
    }

    fn reset_spectrogram_frequency(&mut self) {
        self.spectrogram_min_hz = if self.spectrogram_scale == FrequencyScale::Log {
            20.0
        } else {
            0.0
        };
        self.spectrogram_max_hz = 0.0;
    }

    pub(super) fn spectrogram_view(&self) -> View {
        self.spectrogram_frequency_range().view(
            ColorRange::new(self.spectrogram_floor, self.spectrogram_ceiling).unwrap_or_default(),
        )
    }

    pub(super) fn spectrogram_display_view(&mut self, _ui: &egui::Ui) -> View {
        let mut view = self.spectrogram_view();
        if self.spectrogram_auto_color {
            view.floor_db = self.spectrogram_auto_result.min;
            view.ceiling_db = self.spectrogram_auto_result.max;
        }
        view
    }

    pub(super) fn clear_spectrogram_view(&mut self) {
        self.spectrogram_pending_click = None;
        self.spectrogram_view_worker.clear();
        self.spectrogram_snapshot = Arc::default();
        self.spectrogram_hold = None;
        self.spectrogram_hold_anchor = None;
        self.spectrogram_anchor = 0;
        self.spectrogram_selected = [None, None];
        self.spectrogram_unavailable_selection = [false; 2];
        self.spectrogram_auto_result = ColorRange::default();
        for time in &mut self.cursors.times {
            if time.is_some_and(|t| t.spectrogram_sample().is_some()) {
                *time = None;
            }
        }
    }

    pub(super) fn hold_spectrogram(&mut self) {
        if self.spectrogram_hold.is_none() && self.spectrogram_snapshot.latest().is_some() {
            self.spectrogram_hold = Some(self.spectrogram_snapshot.clone());
            self.spectrogram_hold_anchor = Some(self.spectrogram_anchor);
        }
    }

    pub(super) fn live_spectrogram(&mut self) {
        self.spectrogram_pending_click = None;
        self.spectrogram_hold = None;
        self.spectrogram_hold_anchor = None;
        self.spectrogram_selected = [None, None];
        self.spectrogram_unavailable_selection = [false; 2];
        for time in &mut self.cursors.times {
            if time.is_some_and(|t| t.spectrogram_sample().is_some()) {
                *time = None;
            }
        }
    }

    pub(super) fn receive_spectrogram_view(&mut self) {
        if let Some(prepared) = self.spectrogram_view_worker.take()
            && prepared.snapshot.generation == self.stft_generation
            && prepared.snapshot.input_generation == self.input_generation
        {
            self.spectrogram_prepared_id = prepared.id;
            self.spectrogram_snapshot = prepared.snapshot;
            self.spectrogram_anchor = prepared.anchor;
            self.spectrogram_auto_result = prepared.range;
            self.spectrogram_build_ms = prepared.processing_ms;
            self.last_stft = self.spectrogram_snapshot.latest().map(|f| f.info);
            self.spectrogram_history = Arc::new(Mutex::new(prepared.history));
        }
        for (i, selection) in self.spectrogram_selected.iter_mut().enumerate() {
            if self.cursors.times[i].is_some() {
                self.spectrogram_unavailable_selection[i] = false;
            }
            if self.cursors.times[i]
                .and_then(|t| t.spectrogram_sample())
                .is_none()
            {
                *selection = None;
            }
        }
    }

    pub(super) fn request_spectrogram_view(
        &mut self,
        rect: egui::Rect,
        pixels_per_point: f32,
    ) -> bool {
        let snapshot = self.spectrogram_hold.clone().unwrap_or_else(|| {
            let latest = self.stft_history.snapshot();
            if latest.latest().is_some() {
                latest
            } else {
                self.spectrogram_snapshot.clone()
            }
        });
        if snapshot.latest().is_none() {
            // Static QA fixtures have their own raw cache and no live collector.
            return !self.spectrogram_history.lock().unwrap().is_raster();
        }
        self.spectrogram_view_worker.submit(
            snapshot,
            spectrogram::viewport::Parameters {
                anchor: self.spectrogram_hold_anchor,
                seconds: self.spectrogram_seconds,
                view: self.spectrogram_view(),
                columns: (rect.width() * pixels_per_point).ceil().max(1.0) as usize,
                rows: (rect.height() * pixels_per_point).ceil().max(1.0) as usize,
                auto: self.spectrogram_auto_color,
                live: self.running() && self.spectrogram_hold.is_none(),
            },
        );
        self.receive_spectrogram_view();
        self.spectrogram_prepared_id == self.spectrogram_view_worker.current_id()
    }

    fn pan_spectrogram_time(&mut self, seconds: f64) {
        self.hold_spectrogram();
        let Some(snapshot) = &self.spectrogram_hold else {
            return;
        };
        let (Some(oldest), Some(latest)) = (snapshot.frames().next(), snapshot.latest()) else {
            return;
        };
        let delta = (seconds * latest.info.config.sample_rate as f64).round() as i128;
        let anchor = self.spectrogram_hold_anchor.unwrap_or(latest.info.end) as i128;
        self.spectrogram_hold_anchor =
            Some((anchor - delta).clamp(oldest.info.end as i128, latest.info.end as i128) as u64);
    }

    pub(super) fn select_spectrogram_time(&mut self, index: usize, fraction: f64) {
        self.hold_spectrogram();
        let Some(snapshot) = &self.spectrogram_hold else {
            return;
        };
        let Some(config) = snapshot.config else {
            return;
        };
        let anchor = self
            .spectrogram_hold_anchor
            .unwrap_or(self.spectrogram_anchor);
        if let Some(sample) = cursor::sample_at_age(
            anchor,
            fraction.clamp(0.0, 1.0) * self.spectrogram_seconds,
            config.sample_rate,
        ) {
            self.select_spectrogram_sample(index, sample);
        } else {
            self.spectrogram_unavailable_selection[index] = true;
            self.cursors.times[index] = None;
            self.spectrogram_selected[index] = None;
        }
    }

    pub(super) fn select_spectrogram_sample(&mut self, index: usize, sample: u64) {
        if let Some(snapshot) = &self.spectrogram_hold {
            self.spectrogram_unavailable_selection[index] = false;
            let frame = snapshot.at_sample(sample).cloned();
            // A valid selection refers to the original frame; a gap keeps its
            // actual sample and reason rather than borrowing a neighbour.
            let selected_sample = frame.as_ref().map_or(sample, |f| f.info.end - 1);
            self.spectrogram_selected[index] = frame;
            self.cursors.set_spectrogram_sample(index, selected_sample);
        }
    }

    pub(super) fn spectrogram_interaction(
        &mut self,
        ui: &egui::Ui,
        response: &egui::Response,
        rect: egui::Rect,
    ) {
        if response.double_clicked()
            && response
                .interact_pointer_pos()
                .is_some_and(|p| rect.contains(p))
        {
            self.reset_spectrogram_frequency();
            if let Some(snapshot) = &self.spectrogram_hold {
                self.spectrogram_hold_anchor = snapshot.latest().map(|f| f.info.end);
            }
            self.spectrogram_drag_cursor = None;
            return;
        }
        if response.drag_started() {
            let origin = ui.input(|input| input.pointer.press_origin());
            let samples = self.cursor_samples();
            let config = self.spectrogram_snapshot.config;
            self.spectrogram_drag_cursor = origin.filter(|p| rect.contains(*p)).and_then(|p| {
                samples
                    .iter()
                    .enumerate()
                    .filter_map(|(index, sample)| {
                        let config = config?;
                        let fraction = spectrogram::TimeAxis::new(
                            self.spectrogram_anchor,
                            config.sample_rate,
                            self.spectrogram_seconds,
                        )
                        .fraction((*sample)?.saturating_add(1));
                        if !(0.0..=1.0).contains(&fraction) {
                            return None;
                        }
                        let distance = (rect.top() + rect.height() * fraction - p.y).abs();
                        (distance <= 6.0).then_some((index, distance))
                    })
                    .min_by(|a, b| a.1.total_cmp(&b.1))
                    .map(|(index, _)| index)
            });
        }
        if response.dragged()
            && ui.input(|input| {
                input
                    .pointer
                    .press_origin()
                    .is_some_and(|p| rect.contains(p))
            })
        {
            if let Some(index) = self.spectrogram_drag_cursor {
                if let Some(p) = response.interact_pointer_pos() {
                    self.select_spectrogram_time(
                        index,
                        ((p.y - rect.top()) / rect.height()) as f64,
                    );
                }
            } else {
                let delta = ui.input(|input| input.pointer.delta());
                if delta.x != 0.0 {
                    let axis = self
                        .spectrogram_frequency_range()
                        .pan(-delta.x as f64 / rect.width() as f64);
                    self.spectrogram_min_hz = axis.min as f32;
                    self.spectrogram_max_hz = axis.max as f32;
                }
                if delta.y != 0.0 {
                    self.pan_spectrogram_time(
                        delta.y as f64 / rect.height() as f64 * self.spectrogram_seconds,
                    );
                }
            }
        }
        if response.drag_stopped() {
            self.spectrogram_drag_cursor = None;
        }
        let time_axis = egui::Rect::from_min_max(rect.min - vec2(42.0, 0.0), rect.left_bottom());
        if let Some(pointer) = response
            .hover_pos()
            .filter(|p| rect.contains(*p) || time_axis.contains(*p))
        {
            let time_scroll =
                ui.input(|input| input.modifiers.shift) || time_axis.contains(pointer);
            let scroll = ui.input_mut(|input| {
                let scroll = if time_scroll {
                    input.smooth_scroll_delta.x + input.smooth_scroll_delta.y
                } else {
                    input.smooth_scroll_delta.y
                };
                input.smooth_scroll_delta = egui::Vec2::ZERO;
                scroll
            });
            if scroll != 0.0 {
                if time_scroll {
                    self.pan_spectrogram_time(scroll as f64 * 0.002 * self.spectrogram_seconds);
                } else {
                    let x = (pointer.x - rect.left()) / rect.width();
                    let axis = self
                        .spectrogram_frequency_range()
                        .zoom(x as f64, (-scroll as f64 * 0.005).exp());
                    self.spectrogram_min_hz = axis.min as f32;
                    self.spectrogram_max_hz = axis.max as f32;
                }
            }
        }
    }

    pub(super) fn spectrogram_color_bar(&self, ui: &egui::Ui, rect: egui::Rect, view: View) {
        let bar = egui::Rect::from_min_max(
            rect.right_top() + vec2(8.0, 0.0),
            rect.right_bottom() + vec2(18.0, 0.0),
        );
        for i in 0..64 {
            let top = i as f32 / 64.0;
            let bottom = (i + 1) as f32 / 64.0;
            let db = view.ceiling_db + (view.floor_db - view.ceiling_db) * (top + bottom) * 0.5;
            let rgb = self.spectrogram_color_map.rgb(
                ColorRange::new(view.floor_db, view.ceiling_db)
                    .unwrap()
                    .fraction(db),
            );
            ui.painter().rect_filled(
                egui::Rect::from_min_max(
                    pos2(bar.left(), bar.top() + bar.height() * top),
                    pos2(bar.right(), bar.top() + bar.height() * bottom),
                ),
                0.0,
                Color32::from_rgb(
                    (rgb[0] * 255.0).round() as u8,
                    (rgb[1] * 255.0).round() as u8,
                    (rgb[2] * 255.0).round() as u8,
                ),
            );
        }
        for i in 0..=4 {
            let t = i as f32 / 4.0;
            ui.painter().text(
                pos2(bar.right() + 3.0, bar.top() + bar.height() * t),
                egui::Align2::LEFT_CENTER,
                format!(
                    "{:.0}",
                    view.ceiling_db + (view.floor_db - view.ceiling_db) * t
                ),
                egui::FontId::monospace(10.0),
                MUTED,
            );
        }
        ui.painter().text(
            pos2(bar.left(), bar.top() - 4.0),
            egui::Align2::LEFT_BOTTOM,
            "dBFS",
            egui::FontId::monospace(10.0),
            MUTED,
        );
    }

    fn spectrogram_analysis_controls(&mut self, ui: &mut egui::Ui) {
        let before = (self.spectrogram_settings, self.spectrogram_channel);
        fft_precision(
            ui,
            "spectrogram_precision",
            &mut self.spectrogram_settings.precision,
        );
        setting_label(ui, "FFT LENGTH");
        egui::ComboBox::from_id_salt("stft_size")
            .width(ui.available_width())
            .selected_text(format!("{} points", self.spectrogram_settings.size))
            .show_ui(ui, |ui| {
                for size in STFT_SIZES {
                    ui.selectable_value(
                        &mut self.spectrogram_settings.size,
                        size,
                        format!("{size} points"),
                    );
                }
            });
        setting_label(ui, "WINDOW");
        egui::ComboBox::from_id_salt("stft_window")
            .width(ui.available_width())
            .selected_text(self.spectrogram_settings.window.name())
            .show_ui(ui, |ui| {
                for window in [Window::Hann, Window::BlackmanHarris, Window::Rectangular] {
                    ui.selectable_value(
                        &mut self.spectrogram_settings.window,
                        window,
                        window.name(),
                    );
                }
            });
        ui.checkbox(&mut self.spectrogram_settings.remove_dc, "Remove DC offset");
        if before != (self.spectrogram_settings, self.spectrogram_channel) && self.running() {
            self.reset_stft();
        }
        if !self.running() {
            ui.label(
                RichText::new(
                    "Analysis changes apply when input restarts. The captured image stays held.",
                )
                .small()
                .color(MUTED),
            );
        }
        let captured = self.spectrogram_history.lock().unwrap().config();
        if let Some(config) = captured {
            ui.label(
                RichText::new(format!(
                    "Captured: nominal {} Hz · window {:.3} s · row {:.2} ms · bin {:.3} Hz",
                    config.sample_rate,
                    config.size as f64 / config.sample_rate as f64,
                    config.hop as f64 / config.sample_rate as f64 * 1000.0,
                    config.sample_rate as f64 / config.size as f64,
                ))
                .small()
                .color(MUTED),
            );
        }
        ui.label(RichText::new("Per-window bin amplitude · uncalibrated FS. Orange stripes: missing or invalid STFT. Blank: unavailable history.").small().color(MUTED));
    }
}
