use crate::{
    audio::{AudioWorker, Capture, Command, DeviceInfo, Event},
    cursor::{self, Cursors},
    demo::{Demo, Waveform},
    gpu::{COLORS, PlotId, Segment, TraceCallback, TraceRenderer},
    signal::{Edge, History, Line, Measurement, Sweep, Trigger, build_sweep_lines},
    spectrogram, spectrogram_gpu,
    spectrum::{self, Analyzer, FFT_SIZES, FrequencyScale, Precision, Settings, View, Window},
    stft::{self, RowInfo},
    xy,
};
use eframe::{
    egui::{self, Color32, RichText, Stroke, pos2, vec2},
    egui_wgpu,
};
use std::{
    sync::{Arc, Mutex, atomic::Ordering},
    time::{Duration, Instant},
};

const GREEN: Color32 = Color32::from_rgb(56, 242, 173);
const BLUE: Color32 = Color32::from_rgb(87, 166, 255);
const YELLOW: Color32 = Color32::from_rgb(255, 211, 66);
const HOLD: Color32 = Color32::from_rgb(179, 135, 65);
const PURPLE: Color32 = Color32::from_rgb(204, 153, 255);
const TRIGGER: Color32 = Color32::from_rgb(255, 170, 116);
const MUTED: Color32 = Color32::from_rgb(128, 147, 161);
const BORDER: Color32 = Color32::from_rgb(48, 70, 82);

#[derive(Clone, Copy, PartialEq, Eq)]
enum Source {
    Live,
    Demo,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Instrument {
    Scope,
    Spectrum,
    Spectrogram,
    Xy,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum PlotLayout {
    Auto,
    Columns,
    Rows,
}

impl PlotLayout {
    fn name(self) -> &'static str {
        match self {
            Self::Auto => "Automatic",
            Self::Columns => "Side by side",
            Self::Rows => "Stacked",
        }
    }

    fn columns(self, width: f32) -> bool {
        match self {
            Self::Auto => width >= 1000.0,
            // Keep both plots readable when the window or sidebar is resized.
            Self::Columns => width >= 800.0,
            Self::Rows => false,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
enum SettingsSection {
    Input,
    Scope,
    Spectrum,
    Spectrogram,
    Xy,
    Workspace,
}

impl SettingsSection {
    const ALL: [Self; 6] = [
        Self::Input,
        Self::Scope,
        Self::Spectrum,
        Self::Spectrogram,
        Self::Xy,
        Self::Workspace,
    ];

    fn title(self) -> &'static str {
        match self {
            Self::Input => "Input source",
            Self::Scope => "Oscilloscope",
            Self::Spectrum => "Spectrum analyzer",
            Self::Spectrogram => "Spectrogram",
            Self::Xy => "XY / Lissajous",
            Self::Workspace => "Workspace & help",
        }
    }

    fn color(self) -> Color32 {
        match self {
            Self::Input | Self::Workspace => Color32::from_rgb(192, 207, 217),
            Self::Scope => GREEN,
            Self::Spectrum => YELLOW,
            Self::Spectrogram => BLUE,
            Self::Xy => PURPLE,
        }
    }
}

struct Sidebar {
    visible: bool,
    section: Option<SettingsSection>,
    focus: bool,
}

impl Default for Sidebar {
    fn default() -> Self {
        Self {
            visible: true,
            section: Some(SettingsSection::Input),
            focus: false,
        }
    }
}

impl Sidebar {
    fn reveal(&mut self, section: SettingsSection) {
        self.visible = true;
        self.section = Some(section);
        self.focus = true;
    }
}

pub struct ScopeApp {
    source: Source,
    visible: [bool; 4],
    plot_layout: PlotLayout,
    sidebar: Sidebar,
    demo: Demo,
    demo_running: bool,
    demo_clock: Option<Instant>,
    demo_fraction: f64,
    spectrum_settings: Settings,
    analyzer: Analyzer,
    spectrum_channel: usize,
    frequency_scale: FrequencyScale,
    floor_db: f32,
    span_hz: f32,
    show_hold: bool,
    spectrum_dirty: bool,
    spectrum_pixels: usize,
    spectrum_lines: Vec<Line>,
    spectrum_line_builder: spectrum::LineBuilder,
    spectrum_segments: Arc<Vec<Segment>>,
    spectrum_revision: u64,
    last_spectrum: Instant,
    fft_ms: f64,
    spectrum_build_ms: f64,
    stft: stft::Worker,
    last_stft: Option<RowInfo>,
    spectrogram_history: Arc<Mutex<spectrogram::History>>,
    spectrogram_settings: Settings,
    spectrogram_channel: usize,
    spectrogram_scale: FrequencyScale,
    spectrogram_min_hz: f32,
    spectrogram_max_hz: f32,
    spectrogram_floor: f32,
    spectrogram_ceiling: f32,
    spectrogram_seconds: f64,
    spectrogram_build_ms: f64,
    xy_settings: xy::Settings,
    xy_cursor_mode: xy::CursorMode,
    xy_capture: xy::Capture,
    xy_trace_range: std::ops::Range<u64>,
    xy_lines: Vec<Line>,
    xy_segments: Arc<Vec<Segment>>,
    xy_revision: u64,
    xy_dirty: bool,
    xy_build_ms: f64,
    audio: AudioWorker,
    devices: Vec<DeviceInfo>,
    selected: usize,
    capture: Option<Capture>,
    busy: bool,
    error: Option<String>,
    history: History,
    cursors: Cursors,
    active_cursor: usize,
    scope_range: std::ops::Range<u64>,
    scope_sample_offset: f64,
    expected_sequence: Option<u64>,
    sample_rate: u32,
    channels: u16,
    format: String,
    enabled: [bool; 2],
    ms_per_div: f32,
    fs_per_div: f32,
    trigger: Trigger,
    triggered: bool,
    lines: Vec<Line>,
    segments: Arc<Vec<Segment>>,
    measurements: [Measurement; 2],
    dirty: bool,
    pixels: usize,
    revision: u64,
    build_ms: f64,
    fps: f64,
    last_frame: Instant,
    adapter: String,
    dropped: u64,
    smoke: bool,
    created: Instant,
    #[cfg(feature = "qa")]
    screenshot_requested: bool,
    #[cfg(feature = "qa")]
    profile: Option<crate::qa::Profile>,
    #[cfg(feature = "qa")]
    lifecycle_stage: u8,
    #[cfg(feature = "qa")]
    lifecycle_changed: Instant,
    #[cfg(feature = "qa")]
    lifecycle_scope_samples: [Option<u64>; 2],
    #[cfg(feature = "qa")]
    lifecycle_held: Option<(u64, RowInfo)>,
    #[cfg(feature = "qa")]
    lifecycle_xy_held: Option<(u64, xy::Capture)>,
    #[cfg(feature = "qa")]
    lifecycle_spectrum_held: Option<(spectrum::WindowInfo, Vec<f32>, std::ops::Range<u64>)>,
}

impl ScopeApp {
    pub fn new(
        cc: &eframe::CreationContext<'_>,
        smoke: bool,
        demo: bool,
    ) -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        let render = cc
            .wgpu_render_state
            .as_ref()
            .ok_or("WGPU renderer is unavailable")?;
        render
            .renderer
            .write()
            .callback_resources
            .insert(TraceRenderer::new(&render.device, render.target_format));
        render
            .renderer
            .write()
            .callback_resources
            .insert(spectrogram_gpu::Renderer::new(
                &render.device,
                render.target_format,
            ));
        let info = render.adapter.get_info();
        cc.egui_ctx.set_theme(egui::ThemePreference::Dark);
        let mut visuals = egui::Visuals::dark();
        visuals.panel_fill = Color32::from_rgb(15, 22, 29);
        visuals.window_fill = Color32::from_rgb(20, 29, 37);
        visuals.override_text_color = Some(Color32::from_rgb(217, 228, 234));
        visuals.selection.bg_fill = Color32::from_rgb(25, 89, 76);
        visuals.widgets.inactive.bg_fill = Color32::from_rgb(27, 40, 50);
        visuals.widgets.inactive.weak_bg_fill = Color32::from_rgb(23, 36, 46);
        visuals.widgets.inactive.bg_stroke = Stroke::new(1.0, BORDER);
        visuals.widgets.hovered.bg_fill = Color32::from_rgb(37, 58, 69);
        visuals.widgets.hovered.weak_bg_fill = Color32::from_rgb(31, 48, 60);
        visuals.widgets.active.bg_fill = Color32::from_rgb(29, 107, 87);
        cc.egui_ctx.set_visuals(visuals);
        cc.egui_ctx.global_style_mut(|style| {
            style.spacing.item_spacing = vec2(6.0, 6.0);
            style.spacing.button_padding = vec2(8.0, 4.0);
        });
        let mut app = Self {
            source: if demo || smoke {
                Source::Demo
            } else {
                Source::Live
            },
            visible: [true; 4],
            plot_layout: PlotLayout::Auto,
            sidebar: Sidebar::default(),
            demo: Demo::default(),
            demo_running: demo && !smoke,
            demo_clock: None,
            demo_fraction: 0.0,
            spectrum_settings: Settings::default(),
            analyzer: Analyzer::new(Settings::default(), 48000),
            spectrum_channel: 0,
            frequency_scale: FrequencyScale::Log,
            floor_db: -120.0,
            span_hz: 0.0,
            show_hold: false,
            spectrum_dirty: true,
            spectrum_pixels: 0,
            spectrum_lines: Vec::with_capacity(8192),
            spectrum_line_builder: spectrum::LineBuilder::default(),
            spectrum_segments: Arc::new(Vec::with_capacity(8192)),
            spectrum_revision: 0,
            last_spectrum: Instant::now() - Duration::from_secs(1),
            fft_ms: 0.0,
            spectrum_build_ms: 0.0,
            stft: stft::Worker::new(),
            last_stft: None,
            spectrogram_history: Arc::new(Mutex::new(spectrogram::History::default())),
            spectrogram_settings: Settings {
                averages: 1,
                ..Settings::default()
            },
            spectrogram_channel: 0,
            spectrogram_scale: FrequencyScale::Log,
            spectrogram_min_hz: 20.0,
            spectrogram_max_hz: 0.0,
            spectrogram_floor: -120.0,
            spectrogram_ceiling: 0.0,
            spectrogram_seconds: 5.0,
            spectrogram_build_ms: 0.0,
            xy_settings: xy::Settings::default(),
            xy_cursor_mode: xy::CursorMode::default(),
            xy_capture: xy::Capture::default(),
            xy_trace_range: 0..0,
            xy_lines: Vec::with_capacity(xy::MAX_POINTS),
            xy_segments: Arc::new(Vec::with_capacity(xy::MAX_POINTS)),
            xy_revision: 0,
            xy_dirty: true,
            xy_build_ms: 0.0,
            audio: AudioWorker::new(),
            devices: Vec::new(),
            selected: 0,
            capture: None,
            busy: true,
            error: None,
            history: History::new(96_000),
            cursors: Cursors::default(),
            active_cursor: 0,
            scope_range: 0..0,
            scope_sample_offset: 0.0,
            expected_sequence: None,
            sample_rate: 48_000,
            channels: 0,
            format: String::new(),
            enabled: [true; 2],
            ms_per_div: 1.0,
            fs_per_div: 0.25,
            trigger: Trigger::default(),
            triggered: false,
            lines: Vec::with_capacity(8192),
            segments: Arc::new(Vec::with_capacity(8192)),
            measurements: [Measurement::default(); 2],
            dirty: true,
            pixels: 0,
            revision: 0,
            build_ms: 0.0,
            fps: 0.0,
            last_frame: Instant::now(),
            adapter: format!("{:?} · {}", info.backend, info.name),
            dropped: 0,
            smoke,
            created: Instant::now(),
            #[cfg(feature = "qa")]
            screenshot_requested: false,
            #[cfg(feature = "qa")]
            profile: crate::qa::Profile::from_env()?,
            #[cfg(feature = "qa")]
            lifecycle_stage: 0,
            #[cfg(feature = "qa")]
            lifecycle_changed: Instant::now(),
            #[cfg(feature = "qa")]
            lifecycle_scope_samples: [None; 2],
            #[cfg(feature = "qa")]
            lifecycle_held: None,
            #[cfg(feature = "qa")]
            lifecycle_xy_held: None,
            #[cfg(feature = "qa")]
            lifecycle_spectrum_held: None,
        };
        #[cfg(feature = "qa")]
        if app.profile.is_some() {
            let precision = match std::env::var("MEASURELAB_PROFILE_FFT_PRECISION").as_deref() {
                Ok("f32") => Precision::F32,
                _ => Precision::F64,
            };
            let size = std::env::var("MEASURELAB_PROFILE_FFT_SIZE")
                .ok()
                .and_then(|size| size.parse::<usize>().ok())
                .filter(|size| FFT_SIZES.contains(size))
                .unwrap_or(8192);
            app.spectrum_settings.precision = precision;
            app.spectrogram_settings.precision = precision;
            app.spectrum_settings.size = size;
            app.spectrogram_settings.size = size;
            app.reset_analysis();
        }
        if demo || smoke {
            app.channels = 2;
            #[cfg(feature = "qa")]
            if smoke {
                if let Ok(phase) = std::env::var("MEASURELAB_UI_SMOKE_XY_PHASE") {
                    app.demo.phase_degrees = phase.parse::<f64>()?;
                    app.demo.waveform = Waveform::Sine;
                    app.demo.noise = 0.0;
                    app.demo.channel_2_gain = 1.0;
                }
                if std::env::var("MEASURELAB_UI_SMOKE_CHANNELS").as_deref() == Ok("1") {
                    app.channels = 1;
                    app.history = History::with_channels(96000, 1);
                }
                if std::env::var_os("MEASURELAB_UI_SMOKE_XY_ONLY").is_some() {
                    app.visible = [false, false, false, true];
                }
                if std::env::var_os("MEASURELAB_UI_SMOKE_SCOPE_ONLY").is_some() {
                    app.visible = [true, false, false, false];
                }
            }
            app.format = if smoke { "QA fixture" } else { "Internal demo" }.into();
            app.reset_analysis();
            app.reset_stft();
            app.demo.append_with(
                &mut app.history,
                if smoke { 16384 } else { 0 },
                app.sample_rate,
                |sequence, samples| {
                    app.stft.submit(sequence, samples);
                },
            );
            app.stft.flush();
        }
        #[cfg(feature = "qa")]
        if smoke {
            app.stft.pause();
            app.last_stft = Some(crate::qa::spectrogram_fixture(
                &mut app.spectrogram_history.lock().unwrap(),
            ));
            if std::env::var_os("MEASURELAB_UI_SMOKE_CURSORS").is_some() {
                app.last_stft = Some(crate::qa::cursor_fixture(
                    &mut app.spectrogram_history.lock().unwrap(),
                    &mut app.history,
                    &mut app.demo,
                    app.sample_rate,
                ));
                let sweep = app.history.sweep(480, app.trigger);
                for (index, sample) in [sweep.range.end - 240, sweep.range.end - 120]
                    .into_iter()
                    .enumerate()
                {
                    app.cursors.set_scope_time(
                        index,
                        cursor::fraction_at_sample(sweep.range.clone(), sample).unwrap(),
                    );
                    let frame = app.history.get(sample).unwrap();
                    app.cursors.set_xy_point(index, [frame[0], frame[1]]);
                }
                app.cursors.frequency_hz = Some(app.demo.frequency as f64);
                match std::env::var("MEASURELAB_UI_SMOKE_CURSOR_VIEW").as_deref() {
                    Ok("spectrogram") => {
                        app.spectrogram_seconds = 1.0;
                        app.cursors.set_spectrogram_time(0, 0.2);
                        app.cursors.set_spectrogram_time(1, 0.4);
                    }
                    Ok("trace") => {
                        app.xy_cursor_mode = xy::CursorMode::TraceSnap;
                        app.rebuild_xy();
                        let reference =
                            cursor::trigger_sample(app.xy_capture.range.clone()).unwrap();
                        for (index, offset) in [4, 12].into_iter().enumerate() {
                            app.cursors.set_trace_time(
                                index,
                                reference + offset,
                                app.xy_capture.range.clone(),
                            );
                        }
                    }
                    _ => {}
                }
            }
            // Render every inspector with the same deterministic signal fixture.
            match std::env::var("MEASURELAB_UI_SMOKE_SETTINGS").as_deref() {
                Ok("scope") => app.sidebar.section = Some(SettingsSection::Scope),
                Ok("spectrum") => app.sidebar.section = Some(SettingsSection::Spectrum),
                Ok("spectrogram") => app.sidebar.section = Some(SettingsSection::Spectrogram),
                Ok("xy") => app.sidebar.section = Some(SettingsSection::Xy),
                Ok("workspace") => app.sidebar.section = Some(SettingsSection::Workspace),
                Ok("collapsed") => app.sidebar.section = None,
                Ok("hidden") => app.sidebar.visible = false,
                _ => {}
            }
        }
        if smoke {
            app.update_spectrum(true);
        }
        Ok(app)
    }

    #[cfg(feature = "qa")]
    fn check_lifecycle(&mut self, ctx: &egui::Context, frame_interval: f64) {
        if self.profile.is_none() || std::env::var_os("MEASURELAB_PROFILE_LIFECYCLE").is_none() {
            return;
        }
        let elapsed = self.created.elapsed().as_secs_f64();
        let history = self.spectrogram_history.lock().unwrap();
        let Some(latest) = history.latest() else {
            return;
        };
        let revision = history.revision();
        drop(history);
        match self.lifecycle_stage {
            0 if elapsed > 0.6 => {
                self.refresh_scope_range();
                self.cursors.set_scope_time(0, 0.3);
                self.cursors.set_scope_time(1, 0.7);
                self.lifecycle_scope_samples = self.cursor_samples();
                // Verify cross-instrument resolution with Scope hidden, too.
                self.visible[0] = false;
                self.lifecycle_held = Some((revision, latest));
                self.spectrum_settings.size = 1024;
                self.spectrum_settings.averages = 16;
                self.spectrum_settings.precision = Precision::F32;
                self.spectrum_channel = 1;
                self.reset_analysis();
                self.lifecycle_stage = 1;
            }
            1 if elapsed > 1.0 => {
                self.refresh_scope_range();
                for (index, fraction) in [0.3, 0.7].into_iter().enumerate() {
                    let time = self.cursors.times[index].unwrap();
                    assert_eq!(
                        self.cursors.fraction(time, self.scope_range.clone()),
                        Some(fraction)
                    );
                    let sample = self.cursor_samples()[index].unwrap();
                    assert!(
                        sample > self.lifecycle_scope_samples[index].unwrap(),
                        "Scope cursor retained an old sample ID"
                    );
                    assert!(self.scope_range.contains(&sample));
                    assert!(self.history.get(sample).is_some());
                }
                self.visible[0] = true;
                assert_eq!(latest.config, self.lifecycle_held.unwrap().1.config);
                assert_eq!(latest.generation, self.lifecycle_held.unwrap().1.generation);
                self.stop();
                self.rebuild_xy();
                self.lifecycle_xy_held = Some((self.xy_revision, self.xy_capture.clone()));
                self.lifecycle_spectrum_held = Some((
                    self.analyzer.window().unwrap(),
                    self.analyzer.db().to_vec(),
                    self.history.range(),
                ));
                self.lifecycle_scope_samples = self.cursor_samples();
                self.cursors.frequency_hz = Some(1000.0);
                self.lifecycle_held = Some((revision, latest));
                self.lifecycle_stage = 2;
                ctx.request_repaint_after(Duration::from_millis(450));
            }
            2 if elapsed > 1.3 => {
                if std::env::var_os("MEASURELAB_PROFILE_IDLE").is_some() {
                    assert!(
                        frame_interval > 0.25,
                        "stopped UI kept repainting: {frame_interval:.3} s interval"
                    );
                    println!(
                        "Stopped UI idle OK: {:.1} ms without a redraw",
                        frame_interval * 1000.0
                    );
                }
                self.update_spectrum(false);
                let (held_window, held_db, held_range) =
                    self.lifecycle_spectrum_held.as_ref().unwrap();
                assert_eq!(self.analyzer.window(), Some(*held_window));
                assert_eq!(self.analyzer.db(), held_db);
                assert_eq!(self.history.range(), *held_range);
                assert_eq!(
                    self.cursor_samples(),
                    self.lifecycle_scope_samples,
                    "stopped Scope cursors changed samples"
                );
                for (index, fraction) in [0.3, 0.7].into_iter().enumerate() {
                    assert_eq!(
                        self.cursors
                            .fraction(self.cursors.times[index].unwrap(), self.scope_range.clone()),
                        Some(fraction)
                    );
                }
                self.cursors.set_time(0, latest.end - 240);
                self.cursors.set_time(1, latest.end - 120);
                assert_eq!(
                    self.cursors
                        .delta_seconds(self.sample_rate, self.scope_range.clone()),
                    Some(120.0 / self.sample_rate as f64)
                );
                let sample = self.cursor_samples()[0].unwrap();
                assert!(self.history.get(sample).is_some());
                assert!(
                    self.spectrogram_history
                        .lock()
                        .unwrap()
                        .at_sample(sample)
                        .is_some()
                );
                self.demo.frequency = 6000.0;
                self.apply_demo_settings();
                let (held_window, held_db, held_range) =
                    self.lifecycle_spectrum_held.as_ref().unwrap();
                assert_eq!(
                    self.history.range(),
                    *held_range,
                    "stopped demo edit changed held samples"
                );
                assert_eq!(self.analyzer.window(), Some(*held_window));
                assert_eq!(self.analyzer.db(), held_db);
                self.rebuild_xy();
                let (held_revision, held_capture) = self.lifecycle_xy_held.as_ref().unwrap();
                assert_eq!(
                    self.xy_revision, *held_revision,
                    "stopped XY rebuilt unchanged samples"
                );
                assert_eq!(self.xy_capture.range, held_capture.range);
                let held_range = held_capture.range.clone();
                self.xy_settings.x_fs_per_div = 0.125;
                self.xy_dirty = true;
                self.rebuild_xy();
                assert_eq!(
                    self.xy_capture.range, held_range,
                    "XY display change mutated held samples"
                );
                assert!(!self.xy_segments.is_empty());
                assert_eq!(
                    revision,
                    self.lifecycle_held.unwrap().0,
                    "late result changed stopped image"
                );
                self.spectrogram_seconds = 2.0;
                self.spectrogram_scale = FrequencyScale::Linear;
                self.spectrogram_floor = -100.0;
                self.spectrogram_settings.size = 1024;
                self.spectrogram_settings.precision = Precision::F32;
                self.spectrogram_channel = 1;
                self.spectrum_settings.size = 32768;
                self.spectrum_channel = 0;
                self.frequency_scale = FrequencyScale::Linear;
                self.floor_db = -100.0;
                self.spectrum_dirty = true;
                self.visible = [false, false, false, true];
                self.lifecycle_stage = 3;
                ctx.request_repaint_after(Duration::from_millis(450));
            }
            3 if elapsed > 1.6 => {
                self.update_spectrum(false);
                let (held_window, held_db, _) = self.lifecycle_spectrum_held.as_ref().unwrap();
                assert_eq!(
                    self.analyzer.window(),
                    Some(*held_window),
                    "next-run settings changed held FFT metadata"
                );
                assert_eq!(
                    self.analyzer.db(),
                    held_db,
                    "stopped display change re-averaged input"
                );
                assert_eq!(
                    revision,
                    self.lifecycle_held.unwrap().0,
                    "display-only change mutated held history"
                );
                self.visible = [false, false, true, false];
                self.start();
                assert_eq!(self.cursor_samples(), [None; 2]);
                assert!(self.cursors.frequency_hz.is_none());
                assert!(self.analyzer.window().is_none());
                self.lifecycle_stage = 4;
            }
            4 if elapsed > 2.0 => {
                self.rebuild_xy();
                assert!(
                    self.xy_capture.range.end
                        < self.lifecycle_xy_held.as_ref().unwrap().1.range.end,
                    "XY restart retained source coordinates from the previous capture"
                );
                assert_ne!(latest.generation, self.lifecycle_held.unwrap().1.generation);
                assert_eq!(latest.config.channel, 1);
                assert_eq!(latest.config.size, 1024);
                assert_eq!(latest.config.precision, Precision::F32);
                self.visible = [true; 4];
                self.spectrogram_settings.size = 8192;
                self.spectrogram_settings.precision = Precision::F64;
                self.spectrogram_channel = 0;
                self.reset_stft();
                self.lifecycle_stage = 5;
            }
            5 if elapsed > 2.3 => {
                assert_eq!(latest.config.channel, 0);
                assert_eq!(latest.config.size, 8192);
                assert_eq!(latest.config.precision, Precision::F64);
                self.cursors.set_time(0, self.history.range().end - 1);
                self.source = Source::Live;
                self.switch_source();
                assert_eq!(self.cursor_samples(), [None; 2]);
                assert!(self.cursors.frequency_hz.is_none());
                assert!(self.history.is_empty());
                assert!(self.analyzer.window().is_none());
                assert!(self.last_stft.is_none());
                self.source = Source::Demo;
                self.switch_source();
                self.xy_cursor_mode = xy::CursorMode::TraceSnap;
                self.cursors.set_xy_point(0, [0.25, -0.125]);
                self.cursors.set_xy_point(1, [-0.25, 0.125]);
                self.spectrogram_seconds = 0.5;
                self.cursors.set_spectrogram_time(0, 0.3);
                self.lifecycle_stage = 6;
            }
            6 if elapsed > 2.9 => {
                self.refresh_scope_range();
                self.xy_dirty = true;
                self.rebuild_xy();
                assert!(self.xy_capture.triggered);
                let reference = cursor::trigger_sample(self.xy_capture.range.clone()).unwrap();
                self.cursors
                    .set_trace_time(1, reference + 5, self.xy_capture.range.clone());
                self.lifecycle_scope_samples = self.cursor_samples();
                assert!(self.lifecycle_scope_samples.iter().all(Option::is_some));
                self.visible = [false, false, true, false];
                self.lifecycle_stage = 7;
            }
            7 if elapsed > 3.5 => {
                self.xy_dirty = true;
                self.rebuild_xy();
                let samples = self.cursor_samples();
                for (index, sample) in samples.into_iter().enumerate() {
                    assert!(sample.unwrap() > self.lifecycle_scope_samples[index].unwrap());
                }
                assert_eq!(self.cursors.times[0].unwrap().spectrogram_y(), Some(0.3));
                assert_eq!(self.cursors.times[1].unwrap().trace_offset(), Some(5));
                assert_eq!(
                    self.cursors.xy_points,
                    [Some([0.25, -0.125]), Some([-0.25, 0.125])]
                );
                self.stop();
                self.lifecycle_scope_samples = self.cursor_samples();
                // Mode changes preserve both Free positions and the trigger
                // reference shared by the other instruments while stopped.
                for mode in [xy::CursorMode::Free, xy::CursorMode::TraceSnap] {
                    self.xy_cursor_mode = mode;
                    self.xy_dirty = true;
                    self.rebuild_xy();
                    assert_eq!(self.cursor_samples(), self.lifecycle_scope_samples);
                    assert_eq!(self.cursors.xy_points[0], Some([0.25, -0.125]));
                }
                self.start();
                assert_eq!(self.cursor_samples(), [None; 2]);
                assert_eq!(self.cursors.xy_points, [None; 2]);
                self.visible = [true; 4];
                println!(
                    "UI lifecycle OK: fixed-X Scope and fixed-Y Spectrogram cursors, trigger-relative XY Trace Snap across live/hidden/held views, independent Free positions and mode switching, restart invalidation, independent Spectrum settings, all-instrument hold, stop/late-result exclusion, held FFT metadata/average and demo edits, shared samples, display changes, hide/show, source switching, STFT CH/FFT changes"
                );
                self.lifecycle_stage = 8;
            }
            _ => {}
        }
        // An already queued immediate frame can consume the delayed repaint
        // scheduled when stopping. Keep the held QA stages on a slow timer.
        if matches!(self.lifecycle_stage, 2 | 3) {
            ctx.request_repaint_after(Duration::from_millis(450));
        }
    }

    /// Exercise real CPAL capture through the UI's own asynchronous start/stop
    /// path. This is separate from the deterministic internal-demo lifecycle.
    #[cfg(feature = "qa")]
    fn check_input_lifecycle(&mut self, ctx: &egui::Context) {
        if self.profile.is_none()
            || std::env::var_os("MEASURELAB_PROFILE_INPUT_LIFECYCLE").is_none()
            || self.lifecycle_stage == 6
        {
            return;
        }
        assert!(
            std::env::var_os("MEASURELAB_PROFILE_LIFECYCLE").is_none(),
            "choose one lifecycle check"
        );
        assert!(
            self.error.is_none(),
            "input lifecycle error: {:?}",
            self.error
        );
        let elapsed = self.lifecycle_changed.elapsed().as_secs_f64();
        assert!(
            elapsed < 15.0,
            "input lifecycle stage {} timed out",
            self.lifecycle_stage
        );
        let latest = self.spectrogram_history.lock().unwrap().latest();
        let stage = self.lifecycle_stage;
        match stage {
            0 if elapsed > 0.8 && latest.is_some() && self.analyzer.window().is_some() => {
                assert!(
                    self.capture.is_some(),
                    "input lifecycle requires a CPAL device"
                );
                let latest = latest.unwrap();
                self.stop();
                self.refresh_scope_range();
                self.rebuild_xy();
                self.cursors.set_time(0, latest.end - 240);
                self.cursors.set_time(1, latest.end - 120);
                self.cursors.frequency_hz = Some(1000.0);
                self.lifecycle_scope_samples = self.cursor_samples();
                assert!(self.lifecycle_scope_samples.iter().all(Option::is_some));
                for sample in self.lifecycle_scope_samples.into_iter().flatten() {
                    assert!(self.history.get(sample).is_some());
                    assert!(
                        self.spectrogram_history
                            .lock()
                            .unwrap()
                            .at_sample(sample)
                            .is_some()
                    );
                }
                self.lifecycle_held =
                    Some((self.spectrogram_history.lock().unwrap().revision(), latest));
                self.lifecycle_xy_held = Some((self.xy_revision, self.xy_capture.clone()));
                self.lifecycle_spectrum_held = Some((
                    self.analyzer.window().unwrap(),
                    self.analyzer.db().to_vec(),
                    self.history.range(),
                ));
                self.lifecycle_stage = 1;
            }
            1 if elapsed > 0.4 && !self.busy => {
                let (window, db, range) = self.lifecycle_spectrum_held.as_ref().unwrap();
                assert_eq!(self.analyzer.window(), Some(*window));
                assert_eq!(self.analyzer.db(), db);
                assert_eq!(self.history.range(), *range);
                assert_eq!(self.cursor_samples(), self.lifecycle_scope_samples);
                let history = self.spectrogram_history.lock().unwrap();
                assert_eq!(history.revision(), self.lifecycle_held.unwrap().0);
                assert_eq!(history.latest(), Some(self.lifecycle_held.unwrap().1));
                drop(history);
                self.spectrogram_seconds = 2.0;
                self.spectrogram_scale = FrequencyScale::Linear;
                self.floor_db = -100.0;
                self.spectrum_dirty = true;
                self.spectrogram_settings.size = 1024;
                self.spectrogram_channel = self.channels as usize - 1;
                self.visible = [false, false, true, false];
                self.lifecycle_stage = 2;
            }
            2 if elapsed > 0.4 => {
                self.update_spectrum(false);
                self.rebuild_xy();
                let (window, db, range) = self.lifecycle_spectrum_held.as_ref().unwrap();
                assert_eq!(self.analyzer.window(), Some(*window));
                assert_eq!(self.analyzer.db(), db);
                assert_eq!(self.history.range(), *range);
                assert_eq!(self.xy_revision, self.lifecycle_xy_held.as_ref().unwrap().0);
                assert_eq!(
                    self.spectrogram_history.lock().unwrap().revision(),
                    self.lifecycle_held.unwrap().0
                );
                self.visible = [true; 4];
                self.start();
                assert!(self.history.is_empty());
                assert!(self.analyzer.window().is_none());
                assert!(self.last_stft.is_none());
                assert_eq!(self.cursor_samples(), [None; 2]);
                assert!(self.cursors.frequency_hz.is_none());
                self.lifecycle_stage = 3;
            }
            3 if elapsed > 0.8 && latest.is_some() && !self.busy => {
                let latest = latest.unwrap();
                assert_ne!(latest.generation, self.lifecycle_held.unwrap().1.generation);
                assert_eq!(latest.config.size, 1024);
                assert_eq!(latest.config.channel, self.channels as usize - 1);
                self.cursors.set_scope_time(0, 0.5);
                self.source = Source::Demo;
                self.switch_source();
                assert_eq!(self.cursor_samples(), [None; 2]);
                self.lifecycle_stage = 4;
            }
            4 if elapsed > 0.8 && latest.is_some() && !self.busy => {
                assert!(self.demo_running);
                assert_eq!(self.channels, 2);
                assert_eq!(self.sample_rate, 48000);
                self.cursors.set_scope_time(0, 0.5);
                self.source = Source::Live;
                self.switch_source();
                assert_eq!(self.cursor_samples(), [None; 2]);
                assert!(self.history.is_empty());
                if let Ok(name) = std::env::var("MEASURELAB_PROFILE_SWITCH_DEVICE") {
                    self.selected = self
                        .devices
                        .iter()
                        .position(|device| device.name == name)
                        .expect("QA switch device not found");
                }
                self.start();
                self.lifecycle_stage = 5;
            }
            5 if elapsed > 0.8 && latest.is_some() && !self.busy => {
                let latest = latest.unwrap();
                assert!(self.capture.is_some());
                assert_eq!(latest.config.channels, self.channels as usize);
                assert_eq!(latest.config.sample_rate, self.sample_rate);
                assert_eq!(self.cursor_samples(), [None; 2]);
                self.cursors.set_scope_time(0, 0.3);
                self.cursors.set_scope_time(1, 0.7);
                self.refresh_scope_range();
                for sample in self.cursor_samples().into_iter().flatten() {
                    assert!(self.history.get(sample).is_some());
                }
                println!(
                    "Input lifecycle OK: CPAL hold, late-result exclusion, shared raw/STFT cursors, display and pending analysis edits, hide/show, restart invalidation, live/demo/device switching; final {} / {} Hz / {} ch",
                    self.devices[self.selected].name, self.sample_rate, self.channels
                );
                self.lifecycle_stage = 6;
            }
            _ => {}
        }
        if self.lifecycle_stage != stage {
            self.lifecycle_changed = Instant::now();
        }
        // Only the held stages need a timer; running capture already repaints.
        if matches!(self.lifecycle_stage, 1 | 2) {
            ctx.request_repaint_after(Duration::from_millis(450));
        }
    }

    fn running(&self) -> bool {
        self.capture.is_some() || self.demo_running
    }

    fn begin_observation(&mut self) {
        self.cursors.new_epoch();
        self.history.clear_at(0);
        self.scope_range = 0..0;
        self.scope_sample_offset = 0.0;
        self.xy_capture = xy::Capture::default();
        self.xy_trace_range = 0..0;
        self.measurements = [Measurement::default(); 2];
        self.dirty = true;
        self.xy_dirty = true;
        self.reset_analysis();
        self.reset_stft();
    }

    fn update_spectrum(&mut self, final_snapshot: bool) {
        if (self.running() || final_snapshot)
            && (final_snapshot
                || self.last_spectrum.elapsed() >= Duration::from_secs_f64(1.0 / 30.0))
        {
            let started = Instant::now();
            if self.analyzer.update(&self.history, self.spectrum_channel) {
                self.fft_ms = started.elapsed().as_secs_f64() * 1000.0;
                #[cfg(feature = "qa")]
                if let Some(profile) = &mut self.profile {
                    profile.record_work(crate::qa::Work::Fft, self.fft_ms);
                }
                self.spectrum_dirty = true;
                self.last_spectrum = Instant::now();
            }
        }
    }

    fn cursor_samples(&self) -> [Option<u64>; 2] {
        let latest = self.spectrogram_history.lock().unwrap().latest();
        self.cursors.times.map(|time| {
            let time = time?;
            if time.spectrogram_y().is_some() {
                let row = latest?;
                self.cursors.spectrogram_sample(
                    time,
                    row.end,
                    self.spectrogram_seconds,
                    row.config.sample_rate,
                )
            } else if time.trace_offset().is_some() {
                self.cursors.sample(time, self.xy_trace_range.clone())
            } else {
                self.cursors.sample_with_offset(
                    time,
                    self.scope_range.clone(),
                    self.scope_sample_offset,
                )
            }
        })
    }

    fn scope_cursor_seconds(&self, sample: u64) -> Option<f64> {
        let trigger = cursor::trigger_sample(self.scope_range.clone())?;
        (self.sample_rate > 0).then(|| {
            (cursor::signed_distance(sample, trigger) + self.scope_sample_offset)
                / self.sample_rate as f64
        })
    }

    fn scope_sample_count(&self) -> usize {
        (self.ms_per_div * 0.01 * self.sample_rate as f32)
            .round()
            .max(2.0) as usize
    }

    fn refresh_scope_range(&mut self) {
        if self.dirty {
            let count = self.scope_sample_count();
            let sweep = self.history.sweep(count, self.trigger);
            let ready = self.history.len() >= count;
            self.triggered = ready && sweep.triggered;
            self.scope_sample_offset = if ready { sweep.sample_offset } else { 0.0 };
            self.scope_range = if ready { sweep.range } else { 0..0 };
        }
    }

    fn cursor_controls(&mut self, ui: &mut egui::Ui) {
        ui.separator();
        for (index, title) in ["Cursor A", "B"].into_iter().enumerate() {
            ui.selectable_value(&mut self.active_cursor, index, title)
                .on_hover_text("Scope and Spectrogram keep the cursor's plot position. XY Free keeps X/Y amplitudes; Trace Snap follows a trigger-relative sample. Spectrum and Spectrogram share frequency.");
        }
        if ui.small_button("Clear").clicked() {
            self.cursors.clear();
            ui.ctx().request_repaint();
        }
        let mut text = String::new();
        for (index, time) in self.cursors.times.into_iter().enumerate() {
            let Some(time) = time else { continue };
            if time.scope_x().is_some() {
                if let Some(seconds) = self.cursor_samples()[index]
                    .and_then(|sample| self.scope_cursor_seconds(sample))
                {
                    text.push_str(&format!(
                        "{} {:+.3} ms  ",
                        cursor_name(index),
                        seconds * 1000.0
                    ));
                }
            } else if let Some(y) = time.spectrogram_y() {
                text.push_str(&format!(
                    "{} −{:.3} s  ",
                    cursor_name(index),
                    y * self.spectrogram_seconds
                ));
            } else if let Some(offset) = time.trace_offset() {
                text.push_str(&format!(
                    "{} T{:+.3} ms  ",
                    cursor_name(index),
                    offset as f64 * 1000.0 / self.sample_rate as f64
                ));
            } else if let Some(sample) = self.cursors.sample(time, self.scope_range.clone()) {
                text.push_str(&format!("{} #{sample}  ", cursor_name(index)));
            }
        }
        if let [Some(a), Some(b)] = self.cursor_samples()
            && self.sample_rate > 0
        {
            let delta = cursor::signed_distance(b, a) / self.sample_rate as f64;
            text.push_str(&format!("Δt {:+.3} ms", delta * 1000.0));
        }
        if !text.is_empty() {
            ui.label(RichText::new(text).small().color(MUTED));
        }
    }

    fn reset_analysis(&mut self) {
        self.spectrum_channel = self.spectrum_channel.min(self.channels.max(1) as usize - 1);
        self.analyzer = Analyzer::new(self.spectrum_settings, self.sample_rate);
        self.spectrum_dirty = true;
        self.last_spectrum = Instant::now() - Duration::from_secs(1);
    }

    fn apply_demo_settings(&mut self) {
        // New signal parameters enter the ordinary shared stream at the next
        // poll. Never synthesize private Scope/Spectrum samples while stopped.
        if self.running() {
            self.reset_analysis();
        }
    }

    fn reset_stft(&mut self) {
        self.spectrogram_channel = self
            .spectrogram_channel
            .min(self.channels.max(1) as usize - 1);
        let config = stft::Config {
            sample_rate: self.sample_rate,
            channels: self.channels.max(1) as usize,
            channel: self.spectrogram_channel,
            size: self.spectrogram_settings.size,
            hop: self.spectrogram_settings.size / 4,
            window: self.spectrogram_settings.window,
            remove_dc: self.spectrogram_settings.remove_dc,
            precision: self.spectrogram_settings.precision,
        };
        let generation = self
            .stft
            .configure(config)
            .expect("validated STFT settings");
        self.spectrogram_history
            .lock()
            .unwrap()
            .reset(generation, config);
        self.last_stft = None;
        if !self.running() && !self.smoke {
            self.stft.pause();
        }
    }

    fn poll_demo(&mut self) {
        let now = Instant::now();
        // Acquisition starts at the first poll, after window/GPU setup. Startup
        // time is not a missing interval in a demo that has not produced input.
        let elapsed = self
            .demo_clock
            .replace(now)
            .map_or(0.0, |previous| now.duration_since(previous).as_secs_f64());
        if !self.demo_running {
            return;
        }
        // Bound catch-up after window suspension, and never join a false gap.
        if elapsed > 0.25 {
            let missing = ((elapsed - 0.25) * self.sample_rate as f64) as u64;
            self.history.clear_at(self.history.range().end + missing);
            self.dropped += missing;
            self.analyzer.reset();
            self.spectrum_dirty = true;
        }
        self.demo_fraction += elapsed.min(0.25) * self.sample_rate as f64;
        let count = self.demo_fraction as usize;
        self.demo_fraction -= count as f64;
        self.demo.append_with(
            &mut self.history,
            count,
            self.sample_rate,
            |sequence, samples| {
                self.stft.submit(sequence, samples);
            },
        );
        self.stft.flush();
        self.dirty |= count > 0;
        self.xy_dirty |= count > 0;
    }

    fn start(&mut self) {
        #[cfg(feature = "qa")]
        if let Some(profile) = &mut self.profile {
            profile.new_input(self.dropped);
        }
        if self.source == Source::Demo {
            self.begin_observation();
            self.sample_rate = 48000;
            self.channels = 2;
            self.format = "Internal demo".into();
            self.history = History::new(96000);
            self.xy_dirty = true;
            self.demo_fraction = 0.0;
            self.demo_clock = None;
            self.demo_running = true;
            self.dropped = 0;
            self.error = None;
            self.dirty = true;
            self.reset_analysis();
            self.reset_stft();
            return;
        }
        if self.devices.is_empty() || self.busy {
            return;
        }
        self.error = None;
        self.capture = None;
        self.begin_observation();
        self.busy = true;
        self.audio.send(Command::Start(self.selected));
    }

    fn stop(&mut self) {
        // Complete a final bounded snapshot even for a hidden Spectrum. All
        // subsequent repaints read the held analyzer, never re-average input.
        self.update_spectrum(true);
        self.stft.pause();
        if self.source == Source::Demo {
            self.demo_running = false;
            return;
        }
        self.capture = None;
        self.busy = true;
        self.audio.send(Command::Stop);
    }

    fn poll_audio(&mut self) {
        while let Ok(event) = self.audio.events.try_recv() {
            self.busy = false;
            match event {
                Event::Devices(devices) => {
                    self.selected = devices.iter().position(|d| d.is_default).unwrap_or(0);
                    self.devices = devices;
                    #[cfg(feature = "qa")]
                    if let Some(name) = self.profile.as_ref().and_then(|p| p.device.as_ref()) {
                        if let Some(index) = self.devices.iter().position(|d| &d.name == name) {
                            self.selected = index;
                            self.start();
                        } else {
                            self.error = Some(format!("QA input device not found: {name}"));
                        }
                    }
                }
                Event::Started(capture) => {
                    self.xy_dirty = true;
                    self.sample_rate = capture.sample_rate;
                    self.channels = capture.channels;
                    self.format = capture.format.clone();
                    self.history = History::with_channels(
                        (self.sample_rate as usize * 2).max(32768),
                        self.channels as usize,
                    );
                    self.expected_sequence = None;
                    self.dropped = 0;
                    self.capture = Some(capture);
                    #[cfg(feature = "qa")]
                    if self.profile.is_some() {
                        if let Ok(channel) = std::env::var("MEASURELAB_PROFILE_CHANNEL")
                            && let Ok(channel) = channel.parse::<usize>()
                        {
                            self.spectrum_channel = channel.saturating_sub(1);
                            self.spectrogram_channel = channel.saturating_sub(1);
                        }
                        if std::env::var("MEASURELAB_PROFILE_SETTINGS").as_deref() == Ok("spectrum")
                        {
                            self.sidebar.section = Some(SettingsSection::Spectrum);
                        }
                    }
                    self.dirty = true;
                    self.reset_analysis();
                    self.reset_stft();
                }
                Event::Stopped => {}
                Event::Error(error) => {
                    self.capture = None;
                    self.stft.pause();
                    self.error = Some(error);
                }
            }
        }
        let Some(capture) = self.capture.as_mut() else {
            return;
        };
        self.dropped = capture.metrics.dropped.load(Ordering::Relaxed);
        if capture.metrics.failed.load(Ordering::Relaxed) {
            self.error = Some("Audio stream stopped. Check device connection and microphone permission, then restart.".into());
            self.stop();
            return;
        }
        // Read only the currently available batch: UI work is bounded even if
        // the producer keeps running. A gap clears history instead of drawing
        // a false continuous signal across lost samples.
        let available = capture.consumer.slots();
        if let Ok(chunk) = capture.consumer.read_chunk(available) {
            for frame in chunk {
                if self
                    .expected_sequence
                    .is_some_and(|expected| expected != frame.sequence)
                {
                    self.history.clear();
                    self.analyzer.reset();
                    self.spectrum_dirty = true;
                }
                self.expected_sequence = Some(frame.sequence + 1);
                self.history.push_at(frame.sequence, frame.samples);
                self.stft
                    .submit(frame.sequence, &frame.samples[..self.channels as usize]);
            }
        }
        self.stft.flush();
        self.dirty |= available > 0;
        self.xy_dirty |= available > 0;
    }

    fn section_summary(&self, section: SettingsSection) -> String {
        match section {
            SettingsSection::Input if self.source == Source::Demo => {
                format!(
                    "Demo · {} Hz · {:.2} FS",
                    self.demo.frequency, self.demo.amplitude
                )
            }
            SettingsSection::Input => self
                .devices
                .get(self.selected)
                .map(|device| device.name.clone())
                .unwrap_or_else(|| "Select an audio device".into()),
            SettingsSection::Scope => {
                format!("{} ms/div · {} FS/div", self.ms_per_div, self.fs_per_div)
            }
            SettingsSection::Spectrum => format!(
                "CH {} · {} points · {}",
                self.spectrum_channel + 1,
                self.spectrum_settings.size,
                self.spectrum_settings.window.name()
            ),
            SettingsSection::Spectrogram => format!(
                "CH {} · {:.1} s · {} points",
                self.spectrogram_channel + 1,
                self.spectrogram_seconds,
                self.spectrogram_settings.size
            ),
            SettingsSection::Xy => format!("CH 1 × CH 2 · {:.1} ms", self.xy_settings.milliseconds),
            SettingsSection::Workspace => {
                format!("{} layout · shortcuts & units", self.plot_layout.name())
            }
        }
    }

    fn controls(&mut self, ui: &mut egui::Ui) {
        ui.spacing_mut().item_spacing = vec2(8.0, 8.0);
        ui.visuals_mut().collapsing_header_frame = true;
        for section in SettingsSection::ALL {
            let summary = self.section_summary(section);
            let open = self.sidebar.section == Some(section);
            let response = egui::Frame::new()
                .fill(Color32::from_rgb(17, 27, 35))
                .stroke(Stroke::new(
                    1.0,
                    if open {
                        section.color().gamma_multiply(0.6)
                    } else {
                        BORDER
                    },
                ))
                .corner_radius(5.0)
                .inner_margin(8.0)
                .show(ui, |ui| {
                    ui.set_min_width(ui.available_width());
                    let header = egui::CollapsingHeader::new(
                        RichText::new(section.title())
                            .color(section.color())
                            .strong(),
                    )
                    .id_salt(("settings", section))
                    .open(Some(open))
                    .show_unindented(ui, |ui| {
                        ui.spacing_mut().slider_width = (ui.available_width() - 140.0).max(75.0);
                        ui.add_space(4.0);
                        match section {
                            SettingsSection::Input => self.input_controls(ui),
                            SettingsSection::Scope => self.scope_controls(ui),
                            SettingsSection::Spectrum => self.spectrum_controls(ui),
                            SettingsSection::Spectrogram => self.spectrogram_controls(ui),
                            SettingsSection::Xy => self.xy_controls(ui),
                            SettingsSection::Workspace => self.workspace_controls(ui),
                        }
                        ui.add_space(4.0);
                    });
                    if header.header_response.clicked() {
                        self.sidebar.section = if open { None } else { Some(section) };
                        self.sidebar.focus = !open;
                        ui.ctx().request_repaint();
                    }
                    if !open {
                        ui.add(
                            egui::Label::new(RichText::new(summary).small().color(MUTED))
                                .truncate(),
                        )
                        .on_hover_text(self.section_summary(section));
                    }
                    (header.header_response, header.openness)
                });
            if self.sidebar.focus && open {
                response.inner.0.scroll_to_me(Some(egui::Align::Min));
                self.sidebar.focus = response.inner.1 < 1.0;
            }
            ui.add_space(2.0);
        }
    }

    fn transport(&mut self, ui: &mut egui::Ui) {
        if ui
            .add_enabled(
                !self.busy && (self.source == Source::Demo || !self.devices.is_empty()),
                egui::Button::new(
                    RichText::new(if self.running() {
                        "■  Stop"
                    } else if self.source == Source::Demo {
                        "▶  Start demo"
                    } else {
                        "▶  Start input"
                    })
                    .color(if self.running() {
                        Color32::from_rgb(255, 170, 116)
                    } else {
                        GREEN
                    }),
                ),
            )
            .on_hover_text(
                "Start or stop the shared input for every visible instrument. Shortcut: Space",
            )
            .clicked()
        {
            if self.running() {
                self.stop();
            } else {
                self.start();
            }
        }
    }

    fn switch_source(&mut self) {
        self.cursors.new_epoch();
        self.scope_range = 0..0;
        self.scope_sample_offset = 0.0;
        self.xy_dirty = true;
        self.demo_running = false;
        if self.capture.take().is_some() {
            self.audio.send(Command::Stop);
            self.busy = true;
        }
        self.history.clear();
        self.channels = if self.source == Source::Demo { 2 } else { 0 };
        if self.source == Source::Demo {
            self.sample_rate = 48000;
            self.format = "Internal demo".into();
            self.start();
        } else {
            #[cfg(feature = "qa")]
            if let Some(profile) = &mut self.profile {
                profile.new_input(self.dropped);
            }
            self.format.clear();
            self.expected_sequence = None;
            self.dropped = 0;
        }
        self.dirty = true;
        self.error = None;
        self.reset_analysis();
        self.reset_stft();
    }

    fn input_controls(&mut self, ui: &mut egui::Ui) {
        setting_label(ui, "SOURCE");
        let previous_source = self.source;
        ui.add_enabled_ui(!self.busy, |ui| {
            ui.horizontal(|ui| {
                ui.selectable_value(&mut self.source, Source::Live, "Audio input");
                ui.selectable_value(&mut self.source, Source::Demo, "Demo signal");
            });
        });
        if previous_source != self.source {
            self.switch_source();
        }
        if self.source == Source::Live {
            setting_label(ui, "DEVICE");
            let selected_name = self
                .devices
                .get(self.selected)
                .map(|d| d.name.as_str())
                .unwrap_or("No input device");
            let previous = self.selected;
            ui.add_enabled_ui(!self.busy, |ui| {
                egui::ComboBox::from_id_salt("input")
                    .width(ui.available_width())
                    .truncate()
                    .selected_text(selected_name)
                    .show_ui(ui, |ui| {
                        for (index, device) in self.devices.iter().enumerate() {
                            let name = if device.is_default {
                                format!("{} (default)", device.name)
                            } else {
                                device.name.clone()
                            };
                            ui.selectable_value(&mut self.selected, index, name);
                        }
                    });
            });
            if previous != self.selected && self.capture.is_some() {
                self.start();
            }
        }
        if self.source == Source::Live
            && ui
                .add_enabled(
                    !self.busy && self.capture.is_none(),
                    egui::Button::new("Refresh devices"),
                )
                .clicked()
        {
            self.busy = true;
            self.error = None;
            self.audio.send(Command::Refresh);
        }
        if self.source == Source::Demo {
            let before = (
                self.demo.waveform,
                self.demo.frequency,
                self.demo.amplitude,
                self.demo.noise,
                self.demo.phase_degrees,
                self.demo.channel_2_gain,
            );
            setting_label(ui, "WAVEFORM");
            egui::ComboBox::from_id_salt("demo_waveform")
                .width(ui.available_width())
                .selected_text(self.demo.waveform.name())
                .show_ui(ui, |ui| {
                    for shape in [Waveform::Sine, Waveform::Harmonics, Waveform::Square] {
                        ui.selectable_value(&mut self.demo.waveform, shape, shape.name());
                    }
                });
            setting_label(ui, "FREQUENCY");
            ui.add(
                egui::Slider::new(&mut self.demo.frequency, 20.0..=10000.0)
                    .logarithmic(true)
                    .text("Hz"),
            );
            setting_label(ui, "AMPLITUDE");
            ui.add(egui::Slider::new(&mut self.demo.amplitude, 0.01..=0.8).text("FS peak"));
            setting_label(ui, "NOISE");
            ui.add(
                egui::Slider::new(&mut self.demo.noise, 0.0..=0.05)
                    .logarithmic(true)
                    .smallest_positive(0.000001)
                    .fixed_decimals(4)
                    .text("Noise"),
            )
            .on_hover_text("Noise amplitude in digital full scale (FS).");
            setting_label(ui, "CH 2 PHASE / GAIN");
            ui.add(egui::Slider::new(&mut self.demo.phase_degrees, -180.0..=180.0).text("degrees"));
            ui.add(egui::Slider::new(&mut self.demo.channel_2_gain, 0.0..=1.0).text("CH 2 gain"));
            ui.horizontal(|ui| {
                for phase in [0.0, 90.0, 180.0] {
                    if ui.small_button(format!("{phase:.0}°")).clicked() {
                        self.demo.waveform = Waveform::Sine;
                        self.demo.noise = 0.0;
                        self.demo.phase_degrees = phase;
                        self.demo.channel_2_gain = 1.0;
                    }
                }
            }).response.on_hover_text("Equal-amplitude, noise-free sine signals for XY: in-phase, quadrature or opposite phase.");
            if before
                != (
                    self.demo.waveform,
                    self.demo.frequency,
                    self.demo.amplitude,
                    self.demo.noise,
                    self.demo.phase_degrees,
                    self.demo.channel_2_gain,
                )
            {
                self.apply_demo_settings();
            }
            if !self.running() {
                ui.label(
                    RichText::new(
                        "Signal changes apply when input restarts. Captured samples stay held.",
                    )
                    .small()
                    .color(MUTED),
                );
            }
            ui.label(
                RichText::new("Internal source · no audio output")
                    .small()
                    .color(MUTED),
            );
        }
        ui.label(
            RichText::new("Start / stop is always in the top bar.")
                .small()
                .color(MUTED),
        );
    }

    fn scope_controls(&mut self, ui: &mut egui::Ui) {
        setting_label(ui, "TIMEBASE");
        self.dirty |= ui
            .add(
                egui::Slider::new(&mut self.ms_per_div, 0.05..=100.0)
                    .logarithmic(true)
                    .text("ms / div"),
            )
            .changed();
        ui.label(
            RichText::new(format!("{:.2} ms across screen", self.ms_per_div * 10.0))
                .small()
                .color(MUTED),
        );
        setting_label(ui, "AMPLITUDE");
        self.dirty |= ui
            .add(
                egui::Slider::new(&mut self.fs_per_div, 0.001..=0.5)
                    .logarithmic(true)
                    .text("FS / div"),
            )
            .changed();
        ui.horizontal(|ui| {
            self.dirty |= ui
                .checkbox(&mut self.enabled[0], RichText::new("CH 1").color(GREEN))
                .changed();
            ui.add_enabled_ui(self.channels >= 2, |ui| {
                self.dirty |= ui
                    .checkbox(&mut self.enabled[1], RichText::new("CH 2").color(BLUE))
                    .changed();
            });
        });
        if ui.button("Fit amplitude").clicked() {
            let peak = self
                .measurements
                .iter()
                .map(|m| m.peak)
                .fold(0.0_f64, f64::max);
            self.fs_per_div = (peak / 3.5).clamp(0.001, 0.5) as f32;
            self.dirty = true;
        }
        ui.separator();
        setting_label(ui, "TRIGGER · AUTO");
        let before = (self.trigger.edge, self.trigger.channel);
        egui::ComboBox::from_id_salt("edge")
            .width(ui.available_width())
            .selected_text(match self.trigger.edge {
                Edge::Free => "Free run",
                Edge::Rising => "Rising edge",
                Edge::Falling => "Falling edge",
            })
            .show_ui(ui, |ui| {
                ui.selectable_value(&mut self.trigger.edge, Edge::Free, "Free run");
                ui.selectable_value(&mut self.trigger.edge, Edge::Rising, "Rising edge");
                ui.selectable_value(&mut self.trigger.edge, Edge::Falling, "Falling edge");
            });
        channel_select(
            ui,
            "trigger_channel",
            &mut self.trigger.channel,
            self.channels,
        );
        self.dirty |= before != (self.trigger.edge, self.trigger.channel);
        self.dirty |= ui
            .add(egui::Slider::new(&mut self.trigger.level, -1.0..=1.0).text("FS"))
            .changed();
    }

    fn spectrum_controls(&mut self, ui: &mut egui::Ui) {
        let before = (self.spectrum_settings, self.spectrum_channel);
        fft_precision(
            ui,
            "spectrum_precision",
            &mut self.spectrum_settings.precision,
        );
        setting_label(ui, "SOURCE CHANNEL");
        channel_select(
            ui,
            "spectrum_channel",
            &mut self.spectrum_channel,
            self.channels,
        );
        setting_label(ui, "FFT LENGTH");
        egui::ComboBox::from_id_salt("fft_size")
            .width(ui.available_width())
            .selected_text(format!("{} points", self.spectrum_settings.size))
            .show_ui(ui, |ui| {
                for size in FFT_SIZES {
                    ui.selectable_value(
                        &mut self.spectrum_settings.size,
                        size,
                        format!("{size} points"),
                    );
                }
            });
        setting_label(ui, "WINDOW");
        egui::ComboBox::from_id_salt("fft_window")
            .width(ui.available_width())
            .selected_text(self.spectrum_settings.window.name())
            .show_ui(ui, |ui| {
                for window in [Window::Hann, Window::BlackmanHarris, Window::Rectangular] {
                    ui.selectable_value(&mut self.spectrum_settings.window, window, window.name());
                }
            });
        setting_label(ui, "AVERAGING");
        egui::ComboBox::from_id_salt("fft_average")
            .width(ui.available_width())
            .selected_text(format!("Power average ×{}", self.spectrum_settings.averages))
            .show_ui(ui, |ui| {
                for count in [1, 4, 16, 64] {
                    ui.selectable_value(&mut self.spectrum_settings.averages, count, format!("Power average ×{count}"));
                }
            }).response.on_hover_text("Exponential average of linear power; alpha = 1 / count. Applied once per new FFT snapshot.");
        ui.checkbox(&mut self.spectrum_settings.remove_dc, "Remove DC offset");
        if before != (self.spectrum_settings, self.spectrum_channel) && self.running() {
            self.reset_analysis();
        }
        if !self.running() {
            ui.label(
                RichText::new(
                    "Analysis changes apply when input restarts. The captured spectrum stays held.",
                )
                .small()
                .color(MUTED),
            );
        }
        let view_before = (
            self.frequency_scale,
            self.floor_db,
            self.show_hold,
            self.span_hz,
        );
        ui.separator();
        setting_label(ui, "FREQUENCY AXIS");
        ui.horizontal(|ui| {
            ui.selectable_value(&mut self.frequency_scale, FrequencyScale::Log, "Log Hz");
            ui.selectable_value(
                &mut self.frequency_scale,
                FrequencyScale::Linear,
                "Linear Hz",
            );
        });
        egui::ComboBox::from_id_salt("spectrum_span")
            .width(ui.available_width())
            .selected_text(if self.span_hz == 0.0 {
                "Full / Nyquist".into()
            } else {
                format!("Span {}", frequency_label(self.span_hz))
            })
            .show_ui(ui, |ui| {
                ui.selectable_value(&mut self.span_hz, 0.0, "Full / Nyquist");
                for hz in [1000.0, 2000.0, 5000.0, 10000.0, 20000.0] {
                    ui.selectable_value(
                        &mut self.span_hz,
                        hz,
                        format!("Span {}", frequency_label(hz)),
                    );
                }
            });
        setting_label(ui, "DISPLAY FLOOR");
        ui.add(egui::Slider::new(&mut self.floor_db, -180.0..=-60.0).text("dBFS"));
        ui.horizontal(|ui| {
            if ui.checkbox(&mut self.show_hold, "Peak hold").changed() && self.show_hold {
                self.analyzer.clear_hold();
            }
            if ui.small_button("Clear hold").clicked() {
                self.analyzer.clear_hold();
                self.spectrum_dirty = true;
            }
        });
        self.spectrum_dirty |= view_before
            != (
                self.frequency_scale,
                self.floor_db,
                self.show_hold,
                self.span_hz,
            );
        ui.label(
            RichText::new(format!(
                "Δf {:.2} Hz · RBW {:.2} Hz\nWindow {:.1} ms · up to 30 FFT/s",
                self.analyzer.bin_hz(),
                self.analyzer.rbw_hz(),
                self.analyzer.settings().size as f32 / self.sample_rate as f32 * 1000.0
            ))
            .small()
            .color(MUTED),
        );
    }

    fn spectrogram_controls(&mut self, ui: &mut egui::Ui) {
        let before = (self.spectrogram_settings, self.spectrogram_channel);
        fft_precision(
            ui,
            "spectrogram_precision",
            &mut self.spectrogram_settings.precision,
        );
        setting_label(ui, "SOURCE CHANNEL");
        channel_select(
            ui,
            "spectrogram_channel",
            &mut self.spectrogram_channel,
            self.channels,
        );
        setting_label(ui, "FFT LENGTH");
        egui::ComboBox::from_id_salt("stft_size")
            .width(ui.available_width())
            .selected_text(format!("{} points", self.spectrogram_settings.size))
            .show_ui(ui, |ui| {
                for size in FFT_SIZES {
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
        ui.separator();
        setting_label(ui, "TIME SPAN");
        egui::ComboBox::from_id_salt("spectrogram_time")
            .width(ui.available_width())
            .selected_text(format!("{} s", self.spectrogram_seconds))
            .show_ui(ui, |ui| {
                for seconds in [0.5, 1.0, 2.0, 5.0, 10.0, 20.0] {
                    ui.selectable_value(
                        &mut self.spectrogram_seconds,
                        seconds,
                        format!("{seconds} s"),
                    );
                }
            });
        setting_label(ui, "FREQUENCY AXIS");
        ui.horizontal(|ui| {
            ui.selectable_value(&mut self.spectrogram_scale, FrequencyScale::Log, "Log Hz");
            ui.selectable_value(
                &mut self.spectrogram_scale,
                FrequencyScale::Linear,
                "Linear Hz",
            );
        });
        let nyquist = self.sample_rate as f32 * 0.5;
        ui.horizontal(|ui| {
            ui.label("From");
            ui.add(
                egui::DragValue::new(&mut self.spectrogram_min_hz)
                    .range(0.0..=nyquist)
                    .suffix(" Hz"),
            );
        });
        ui.horizontal(|ui| {
            ui.label("To");
            ui.add(
                egui::DragValue::new(&mut self.spectrogram_max_hz)
                    .range(0.0..=nyquist)
                    .suffix(" Hz"),
            );
        });
        ui.label(
            RichText::new("To = 0 uses Nyquist. Log scale excludes DC.")
                .small()
                .color(MUTED),
        );
        setting_label(ui, "COLOR RANGE");
        ui.add(egui::Slider::new(&mut self.spectrogram_floor, -180.0..=-20.0).text("Floor dBFS"));
        ui.add(egui::Slider::new(&mut self.spectrogram_ceiling, -20.0..=6.0).text("Ceiling dBFS"));
        self.spectrogram_ceiling = self.spectrogram_ceiling.max(self.spectrogram_floor + 1.0);
        ui.label(
            RichText::new(format!(
                "Hop {} samples · {:.2} ms/row\nFixed {} rows · up to {:.1} s retained",
                self.spectrogram_settings.size / 4,
                self.spectrogram_settings.size as f64 / 4.0 / self.sample_rate as f64 * 1000.0,
                spectrogram::ROWS,
                spectrogram::ROWS as f64 * self.spectrogram_settings.size as f64
                    / 4.0
                    / self.sample_rate as f64
            ))
            .small()
            .color(MUTED),
        );
        ui.label(RichText::new("Per-window bin amplitude, without power averaging or peak hold. Orange stripes mark missing STFT intervals.").small().color(MUTED));
    }

    fn spectrogram_view(&self) -> View {
        let config = self.spectrogram_history.lock().unwrap().config();
        let sample_rate = config.map_or(self.sample_rate, |c| c.sample_rate);
        let bin_hz =
            sample_rate as f32 / config.map_or(self.spectrogram_settings.size, |c| c.size) as f32;
        let max_hz = if self.spectrogram_max_hz == 0.0 {
            sample_rate as f32 * 0.5
        } else {
            self.spectrogram_max_hz
                .clamp(bin_hz, sample_rate as f32 * 0.5)
        };
        let lower = if self.spectrogram_scale == FrequencyScale::Log {
            bin_hz.min(1.0)
        } else {
            0.0
        };
        let max_hz = max_hz.max(bin_hz + lower);
        let min_hz = self.spectrogram_min_hz.max(lower).min(max_hz - bin_hz);
        View {
            scale: self.spectrogram_scale,
            min_hz,
            max_hz,
            floor_db: self.spectrogram_floor,
            ceiling_db: self.spectrogram_ceiling,
        }
    }

    fn spectrogram_panel(&mut self, ui: &mut egui::Ui) {
        egui::Frame::new()
            .fill(Color32::from_rgb(17, 27, 35))
            .stroke(Stroke::new(1.0, BORDER))
            .inner_margin(5.0)
            .show(ui, |ui| {
                compact_plot_style(ui);
                ui.horizontal(|ui| {
                    ui.label(RichText::new("Spectrogram").size(13.0).strong());
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if ui.small_button("Settings").clicked() {
                            self.sidebar.reveal(SettingsSection::Spectrogram);
                            ui.ctx().request_repaint();
                        }
                        let channel = self
                            .last_stft
                            .map_or(self.spectrogram_channel, |r| r.config.channel);
                        ui.label(
                            RichText::new(format!("CH {} · dBFS", channel + 1))
                                .small()
                                .color(BLUE),
                        );
                    });
                });
                {
                    let history = self.spectrogram_history.lock().unwrap();
                    ui.label(
                        RichText::new(if let Some(row) = history.latest() {
                            format!(
                                "End {:.3} s · {} rows · {:.2} s retained · N {} / hop {}",
                                row.end as f64 / row.config.sample_rate as f64,
                                history.len(),
                                history.retained_seconds(),
                                row.config.size,
                                row.config.hop
                            )
                        } else {
                            "Continuous STFT · sample-clock time · newest at top".into()
                        })
                        .small()
                        .color(MUTED),
                    );
                }
                let view = self.spectrogram_view();
                let (outer, response) =
                    ui.allocate_exact_size(plot_size(ui), egui::Sense::click_and_drag());
                let rect = egui::Rect::from_min_max(
                    outer.min + vec2(42.0, 4.0),
                    outer.max - vec2(14.0, 18.0),
                );
                let painter = ui.painter();
                painter.rect_filled(rect, 0.0, Color32::from_rgb(7, 14, 19));
                painter.add(egui_wgpu::Callback::new_paint_callback(
                    rect,
                    spectrogram_gpu::Callback {
                        history: self.spectrogram_history.clone(),
                        view,
                        seconds: self.spectrogram_seconds,
                        width: rect.width() * ui.ctx().pixels_per_point(),
                    },
                ));
                let age_divisions = if rect.height() < 72.0 { 2 } else { 4 };
                for i in 0..=age_divisions {
                    let y = rect.top() + rect.height() * i as f32 / age_divisions as f32;
                    painter.text(
                        pos2(rect.left() - 6.0, y),
                        egui::Align2::RIGHT_CENTER,
                        format!(
                            "{:.2}",
                            if i == 0 {
                                0.0
                            } else {
                                -(self.spectrogram_seconds * i as f64 / age_divisions as f64)
                            }
                        ),
                        egui::FontId::monospace(10.0),
                        MUTED,
                    );
                }
                for i in 0..=5 {
                    let x = i as f32 / 5.0;
                    painter.text(
                        pos2(rect.left() + rect.width() * x, rect.bottom() + 4.0),
                        egui::Align2::CENTER_TOP,
                        frequency_label(view.frequency(x)),
                        egui::FontId::monospace(10.0),
                        MUTED,
                    );
                }
                self.spectrogram_cursors(ui, &response, rect, view);
                let history = self.spectrogram_history.lock().unwrap();
                if history.is_empty() {
                    painter.text(
                        rect.center(),
                        egui::Align2::CENTER_CENTER,
                        if self.running() {
                            "Collecting a complete STFT window…"
                        } else {
                            "Start audio input or select Demo signal"
                        },
                        egui::FontId::proportional(14.0),
                        MUTED,
                    );
                }
                if let Some(position) = response.hover_pos().filter(|p| rect.contains(*p)) {
                    let age = (position.y - rect.top()) as f64 / rect.height() as f64
                        * self.spectrogram_seconds;
                    let hz = view.frequency((position.x - rect.left()) / rect.width());
                    let text = if let Some((row, db)) = history.at_age(age) {
                        let bin = (hz * row.config.size as f32 / row.config.sample_rate as f32)
                            .round() as usize;
                        format!(
                            "{:.1} Hz · {:.2} dBFS · samples {}..{}",
                            bin as f32 * row.config.sample_rate as f32 / row.config.size as f32,
                            db[bin.min(db.len() - 1)],
                            row.start,
                            row.end
                        )
                    } else {
                        "No STFT data at this time".into()
                    };
                    response.clone().on_hover_text(text);
                }
                drop(history);
                ui.horizontal(|ui| {
                    ui.label(RichText::new("Age / s").small().color(MUTED));
                    let (legend, _) = ui.allocate_exact_size(vec2(76.0, 8.0), egui::Sense::hover());
                    for i in 0..24 {
                        let t = i as f32 / 23.0;
                        let rgb = if t < 0.5 {
                            [
                                0.025 + 0.025 * t * 2.0,
                                0.04 + 0.51 * t * 2.0,
                                0.1 + 0.7 * t * 2.0,
                            ]
                        } else {
                            [
                                0.05 + 0.95 * (t - 0.5) * 2.0,
                                0.55 + 0.3 * (t - 0.5) * 2.0,
                                0.8 - 0.55 * (t - 0.5) * 2.0,
                            ]
                        };
                        ui.painter().rect_filled(
                            egui::Rect::from_min_max(
                                pos2(
                                    legend.left() + legend.width() * i as f32 / 24.0,
                                    legend.top(),
                                ),
                                pos2(
                                    legend.left() + legend.width() * (i + 1) as f32 / 24.0,
                                    legend.bottom(),
                                ),
                            ),
                            0.0,
                            Color32::from_rgb(
                                (rgb[0] * 255.0) as u8,
                                (rgb[1] * 255.0) as u8,
                                (rgb[2] * 255.0) as u8,
                            ),
                        );
                    }
                    ui.label(
                        RichText::new(format!("{:.0}…{:.0} dBFS", view.floor_db, view.ceiling_db))
                            .small()
                            .color(MUTED),
                    );
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.label(RichText::new("Frequency / Hz").small().color(MUTED));
                    });
                });
            });
    }

    fn sample_text(&self, sample: u64) -> String {
        if let Some(frame) = self.history.get(sample) {
            if self.channels >= 2 {
                format!(
                    "#{sample} · CH 1 {:+.5} · CH 2 {:+.5} FS",
                    frame[0], frame[1]
                )
            } else {
                format!("#{sample} · CH 1 {:+.5} FS", frame[0])
            }
        } else {
            format!("#{sample} · raw sample unavailable")
        }
    }

    fn scope_cursors(&mut self, ui: &egui::Ui, response: &egui::Response, rect: egui::Rect) {
        if let Some(position) = cursor_pointer(response, rect) {
            self.cursors.set_scope_time(
                self.active_cursor,
                ((position.x - rect.left()) / rect.width()) as f64,
            );
            ui.ctx().request_repaint();
        }
        for (index, time) in self.cursors.times.into_iter().enumerate() {
            let Some(time) = time else { continue };
            let sample = self.cursor_samples()[index];
            let fraction = time.scope_x().or_else(|| {
                sample.and_then(|sample| {
                    cursor::fraction_at_sample_with_offset(
                        self.scope_range.clone(),
                        sample,
                        self.scope_sample_offset,
                    )
                })
            });
            let text = if let Some(x) = fraction {
                cursor_line(ui, rect, x as f32, true, cursor_color(index));
                if let Some(frame) = sample.and_then(|sample| self.history.get(sample)) {
                    for (channel, value) in frame.iter().take(2).enumerate() {
                        if !self.enabled[channel] {
                            continue;
                        }
                        let position = pos2(
                            rect.left() + x as f32 * rect.width(),
                            rect.center().y
                                - (*value / (self.fs_per_div as f64 * 8.0)) as f32 * rect.height(),
                        );
                        if rect.contains(position) {
                            ui.painter()
                                .circle_filled(position, 3.0, cursor_color(index));
                        }
                    }
                }
                if let Some(sample) = sample
                    && let Some(seconds) = self.scope_cursor_seconds(sample)
                {
                    format!(
                        "{} {:+.3} ms · {}",
                        cursor_name(index),
                        seconds * 1000.0,
                        self.sample_text(sample)
                    )
                } else {
                    format!("{} · waiting for sweep", cursor_name(index))
                }
            } else if let Some(sample) = sample {
                format!("{} #{sample} · outside sweep", cursor_name(index),)
            } else {
                continue;
            };
            cursor_note(ui, rect, index, &text, cursor_color(index));
        }
    }

    fn spectrum_cursors(
        &mut self,
        ui: &egui::Ui,
        response: &egui::Response,
        rect: egui::Rect,
        view: View,
    ) {
        if let Some(position) = cursor_pointer(response, rect) {
            self.cursors.frequency_hz =
                Some(view.frequency((position.x - rect.left()) / rect.width()) as f64);
            ui.ctx().request_repaint();
        }
        let Some(frequency) = self.cursors.frequency_hz else {
            return;
        };
        let Some(reading) = self.analyzer.cursor(frequency) else {
            return;
        };
        let hz = reading.frequency_hz as f32;
        if hz >= view.min_hz && hz <= view.max_hz {
            cursor_line(ui, rect, view.x(hz), true, YELLOW);
        }
        let window = reading.window;
        let mut times = String::new();
        for (index, sample) in self.cursor_samples().into_iter().enumerate() {
            if let Some(sample) = sample {
                times.push_str(&format!(
                    " · {} {} window",
                    cursor_name(index),
                    if (window.start..window.end).contains(&sample) {
                        "in"
                    } else {
                        "outside"
                    }
                ));
            }
        }
        let text = format!(
            "F {:.1} Hz · {:.2} dBFS\nCH {} · {}..{} · avg ×{}",
            reading.frequency_hz,
            reading.dbfs,
            window.channel + 1,
            window.start,
            window.end,
            window.settings.averages
        );
        cursor_note(ui, rect, 0, &text, YELLOW);
        response.clone().on_hover_text(format!("Nearest bin of the displayed power spectrum. Latest contributing window: samples {}..{} (exclusive end), CH {}, {} Hz, {} points, {}, {}. Power average ×{}.{}", window.start, window.end, window.channel + 1, window.sample_rate, window.settings.size, window.settings.window.name(), window.settings.precision.name(), window.settings.averages, times));
    }

    fn spectrogram_cursors(
        &mut self,
        ui: &egui::Ui,
        response: &egui::Response,
        rect: egui::Rect,
        view: View,
    ) {
        if let Some(position) = cursor_pointer(response, rect) {
            self.cursors.set_spectrogram_time(
                self.active_cursor,
                ((position.y - rect.top()) / rect.height()) as f64,
            );
            self.cursors.frequency_hz =
                Some(view.frequency((position.x - rect.left()) / rect.width()) as f64);
            ui.ctx().request_repaint();
        }
        // Resolve shared times before taking the history lock.
        let samples = self.cursor_samples();
        let history = self.spectrogram_history.lock().unwrap();
        let latest = history.latest();
        let frequency = self.cursors.frequency_hz;
        if let Some(hz) = frequency
            && let Some(latest) = latest
            && let Some(bin) =
                cursor::nearest_bin(hz, latest.config.size, latest.config.sample_rate)
        {
            let hz = bin as f32 * latest.config.sample_rate as f32 / latest.config.size as f32;
            if hz >= view.min_hz && hz <= view.max_hz {
                cursor_line(ui, rect, view.x(hz), true, YELLOW);
            }
        }
        let frequency_only = self.cursors.times.iter().all(Option::is_none) && frequency.is_some();
        for (index, time) in self.cursors.times.into_iter().enumerate() {
            let fixed_y = time.and_then(|time| time.spectrogram_y());
            let sample = samples[index].or_else(|| {
                (frequency_only && index == self.active_cursor)
                    .then(|| latest?.end.checked_sub(1))
                    .flatten()
            });
            let age = fixed_y.map(|y| y * self.spectrogram_seconds).or_else(|| {
                let latest = latest?;
                Some(
                    cursor::signed_distance(latest.end - 1, sample?)
                        / latest.config.sample_rate as f64,
                )
            });
            let Some(age) = age else { continue };
            if age >= 0.0 && age <= self.spectrogram_seconds {
                cursor_line(
                    ui,
                    rect,
                    (age / self.spectrogram_seconds) as f32,
                    false,
                    cursor_color(index),
                );
            }
            let row = if fixed_y.is_some() {
                history.at_age(age)
            } else {
                sample.and_then(|sample| history.at_sample(sample))
            };
            let text = if let Some((row, db)) = row {
                if let Some(bin) = frequency
                    .and_then(|hz| cursor::nearest_bin(hz, row.config.size, row.config.sample_rate))
                {
                    format!(
                        "{} {:.1} Hz · {:.2} dBFS\nCH {} · {}..{}",
                        cursor_name(index),
                        bin as f64 * row.config.sample_rate as f64 / row.config.size as f64,
                        db[bin],
                        row.config.channel + 1,
                        row.start,
                        row.end
                    )
                } else {
                    format!(
                        "{} −{age:.3} s\nCH {} · {}..{}",
                        cursor_name(index),
                        row.config.channel + 1,
                        row.start,
                        row.end
                    )
                }
            } else {
                format!(
                    "{} −{age:.3} s\nNo STFT row · gap or unavailable",
                    cursor_name(index)
                )
            };
            cursor_note(ui, rect, index, &text, cursor_color(index));
        }
    }

    fn xy_cursors(
        &mut self,
        ui: &egui::Ui,
        response: &egui::Response,
        rect: egui::Rect,
        bounds: egui::Rect,
    ) {
        if let Some(position) = cursor_pointer(response, rect) {
            let fraction = [
                ((position.x - rect.left()) / rect.width()) as f64,
                ((position.y - rect.top()) / rect.height()) as f64,
            ];
            match self.xy_cursor_mode {
                xy::CursorMode::Free => self.cursors.set_xy_point(
                    self.active_cursor,
                    self.xy_settings.point_at_fraction(fraction),
                ),
                xy::CursorMode::TraceSnap => {
                    if let Some(sample) = xy::nearest_sample(
                        &self.history,
                        self.xy_capture.range.clone(),
                        self.xy_settings,
                        fraction,
                    ) {
                        self.cursors.set_trace_time(
                            self.active_cursor,
                            sample,
                            self.xy_capture.range.clone(),
                        );
                    }
                }
            }
            ui.ctx().request_repaint();
        }
        let samples = self.cursor_samples();
        let points = match self.xy_cursor_mode {
            xy::CursorMode::Free => self.cursors.xy_points,
            xy::CursorMode::TraceSnap => samples.map(|sample| {
                let sample = sample?;
                if !self.xy_capture.range.contains(&sample) {
                    return None;
                }
                let frame = self.history.get(sample).filter(|frame| frame.len() >= 2)?;
                Some([frame[0], frame[1]])
            }),
        };
        let painter = ui.painter().with_clip_rect(rect.intersect(ui.clip_rect()));
        let position = |point| {
            let [x, y] = self.xy_settings.fraction_at_point(point);
            pos2(
                rect.left() + x as f32 * rect.width(),
                rect.top() + y as f32 * rect.height(),
            )
        };
        if self.xy_cursor_mode == xy::CursorMode::TraceSnap
            && self.xy_capture.triggered
            && let Some(reference) = cursor::trigger_sample(self.xy_capture.range.clone())
            && let Some(frame) = self.history.get(reference)
        {
            let at = position([frame[0], frame[1]]);
            if rect.contains(at) {
                painter.circle_stroke(at, 5.0, Stroke::new(1.5, TRIGGER));
                painter.text(
                    at + vec2(-7.0, 7.0),
                    egui::Align2::RIGHT_TOP,
                    "T",
                    egui::FontId::monospace(10.0),
                    TRIGGER,
                );
            }
        }
        if let [Some(a), Some(b)] = points {
            painter.line_segment([position(a), position(b)], Stroke::new(1.0, MUTED));
        }
        for (index, point) in points.into_iter().enumerate() {
            let Some(point) = point else {
                if self.xy_cursor_mode == xy::CursorMode::TraceSnap
                    && self.cursors.times[index].is_some()
                {
                    cursor_note(
                        ui,
                        bounds,
                        index,
                        &format!("{} · outside XY window or unavailable", cursor_name(index)),
                        cursor_color(index),
                    );
                }
                continue;
            };
            let at = position(point);
            if rect.contains(at) {
                painter.circle_stroke(at, 4.0, Stroke::new(2.0, cursor_color(index)));
                painter.line_segment(
                    [at - vec2(7.0, 0.0), at + vec2(7.0, 0.0)],
                    Stroke::new(1.0, cursor_color(index)),
                );
                painter.line_segment(
                    [at - vec2(0.0, 7.0), at + vec2(0.0, 7.0)],
                    Stroke::new(1.0, cursor_color(index)),
                );
                painter.text(
                    at + vec2(6.0, -6.0),
                    egui::Align2::LEFT_BOTTOM,
                    cursor_name(index),
                    egui::FontId::monospace(10.0),
                    cursor_color(index),
                );
            }
            let detail = match self.xy_cursor_mode {
                xy::CursorMode::Free => {
                    if rect.contains(at) {
                        "Free".into()
                    } else {
                        "Free · outside plot".into()
                    }
                }
                xy::CursorMode::TraceSnap => {
                    let sample = samples[index].unwrap();
                    let reference = cursor::trigger_sample(self.xy_capture.range.clone()).unwrap();
                    format!(
                        "T{:+.3} ms · #{sample}",
                        cursor::signed_distance(sample, reference) * 1000.0
                            / self.sample_rate as f64
                    )
                }
            };
            cursor_note(
                ui,
                bounds,
                index,
                &format!(
                    "{} X {:+.4} FS · Y {:+.4} FS\n{detail}",
                    cursor_name(index),
                    point[0],
                    point[1]
                ),
                cursor_color(index),
            );
        }
        if let [Some(a), Some(b)] = points {
            let delta = [b[0] - a[0], b[1] - a[1]];
            cursor_note(
                ui,
                bounds,
                2,
                &format!("B−A ΔX {:+.4} · ΔY {:+.4} FS", delta[0], delta[1]),
                MUTED,
            );
        }
        response.clone().on_hover_text(match self.xy_cursor_mode {
            xy::CursorMode::Free => "Free: click or drag to fix X/Y amplitudes. A/B measure ΔX and ΔY independently of the moving trace. Free positions are retained when switching to Trace Snap.",
            xy::CursorMode::TraceSnap => "Trace Snap: selects the nearest actual CH 1/CH 2 pair and keeps its sample offset from the XY trigger. Uses Scope's trigger source, edge and level. Without a crossing, the reference moves with the latest window. Overlapping points select the latest sample; Stop freezes the capture.",
        });
    }

    fn xy_cursor_mode_controls(&mut self, ui: &mut egui::Ui) {
        let before = self.xy_cursor_mode;
        ui.selectable_value(&mut self.xy_cursor_mode, xy::CursorMode::Free, "Free")
            .on_hover_text(
                "Fix X/Y amplitudes independently of the moving trace. Measure ΔX and ΔY.",
            );
        ui.selectable_value(&mut self.xy_cursor_mode, xy::CursorMode::TraceSnap, "Trace Snap")
            .on_hover_text("Follow a real sample at a fixed time offset from the XY trigger. Uses Scope trigger settings.");
        if self.xy_cursor_mode != before {
            self.xy_dirty = true;
            ui.ctx().request_repaint();
        }
    }

    fn xy_controls(&mut self, ui: &mut egui::Ui) {
        ui.label(
            RichText::new("X = CH 1 · Y = CH 2 · synchronous frames")
                .small()
                .color(PURPLE),
        );
        setting_label(ui, "CURSOR MODE");
        ui.horizontal(|ui| self.xy_cursor_mode_controls(ui));
        ui.label(RichText::new(match self.xy_cursor_mode {
            xy::CursorMode::Free => "Free keeps X/Y amplitudes fixed and reads ΔX/ΔY. Free positions and shared time cursors are retained separately when switching modes.",
            xy::CursorMode::TraceSnap => "Trace Snap keeps time relative to the XY trigger. Source, edge and level use Scope settings. Auto/free run may move the marker; Stop freezes it.",
        }).small().color(MUTED));
        if self.channels < 2 {
            ui.label(
                RichText::new("XY requires at least two input channels.")
                    .small()
                    .color(YELLOW),
            );
        }
        let before = self.xy_settings;
        setting_label(ui, "OBSERVATION WINDOW");
        ui.add(
            egui::Slider::new(&mut self.xy_settings.milliseconds, 0.5..=200.0)
                .logarithmic(true)
                .text("ms"),
        );
        setting_label(ui, "X AMPLITUDE");
        ui.add(
            egui::Slider::new(&mut self.xy_settings.x_fs_per_div, 0.001..=0.5)
                .logarithmic(true)
                .text("FS / div"),
        );
        setting_label(ui, "Y AMPLITUDE");
        ui.add(
            egui::Slider::new(&mut self.xy_settings.y_fs_per_div, 0.001..=0.5)
                .logarithmic(true)
                .text("FS / div"),
        );
        if ui.button("Reset XY scales").clicked() {
            self.xy_settings = xy::Settings::default();
        }
        self.xy_dirty |= self.xy_settings != before;
        ui.label(RichText::new("Continuous samples are connected in time order. Free shows the latest window; Trace Snap uses a triggered window. Equal axis scales preserve circles on the square plot.").small().color(MUTED));
        ui.label(
            RichText::new(format!(
                "Up to {} real sample pairs; longer windows show the latest contiguous portion.",
                xy::MAX_POINTS
            ))
            .small()
            .color(MUTED),
        );
    }

    fn rebuild_xy(&mut self) {
        if !self.xy_dirty {
            return;
        }
        let started = Instant::now();
        self.xy_capture = xy::build_triggered_lines(
            &self.history,
            self.sample_rate,
            self.xy_settings,
            if self.xy_cursor_mode == xy::CursorMode::TraceSnap {
                self.trigger
            } else {
                Trigger {
                    edge: Edge::Free,
                    ..self.trigger
                }
            },
            &mut self.xy_lines,
        );
        // Preserve the trigger reference of shared Trace Snap cursors while
        // Free displays its independent latest-sample trajectory.
        self.xy_trace_range = if self.xy_cursor_mode == xy::CursorMode::TraceSnap {
            self.xy_capture.range.clone()
        } else if self
            .cursors
            .times
            .iter()
            .flatten()
            .any(|time| time.trace_offset().is_some())
        {
            xy::select_capture(
                &self.history,
                self.sample_rate,
                self.xy_settings,
                self.trigger,
            )
            .range
        } else {
            0..0
        };
        let segments = Arc::make_mut(&mut self.xy_segments);
        segments.clear();
        segments.extend(self.xy_lines.iter().map(|line| Segment {
            a: line.a,
            b: line.b,
            color: crate::gpu::XY_COLOR,
        }));
        self.xy_revision = self.xy_revision.wrapping_add(1);
        self.xy_dirty = false;
        self.xy_build_ms = started.elapsed().as_secs_f64() * 1000.0;
        #[cfg(feature = "qa")]
        if let Some(profile) = &mut self.profile {
            profile.record_work(crate::qa::Work::Xy, self.xy_build_ms);
        }
    }

    fn xy_panel(&mut self, ui: &mut egui::Ui) {
        egui::Frame::new()
            .fill(Color32::from_rgb(17, 27, 35))
            .stroke(Stroke::new(1.0, BORDER))
            .inner_margin(5.0)
            .show(ui, |ui| {
                compact_plot_style(ui);
                ui.horizontal(|ui| {
                    ui.label(RichText::new("XY / Lissajous").size(13.0).strong());
                    self.xy_cursor_mode_controls(ui);
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if ui.small_button("Settings").clicked() {
                            self.sidebar.reveal(SettingsSection::Xy);
                            ui.ctx().request_repaint();
                        }
                    });
                });
                ui.label(
                    RichText::new(format!(
                        "X: CH 1 · {:.3} FS/div   Y: CH 2 · {:.3} FS/div",
                        self.xy_settings.x_fs_per_div, self.xy_settings.y_fs_per_div
                    ))
                    .small()
                    .color(PURPLE),
                );
                let (outer, response) =
                    ui.allocate_exact_size(plot_size(ui), egui::Sense::click_and_drag());
                if response.double_clicked() {
                    self.xy_settings = xy::Settings::default();
                    self.xy_dirty = true;
                }
                self.rebuild_xy();
                let bounds = egui::Rect::from_min_max(
                    outer.min + vec2(42.0, 4.0),
                    outer.max - vec2(14.0, 18.0),
                );
                let side = bounds.width().min(bounds.height()).max(1.0);
                let rect = egui::Rect::from_center_size(bounds.center(), vec2(side, side));
                let painter = ui.painter();
                painter.rect_filled(rect, 0.0, Color32::from_rgb(7, 14, 19));
                for division in 0..=8 {
                    let fraction = division as f32 / 8.0;
                    let x = rect.left() + fraction * side;
                    let y = rect.top() + fraction * side;
                    let color = if division == 4 {
                        BORDER
                    } else {
                        Color32::from_rgb(24, 39, 47)
                    };
                    painter.line_segment(
                        [pos2(x, rect.top()), pos2(x, rect.bottom())],
                        Stroke::new(1.0, color),
                    );
                    painter.line_segment(
                        [pos2(rect.left(), y), pos2(rect.right(), y)],
                        Stroke::new(1.0, color),
                    );
                    if division % 4 == 0 {
                        painter.text(
                            pos2(x, rect.bottom() + 4.0),
                            egui::Align2::CENTER_TOP,
                            format!(
                                "{:.3}",
                                (division as f64 - 4.0) * self.xy_settings.x_fs_per_div
                            ),
                            egui::FontId::monospace(10.0),
                            MUTED,
                        );
                        painter.text(
                            pos2(rect.left() - 8.0, y),
                            egui::Align2::RIGHT_CENTER,
                            format!(
                                "{:.3}",
                                (4.0 - division as f64) * self.xy_settings.y_fs_per_div
                            ),
                            egui::FontId::monospace(10.0),
                            MUTED,
                        );
                    }
                }
                let ppp = ui.ctx().pixels_per_point();
                painter.add(egui_wgpu::Callback::new_paint_callback(
                    rect,
                    TraceCallback {
                        plot: PlotId::Xy,
                        segments: self.xy_segments.clone(),
                        dimensions: [side * ppp; 2],
                        width: 1.3 * ppp,
                        revision: self.xy_revision,
                    },
                ));
                if self.channels < 2 || self.xy_segments.is_empty() {
                    painter.text(
                        outer.center(),
                        egui::Align2::CENTER_CENTER,
                        if self.channels == 1 {
                            "XY unavailable: mono input"
                        } else if self.channels == 0 {
                            "XY requires two input channels"
                        } else {
                            "Waiting for sample pairs…"
                        },
                        egui::FontId::proportional(13.0),
                        MUTED,
                    );
                }
                if let Some(position) = response.hover_pos().filter(|point| rect.contains(*point)) {
                    response.clone().on_hover_text(format!(
                        "X {:+.4} FS · Y {:+.4} FS",
                        (position.x - rect.center().x) as f64 / side as f64
                            * self.xy_settings.x_fs_per_div
                            * 8.0,
                        (rect.center().y - position.y) as f64 / side as f64
                            * self.xy_settings.y_fs_per_div
                            * 8.0,
                    ));
                }
                self.xy_cursors(ui, &response, rect, bounds);
                let capture = &self.xy_capture;
                ui.label(
                    RichText::new(format!(
                        "{:.1} ms · samples {}..{}{}{}",
                        (capture.range.end - capture.range.start) as f64 * 1000.0
                            / self.sample_rate as f64,
                        capture.range.start,
                        capture.range.end,
                        if capture.limited {
                            " · point limit"
                        } else {
                            ""
                        },
                        if self.xy_cursor_mode == xy::CursorMode::Free {
                            ""
                        } else if capture.triggered {
                            " · Triggered"
                        } else if self.trigger.edge == Edge::Free {
                            " · Free run (moving reference)"
                        } else {
                            " · Auto (no crossing)"
                        }
                    ))
                    .small()
                    .color(MUTED),
                );
            });
    }

    fn workspace_controls(&mut self, ui: &mut egui::Ui) {
        setting_label(ui, "INSTRUMENT LAYOUT");
        egui::ComboBox::from_id_salt("plot_layout")
            .width(ui.available_width())
            .selected_text(self.plot_layout.name())
            .show_ui(ui, |ui| {
                for layout in [PlotLayout::Auto, PlotLayout::Columns, PlotLayout::Rows] {
                    ui.selectable_value(&mut self.plot_layout, layout, layout.name());
                }
            });
        ui.label(RichText::new("Side by side switches to stacked when space is limited. Hide Settings to give the plots more room.").small().color(MUTED));
        ui.separator();
        setting_label(ui, "SHORTCUTS");
        egui::Grid::new("shortcuts")
            .spacing(vec2(10.0, 8.0))
            .show(ui, |ui| {
                for (key, action) in [
                    ("Space", "Start / stop"),
                    ("Wheel", "Scope timebase"),
                    ("Shift + wheel", "Scope amplitude"),
                    ("Double click", "Reset scope scales"),
                ] {
                    ui.label(RichText::new(key).small().strong());
                    ui.label(RichText::new(action).small().color(MUTED));
                    ui.end_row();
                }
            });
        ui.separator();
        setting_label(ui, "MEASUREMENT UNITS");
        ui.label(RichText::new("Amplitude is digital full scale (FS). Spectrum is bin amplitude in dBFS: 0 dBFS = 1 FS sine peak. Δf is Fs / N; RBW is the window's equivalent noise bandwidth.").small().color(MUTED));
        ui.label(
            RichText::new(
                "Audio input uses the device's native sample rate. Demo signals stay internal.",
            )
            .small()
            .color(MUTED),
        );
    }

    fn scope_panel(&mut self, ui: &mut egui::Ui) {
        egui::Frame::new()
            .fill(Color32::from_rgb(17, 27, 35))
            .stroke(Stroke::new(1.0, Color32::from_rgb(48, 70, 82)))
            .inner_margin(5.0)
            .show(ui, |ui| {
                compact_plot_style(ui);
                ui.horizontal(|ui| {
                    ui.label(RichText::new("Oscilloscope").size(13.0).strong());
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if ui
                            .small_button("Settings")
                            .on_hover_text("Open timebase, amplitude and trigger settings")
                            .clicked()
                        {
                            self.sidebar.reveal(SettingsSection::Scope);
                            ui.ctx().request_repaint();
                        }
                        ui.label(
                            RichText::new(if self.triggered {
                                "TRIGGERED"
                            } else {
                                "AUTO / FREE"
                            })
                            .small()
                            .color(GREEN),
                        );
                    });
                });
                ui.horizontal_wrapped(|ui| {
                    ui.label(
                        RichText::new(format!(
                            "{} ms/div · {} FS/div",
                            self.ms_per_div, self.fs_per_div
                        ))
                        .small()
                        .color(MUTED),
                    );
                    for (index, color) in [GREEN, BLUE].into_iter().enumerate() {
                        if !self.enabled[index] || (index == 1 && self.channels < 2) {
                            continue;
                        }
                        let m = self.measurements[index];
                        ui.label(
                            RichText::new(format!(
                                "CH {}  RMS {:.3} · P-P {:.3} FS",
                                index + 1,
                                m.rms,
                                m.peak_to_peak
                            ))
                            .monospace()
                            .small()
                            .color(color),
                        )
                        .on_hover_text(format!("Peak {:.5} FS", m.peak));
                    }
                });
                self.plot(ui);
            });
    }

    fn spectrum_view(&self) -> View {
        let mut view = View::full(self.sample_rate, self.frequency_scale, self.floor_db);
        if self.span_hz > 0.0 {
            view.max_hz = self.span_hz.min(view.max_hz);
        }
        // Keep a valid log interval even for unusual low-rate input devices.
        view.min_hz = view.min_hz.min(view.max_hz * 0.1);
        view
    }

    fn spectrum_panel(&mut self, ui: &mut egui::Ui) {
        self.update_spectrum(false);
        egui::Frame::new()
            .fill(Color32::from_rgb(17, 27, 35))
            .stroke(Stroke::new(1.0, Color32::from_rgb(48, 70, 82)))
            .inner_margin(5.0)
            .show(ui, |ui| {
                compact_plot_style(ui);
                ui.horizontal(|ui| {
                    ui.label(RichText::new("Spectrum Analyzer").size(13.0).strong());
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if ui
                            .small_button("Settings")
                            .on_hover_text("Open FFT and spectrum display settings")
                            .clicked()
                        {
                            self.sidebar.reveal(SettingsSection::Spectrum);
                            ui.ctx().request_repaint();
                        }
                        ui.label(
                            RichText::new(format!(
                                "CH {} · dBFS",
                                self.analyzer
                                    .window()
                                    .map_or(self.spectrum_channel, |window| window.channel)
                                    + 1
                            ))
                            .small()
                            .color(YELLOW),
                        );
                    });
                });
                let view = self.spectrum_view();
                if let Some(peak) = self.analyzer.peak(view) {
                    ui.label(
                        RichText::new(format!(
                            "Peak bin  {:.1} Hz · {:.2} dBFS    Δf {:.2} Hz",
                            peak.frequency,
                            peak.dbfs,
                            self.analyzer.bin_hz()
                        ))
                        .monospace()
                        .small()
                        .color(YELLOW),
                    );
                } else {
                    ui.label(
                        RichText::new(
                            "Windowed FFT · coherent gain corrected · 0 dBFS = 1 FS sine peak",
                        )
                        .small()
                        .color(MUTED),
                    );
                }
                self.spectrum_plot(ui, view);
            });
    }

    fn spectrum_plot(&mut self, ui: &mut egui::Ui, view: View) {
        let (outer, response) =
            ui.allocate_exact_size(plot_size(ui), egui::Sense::click_and_drag());
        let rect =
            egui::Rect::from_min_max(outer.min + vec2(32.0, 4.0), outer.max - vec2(14.0, 18.0));
        let painter = ui.painter();
        painter.rect_filled(rect, 0.0, Color32::from_rgb(7, 14, 19));
        let label_step = (((view.ceiling_db - view.floor_db) * 14.0 / rect.height()) / 20.0)
            .ceil()
            .max(1.0) as i32
            * 20;
        for db in (view.floor_db as i32..=0).filter(|db| db % 20 == 0) {
            let y = rect.top()
                + (view.ceiling_db - db as f32) / (view.ceiling_db - view.floor_db) * rect.height();
            painter.line_segment(
                [pos2(rect.left(), y), pos2(rect.right(), y)],
                Stroke::new(1.0, Color32::from_rgb(24, 39, 47)),
            );
            if db % label_step == 0 || db == view.floor_db as i32 {
                painter.text(
                    pos2(rect.left() - 7.0, y),
                    egui::Align2::RIGHT_CENTER,
                    db.to_string(),
                    egui::FontId::monospace(10.0),
                    MUTED,
                );
            }
        }
        let ticks: Vec<(f32, bool)> = if view.scale == FrequencyScale::Linear {
            (0..=5)
                .map(|i| (view.max_hz * i as f32 / 5.0, true))
                .collect()
        } else {
            (0..=5)
                .flat_map(|power| {
                    (1..=9).map(move |multiple| {
                        (
                            10.0_f32.powi(power) * multiple as f32,
                            multiple == 1 || multiple == 2 || multiple == 5,
                        )
                    })
                })
                .filter(|(hz, _)| *hz >= view.min_hz && *hz <= view.max_hz)
                .collect()
        };
        let mut last_label = f32::NEG_INFINITY;
        for (hz, labelled) in ticks {
            let x = rect.left() + view.x(hz) * rect.width();
            painter.line_segment(
                [pos2(x, rect.top()), pos2(x, rect.bottom())],
                Stroke::new(
                    1.0,
                    if labelled {
                        Color32::from_rgb(29, 46, 55)
                    } else {
                        Color32::from_rgb(17, 28, 35)
                    },
                ),
            );
            if labelled && x - last_label >= 46.0 {
                painter.text(
                    pos2(x, rect.bottom() + 4.0),
                    egui::Align2::CENTER_TOP,
                    frequency_label(hz),
                    egui::FontId::monospace(10.0),
                    MUTED,
                );
                last_label = x;
            }
        }
        let ppp = ui.ctx().pixels_per_point();
        let pixels = (rect.width() * ppp).ceil().max(1.0) as usize;
        self.spectrum_dirty |= pixels != self.spectrum_pixels;
        self.spectrum_pixels = pixels;
        if self.spectrum_dirty {
            let started = Instant::now();
            self.spectrum_line_builder.build(
                &self.analyzer,
                view,
                pixels,
                self.show_hold,
                &mut self.spectrum_lines,
            );
            let segments = Arc::make_mut(&mut self.spectrum_segments);
            segments.clear();
            // Hold first, so the active trace remains bright wherever they overlap.
            for channel in [1, 0] {
                segments.extend(
                    self.spectrum_lines
                        .iter()
                        .filter(|line| line.channel == channel)
                        .map(|line| Segment {
                            a: line.a,
                            b: line.b,
                            color: if channel == 0 {
                                [1.0, 0.827, 0.259, 1.0]
                            } else {
                                [0.702, 0.529, 0.255, 0.7]
                            },
                        }),
                );
            }
            self.spectrum_revision = self.spectrum_revision.wrapping_add(1);
            self.spectrum_dirty = false;
            self.spectrum_build_ms = started.elapsed().as_secs_f64() * 1000.0;
            #[cfg(feature = "qa")]
            if let Some(profile) = &mut self.profile {
                profile.record_work(crate::qa::Work::Spectrum, self.spectrum_build_ms);
            }
        }
        painter.add(egui_wgpu::Callback::new_paint_callback(
            rect,
            TraceCallback {
                plot: PlotId::Spectrum,
                segments: self.spectrum_segments.clone(),
                dimensions: [rect.width() * ppp, rect.height() * ppp],
                width: 1.3 * ppp,
                revision: self.spectrum_revision,
            },
        ));
        if let Some(peak) = self.analyzer.peak(view) {
            let x = rect.left() + view.x(peak.frequency) * rect.width();
            painter.line_segment(
                [pos2(x, rect.top()), pos2(x, rect.top() + 10.0)],
                Stroke::new(2.0, YELLOW),
            );
        }
        if !self.analyzer.is_ready() {
            painter.text(
                rect.center(),
                egui::Align2::CENTER_CENTER,
                if self.running() {
                    "Collecting a complete FFT window…"
                } else {
                    "Start audio input or select Demo signal"
                },
                egui::FontId::proportional(16.0),
                MUTED,
            );
        }
        if let Some(position) = response.hover_pos().filter(|p| rect.contains(*p)) {
            let hz = view.frequency((position.x - rect.left()) / rect.width());
            let bin = (hz / self.analyzer.bin_hz()).round() as usize;
            painter.line_segment(
                [
                    pos2(position.x, rect.top()),
                    pos2(position.x, rect.bottom()),
                ],
                Stroke::new(1.0, Color32::from_white_alpha(65)),
            );
            let db = self
                .analyzer
                .db()
                .get(bin)
                .copied()
                .unwrap_or(spectrum::DB_MIN);
            painter.text(
                rect.right_top() + vec2(-10.0, 10.0),
                egui::Align2::RIGHT_TOP,
                format!(
                    "{:.1} Hz · {db:.2} dBFS",
                    bin as f32 * self.analyzer.bin_hz()
                ),
                egui::FontId::monospace(11.0),
                YELLOW,
            );
        }
        self.spectrum_cursors(ui, &response, rect, view);
        ui.horizontal(|ui| {
            ui.label(RichText::new("dBFS").small().color(MUTED));
            if self.show_hold {
                ui.label(RichText::new("Peak hold").small().color(HOLD));
            }
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                ui.label(RichText::new("Hz").small().color(MUTED));
            });
        });
    }

    fn plot(&mut self, ui: &mut egui::Ui) {
        let (outer, response) =
            ui.allocate_exact_size(plot_size(ui), egui::Sense::click_and_drag());
        let rect =
            egui::Rect::from_min_max(outer.min + vec2(42.0, 4.0), outer.max - vec2(28.0, 18.0));
        if response.hovered() {
            let (scroll, shift) = ui.input(|i| (i.smooth_scroll_delta.y, i.modifiers.shift));
            if scroll != 0.0 {
                let factor = (-scroll * 0.008).exp();
                if shift {
                    self.fs_per_div = (self.fs_per_div * factor).clamp(0.001, 0.5);
                } else {
                    self.ms_per_div = (self.ms_per_div * factor).clamp(0.05, 100.0);
                }
                self.dirty = true;
            }
        }
        if response.double_clicked() {
            self.ms_per_div = 1.0;
            self.fs_per_div = 0.25;
            self.dirty = true;
        }
        let painter = ui.painter();
        painter.rect_filled(rect, 0.0, Color32::from_rgb(7, 14, 19));
        for x in 0..=10 {
            let px = rect.left() + rect.width() * x as f32 / 10.0;
            painter.line_segment(
                [pos2(px, rect.top()), pos2(px, rect.bottom())],
                Stroke::new(1.0, Color32::from_rgb(24, 39, 47)),
            );
            painter.text(
                pos2(px, rect.bottom() + 4.0),
                egui::Align2::CENTER_TOP,
                format!("{:.1}", (x as f32 - 2.0) * self.ms_per_div),
                egui::FontId::monospace(10.0),
                MUTED,
            );
        }
        for y in 0..=8 {
            let py = rect.top() + rect.height() * y as f32 / 8.0;
            painter.line_segment(
                [pos2(rect.left(), py), pos2(rect.right(), py)],
                Stroke::new(
                    1.0,
                    if y == 4 {
                        Color32::from_rgb(44, 64, 72)
                    } else {
                        Color32::from_rgb(24, 39, 47)
                    },
                ),
            );
            let label_step = if rect.height() < 96.0 {
                4
            } else if rect.height() < 160.0 {
                2
            } else {
                1
            };
            if y % label_step == 0 {
                painter.text(
                    pos2(rect.left() - 8.0, py),
                    egui::Align2::RIGHT_CENTER,
                    format!("{:.3}", (4.0 - y as f32) * self.fs_per_div),
                    egui::FontId::monospace(10.0),
                    MUTED,
                );
            }
        }
        let ppp = ui.ctx().pixels_per_point();
        let pixels = (rect.width() * ppp).ceil().max(1.0) as usize;
        self.dirty |= pixels != self.pixels;
        self.pixels = pixels;
        if self.dirty {
            let started = Instant::now();
            self.refresh_scope_range();
            self.measurements = build_sweep_lines(
                &self.history,
                &Sweep {
                    range: self.scope_range.clone(),
                    triggered: self.triggered,
                    sample_offset: self.scope_sample_offset,
                },
                pixels,
                self.fs_per_div,
                [self.enabled[0], self.enabled[1] && self.channels >= 2],
                &mut self.lines,
            );
            let segments = Arc::make_mut(&mut self.segments);
            segments.clear();
            segments.extend(self.lines.iter().map(|line| Segment {
                a: line.a,
                b: line.b,
                color: COLORS[line.channel],
            }));
            self.revision = self.revision.wrapping_add(1);
            self.dirty = false;
            self.build_ms = started.elapsed().as_secs_f64() * 1000.0;
            #[cfg(feature = "qa")]
            if let Some(profile) = &mut self.profile {
                profile.record_work(crate::qa::Work::Scope, self.build_ms);
            }
        }
        painter.add(egui_wgpu::Callback::new_paint_callback(
            rect,
            TraceCallback {
                plot: PlotId::Scope,
                segments: self.segments.clone(),
                dimensions: [rect.width() * ppp, rect.height() * ppp],
                width: 1.4 * ppp,
                revision: self.revision,
            },
        ));
        if self.trigger.edge != Edge::Free {
            let tx = rect.left() + rect.width() * 0.2;
            painter.line_segment(
                [pos2(tx, rect.top()), pos2(tx, rect.top() + 12.0)],
                Stroke::new(2.0, TRIGGER),
            );
            painter.text(
                pos2(tx, rect.top() + 17.0),
                egui::Align2::CENTER_TOP,
                "T",
                egui::FontId::monospace(11.0),
                TRIGGER,
            );
            let ty = rect.center().y
                - (self.trigger.level / (self.fs_per_div as f64 * 8.0)) as f32 * rect.height();
            if rect.y_range().contains(ty) {
                // Keep the trigger-level indicator outside the waveform area.
                painter.add(egui::Shape::convex_polygon(
                    vec![
                        pos2(rect.right() + 2.0, ty),
                        pos2(rect.right() + 9.0, ty - 4.0),
                        pos2(rect.right() + 9.0, ty + 4.0),
                    ],
                    TRIGGER,
                    Stroke::NONE,
                ));
                painter.text(
                    pos2(rect.right() + 12.0, ty),
                    egui::Align2::LEFT_CENTER,
                    "T",
                    egui::FontId::monospace(10.0),
                    TRIGGER,
                );
                ui.interact(
                    egui::Rect::from_min_max(
                        pos2(rect.right(), ty - 8.0),
                        pos2(rect.right() + 26.0, ty + 8.0),
                    ),
                    ui.id().with("trigger_level_marker"),
                    egui::Sense::hover(),
                )
                .on_hover_text(format!(
                    "Trigger level · CH {} · {:+.3} FS",
                    self.trigger.channel + 1,
                    self.trigger.level
                ));
            }
        }
        if self.segments.is_empty() && self.history.len() < self.scope_sample_count() {
            painter.text(
                rect.center(),
                egui::Align2::CENTER_CENTER,
                if self.running() {
                    "Waiting for audio samples…"
                } else {
                    "Choose an audio input and press Start input"
                },
                egui::FontId::proportional(17.0),
                MUTED,
            );
        }
        if let Some(position) = response.hover_pos().filter(|p| rect.contains(*p)) {
            painter.line_segment(
                [
                    pos2(position.x, rect.top()),
                    pos2(position.x, rect.bottom()),
                ],
                Stroke::new(1.0, Color32::from_white_alpha(65)),
            );
            if let Some(sample) = cursor::sample_at_fraction_with_offset(
                self.scope_range.clone(),
                ((position.x - rect.left()) / rect.width()) as f64,
                self.scope_sample_offset,
            ) {
                response.clone().on_hover_text(self.sample_text(sample));
            }
        }
        self.scope_cursors(ui, &response, rect);
        ui.horizontal(|ui| {
            ui.label(RichText::new("FS").small().color(MUTED));
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                ui.label(RichText::new("time / ms").small().color(MUTED));
            });
        });
    }
}

impl eframe::App for ScopeApp {
    fn ui(&mut self, ui: &mut egui::Ui, frame: &mut eframe::Frame) {
        #[cfg(not(feature = "qa"))]
        let _ = frame;
        let ctx = ui.ctx().clone();
        let now = Instant::now();
        let elapsed = now.duration_since(self.last_frame).as_secs_f64();
        self.last_frame = now;
        if elapsed > 0.0 && elapsed < 0.2 {
            self.fps = self.fps * 0.9 + 0.1 / elapsed;
        }
        #[cfg(feature = "qa")]
        let input_started = Instant::now();
        self.poll_audio();
        self.poll_demo();
        #[cfg(feature = "qa")]
        if self.running()
            && let Some(profile) = &mut self.profile
        {
            profile.record_work(
                crate::qa::Work::Input,
                input_started.elapsed().as_secs_f64() * 1000.0,
            );
            profile.record_input_loss(self.dropped);
        }
        let started = Instant::now();
        self.stft.drain(|row| {
            if self
                .spectrogram_history
                .lock()
                .unwrap()
                .push(row.info, row.db())
            {
                self.last_stft = Some(row.info);
            }
        });
        self.spectrogram_build_ms = started.elapsed().as_secs_f64() * 1000.0;
        #[cfg(feature = "qa")]
        {
            if self.running()
                && let Some(profile) = &mut self.profile
            {
                profile.record_work(crate::qa::Work::Spectrogram, self.spectrogram_build_ms);
            }
            self.check_lifecycle(&ctx, elapsed);
            self.check_input_lifecycle(&ctx);
            let running = self.running();
            if let Some(profile) = &mut self.profile {
                profile.record(elapsed, running, frame.info().cpu_usage);
                if profile.finished() {
                    assert!(self.error.is_none(), "UI QA input failed: {:?}", self.error);
                    if std::env::var_os("MEASURELAB_PROFILE_LIFECYCLE").is_some() {
                        assert_eq!(self.lifecycle_stage, 8, "UI lifecycle did not finish");
                    }
                    if std::env::var_os("MEASURELAB_PROFILE_INPUT_LIFECYCLE").is_some() {
                        assert_eq!(self.lifecycle_stage, 6, "input lifecycle did not finish");
                    }
                    profile.report(self.dropped);
                    println!(
                        "STFT profile: {} Hz, {} ch, CH {}, {}-point {:?}, rows {}, input dropped {}, result dropped {}, worker CPU {:.3} ms total",
                        self.sample_rate,
                        self.channels,
                        self.spectrogram_channel + 1,
                        self.spectrogram_settings.size,
                        self.spectrogram_settings.precision,
                        self.stft.metrics.produced.load(Ordering::Relaxed),
                        self.stft.metrics.input_dropped.load(Ordering::Relaxed),
                        self.stft.metrics.result_dropped.load(Ordering::Relaxed),
                        self.stft.metrics.processing_nanos.load(Ordering::Relaxed) as f64 / 1e6
                    );
                    let history = self.spectrogram_history.lock().unwrap();
                    println!(
                        "Spectrogram profile: {} retained rows, {:.1} MiB CPU storage",
                        history.len(),
                        history.storage_bytes() as f64 / 1048576.0
                    );
                    self.profile = None;
                    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                }
                if running || std::env::var_os("MEASURELAB_PROFILE_IDLE").is_none() {
                    ctx.request_repaint();
                }
                if std::env::var_os("MEASURELAB_PROFILE_SCREENSHOT").is_some()
                    && !self.screenshot_requested
                    && self.created.elapsed() > Duration::from_secs(3)
                {
                    self.screenshot_requested = true;
                    ctx.send_viewport_cmd(egui::ViewportCommand::Screenshot(Default::default()));
                }
            }
        }
        // Input validity must not depend on whether its settings are expanded.
        {
            let last_channel = self.channels.max(1) as usize - 1;
            if self.spectrum_channel > last_channel {
                self.spectrum_channel = last_channel;
                self.reset_analysis();
            }
            if self.trigger.channel > last_channel {
                self.trigger.channel = last_channel;
                self.dirty = true;
            }
        }
        #[cfg(feature = "qa")]
        if self.smoke || self.profile.is_some() {
            let screenshot = ctx.input(|input| {
                input.events.iter().find_map(|event| {
                    if let egui::Event::Screenshot { image, .. } = event {
                        Some(image.clone())
                    } else {
                        None
                    }
                })
            });
            if let Some(image) = screenshot
                && let Err(error) = save_screenshot(&image)
            {
                eprintln!("UI screenshot failed: {error}");
            }
        }
        if ctx.input(|i| i.key_pressed(egui::Key::Space))
            && !self.busy
            && !ctx.egui_wants_keyboard_input()
        {
            if self.running() {
                self.stop();
            } else {
                self.start();
            }
        }
        egui::Panel::top("header").show(ui, |ui| {
            ui.add_space(2.0);
            ui.horizontal(|ui| {
                let mut title = egui::text::LayoutJob::default();
                RichText::new("MeasureLab")
                    .size(21.0)
                    .strong()
                    .color(GREEN)
                    .append_to(
                        &mut title,
                        ui.style(),
                        egui::FontSelection::Default,
                        egui::Align::Center,
                    );
                RichText::new(" ⭐")
                    .size(14.0)
                    .raised()
                    .color(YELLOW)
                    .append_to(
                        &mut title,
                        ui.style(),
                        egui::FontSelection::Default,
                        egui::Align::Center,
                    );
                ui.label(title);
                ui.label(
                    RichText::new("AUDIO MEASUREMENT LAB")
                        .size(12.0)
                        .color(MUTED),
                );
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    self.transport(ui);
                    ui.separator();
                    ui.label(
                        RichText::new(if self.busy {
                            "OPENING DEVICE…"
                        } else if self.smoke {
                            "UI TEST FIXTURE"
                        } else if self.demo_running {
                            "● DEMO SIGNAL"
                        } else if self.capture.is_some() {
                            "● LIVE INPUT"
                        } else {
                            "○ STOPPED"
                        })
                        .monospace()
                        .color(if self.running() { GREEN } else { MUTED }),
                    );
                });
            });
            ui.add_space(4.0);
        });
        egui::Panel::bottom("status").show(ui, |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.label(
                    RichText::new(format!(
                        "{:.1} kSa/s · {} ch · {}",
                        self.sample_rate as f32 / 1000.0,
                        self.channels,
                        if self.format.is_empty() {
                            "No active input"
                        } else {
                            &self.format
                        }
                    ))
                    .small()
                    .color(MUTED),
                );
                ui.separator();
                ui.label(
                    RichText::new(format!("Dropped {}", self.dropped))
                        .small()
                        .color(if self.dropped > 0 { YELLOW } else { MUTED }),
                );
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    ui.menu_button(RichText::new("Performance").small(), |ui| {
                        ui.label(RichText::new(&self.adapter).small().color(MUTED));
                        ui.separator();
                        ui.label(format!("UI {:.0} fps", self.fps));
                        ui.label(format!("Scope prep {:.2} ms", self.build_ms));
                        ui.label(format!("FFT {:.2} ms", self.fft_ms));
                        ui.label(format!("Spectrum prep {:.2} ms", self.spectrum_build_ms));
                        ui.label(format!("XY prep {:.2} ms", self.xy_build_ms));
                        ui.label(format!(
                            "Spectrogram history {:.2} ms",
                            self.spectrogram_build_ms
                        ));
                        let history = self.spectrogram_history.lock().unwrap();
                        ui.label(format!(
                            "Spectrogram {} / {} rows · {:.1} MiB CPU storage",
                            history.len(),
                            spectrogram::ROWS,
                            history.storage_bytes() as f64 / 1048576.0
                        ));
                        ui.label(format!(
                            "STFT input dropped {} · rows dropped {}",
                            self.stft.metrics.input_dropped.load(Ordering::Relaxed),
                            self.stft.metrics.result_dropped.load(Ordering::Relaxed)
                        ));
                        if let Some(row) = self.last_stft {
                            ui.label(format!(
                                "STFT CH {} · N {} / hop {} · samples {}..{}",
                                row.config.channel + 1,
                                row.config.size,
                                row.config.hop,
                                row.start,
                                row.end
                            ));
                        }
                        ui.label(format!(
                            "{} GPU segments",
                            self.segments.len()
                                + self.spectrum_segments.len()
                                + self.xy_segments.len()
                        ));
                        ui.label(
                            RichText::new("Timings are CPU work, not GPU execution.")
                                .small()
                                .color(MUTED),
                        );
                    });
                });
            });
        });
        if self.sidebar.visible {
            egui::Panel::left("controls")
                .default_size(280.0)
                .size_range(260.0..=360.0)
                .resizable(true)
                .show(ui, |ui| {
                    ui.horizontal(|ui| {
                        ui.label(RichText::new("SETTINGS").small().strong().color(MUTED));
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            if ui
                                .add_enabled(
                                    self.sidebar.section.is_some(),
                                    egui::Button::new("Collapse all").small(),
                                )
                                .clicked()
                            {
                                self.sidebar.section = None;
                                self.sidebar.focus = false;
                                ui.ctx().request_repaint();
                            }
                        });
                    });
                    ui.separator();
                    egui::ScrollArea::vertical()
                        .id_salt("settings_scroll")
                        .auto_shrink([false, false])
                        .show(ui, |ui| self.controls(ui));
                });
        }
        // Resolve X-anchored cursors against this frame's sweep, including when
        // Scope is hidden. The other instruments must not read a stale ID.
        self.refresh_scope_range();
        // Trace offsets must resolve against current XY samples even if XY is hidden.
        if self.xy_cursor_mode == xy::CursorMode::TraceSnap
            || self
                .cursors
                .times
                .iter()
                .flatten()
                .any(|time| time.trace_offset().is_some())
        {
            self.xy_dirty |= self.dirty;
            self.rebuild_xy();
        }
        egui::CentralPanel::default().show(ui, |ui| {
            ui.spacing_mut().item_spacing = vec2(6.0, 4.0);
            ui.horizontal_wrapped(|ui| {
                for (index, title) in ["Scope", "Spectrum", "Spectrogram", "XY"]
                    .into_iter()
                    .enumerate()
                {
                    let enabled =
                        self.visible.iter().filter(|v| **v).count() > 1 || !self.visible[index];
                    if ui
                        .add_enabled(
                            enabled,
                            egui::Button::new(title).selected(self.visible[index]),
                        )
                        .clicked()
                    {
                        self.visible[index] = !self.visible[index];
                    }
                }
                self.cursor_controls(ui);
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if ui
                        .selectable_label(self.sidebar.visible, "Settings")
                        .on_hover_text("Show or hide the settings sidebar")
                        .clicked()
                    {
                        self.sidebar.visible = !self.sidebar.visible;
                        ui.ctx().request_repaint();
                    }
                });
            });
            if let Some(error) = &self.error {
                ui.colored_label(Color32::from_rgb(255, 170, 116), error);
            }
            ui.add_space(4.0);
            let available = ui.available_size();
            let instruments: Vec<_> = [
                Instrument::Scope,
                Instrument::Spectrum,
                Instrument::Spectrogram,
                Instrument::Xy,
            ]
            .into_iter()
            .enumerate()
            .filter_map(|(i, plot)| self.visible[i].then_some(plot))
            .collect();
            let columns = instruments.len() > 1 && self.plot_layout.columns(available.x);
            let rows = if columns {
                instruments.len().div_ceil(2)
            } else {
                instruments.len()
            };
            let gap = ui.spacing().item_spacing;
            let height = ((available.y - gap.y * (rows - 1) as f32) / rows as f32).max(132.0);
            let scroll = egui::ScrollArea::vertical().auto_shrink([false, false]);
            #[cfg(feature = "qa")]
            let scroll = if self.smoke
                && std::env::var_os("MEASURELAB_UI_SMOKE_SCROLL_END").is_some()
            {
                scroll
                    .vertical_scroll_offset((rows as f32 * (height + gap.y) - available.y).max(0.0))
            } else {
                scroll
            };
            scroll.show(ui, |ui| {
                for plots in instruments.chunks(if columns { 2 } else { 1 }) {
                    ui.horizontal_top(|ui| {
                        let width =
                            (available.x - gap.x * (plots.len() - 1) as f32) / plots.len() as f32;
                        for &plot in plots {
                            ui.allocate_ui_with_layout(
                                vec2(width, height),
                                egui::Layout::top_down(egui::Align::Min),
                                |ui| match plot {
                                    Instrument::Scope => self.scope_panel(ui),
                                    Instrument::Spectrum => self.spectrum_panel(ui),
                                    Instrument::Spectrogram => self.spectrogram_panel(ui),
                                    Instrument::Xy => self.xy_panel(ui),
                                },
                            );
                        }
                    });
                }
            });
        });
        if self.running() || self.busy {
            // Let VSync pace acquisition frames without an additional timer.
            ctx.request_repaint();
        }
        if self.smoke {
            #[cfg(feature = "qa")]
            if !self.screenshot_requested && self.created.elapsed() > Duration::from_secs(1) {
                self.screenshot_requested = true;
                ctx.send_viewport_cmd(egui::ViewportCommand::Screenshot(Default::default()));
            }
            if self.created.elapsed() > Duration::from_secs(2) {
                println!("UI OK: {}", self.adapter);
                ctx.send_viewport_cmd(egui::ViewportCommand::Close);
            } else {
                ctx.request_repaint_after(Duration::from_millis(16));
            }
        }
    }
}

fn compact_plot_style(ui: &mut egui::Ui) {
    ui.spacing_mut().item_spacing = vec2(6.0, 3.0);
    ui.spacing_mut().button_padding = vec2(4.0, 1.0);
    ui.spacing_mut().interact_size.y = 16.0;
}

fn cursor_name(index: usize) -> &'static str {
    if index == 0 { "A" } else { "B" }
}

fn cursor_color(index: usize) -> Color32 {
    if index == 0 { GREEN } else { PURPLE }
}

fn cursor_pointer(response: &egui::Response, rect: egui::Rect) -> Option<egui::Pos2> {
    if (response.clicked() || response.dragged()) && !response.double_clicked() {
        response
            .interact_pointer_pos()
            .filter(|point| rect.contains(*point))
    } else {
        None
    }
}

fn cursor_line(ui: &egui::Ui, rect: egui::Rect, fraction: f32, vertical: bool, color: Color32) {
    let points = if vertical {
        let x = rect.left() + fraction * rect.width();
        [pos2(x, rect.top()), pos2(x, rect.bottom())]
    } else {
        let y = rect.top() + fraction * rect.height();
        [pos2(rect.left(), y), pos2(rect.right(), y)]
    };
    ui.painter().line_segment(points, Stroke::new(1.0, color));
}

fn cursor_note(ui: &egui::Ui, rect: egui::Rect, index: usize, text: &str, color: Color32) {
    let painter = ui.painter().with_clip_rect(rect.intersect(ui.clip_rect()));
    let galley = painter.layout_no_wrap(text.into(), egui::FontId::monospace(10.0), color);
    let position = rect.right_top() + vec2(-galley.size().x - 4.0, 4.0 + index as f32 * 26.0);
    painter.rect_filled(
        egui::Rect::from_min_size(position - vec2(2.0, 1.0), galley.size() + vec2(4.0, 2.0)),
        2.0,
        Color32::from_rgba_unmultiplied(7, 14, 19, 220),
    );
    painter.galley(position, galley, color);
}

fn plot_size(ui: &egui::Ui) -> egui::Vec2 {
    // Reserve a compact footer without taking space from the data rectangle.
    let footer_height = ui.spacing().interact_size.y + ui.spacing().item_spacing.y;
    vec2(
        ui.available_width(),
        (ui.available_height() - footer_height).max(44.0),
    )
}

fn setting_label(ui: &mut egui::Ui, text: &str) {
    ui.label(RichText::new(text).small().color(MUTED));
}

fn fft_precision(ui: &mut egui::Ui, id: &str, precision: &mut Precision) {
    setting_label(ui, "FFT PRECISION");
    egui::ComboBox::from_id_salt(id)
        .width(ui.available_width())
        .selected_text(precision.name())
        .show_ui(ui, |ui| {
            for mode in [Precision::F64, Precision::F32] {
                ui.selectable_value(precision, mode, mode.name());
            }
        })
        .response
        .on_hover_text("Only this instrument's FFT changes precision. Input history, DC removal and power averaging use 64-bit.");
}

fn channel_select(ui: &mut egui::Ui, id: &str, selected: &mut usize, channels: u16) {
    egui::ComboBox::from_id_salt(id)
        .width(ui.available_width())
        .selected_text(format!("CH {}", *selected + 1))
        .show_ui(ui, |ui| {
            for channel in 0..channels.max(1) as usize {
                ui.selectable_value(selected, channel, format!("CH {}", channel + 1));
            }
        });
}

fn frequency_label(hz: f32) -> String {
    if hz >= 1000.0 {
        format!(
            "{}k",
            format!("{:.2}", hz / 1000.0)
                .trim_end_matches('0')
                .trim_end_matches('.')
        )
    } else {
        format!("{hz:.0}")
    }
}

#[cfg(feature = "qa")]
fn save_screenshot(image: &egui::ColorImage) -> Result<(), Box<dyn std::error::Error>> {
    std::fs::create_dir_all("dist")?;
    let file = std::fs::File::create("dist/ui-smoke.png")?;
    let mut encoder = png::Encoder::new(file, image.width() as u32, image.height() as u32);
    encoder.set_color(png::ColorType::Rgba);
    encoder.set_depth(png::BitDepth::Eight);
    encoder.write_header()?.write_image_data(image.as_raw())?;
    println!("UI screenshot: dist/ui-smoke.png");
    Ok(())
}
