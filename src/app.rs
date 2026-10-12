#[cfg(feature = "qa")]
use crate::demo::{Demo, Waveform};
use crate::{
    acquisition,
    audio::{AudioWorker, Command, DeviceInfo, Event},
    calibration::{self, Calibration, Reading},
    channel::{self, ChannelId, Pair},
    cursor::{self, Cursors},
    export,
    gpu::{COLORS, PlotId, Segment, TraceCallback, TraceRenderer},
    lockin, loopback,
    measurement::{self, ScopeSettings, SpectrumMode},
    settings::{self, PlotLayout},
    signal::{Edge, History, Line, Measurement, Sweep, Trigger, build_sweep_lines},
    spectrogram, spectrogram_gpu,
    spectrum::{
        self, Analyzer, FFT_SIZES, FrequencyScale, Precision, Quantity, STFT_SIZES, Settings, View,
        Window,
    },
    stft::{self, RowInfo},
    workspace_io, xy,
};
use eframe::{
    egui::{self, Color32, RichText, Stroke, pos2, vec2},
    egui_wgpu,
};
use std::{
    sync::{Arc, Mutex, atomic::Ordering},
    time::{Duration, Instant},
};
mod lockin_panel;
mod workspace;

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
    Software,
    #[cfg(feature = "qa")]
    Demo,
}

impl Source {
    fn on_startup(demo: bool, smoke: bool) -> Result<Self, &'static str> {
        if demo || smoke {
            #[cfg(feature = "qa")]
            return Ok(Self::Demo);
            #[cfg(not(feature = "qa"))]
            return Err("Internal signals require --features qa");
        }
        Ok(Self::Live)
    }

    fn is_demo(self) -> bool {
        match self {
            Self::Live | Self::Software => false,
            #[cfg(feature = "qa")]
            Self::Demo => true,
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Instrument {
    Scope,
    Spectrum,
    Spectrogram,
    Xy,
    Lockin,
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

#[derive(Clone, Copy, PartialEq, Eq)]
enum SettingsTask {
    Save,
    Restore,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
enum SettingsSection {
    Input,
    Scope,
    Spectrum,
    Spectrogram,
    Xy,
    Lockin,
    Calibration,
    Workspace,
}

impl SettingsSection {
    const ALL: [Self; 8] = [
        Self::Input,
        Self::Scope,
        Self::Spectrum,
        Self::Spectrogram,
        Self::Xy,
        Self::Lockin,
        Self::Calibration,
        Self::Workspace,
    ];

    fn title(self) -> &'static str {
        match self {
            Self::Input => "Input source",
            Self::Scope => "Oscilloscope",
            Self::Spectrum => "Spectrum analyzer",
            Self::Spectrogram => "Spectrogram",
            Self::Xy => "XY / Lissajous",
            Self::Lockin => "Lock-in amplifier",
            Self::Calibration => "Channel calibration",
            Self::Workspace => "Workspace & help",
        }
    }

    fn color(self) -> Color32 {
        match self {
            Self::Input | Self::Calibration | Self::Workspace => Color32::from_rgb(192, 207, 217),
            Self::Scope => GREEN,
            Self::Spectrum => YELLOW,
            Self::Spectrogram => BLUE,
            Self::Xy => PURPLE,
            Self::Lockin => YELLOW,
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

struct CalibrationEditor {
    pending: calibration::Set,
    captured: calibration::Set,
    channel: ChannelId,
    gain: f64,
    offset: f64,
    unit: String,
    conditions: String,
    session_id: String,
    revision: u64,
    error: Option<String>,
}

impl Default for CalibrationEditor {
    fn default() -> Self {
        Self {
            pending: calibration::Set::default(),
            captured: calibration::Set::default(),
            channel: 0,
            gain: 1.0,
            offset: 0.0,
            unit: "V".into(),
            conditions: String::new(),
            session_id: format!(
                "scope-{}",
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_nanos()
            ),
            revision: 0,
            error: None,
        }
    }
}

impl CalibrationEditor {
    fn select(&mut self) {
        if let Some(calibration) = self.pending.get(self.channel) {
            self.gain = calibration.gain();
            self.offset = calibration.offset();
            self.unit = calibration.unit().into();
            self.conditions = calibration.conditions().into();
        } else {
            self.gain = 1.0;
            self.offset = 0.0;
            self.unit = "V".into();
            self.conditions.clear();
        }
        self.error = None;
    }

    fn clear_input(&mut self) {
        self.pending = calibration::Set::default();
        self.select();
    }

    fn apply(&mut self) -> Result<(), &'static str> {
        let revision = self
            .revision
            .checked_add(1)
            .ok_or("Calibration revision exhausted")?;
        let calibration = Calibration::new(
            format!("{}-ch{}", self.session_id, self.channel + 1),
            revision,
            self.gain,
            self.offset,
            self.unit.clone(),
            self.conditions.clone(),
        )?;
        self.pending = self.pending.with(self.channel, Some(calibration))?;
        self.revision = revision;
        self.error = None;
        Ok(())
    }
}

pub struct ScopeApp {
    source: Source,
    software_running: bool,
    loopback_settings: loopback::Settings,
    lockin_settings: lockin::Settings,
    lockin_result: lockin::Result,
    lockin_visible: bool,
    lockin_display: settings::LockinDisplay,
    workspace_io: workspace_io::Worker,
    workspace_pending: bool,
    workspace_restoring: bool,
    workspace_status: Option<String>,
    reference: Option<Box<export::Document>>,
    reference_label: String,
    compare_open: bool,
    comparison_current: Option<Box<export::Document>>,
    visible: [bool; 4],
    plot_layout: PlotLayout,
    previous_view: Option<([bool; 4], bool, PlotLayout)>,
    spectrum_adjust_analysis: bool,
    sidebar: Sidebar,
    #[cfg(feature = "qa")]
    demo: Demo,
    #[cfg(feature = "qa")]
    demo_enabled: bool,
    demo_running: bool,
    core: Option<measurement::Worker>,
    pending_stop: Option<measurement::PendingSnapshot>,
    pending_scope: Option<measurement::PendingSnapshot>,
    #[cfg(feature = "qa")]
    known_output: Option<(cpal::Stream, Arc<std::sync::atomic::AtomicBool>)>,
    start_after_stop: bool,
    spectrum_publication: (u64, u64),
    input_generation: u64,
    snapshot_revision: u64,
    core_scope: ScopeSettings,
    acquisition_mode: acquisition::Mode,
    acquisition_state: acquisition::State,
    scope_capture: Option<History>,
    autoset_pending: Option<std::sync::mpsc::Receiver<Result<acquisition::Autoset, String>>>,
    autoset_status: Option<String>,
    scope_channels: Pair,
    xy_channels: Pair,
    spectrum_mode: SpectrumMode,
    spectrum_info: measurement::SpectrumInfo,
    stft_generation: u64,
    spectrum_settings: Settings,
    analyzer: spectrum::Result,
    spectrum_channel: ChannelId,
    frequency_scale: FrequencyScale,
    floor_db: f32,
    spectrum_ceiling_db: f32,
    span_hz: f32,
    spectrum_min_hz: f32,
    spectrum_numeric_key: Option<(f32, f32, f64, f64)>,
    spectrum_peak: Option<spectrum::Peak>,
    spectrum_band: Option<spectrum::BandReading>,
    band_min_hz: f64,
    /// Zero selects the captured result's Nyquist frequency.
    band_max_hz: f64,
    show_hold: bool,
    spectrum_dirty: bool,
    spectrum_pixels: usize,
    spectrum_lines: Vec<Line>,
    spectrum_line_builder: spectrum::LineBuilder,
    spectrum_segments: Arc<Vec<Segment>>,
    spectrum_revision: u64,
    fft_ms: f64,
    spectrum_build_ms: f64,
    stft: stft::Worker,
    last_stft: Option<RowInfo>,
    spectrogram_history: Arc<Mutex<spectrogram::History>>,
    spectrogram_settings: Settings,
    spectrogram_channel: ChannelId,
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
    requested_sample_rate: Option<u32>,
    capture: Option<()>,
    busy: bool,
    error: Option<String>,
    history: History,
    cursors: Cursors,
    active_cursor: usize,
    scope_range: std::ops::Range<u64>,
    scope_sample_offset: f64,
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
    scope_readings: [Reading; 2],
    calibration: CalibrationEditor,
    settings_worker: settings::Worker,
    settings_path: String,
    settings_task: Option<SettingsTask>,
    settings_status: Option<String>,
    settings_error: bool,
    restored_input: Option<settings::Input>,
    held_input: Option<export::Input>,
    input_failed: bool,
    export_worker: export::Worker,
    export_path: String,
    export_pending: bool,
    export_status: Option<String>,
    export_error: bool,
    scope_missing: u64,
    dirty: bool,
    pixels: usize,
    revision: u64,
    build_ms: f64,
    fps: f64,
    last_frame: Instant,
    adapter: String,
    dropped: u64,
    smoke: bool,
    #[cfg(feature = "qa")]
    created: Instant,
    #[cfg(feature = "qa")]
    screenshot_requested: bool,
    #[cfg(feature = "qa")]
    screenshot_received: bool,
    #[cfg(feature = "qa")]
    profile: Option<crate::qa::Profile>,
    #[cfg(feature = "qa")]
    lifecycle_stage: u8,
    #[cfg(feature = "qa")]
    ui_stall_checked: bool,
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
    #[cfg(feature = "qa")]
    lifecycle_calibration_held: Option<(calibration::Set, [Reading; 2], String)>,
}

impl ScopeApp {
    pub fn new(
        cc: &eframe::CreationContext<'_>,
        smoke: bool,
        demo: bool,
    ) -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        let source = Source::on_startup(demo, smoke)?;
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
        let mut stft = stft::Worker::new();
        let core = (!smoke).then(|| measurement::Worker::new(stft.take_feeder()));
        let mut app = Self {
            source,
            software_running: false,
            loopback_settings: loopback::Settings::default(),
            lockin_settings: lockin::Settings::default(),
            lockin_visible: false,
            lockin_display: settings::LockinDisplay::Polar,
            lockin_result: lockin::Analyzer::new(lockin::Settings::default(), 48000)
                .result()
                .clone(),
            workspace_io: workspace_io::Worker::default(),
            workspace_pending: false,
            workspace_restoring: false,
            workspace_status: None,
            reference: None,
            reference_label: String::new(),
            compare_open: false,
            comparison_current: None,
            visible: [true; 4],
            plot_layout: PlotLayout::Auto,
            previous_view: None,
            spectrum_adjust_analysis: false,
            sidebar: Sidebar::default(),
            #[cfg(feature = "qa")]
            demo: Demo::default(),
            #[cfg(feature = "qa")]
            demo_enabled: demo || smoke,
            demo_running: demo && !smoke,
            core,
            pending_stop: None,
            pending_scope: None,
            #[cfg(feature = "qa")]
            known_output: None,
            start_after_stop: false,
            spectrum_publication: (0, 0),
            input_generation: 1,
            snapshot_revision: 0,
            core_scope: ScopeSettings::default(),
            acquisition_mode: acquisition::Mode::Auto,
            acquisition_state: acquisition::State::Waiting,
            scope_capture: None,
            autoset_pending: None,
            autoset_status: None,
            scope_channels: Pair::default(),
            xy_channels: Pair::default(),
            spectrum_mode: SpectrumMode::Live,
            spectrum_info: measurement::SpectrumInfo {
                mode: SpectrumMode::Live,
                observation_ms: crate::spectrum_worker::LIVE_INTERVAL
                    .as_micros()
                    .div_ceil(1000) as u32,
                ..Default::default()
            },
            stft_generation: 0,
            spectrum_settings: Settings::default(),
            analyzer: spectrum::Result::empty(Settings::default(), 48000),
            spectrum_channel: 0,
            frequency_scale: FrequencyScale::Log,
            floor_db: -120.0,
            spectrum_ceiling_db: 6.0,
            span_hz: 0.0,
            spectrum_min_hz: 0.0,
            spectrum_numeric_key: None,
            spectrum_peak: None,
            spectrum_band: None,
            band_min_hz: 0.0,
            band_max_hz: 0.0,
            show_hold: false,
            spectrum_dirty: true,
            spectrum_pixels: 0,
            spectrum_lines: Vec::with_capacity(8192),
            spectrum_line_builder: spectrum::LineBuilder::default(),
            spectrum_segments: Arc::new(Vec::with_capacity(8192)),
            spectrum_revision: 0,
            fft_ms: 0.0,
            spectrum_build_ms: 0.0,
            stft,
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
            requested_sample_rate: None,
            capture: None,
            busy: true,
            error: None,
            history: History::new(96_000),
            cursors: Cursors::default(),
            active_cursor: 0,
            scope_range: 0..0,
            scope_sample_offset: 0.0,
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
            scope_readings: [Reading::Unavailable; 2],
            calibration: CalibrationEditor::default(),
            settings_worker: settings::Worker::default(),
            settings_path: settings::default_path()
                .map(|path| path.to_string_lossy().into_owned())
                .unwrap_or_default(),
            settings_task: None,
            settings_status: None,
            settings_error: false,
            restored_input: None,
            held_input: None,
            input_failed: false,
            export_worker: export::Worker::default(),
            export_path: settings::default_path()
                .map(|path| {
                    path.with_file_name("measurement-results.json")
                        .to_string_lossy()
                        .into_owned()
                })
                .unwrap_or_default(),
            export_pending: false,
            export_status: None,
            export_error: false,
            scope_missing: 0,
            dirty: true,
            pixels: 0,
            revision: 0,
            build_ms: 0.0,
            fps: 0.0,
            last_frame: Instant::now(),
            adapter: format!("{:?} · {}", info.backend, info.name),
            dropped: 0,
            smoke,
            #[cfg(feature = "qa")]
            created: Instant::now(),
            #[cfg(feature = "qa")]
            screenshot_requested: false,
            #[cfg(feature = "qa")]
            screenshot_received: false,
            #[cfg(feature = "qa")]
            profile: crate::qa::Profile::from_env()?,
            #[cfg(feature = "qa")]
            lifecycle_stage: 0,
            #[cfg(feature = "qa")]
            ui_stall_checked: false,
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
            #[cfg(feature = "qa")]
            lifecycle_calibration_held: None,
        };
        #[cfg(feature = "qa")]
        if app.profile.is_some() {
            if std::env::var_os("MEASURELAB_PROFILE_SPECTRUM_ONLY").is_some() {
                app.visible = [false, true, false, false];
            }
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
            app.spectrogram_settings.size = std::env::var("MEASURELAB_PROFILE_STFT_SIZE")
                .ok()
                .and_then(|s| s.parse().ok())
                .filter(|s| STFT_SIZES.contains(s))
                .unwrap_or(size.min(32768));
            app.spectrum_mode = match std::env::var("MEASURELAB_PROFILE_SPECTRUM_MODE").as_deref() {
                Ok("latest") => SpectrumMode::Latest,
                Ok("continuous") => SpectrumMode::Continuous,
                _ => SpectrumMode::Live,
            };
            app.reset_analysis();
        }
        #[cfg(feature = "qa")]
        if std::env::var_os("MEASURELAB_SPECTRUM_PSD").is_some() {
            app.spectrum_settings.quantity = Quantity::Psd;
            app.reset_analysis();
        }
        #[cfg(feature = "qa")]
        if std::env::var_os("MEASURELAB_PROFILE_KNOWN_OUTPUT").is_some() {
            let name = app
                .profile
                .as_ref()
                .and_then(|p| p.device.as_deref())
                .ok_or("Known-output QA requires a BlackHole profile device")?;
            app.known_output =
                Some(crate::qa::blackhole_tone_output(name).map_err(|e| e.to_string())?);
        }
        #[cfg(feature = "qa")]
        if demo && std::env::var_os("MEASURELAB_PROFILE_DEMO_BIN_TONE").is_some() {
            app.demo.waveform = Waveform::Sine;
            app.demo.frequency = 750.0;
            app.demo.amplitude = 0.125;
            app.demo.noise = 0.0;
            app.demo.channel_2_gain = 1.0;
            app.demo.phase_degrees = 90.0;
        }
        #[cfg(feature = "qa")]
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
            app.held_input = Some(export::Input {
                generation: app.input_generation,
                source: export::Source::InternalQa {
                    description: app.format.clone(),
                },
                nominal_sample_rate_hz: app.sample_rate,
                channels: app.channels as usize,
            });
            app.reset_analysis();
            app.reset_stft();
            if smoke {
                app.demo.append_with(
                    &mut app.history,
                    16384,
                    app.sample_rate,
                    |sequence, samples| {
                        app.stft.submit(sequence, samples);
                    },
                );
                app.stft.flush();
            } else {
                app.core.as_ref().unwrap().start_demo(
                    app.input_generation,
                    app.demo.clone(),
                    app.core_config(),
                );
            }
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
            if std::env::var_os("MEASURELAB_UI_SMOKE_ROUTING").is_some() {
                app.channels = 16;
                app.history = History::with_channels(96000, 16);
                app.scope_channels = Pair([15, 7]);
                app.xy_settings.channels = Pair([15, 7]);
                app.trigger.channel = 15;
                app.spectrum_channel = 15;
                for sample in 0..16384 {
                    let angle = std::f64::consts::TAU * sample as f64 / 48.0;
                    let mut frame = [0.1; 16];
                    frame[15] = 0.375 * angle.sin();
                    frame[7] = 0.25 * angle.cos();
                    app.history.push(frame);
                }
                app.cursors.set_scope_time(0, 0.3);
                app.cursors.set_scope_time(1, 0.7);
            }
            if std::env::var_os("MEASURELAB_UI_SMOKE_CALIBRATION").is_some() {
                app.calibration.channel = app.scope_channels.0[0];
                app.calibration.gain = 4.0;
                app.calibration.offset = 0.5;
                app.calibration.conditions =
                    "QA coefficients: 4 V/FS + 0.5 V; internal fixture, not a physical reference"
                        .into();
                app.calibration.apply()?;
                app.calibration.captured = app.calibration.pending.clone();
                app.cursors.set_scope_time(0, 0.3);
                app.cursors.set_scope_time(1, 0.7);
            }
            match std::env::var("MEASURELAB_UI_SMOKE_SETTINGS").as_deref() {
                Ok("calibration") => app.sidebar.reveal(SettingsSection::Calibration),
                Ok("scope") => app.sidebar.section = Some(SettingsSection::Scope),
                Ok("spectrum") => app.sidebar.section = Some(SettingsSection::Spectrum),
                Ok("spectrogram") => app.sidebar.section = Some(SettingsSection::Spectrogram),
                Ok("xy") => app.sidebar.section = Some(SettingsSection::Xy),
                Ok("lockin") => app.sidebar.section = Some(SettingsSection::Lockin),
                Ok("workspace") => app.sidebar.section = Some(SettingsSection::Workspace),
                Ok("collapsed") => app.sidebar.section = None,
                Ok("hidden") => app.sidebar.visible = false,
                _ => {}
            }
            match std::env::var("MEASURELAB_UI_SMOKE_VIEW").as_deref() {
                Ok("scope") => app.select_view([true, false, false, false]),
                Ok("spectrum") => app.select_view([false, true, false, false]),
                Ok("pair") => app.select_view([true, true, false, false]),
                _ => {}
            }
            app.spectrum_adjust_analysis =
                std::env::var("MEASURELAB_UI_SMOKE_ADJUST").as_deref() == Ok("analysis");
        }
        if smoke {
            app.update_spectrum(true);
            #[cfg(feature = "qa")]
            if std::env::var_os("MEASURELAB_UI_SMOKE_SETTINGS_RESTORE").is_some() {
                app.check_settings_restore()?;
            }
            #[cfg(feature = "qa")]
            if std::env::var_os("MEASURELAB_UI_SMOKE_EXPORT").is_some() {
                app.refresh_scope_range();
                app.check_results_export()?;
            }
        }
        #[cfg(feature = "qa")]
        if smoke && std::env::var_os("MEASURELAB_UI_SMOKE_STAGE3F").is_some() {
            app.check_stage3f()?;
        }
        #[cfg(feature = "qa")]
        if smoke && let Ok(mode) = std::env::var("MEASURELAB_UI_SMOKE_LOCKIN") {
            app.check_lockin_ui(&mode)?;
        }
        Ok(app)
    }

    #[cfg(feature = "qa")]
    fn check_results_export(&mut self) -> Result<(), String> {
        // The fixture is already populated before the first UI update, but
        // AudioWorker's initial enumeration reply has not been polled yet.
        self.busy = true;
        assert!(!self.can_export());
        self.busy = false;
        assert!(self.can_export());
        let expected = self.capture_results()?;
        self.demo_running = true;
        assert!(self.capture_results().is_err());
        self.demo_running = false;
        self.settings_task = Some(SettingsTask::Restore);
        assert!(self.capture_results().is_err());
        self.settings_task = None;
        let path = std::path::PathBuf::from("dist/results-export-qa.json");
        self.export_path = path.display().to_string();
        self.request_export();
        assert!(
            self.export_pending,
            "export request failed: {:?}",
            self.export_status
        );
        // Change next-run conditions after the owned result crossed the I/O
        // boundary. These choices must not relabel the in-flight document.
        self.spectrum_settings.size = 1024;
        self.spectrum_settings.quantity = Quantity::Psd;
        self.spectrum_mode = SpectrumMode::Latest;
        self.spectrum_channel = 15;
        self.scope_channels = Pair([15, 7]);
        self.requested_sample_rate = Some(96_000);
        self.calibration.gain = 8.0;
        self.calibration.conditions = "Next-run export QA calibration".into();
        self.calibration.apply()?;
        let event = self
            .export_worker
            .events
            .recv_timeout(Duration::from_secs(10))
            .map_err(|e| e.to_string())?;
        match event {
            export::Event::Saved(saved) => assert_eq!(saved, path),
            export::Event::Error(error) => return Err(error),
        }
        self.export_pending = false;
        let saved: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&path).map_err(|e| e.to_string())?)
                .map_err(|e| e.to_string())?;
        let expected = serde_json::to_value(expected).map_err(|e| e.to_string())?;
        for key in ["input", "scope", "spectrum", "loss"] {
            assert_eq!(saved[key], expected[key], "in-flight export changed {key}");
        }
        assert!(!self.running());
        assert!(self.capture.is_none());
        self.scope_channels = Pair([
            saved["scope"]["traces"][0]["channel"].as_u64().unwrap() as usize,
            saved["scope"]["traces"][1]["channel"].as_u64().unwrap() as usize,
        ]);
        self.export_status = Some("Export QA passed; captured conditions preserved".into());
        self.sidebar.reveal(SettingsSection::Workspace);
        // Start the screenshot interval after fixture setup and its bounded
        // I/O wait, so requesting a screenshot cannot coincide with Close.
        self.created = Instant::now();
        println!(
            "Results export UI QA OK: running/restoring requests rejected; owned f64 Scope/Spectrum, source identity, intervals and calibration preserved after next-run edits; input remains stopped"
        );
        Ok(())
    }

    #[cfg(feature = "qa")]
    fn check_settings_restore(&mut self) -> Result<(), String> {
        // Synthetic device identity: this QA never opens an input stream.
        self.source = Source::Live;
        self.busy = false;
        self.devices = vec![DeviceInfo {
            id: Some("coreaudio:settings-qa-fixture".into()),
            name: "Settings QA 16ch (synthetic)".into(),
            channels: 16,
            default_sample_rate: 48_000,
            sample_rates: vec![48_000, 96_000],
            is_default: true,
        }];
        self.selected = 0;
        self.calibration.channel = 0;
        self.calibration.conditions = "Settings QA pending calibration".into();
        self.calibration.apply()?;
        let original = self.capture_settings()?;
        let mut invalid = original.clone();
        invalid.measurement.input.device_id = "coreaudio:missing".into();
        assert!(self.restore_settings(invalid).is_err());
        assert_eq!(self.capture_settings()?, original);
        let mut invalid = original.clone();
        invalid.measurement.calibrations[0].gain += 1.0;
        assert!(self.restore_settings(invalid).is_err());
        assert_eq!(self.capture_settings()?, original);
        self.demo_running = true;
        assert!(self.restore_settings(original.clone()).is_err());
        self.demo_running = false;
        let generation = self.input_generation;
        self.settings_task = Some(SettingsTask::Restore);
        self.start();
        assert_eq!(self.input_generation, generation);
        assert!(!self.running());
        assert!(!self.busy);
        self.settings_task = None;
        let captured = self.calibration.captured.clone();
        let window = self.analyzer.window();
        let power = self.analyzer.power().to_vec();
        let range = self.history.range();
        let sample_rate = self.sample_rate;
        let channels = self.channels;
        let mut document = original;
        document.measurement.scope.channels = Pair([15, 7]);
        document.measurement.spectrum.channel = 15;
        document.measurement.spectrum.analysis.size = 1024;
        document.measurement.spectrum.analysis.quantity = Quantity::Psd;
        document.measurement.spectrum.mode = SpectrumMode::Latest;
        document.measurement.spectrogram.channel = 15;
        document.measurement.xy.channels = Pair([15, 7]);
        document.measurement.input.sample_rate = Some(96_000);
        document.workspace.sidebar_visible = true;
        document.measurement.calibrations[0].revision += 1;
        document.measurement.calibrations[0].gain = 8.0;
        let path = std::path::PathBuf::from("dist/settings-restore-qa.json");
        settings::save(&path, &document)?;
        self.restore_settings(settings::load(&path)?)?;
        assert_eq!(self.capture_settings()?, document);
        assert_eq!(self.calibration.captured, captured);
        assert_eq!(self.analyzer.window(), window);
        assert_eq!(self.analyzer.power(), power);
        assert_eq!(self.history.range(), range);
        assert_eq!(self.sample_rate, sample_rate);
        assert_eq!(self.channels, channels);
        assert_eq!(self.input_generation, generation);
        assert!(!self.running());
        assert!(self.capture.is_none());
        self.begin_observation();
        assert_eq!(self.spectrum_channel, 15);
        assert_eq!(self.spectrogram_channel, 15);
        assert!(self.analyzer.window().is_none());
        assert!(self.spectrogram_history.lock().unwrap().config().is_none());
        assert_eq!(self.calibration.captured, self.calibration.pending);
        self.settings_path = path.display().to_string();
        self.settings_status = Some("Settings QA passed; input stays stopped".into());
        self.sidebar.reveal(SettingsSection::Workspace);
        println!(
            "Settings restore UI QA OK: missing/conflicting/running restores rejected atomically, Start blocked during restore, held data/metadata preserved, CH 16 survives new observation without automatic capture"
        );
        Ok(())
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
                self.select_view([false, true, false, false]);
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
                self.restore_view();
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
                self.lifecycle_calibration_held = Some((
                    self.calibration.captured.clone(),
                    self.scope_readings,
                    self.sample_text(self.cursor_samples()[0].unwrap()),
                ));
                self.calibration.channel = 0;
                self.calibration.gain = 2.0;
                self.calibration.offset = 0.5;
                self.calibration.conditions = "Lifecycle QA: internal demo coefficients".into();
                self.calibration.apply().unwrap();
                self.lifecycle_held = Some((revision, latest));
                self.lifecycle_stage = 2;
                ctx.request_repaint_after(Duration::from_millis(450));
            }
            2 if elapsed > 1.3 => {
                let (held_calibration, held_readings, held_cursor) =
                    self.lifecycle_calibration_held.as_ref().unwrap();
                assert_eq!(self.calibration.captured, *held_calibration);
                assert_eq!(self.scope_readings, *held_readings);
                assert_eq!(
                    self.sample_text(self.cursor_samples()[0].unwrap()),
                    *held_cursor
                );
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
                assert_eq!(self.analyzer.window(), Some(held_window.clone()));
                assert_eq!(self.analyzer.db(), held_db);
                assert_eq!(self.history.range(), *held_range);
                let held_results = self.capture_results().unwrap();
                let original_view = (self.visible, self.plot_layout);
                for visible in [
                    [true, false, false, false],
                    [true, true, false, false],
                    [false, true, false, false],
                    [true; 4],
                ] {
                    self.select_view(visible);
                    assert_eq!(self.capture_results().unwrap(), held_results);
                    assert_eq!(self.cursor_samples(), self.lifecycle_scope_samples);
                }
                self.restore_view();
                assert_eq!((self.visible, self.plot_layout), original_view);
                assert_eq!(self.capture_results().unwrap(), held_results);
                println!(
                    "Quick views OK: hidden instruments continue; held f64 results, conditions and cursors survive single/pair/all views and original arrangement is restored"
                );
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
                assert_eq!(self.analyzer.window(), Some(held_window.clone()));
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
                self.spectrum_settings.quantity = match self.analyzer.settings().quantity {
                    Quantity::Amplitude => Quantity::Psd,
                    Quantity::Psd => Quantity::Amplitude,
                };
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
                    Some(held_window.clone()),
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
                assert_eq!(self.calibration.captured, self.calibration.pending);
                assert_eq!(self.calibration.captured.get(0).unwrap().gain(), 2.0);
                assert_eq!(self.cursor_samples(), [None; 2]);
                assert!(self.cursors.frequency_hz.is_none());
                assert!(self.analyzer.window().is_none());
                self.lifecycle_stage = 4;
            }
            4 if elapsed > 2.0 && self.analyzer.is_ready() => {
                assert_eq!(self.calibration.captured.get(0).unwrap().offset(), 0.5);
                let calibration = self
                    .analyzer
                    .calibration()
                    .expect("Spectrum calibration after restart");
                assert_eq!(calibration, self.calibration.captured.get(0).unwrap());
                assert_eq!(
                    self.analyzer.window().unwrap().calibration.as_deref(),
                    Some(calibration)
                );
                assert_eq!(self.analyzer.unit(), "V");
                assert_eq!(
                    self.scope_readings,
                    calibration::measure(
                        &self.history,
                        self.scope_range.clone(),
                        self.scope_view_channels(),
                        &self.calibration.captured,
                    )
                );
                println!(
                    "Channel calibration lifecycle OK: held Scope/Spectrum readouts and conditions unchanged; queued calibration applied on restart"
                );
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
                assert!(self.calibration.pending.get(0).is_none());
                assert!(self.calibration.captured.get(0).is_none());
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
                self.scope_channels = Pair([self.channels as usize - 1, 0]);
                self.xy_settings.channels = Pair([0, self.channels as usize - 1]);
                self.dirty = true;
                self.refresh_scope_range();
                self.core
                    .as_ref()
                    .unwrap()
                    .configure_xy(self.xy_settings.channels);
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
                assert_eq!(self.analyzer.window(), Some(window.clone()));
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
                self.scope_channels = Pair([0, self.channels as usize - 1]);
                self.xy_settings.channels = Pair([self.channels as usize - 1, 0]);
                self.dirty = true;
                self.xy_dirty = true;
                self.visible = [false, false, true, false];
                if let Ok(rate) = std::env::var("MEASURELAB_PROFILE_SWITCH_SAMPLE_RATE") {
                    let rate = rate.parse().expect("QA switch sample rate must be Hz");
                    crate::audio::validate_sample_rate(rate)
                        .expect("QA switch sample rate is invalid");
                    self.requested_sample_rate = Some(rate);
                }
                self.lifecycle_stage = 2;
            }
            2 if elapsed > 0.4 => {
                self.update_spectrum(false);
                self.rebuild_xy();
                let (window, db, range) = self.lifecycle_spectrum_held.as_ref().unwrap();
                assert_eq!(self.analyzer.window(), Some(window.clone()));
                assert_eq!(self.sample_rate, window.sample_rate);
                assert_eq!(self.analyzer.db(), db);
                assert_eq!(self.history.range(), *range);
                assert_eq!(
                    self.scope_view_channels(),
                    Pair([self.channels as usize - 1, 0])
                );
                assert_eq!(
                    self.xy_capture.channels,
                    self.lifecycle_xy_held.as_ref().unwrap().1.channels
                );
                assert_eq!(
                    self.xy_capture.range,
                    self.lifecycle_xy_held.as_ref().unwrap().1.range
                );
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
                if let Some(rate) = self.requested_sample_rate {
                    assert_eq!(self.sample_rate, rate);
                    assert_eq!(latest.config.sample_rate, rate);
                    assert_eq!(self.analyzer.window().unwrap().sample_rate, rate);
                }
                assert_ne!(latest.generation, self.lifecycle_held.unwrap().1.generation);
                assert_eq!(latest.config.size, 1024);
                assert_eq!(latest.config.channel, self.channels as usize - 1);
                assert_eq!(self.scope_view_channels(), self.scope_channels);
                assert_eq!(self.xy_view_settings().channels, self.xy_settings.channels);
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
                if self.scope_channels.0[1] >= self.channels as usize {
                    assert_eq!(self.measurements[1].samples, 0);
                    self.rebuild_xy();
                    assert!(self.xy_capture.range.is_empty());
                }
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
                    self.requested_sample_rate = None;
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
                assert_eq!(self.scope_view_channels(), self.scope_channels);
                assert_eq!(self.xy_view_settings().channels, self.xy_settings.channels);
                if self.scope_channels.0[1] >= self.channels as usize {
                    assert_eq!(self.measurements[1].samples, 0);
                    self.rebuild_xy();
                    assert!(self.xy_capture.range.is_empty());
                }
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
        self.capture.is_some() || self.demo_running || self.software_running
    }

    fn begin_observation(&mut self) {
        self.cursors.new_epoch();
        self.input_generation += 1;
        self.held_input = None;
        self.lockin_result = lockin::Analyzer::new(self.lockin_settings, self.sample_rate)
            .result()
            .clone();
        self.input_failed = false;
        self.core_scope.channels = self.scope_channels;
        self.xy_channels = self.xy_settings.channels;
        self.history.clear_at(0);
        self.scope_capture = None;
        self.scope_range = 0..0;
        self.scope_sample_offset = 0.0;
        self.xy_capture = xy::Capture::default();
        self.xy_trace_range = 0..0;
        self.measurements = [Measurement::default(); 2];
        self.scope_readings = [Reading::Unavailable; 2];
        self.calibration.captured = self.calibration.pending.clone();
        self.scope_missing = 0;
        self.dirty = true;
        self.xy_dirty = true;
        // The new device topology is not known until Started. Preparing the
        // old topology here used to clamp queued CH 16 back to CH 1 at startup.
        self.analyzer = spectrum::Result::empty(self.spectrum_settings, self.sample_rate);
        self.spectrum_numeric_key = None;
        self.spectrum_info = measurement::SpectrumInfo {
            mode: self.spectrum_mode,
            ..Default::default()
        };
        self.spectrum_dirty = true;
        self.stft.pause();
        self.last_stft = None;
        self.spectrogram_history.lock().unwrap().clear();
    }

    fn core_config(&self) -> measurement::Config {
        measurement::Config {
            lockin: self.lockin_settings,
            spectrum: self.spectrum_settings,
            spectrum_channel: self.spectrum_channel,
            spectrum_mode: self.spectrum_mode,
            scope: ScopeSettings {
                mode: self.acquisition_mode,
                channels: self.scope_channels,
                samples: self.scope_sample_count(),
                trigger: self.trigger,
            },
            calibrations: self.calibration.captured.clone(),
            xy_channels: self.xy_settings.channels,
            stft_generation: self.stft_generation,
            stft: self.stft_config(),
        }
    }

    fn accept_snapshot(&mut self, snapshot: &mut measurement::Snapshot) {
        if snapshot.generation != self.input_generation
            || snapshot.revision <= self.snapshot_revision
        {
            return;
        }
        self.snapshot_revision = snapshot.revision;
        self.comparison_current = None;
        let samples_changed = self.history.range() != snapshot.history.range();
        self.dirty |= self.core_scope != snapshot.scope_settings;
        self.xy_dirty |= self.xy_channels != snapshot.xy_channels;
        self.lockin_result = snapshot.lockin.clone();
        self.sample_rate = snapshot.sample_rate;
        std::mem::swap(&mut self.history, &mut snapshot.history);
        if snapshot.has_spectrum {
            std::mem::swap(&mut self.analyzer, &mut snapshot.spectrum);
            self.spectrum_info = snapshot.spectrum_info.clone();
            self.fft_ms = snapshot.fft_ms;
            self.spectrum_dirty = true;
            self.spectrum_numeric_key = None;
        }
        std::mem::swap(&mut self.scope_capture, &mut snapshot.scope_capture);
        self.acquisition_state = snapshot.acquisition_state;
        self.dirty = true;
        self.core_scope = snapshot.scope_settings;
        self.xy_channels = snapshot.xy_channels;
        self.scope_range = snapshot.sweep.range.clone();
        self.scope_sample_offset = snapshot.sweep.sample_offset;
        self.triggered = snapshot.sweep.triggered;
        self.measurements = snapshot.measurements;
        self.scope_readings = snapshot.scope_readings;
        self.calibration.captured.clone_from(&snapshot.calibrations);
        self.scope_missing = snapshot.scope_missing;
        self.dropped = snapshot.input_dropped;
        self.input_failed |= snapshot.failed;
        self.dirty |= samples_changed;
        self.xy_dirty |= samples_changed;
        if snapshot.failed && self.running() {
            self.error = Some("Audio stream stopped. Check device connection and microphone permission, then restart.".into());
            self.stop();
        }
    }

    fn poll_measurement(&mut self) {
        if let Some(result) = self
            .autoset_pending
            .as_ref()
            .and_then(|r| r.try_recv().ok())
        {
            self.autoset_pending = None;
            self.autoset_status = Some(match result {
                Ok(result) => {
                    self.fs_per_div = result.fs_per_div as f32;
                    self.ms_per_div = result.samples as f32 * 100.0 / self.sample_rate as f32;
                    self.trigger = result.trigger;
                    if self.running() || self.acquisition_mode == acquisition::Mode::Auto {
                        self.ms_per_div = result.samples as f32 * 100.0 / self.sample_rate as f32;
                        self.trigger = result.trigger;
                        self.dirty = true;
                        format!("Autoset: {:.3} Hz from raw crossings", result.frequency_hz)
                    } else {
                        format!(
                            "Held capture amplitude fitted; time/trigger apply on next Start ({:.3} Hz)",
                            result.frequency_hz
                        )
                    }
                }
                Err(error) => error,
            });
        }
        if self.running()
            && self
                .core
                .as_ref()
                .is_some_and(|c| c.metrics.single_complete.load(Ordering::Acquire))
        {
            self.stop();
        }
        if let Some(mut snapshot) = self.pending_scope.as_mut().and_then(|p| p.try_take()) {
            self.pending_scope = None;
            // Spectrum has its own delivery; a Scope setting reply must not
            // replace a newer independently received Spectrum publication.
            snapshot.has_spectrum = false;
            self.accept_snapshot(&mut snapshot);
        }
        if let Some(snapshot) = self.pending_stop.as_mut().and_then(|p| p.try_take()) {
            self.pending_stop = None;
            let mut snapshot = snapshot;
            self.accept_snapshot(&mut snapshot);
            self.rebuild_xy();
            if self.start_after_stop {
                self.start_after_stop = false;
                self.start();
            }
        }
        if self.running() && self.pending_stop.is_none() {
            let publication = self
                .core
                .as_mut()
                .and_then(|core| core.spectrum.take_latest());
            if let Some(mut publication) = publication {
                if publication.generation == self.input_generation
                    && publication.channel == self.spectrum_channel
                    && publication.result.settings() == self.spectrum_settings
                    && publication.info.mode == self.spectrum_mode
                    && (publication.epoch, publication.revision) > self.spectrum_publication
                {
                    self.spectrum_publication = (publication.epoch, publication.revision);
                    std::mem::swap(&mut self.analyzer, &mut publication.result);
                    self.spectrum_info.clone_from(&publication.info);
                    self.fft_ms = publication.fft_ms;
                    self.spectrum_dirty = true;
                    self.spectrum_numeric_key = None;
                }
                self.core.as_mut().unwrap().spectrum.recycle(publication);
            }
        }

        if let Some(mut snapshot) = self.core.as_mut().and_then(|core| core.take_latest()) {
            if self.running() {
                self.accept_snapshot(&mut snapshot);
            }
            self.core.as_mut().unwrap().recycle(snapshot);
        }
        if self.running()
            && self
                .core
                .as_ref()
                .is_some_and(|core| core.metrics.failed.load(Ordering::Acquire))
        {
            self.error = Some("Audio stream stopped. Check device connection and microphone permission, then restart.".into());
            self.stop();
        }
    }

    #[cfg(feature = "qa")]
    fn check_ui_stall(&mut self) {
        if self.ui_stall_checked
            || self.profile.is_none()
            || !self.running()
            || self.created.elapsed().as_secs_f64()
                < (self.spectrum_settings.size as f64 / self.sample_rate as f64 + 1.0).max(0.8)
            || std::env::var_os("MEASURELAB_PROFILE_UI_STALL").is_none()
        {
            return;
        }
        self.ui_stall_checked = true;
        let core = self.core.as_ref().unwrap();
        let frames = core.metrics.input_frames.load(Ordering::Relaxed);
        let windows = core.spectrum.metrics.windows.load(Ordering::Relaxed);
        let stall = Duration::from_secs_f64(
            (3.0 * self.spectrum_settings.size as f64 / 4.0 / self.sample_rate as f64).max(1.0),
        );
        std::thread::sleep(stall);
        let frames = core.metrics.input_frames.load(Ordering::Relaxed) - frames;
        let windows = core.spectrum.metrics.windows.load(Ordering::Relaxed) - windows;
        assert!(
            frames > self.sample_rate as u64 / 2,
            "UI stall stopped acquisition"
        );
        assert!(windows > 0, "UI stall stopped Spectrum analysis");
        assert!(core.metrics.display_skipped.load(Ordering::Relaxed) > 0);
        let mut snapshot = core.scope(self.core_config().scope);
        assert_eq!(snapshot.input_dropped, 0, "UI stall lost measurement input");
        assert_eq!(snapshot.spectrum_info.missing_windows, 0);
        assert_eq!(snapshot.spectrum_info.input_missing, 0);
        if self.spectrum_mode == SpectrumMode::Continuous {
            assert_eq!(
                snapshot.spectrum_info.updates,
                1 + (snapshot.history.range().end - self.spectrum_settings.size as u64)
                    / (self.spectrum_settings.size / 4) as u64
            );
        }
        self.accept_snapshot(&mut snapshot);
        println!(
            "UI stall OK: {:.3} ms without UI updates; {frames} input frames and {windows} FFT windows continued",
            stall.as_secs_f64() * 1000.0
        );
    }

    #[cfg(feature = "qa")]
    fn check_large_fft_lifecycle(&mut self, ctx: &egui::Context) {
        if std::env::var_os("MEASURELAB_PROFILE_LARGE_LIFECYCLE").is_none() {
            return;
        }
        assert_eq!(self.spectrum_settings.size, 524288);
        match self.lifecycle_stage {
            0 if self.analyzer.is_ready() && self.spectrum_info.updates >= 3 => {
                self.lifecycle_changed = Instant::now();
                self.stop();
                assert!(self.pending_stop.is_some());
                assert!(!self.running());
                println!(
                    "Large FFT Stop request accepted in {:.3} ms",
                    self.lifecycle_changed.elapsed().as_secs_f64() * 1000.0
                );
                self.lifecycle_stage = 1;
            }
            1 if self.pending_stop.is_none() => {
                let window = self.analyzer.window().unwrap();
                if self.spectrum_info.mode == SpectrumMode::Continuous {
                    assert_eq!(
                        self.spectrum_info.updates,
                        1 + (self.history.range().end - 524288) / 131072
                    );
                }
                assert_eq!(self.spectrum_info.input_missing, 0);
                assert_eq!(self.spectrum_info.missing_windows, 0);
                self.lifecycle_spectrum_held =
                    Some((window, self.analyzer.db().to_vec(), self.history.range()));
                println!(
                    "Large FFT Stop completion observed after {:.3} ms",
                    self.lifecycle_changed.elapsed().as_secs_f64() * 1000.0
                );
                self.spectrum_settings.quantity = Quantity::Psd;
                self.spectrum_mode = SpectrumMode::Latest;
                self.spectrum_channel = 1;
                self.frequency_scale = FrequencyScale::Linear;
                self.spectrum_min_hz = 749.5;
                self.span_hz = 750.5;
                self.spectrum_dirty = true;
                self.lifecycle_changed = Instant::now();
                self.lifecycle_stage = 2;
            }
            2 if self.lifecycle_changed.elapsed() > Duration::from_millis(150) => {
                let (window, db, range) = self.lifecycle_spectrum_held.as_ref().unwrap();
                assert_eq!(self.analyzer.window().unwrap(), *window);
                assert_eq!(self.analyzer.db(), db);
                assert_eq!(self.history.range(), *range);
                self.analyzer.clear_hold();
                self.core.as_ref().unwrap().clear_hold();
                assert_eq!(self.analyzer.hold_power(), self.analyzer.power());
                self.visible[1] = false;
                self.start();
                assert!(!self.analyzer.is_ready());
                self.lifecycle_stage = 3;
            }
            3 if self.analyzer.is_ready() && self.spectrum_info.updates >= 10 => {
                assert_eq!(self.spectrum_info.mode, SpectrumMode::Latest);
                assert_eq!(self.analyzer.settings().quantity, Quantity::Psd);
                assert_eq!(self.analyzer.window().unwrap().channel, 1);
                assert!(
                    (self.analyzer.band(0.0, 24000.0).unwrap().power - 0.0078125).abs() < 1e-12
                );
                self.visible[1] = true;
                self.stop();
                self.lifecycle_stage = 4;
            }
            4 if self.pending_stop.is_none() => {
                assert_eq!(self.spectrum_info.input_missing, 0);
                assert_eq!(self.spectrum_info.missing_windows, 0);
                assert_eq!(
                    self.core
                        .as_ref()
                        .unwrap()
                        .spectrum
                        .metrics
                        .input_dropped
                        .load(Ordering::Relaxed),
                    0
                );
                println!(
                    "Large FFT UI lifecycle OK: asynchronous finite-end Stop, held settings/data, narrow individual-bin display, Clear hold, new generation/CH/PSD/Latest, hidden Spectrum continues, final Latest window"
                );
                self.lifecycle_stage = 5;
            }
            _ => {}
        }
        if self.lifecycle_stage < 5 {
            ctx.request_repaint_after(Duration::from_millis(10));
        }
    }

    fn update_spectrum(&mut self, final_snapshot: bool) {
        if self.smoke && final_snapshot {
            let mut analyzer = Analyzer::new(self.spectrum_settings, self.sample_rate);
            analyzer.set_calibration(
                self.calibration
                    .captured
                    .get(self.spectrum_channel)
                    .cloned()
                    .map(Arc::new),
            );
            analyzer.update(&self.history, self.spectrum_channel);
            analyzer.copy_result(&mut self.analyzer);
            if let Some(average) = self.analyzer.average() {
                self.spectrum_info.updates = average.updates;
                self.spectrum_info.contributing = average.start..average.end;
            }
            self.spectrum_dirty = true;
            self.spectrum_numeric_key = None;
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

    fn scope_history(&self) -> &History {
        self.scope_capture.as_ref().unwrap_or(&self.history)
    }

    fn scope_display_ms_per_div(&self) -> f32 {
        if !self.running() && self.core_scope.mode != acquisition::Mode::Auto {
            self.core_scope.samples as f32 * 100.0 / self.sample_rate as f32
        } else {
            self.ms_per_div
        }
    }

    fn scope_sample_count(&self) -> usize {
        (self.ms_per_div * 0.01 * self.sample_rate as f32)
            .round()
            .max(2.0) as usize
    }

    fn scope_view_channels(&self) -> Pair {
        if self.core.is_some() {
            self.core_scope.channels
        } else {
            self.scope_channels
        }
    }

    fn xy_view_settings(&self) -> xy::Settings {
        xy::Settings {
            channels: if self.core.is_some() {
                self.xy_channels
            } else {
                self.xy_settings.channels
            },
            ..self.xy_settings
        }
    }

    fn refresh_scope_range(&mut self) {
        if self.dirty {
            let settings = ScopeSettings {
                mode: self.acquisition_mode,
                channels: if self.running() || self.core.is_none() {
                    self.scope_channels
                } else {
                    self.core_scope.channels
                },
                samples: self.scope_sample_count(),
                trigger: self.trigger,
            };
            if let Some(core) = &self.core {
                if settings != self.core_scope
                    && self.pending_scope.is_none()
                    && (self.running() || self.core_scope.mode == acquisition::Mode::Auto)
                {
                    self.pending_scope = Some(core.scope_async(settings));
                    #[cfg(feature = "qa")]
                    if std::env::var_os("MEASURELAB_PROFILE_LIFECYCLE").is_some()
                        || std::env::var_os("MEASURELAB_PROFILE_INPUT_LIFECYCLE").is_some()
                    {
                        let mut snapshot = self.pending_scope.take().unwrap().wait();
                        self.accept_snapshot(&mut snapshot);
                    }
                }
            } else {
                let sweep = self.history.sweep(settings.samples, self.trigger);
                let ready = self.history.len() >= settings.samples;
                self.triggered = ready && sweep.triggered;
                self.scope_sample_offset = if ready { sweep.sample_offset } else { 0.0 };
                self.scope_range = if ready { sweep.range } else { 0..0 };
                self.core_scope = settings;
                self.measurements = crate::signal::measure(
                    &self.history,
                    self.scope_range.clone(),
                    settings.channels,
                );
                self.scope_readings = calibration::measure(
                    &self.history,
                    self.scope_range.clone(),
                    settings.channels,
                    &self.calibration.captured,
                );
            }
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
        self.analyzer = spectrum::Result::empty(self.spectrum_settings, self.sample_rate);
        self.spectrum_numeric_key = None;
        self.spectrum_info = measurement::SpectrumInfo {
            mode: self.spectrum_mode,
            ..Default::default()
        };
        if let Some(core) = &self.core {
            core.configure_spectrum(
                self.spectrum_settings,
                self.spectrum_channel,
                self.spectrum_mode,
            );
        }
        self.spectrum_dirty = true;
    }

    #[cfg(feature = "qa")]
    fn apply_demo_settings(&mut self) {
        if self.running() {
            if let Some(core) = &self.core {
                core.configure_demo(self.demo.clone());
            }
            self.reset_analysis();
        }
    }

    fn reset_stft(&mut self) {
        self.spectrogram_channel = self
            .spectrogram_channel
            .min(self.channels.max(1) as usize - 1);
        let config = self.stft_config();
        let generation = self
            .stft
            .configure(config)
            .expect("validated STFT settings");
        self.stft_generation = generation;
        if let Some(core) = &self.core {
            core.configure_stft(generation, config);
        }
        self.spectrogram_history
            .lock()
            .unwrap()
            .reset(generation, config);
        self.last_stft = None;
        if !self.running() && !self.smoke {
            self.stft.pause();
        }
    }

    fn stft_config(&self) -> stft::Config {
        stft::Config {
            sample_rate: self.sample_rate,
            channels: self.channels.max(1) as usize,
            channel: self.spectrogram_channel,
            size: self.spectrogram_settings.size,
            hop: self.spectrogram_settings.size / 4,
            window: self.spectrogram_settings.window,
            remove_dc: self.spectrogram_settings.remove_dc,
            precision: self.spectrogram_settings.precision,
        }
    }

    fn start(&mut self) {
        if self.settings_task == Some(SettingsTask::Restore) || self.workspace_restoring {
            return;
        }
        if self.pending_stop.is_some() {
            self.start_after_stop = true;
            return;
        }
        if self.source == Source::Software {
            let rate = self.requested_sample_rate.unwrap_or(48000);
            if let Err(e) = self
                .loopback_settings
                .validate(rate)
                .and_then(|()| self.lockin_settings.validate(rate))
            {
                self.error = Some(e);
                return;
            }
            self.begin_observation();
            self.sample_rate = rate;
            self.channels = 2;
            self.format = "Software Loopback".into();
            self.held_input = Some(export::Input {
                generation: self.input_generation,
                source: export::Source::SoftwareLoopback {
                    settings: self.loopback_settings.clone(),
                },
                nominal_sample_rate_hz: rate,
                channels: 2,
            });
            self.history = History::with_channels((rate as usize * 2).max(32768), 2);
            self.scope_capture = None;
            self.xy_dirty = true;
            self.dirty = true;
            self.dropped = 0;
            self.error = None;
            self.reset_analysis();
            self.reset_stft();
            match self.core.as_ref().unwrap().start_loopback(
                self.input_generation,
                self.loopback_settings.clone(),
                rate,
                self.core_config(),
            ) {
                Ok(()) => self.software_running = true,
                Err(e) => self.error = Some(e),
            }
            return;
        }
        #[cfg(feature = "qa")]
        if let Some(profile) = &mut self.profile {
            profile.new_input(self.dropped);
        }
        #[cfg(feature = "qa")]
        if self.source.is_demo() {
            self.begin_observation();
            self.sample_rate = 48000;
            self.channels = 2;
            self.format = "Internal demo".into();
            self.held_input = Some(export::Input {
                generation: self.input_generation,
                source: export::Source::InternalQa {
                    description: self.format.clone(),
                },
                nominal_sample_rate_hz: self.sample_rate,
                channels: self.channels as usize,
            });
            self.history = History::new(96000);
            self.xy_dirty = true;
            self.demo_running = true;
            self.dropped = 0;
            self.error = None;
            self.dirty = true;
            self.reset_analysis();
            self.reset_stft();
            self.core.as_ref().unwrap().start_demo(
                self.input_generation,
                self.demo.clone(),
                self.core_config(),
            );
            return;
        }
        if self.devices.is_empty() || self.busy {
            return;
        }
        if let Some(input) = &self.restored_input {
            match input.resolve(&self.devices) {
                Ok(index) if index == self.selected => {}
                Ok(_) => {
                    self.error =
                        Some("Restored input selection changed; restore settings again".into());
                    return;
                }
                Err(error) => {
                    self.error = Some(error);
                    return;
                }
            }
        }
        self.error = None;
        self.capture = None;
        self.begin_observation();
        self.busy = true;
        self.audio.send(Command::Start {
            device: self.selected,
            sample_rate: self.requested_sample_rate,
        });
    }

    fn stop(&mut self) {
        self.start_after_stop = false;
        self.stft.pause();
        let was_audio = self.capture.take().is_some();
        self.demo_running = false;
        self.software_running = false;
        if self.pending_stop.is_none()
            && let Some(core) = &self.core
        {
            self.pending_stop = Some(core.stop_async());
        }
        #[cfg(feature = "qa")]
        if std::env::var_os("MEASURELAB_PROFILE_LIFECYCLE").is_some()
            || std::env::var_os("MEASURELAB_PROFILE_INPUT_LIFECYCLE").is_some()
        {
            // Existing lifecycle assertions inspect the completed barrier. Normal
            // UI Stop uses poll_measurement and never waits for this completion.
            if let Some(pending) = self.pending_stop.take() {
                let mut snapshot = pending.wait();
                self.accept_snapshot(&mut snapshot);
            }
        }
        // The final raw snapshot may be newer than the last displayed XY
        // capture. Freeze its trigger reference before any cursor readout.
        self.rebuild_xy();
        if was_audio {
            self.busy = true;
            self.audio.send(Command::Stop);
        }
    }

    fn poll_audio(&mut self) {
        while let Ok(event) = self.audio.events.try_recv() {
            self.busy = false;
            match event {
                Event::Devices(devices) => {
                    self.restored_input = None;
                    if self.source == Source::Live {
                        self.calibration.clear_input();
                    }
                    self.selected = devices.iter().position(|d| d.is_default).unwrap_or(0);
                    self.requested_sample_rate = None;
                    self.devices = devices;
                    #[cfg(feature = "qa")]
                    if let Some(name) = self.profile.as_ref().and_then(|p| p.device.as_ref()) {
                        if let Some(index) = self.devices.iter().position(|d| &d.name == name) {
                            self.selected = index;
                            self.requested_sample_rate =
                                self.profile.as_ref().and_then(|p| p.sample_rate);
                            if let Some((stream, failed)) = &self.known_output {
                                use cpal::traits::StreamTrait;
                                if let Err(error) = stream.play() {
                                    failed.store(true, Ordering::Relaxed);
                                    self.error = Some(format!("QA output start failed: {error}"));
                                    continue;
                                }
                            }
                            self.start();
                        } else {
                            self.error = Some(format!("QA input device not found: {name}"));
                        }
                    }
                }
                Event::Started(capture) => {
                    if self.restored_input.as_ref().is_some_and(|input| {
                        input.channels != capture.channels
                            || input.expected_sample_rate() != capture.sample_rate
                    }) {
                        self.audio.send(Command::Stop);
                        self.busy = true;
                        self.error = Some("Input conditions changed since restoration; refresh devices and restore again".into());
                        continue;
                    }
                    self.xy_dirty = true;
                    self.sample_rate = capture.sample_rate;
                    self.channels = capture.channels;
                    self.format = capture.format.clone();
                    self.held_input = self.devices.get(self.selected).map(|device| export::Input {
                        generation: self.input_generation,
                        source: export::Source::Audio {
                            device_id: device.id.clone(),
                            device_name: device.name.clone(),
                            sample_format: capture.format.clone(),
                            requested_sample_rate_hz: self.requested_sample_rate,
                        },
                        nominal_sample_rate_hz: capture.sample_rate,
                        channels: capture.channels as usize,
                    });
                    self.history = History::with_channels(
                        (self.sample_rate as usize * 2).max(32768),
                        self.channels as usize,
                    );
                    self.dropped = 0;
                    self.capture = Some(());
                    #[cfg(feature = "qa")]
                    if self.profile.is_some() {
                        if let Ok(channel) = std::env::var("MEASURELAB_PROFILE_CHANNEL")
                            && let Ok(channel) = channel.parse::<usize>()
                        {
                            self.spectrum_channel = channel.saturating_sub(1);
                            self.spectrogram_channel = channel.saturating_sub(1);
                        }
                        match std::env::var("MEASURELAB_PROFILE_SETTINGS").as_deref() {
                            Ok("input") => self.sidebar.section = Some(SettingsSection::Input),
                            Ok("spectrum") => {
                                self.sidebar.section = Some(SettingsSection::Spectrum)
                            }
                            _ => {}
                        }
                    }
                    self.dirty = true;
                    self.reset_analysis();
                    self.reset_stft();
                    self.core.as_ref().unwrap().start_capture(
                        self.input_generation,
                        capture,
                        self.core_config(),
                    );
                }
                Event::Stopped => {}
                Event::Error(error) => {
                    self.stop();
                    self.error = Some(error);
                }
            }
        }
    }

    fn section_summary(&self, section: SettingsSection) -> String {
        match section {
            #[cfg(feature = "qa")]
            SettingsSection::Input if self.source.is_demo() => {
                format!(
                    "Demo · {} Hz · {:.2} FS",
                    self.demo.frequency, self.demo.amplitude
                )
            }
            SettingsSection::Input if self.source == Source::Software => format!(
                "Software Loopback · {} Hz · 2 ch",
                self.requested_sample_rate.unwrap_or(48000)
            ),
            SettingsSection::Input => self
                .devices
                .get(self.selected)
                .map(|device| format!("{} · {}", device.name, self.input_rate_label()))
                .unwrap_or_else(|| "Select an audio device".into()),
            SettingsSection::Scope => {
                format!("{} ms/div · {} FS/div", self.ms_per_div, self.fs_per_div)
            }
            SettingsSection::Spectrum => format!(
                "CH {} · {} points · {}",
                self.spectrum_channel + 1,
                self.spectrum_settings.size,
                self.spectrum_settings.quantity.name()
            ),
            SettingsSection::Spectrogram => format!(
                "CH {} · {:.1} s · {} points",
                self.spectrogram_channel + 1,
                self.spectrogram_seconds,
                self.spectrogram_settings.size
            ),
            SettingsSection::Xy => format!(
                "{} × {} · {:.1} ms",
                channel::name(self.xy_settings.channels.0[0]),
                channel::name(self.xy_settings.channels.0[1]),
                self.xy_settings.milliseconds
            ),
            SettingsSection::Workspace => {
                format!("{} layout · shortcuts & units", self.plot_layout.name())
            }
            SettingsSection::Calibration => "Scope numeric readouts · next Start".into(),
            SettingsSection::Lockin => format!(
                "REF CH {} → SIG CH {} · τ {} s",
                self.lockin_settings.reference_channel + 1,
                self.lockin_settings.response_channel + 1,
                self.lockin_settings.time_constant_seconds,
            ),
        }
    }

    fn controls(&mut self, ui: &mut egui::Ui) {
        if self.settings_task == Some(SettingsTask::Restore) || self.workspace_restoring {
            ui.label("Restoring measurement settings…");
            return;
        }
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
                            SettingsSection::Lockin => self.lockin_controls(ui),
                            SettingsSection::Calibration => self.calibration_controls(ui),
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
                !self.busy
                    && self.settings_task != Some(SettingsTask::Restore)
                    && self.pending_stop.is_none()
                    && (self.source.is_demo()
                        || self.source == Source::Software
                        || !self.devices.is_empty()),
                egui::Button::new(
                    RichText::new(if self.running() {
                        "■  Stop"
                    } else if self.source.is_demo() {
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
        self.restored_input = None;
        self.calibration.clear_input();
        self.cursors.new_epoch();
        self.scope_capture = None;
        self.scope_range = 0..0;
        self.scope_sample_offset = 0.0;
        self.xy_dirty = true;
        self.stop();
        self.input_generation += 1;
        self.lockin_result = lockin::Analyzer::new(self.lockin_settings, self.sample_rate)
            .result()
            .clone();
        if self.capture.take().is_some() {
            self.audio.send(Command::Stop);
            self.busy = true;
        }
        self.history.clear();
        self.scope_capture = None;
        self.scope_range = 0..0;
        self.measurements = [Measurement::default(); 2];
        self.scope_readings = [Reading::Unavailable; 2];
        self.calibration.captured = calibration::Set::default();
        self.channels = if self.source.is_demo() { 2 } else { 0 };
        if self.source.is_demo() {
            self.sample_rate = 48000;
            self.format = "Internal demo".into();
            self.start();
        } else {
            #[cfg(feature = "qa")]
            if let Some(profile) = &mut self.profile {
                profile.new_input(self.dropped);
            }
            self.format.clear();
            self.dropped = 0;
        }
        self.dirty = true;
        self.error = None;
        self.reset_analysis();
        self.reset_stft();
    }

    fn input_controls(&mut self, ui: &mut egui::Ui) {
        let old_source = self.source;
        ui.add_enabled_ui(!self.busy && self.pending_stop.is_none(), |ui| {
            ui.horizontal(|ui| {
                ui.selectable_value(&mut self.source, Source::Live, "Audio input");
                ui.selectable_value(&mut self.source, Source::Software, "Software Loopback");
            });
        });
        if old_source != self.source {
            self.switch_source();
            self.requested_sample_rate = None;
        }
        if self.source == Source::Software {
            self.software_controls(ui);
        }
        #[cfg(feature = "qa")]
        if self.demo_enabled {
            setting_label(ui, "SOURCE");
            let previous_source = self.source;
            ui.add_enabled_ui(!self.busy, |ui| {
                ui.horizontal(|ui| {
                    ui.selectable_value(&mut self.source, Source::Live, "Audio input");
                    ui.selectable_value(&mut self.source, Source::Demo, "Demo signal (QA)");
                });
            });
            if previous_source != self.source {
                self.switch_source();
            }
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
            if previous != self.selected {
                self.restored_input = None;
                self.calibration.clear_input();
                self.requested_sample_rate = None;
            }
            setting_label(ui, "SAMPLE RATE");
            let previous_rate = self.requested_sample_rate;
            ui.add_enabled_ui(!self.busy && !self.devices.is_empty(), |ui| {
                egui::ComboBox::from_id_salt("input_sample_rate")
                    .width(ui.available_width())
                    .selected_text(self.input_rate_label())
                    .show_ui(ui, |ui| {
                        ui.selectable_value(
                            &mut self.requested_sample_rate,
                            None,
                            "Device default",
                        );
                        if let Some(device) = self.devices.get(self.selected) {
                            for &rate in &device.sample_rates {
                                ui.selectable_value(
                                    &mut self.requested_sample_rate,
                                    Some(rate),
                                    format!("{} kHz", rate as f64 / 1000.0),
                                );
                            }
                        }
                    });
            });
            ui.label(
                RichText::new("Supported device rates · up to 768 kHz")
                    .small()
                    .color(MUTED),
            );
            if !self.running() {
                ui.label(
                    RichText::new("Rate changes apply on Start. Held results keep their rate.")
                        .small()
                        .color(MUTED),
                );
            }
            if previous_rate != self.requested_sample_rate
                && let Some(input) = &mut self.restored_input
            {
                input.sample_rate = self.requested_sample_rate;
            }
            if (previous != self.selected || previous_rate != self.requested_sample_rate)
                && self.capture.is_some()
            {
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
        #[cfg(feature = "qa")]
        if self.source.is_demo() {
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

    fn input_rate_label(&self) -> String {
        self.requested_sample_rate.map_or_else(
            || {
                if self.capture.is_some() {
                    format!("Device default ({} kHz)", self.sample_rate as f64 / 1000.0)
                } else {
                    "Device default".into()
                }
            },
            |rate| format!("{} kHz", rate as f64 / 1000.0),
        )
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
        setting_label(ui, "TRACE SOURCES");
        let before_channels = self.scope_channels;
        for (trace, color) in [GREEN, BLUE].into_iter().enumerate() {
            ui.horizontal(|ui| {
                self.dirty |= ui
                    .checkbox(
                        &mut self.enabled[trace],
                        RichText::new(format!("Trace {}", trace + 1)).color(color),
                    )
                    .changed();
                channel_select(
                    ui,
                    if trace == 0 {
                        "scope_trace_1"
                    } else {
                        "scope_trace_2"
                    },
                    &mut self.scope_channels.0[trace],
                    self.channels,
                );
            });
        }
        self.dirty |= self.scope_channels != before_channels;
        if !self.running() && self.scope_channels != self.scope_view_channels() {
            ui.label(
                RichText::new("Source changes apply on Start. Held traces keep their channels.")
                    .small()
                    .color(YELLOW),
            );
        }
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
        setting_label(ui, "ACQUISITION");
        let old_mode = self.acquisition_mode;
        ui.horizontal(|ui| {
            ui.selectable_value(&mut self.acquisition_mode, acquisition::Mode::Auto, "Auto");
            ui.selectable_value(
                &mut self.acquisition_mode,
                acquisition::Mode::Normal,
                "Normal",
            );
            ui.selectable_value(
                &mut self.acquisition_mode,
                acquisition::Mode::Single,
                "Single",
            );
        });
        self.dirty |= old_mode != self.acquisition_mode;
        ui.horizontal(|ui| {
            if ui
                .add_enabled(
                    !self.running() && self.pending_stop.is_none(),
                    egui::Button::new("Arm single"),
                )
                .clicked()
            {
                self.acquisition_mode = acquisition::Mode::Single;
                self.start();
            }
            if ui
                .add_enabled(self.autoset_pending.is_none(), egui::Button::new("Autoset"))
                .clicked()
                && let Some(core) = &self.core
            {
                self.autoset_pending = Some(core.autoset(self.scope_view_channels().0[0]));
            }
        });
        if let Some(status) = &self.autoset_status {
            ui.label(RichText::new(status).small());
        }
        setting_label(ui, "TRIGGER");
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

    fn calibration_controls(&mut self, ui: &mut egui::Ui) {
        ui.label(RichText::new("Scope readouts and Spectrum use y = gain × FS + offset. Spectrum Remove DC cancels offset. Scope trace/trigger, Spectrogram and XY axes use FS.").small().color(MUTED));
        ui.label(RichText::new("Queued definitions apply on the next Start. Source/device selection or device refresh clears the queue. Coefficients are supplied by you; reference conditions describe their validity.").small().color(MUTED));
        setting_label(ui, "INPUT CHANNEL");
        let before = self.calibration.channel;
        egui::ComboBox::from_id_salt("calibration_channel")
            .width(ui.available_width())
            .selected_text(channel::name(self.calibration.channel))
            .show_ui(ui, |ui| {
                for channel in 0..crate::signal::MAX_CHANNELS {
                    ui.selectable_value(
                        &mut self.calibration.channel,
                        channel,
                        channel::name(channel),
                    );
                }
            });
        if before != self.calibration.channel {
            self.calibration.select();
        }
        let channel = self.calibration.channel;
        if !channel::available(channel, self.channels as usize) {
            ui.label(
                RichText::new("Channel unavailable in the current input")
                    .small()
                    .color(YELLOW),
            );
        }
        setting_label(ui, "CAPTURED READOUT CONDITION");
        ui.label(
            RichText::new(calibration_description(&self.calibration.captured, channel))
                .small()
                .color(MUTED),
        );
        setting_label(ui, "QUEUED FOR NEXT START");
        ui.label(
            RichText::new(calibration_description(&self.calibration.pending, channel))
                .small()
                .color(MUTED),
        );
        ui.horizontal(|ui| {
            ui.label("Gain");
            ui.add(
                egui::DragValue::new(&mut self.calibration.gain)
                    .speed(0.01)
                    .max_decimals(15)
                    .range(-f64::MAX..=f64::MAX),
            );
            ui.label("unit/FS");
        });
        ui.horizontal(|ui| {
            ui.label("Offset");
            ui.add(
                egui::DragValue::new(&mut self.calibration.offset)
                    .speed(0.001)
                    .max_decimals(15)
                    .range(-f64::MAX..=f64::MAX),
            );
            ui.label("unit");
        });
        setting_label(ui, "PHYSICAL UNIT (E.G. V, A, Pa)");
        ui.add(
            egui::TextEdit::singleline(&mut self.calibration.unit)
                .desired_width(f32::INFINITY)
                .char_limit(24),
        );
        setting_label(ui, "REFERENCE CONDITIONS");
        ui.add(
            egui::TextEdit::singleline(&mut self.calibration.conditions)
                .desired_width(f32::INFINITY)
                .char_limit(1024)
                .hint_text("Reference, device/range, date, uncertainty"),
        );
        if ui.button("Queue calibration").clicked()
            && let Err(error) = self.calibration.apply()
        {
            self.calibration.error = Some(error.into());
        }
        if ui.button("Queue uncalibrated FS").clicked() {
            self.calibration.pending = self
                .calibration
                .pending
                .with(channel, None)
                .expect("bounded UI channel");
            self.calibration.select();
        }
        if let Some(error) = &self.calibration.error {
            ui.label(RichText::new(error).small().color(YELLOW));
        }
    }

    fn spectrum_analysis_controls(&mut self, ui: &mut egui::Ui) {
        let before = (
            self.spectrum_settings,
            self.spectrum_channel,
            self.spectrum_mode,
        );
        setting_label(ui, "MEASUREMENT");
        egui::ComboBox::from_id_salt("spectrum_quantity")
            .width(ui.available_width())
            .selected_text(self.spectrum_settings.quantity.name())
            .show_ui(ui, |ui| {
                for quantity in [Quantity::Amplitude, Quantity::Psd] {
                    ui.selectable_value(
                        &mut self.spectrum_settings.quantity,
                        quantity,
                        quantity.name(),
                    );
                }
            });
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
        setting_label(ui, "UPDATE MODE");
        ui.selectable_value(
            &mut self.spectrum_mode,
            SpectrumMode::Live,
            "Live · up to 60 updates/s",
        ).on_hover_text("Observe the newest complete window with a processing-time budget. Average and hold update per observed window, independently of drawing. Use Continuous to process every N/4 window.");
        ui.selectable_value(
            &mut self.spectrum_mode,
            SpectrumMode::Continuous,
            "Continuous · N/4 hop",
        );
        ui.selectable_value(
            &mut self.spectrum_mode,
            SpectrumMode::Latest,
            if self.spectrum_settings.size <= 32768 {
                "Latest window · 33 ms / N/4 minimum"
            } else {
                "Latest window · 100 ms observation"
            },
        );
        setting_label(ui, "AVERAGING");
        egui::ComboBox::from_id_salt("fft_average")
            .width(ui.available_width())
            .selected_text(format!("EMA α = 1/{}", self.spectrum_settings.averages))
            .show_ui(ui, |ui| {
                for count in [1, 4, 16, 64] {
                    ui.selectable_value(&mut self.spectrum_settings.averages, count, format!("EMA α = 1/{count}"));
                }
            }).response.on_hover_text("Exponential average of linear power; alpha = 1 / count. Applied once per contributing FFT window, independently of display updates.");
        ui.checkbox(&mut self.spectrum_settings.remove_dc, "Remove DC offset");
        if before
            != (
                self.spectrum_settings,
                self.spectrum_channel,
                self.spectrum_mode,
            )
            && self.running()
        {
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
    }

    fn spectrum_display_controls(&mut self, ui: &mut egui::Ui) {
        let view_before = (
            self.frequency_scale,
            self.floor_db,
            self.spectrum_ceiling_db,
            self.show_hold,
            self.span_hz,
            self.spectrum_min_hz,
        );
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
        setting_label(ui, "DISPLAY FREQUENCY RANGE");
        ui.horizontal(|ui| {
            ui.label("From");
            ui.add(
                egui::DragValue::new(&mut self.spectrum_min_hz)
                    .range(0.0..=self.sample_rate as f32 / 2.0)
                    .speed(0.1)
                    .suffix(" Hz"),
            );
        });
        ui.horizontal(|ui| {
            ui.label("To");
            ui.add(
                egui::DragValue::new(&mut self.span_hz)
                    .range(0.0..=self.sample_rate as f32 / 2.0)
                    .speed(0.1)
                    .suffix(" Hz"),
            );
        });
        ui.label(
            RichText::new("To = 0 uses Nyquist. Narrow ranges show individual bins.")
                .small()
                .color(MUTED),
        );
        setting_label(ui, "DISPLAY FLOOR");
        ui.add(egui::Slider::new(&mut self.floor_db, -180.0..=-60.0).text(self.analyzer.db_unit()));
        setting_label(ui, "DISPLAY CEILING");
        ui.add(egui::DragValue::new(&mut self.spectrum_ceiling_db)
            .range(self.floor_db + 6.0..=3200.0).speed(1.0).suffix(" dB"))
            .on_hover_text("Raise the display ceiling for calibrated levels above 0 dB. Display limits do not change numeric values.");
        ui.horizontal(|ui| {
            if ui.checkbox(&mut self.show_hold, "Peak hold").changed()
                && self.show_hold
                && self.pending_stop.is_none()
            {
                self.analyzer.clear_hold();
                if let Some(core) = &self.core {
                    core.clear_hold();
                }
            }
            if ui
                .add_enabled(
                    self.pending_stop.is_none(),
                    egui::Button::new("Clear hold").small(),
                )
                .clicked()
            {
                self.analyzer.clear_hold();
                if let Some(core) = &self.core {
                    core.clear_hold();
                }
                self.spectrum_dirty = true;
            }
        });
        self.spectrum_dirty |= view_before
            != (
                self.frequency_scale,
                self.floor_db,
                self.spectrum_ceiling_db,
                self.show_hold,
                self.span_hz,
                self.spectrum_min_hz,
            );
    }

    fn spectrum_controls(&mut self, ui: &mut egui::Ui) {
        self.spectrum_analysis_controls(ui);
        ui.separator();
        self.spectrum_display_controls(ui);
        ui.label(
            RichText::new(format!(
                "Δf {:.6} Hz · RBW {:.6} Hz\nWindow {:.1} ms · {} processed windows",
                self.analyzer.bin_hz(),
                self.analyzer.rbw_hz(),
                self.analyzer.settings().size as f32 / self.sample_rate as f32 * 1000.0,
                self.spectrum_info.updates
            ))
            .small()
            .color(MUTED),
        );
        if self.pending_stop.is_some() {
            ui.label(
                RichText::new("Stopping · finishing Spectrum windows")
                    .small()
                    .color(YELLOW),
            );
        } else if self.analyzer.validity() == spectrum::Validity::NonFinite {
            ui.label(
                RichText::new("Invalid FFT window · nonfinite sample or calibrated power")
                    .small()
                    .color(YELLOW),
            );
        } else if self.running() && !self.analyzer.is_ready() {
            ui.label(
                RichText::new(format!(
                    "Filling window · {} / {} samples",
                    self.spectrum_info.filled_samples, self.spectrum_settings.size
                ))
                .small()
                .color(MUTED),
            );
        }
        let cadence = match self.spectrum_info.mode {
            SpectrumMode::Continuous => format!(
                "Continuous · hop {:.1} ms",
                self.analyzer.settings().size as f64 / 4.0 / self.sample_rate as f64 * 1000.0
            ),
            SpectrumMode::Live if self.spectrum_info.observation_ms == 0 => {
                "Live · up to 60 updates/s".into()
            }
            SpectrumMode::Live => format!("Live · target {} ms", self.spectrum_info.observation_ms),
            SpectrumMode::Latest => {
                format!("Latest · target {} ms", self.spectrum_info.observation_ms)
            }
        };
        ui.label(
            RichText::new(format!(
                "{cadence} · missing input {} · invalid windows {} · missed observations {}",
                self.spectrum_info.input_missing,
                self.spectrum_info.invalid_windows,
                self.spectrum_info.missed_observations
            ))
            .small()
            .color(MUTED),
        );
        if let Some(window) = self.analyzer.window() {
            ui.label(RichText::new(format!("FFT end #{} · acquired end #{}", window.end, self.history.range().end)).small().color(MUTED))
                .on_hover_text("Spectrum and Scope/XY have independent sample intervals. FFT processing time and the age of this window are separate conditions.");
        }
        self.spectrum_band_controls(ui);
    }

    fn spectrum_band_controls(&mut self, ui: &mut egui::Ui) {
        if self.analyzer.settings().quantity == Quantity::Psd {
            ui.separator();
            setting_label(ui, "POWER IN BAND");
            let nyquist = self.analyzer.nyquist() as f64;
            ui.horizontal(|ui| {
                ui.label("From");
                ui.add(
                    egui::DragValue::new(&mut self.band_min_hz)
                        .range(0.0..=nyquist)
                        .speed(10.0)
                        .suffix(" Hz"),
                );
            });
            ui.horizontal(|ui| {
                ui.label("To");
                ui.add(
                    egui::DragValue::new(&mut self.band_max_hz)
                        .range(0.0..=nyquist)
                        .speed(10.0)
                        .suffix(" Hz"),
                );
            });
            ui.label(RichText::new("To = 0 uses Nyquist. Inclusive bin centres; whole bins. Band changes read the held PSD without resetting the average.").small().color(MUTED));
        }
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
                            "Start input to begin acquisition"
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
        if let Some(frame) = self.scope_history().get(sample) {
            let mut text = format!("#{sample}");
            for (trace, channel) in self.scope_view_channels().0.into_iter().enumerate() {
                if !self.enabled[trace] {
                    continue;
                }
                if let Some(value) = frame.get(channel) {
                    if let Some(value) = self.calibration.captured.value(channel, *value) {
                        text.push_str(&format!(
                            " · {} {value:+.5} {}",
                            channel::name(channel),
                            self.calibration.captured.unit(channel)
                        ));
                    } else {
                        text.push_str(&format!(" · {} invalid value", channel::name(channel)));
                    }
                } else {
                    text.push_str(&format!(" · {} unavailable", channel::name(channel)));
                }
            }
            text
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
                if let Some(frame) = sample.and_then(|sample| self.scope_history().get(sample)) {
                    for (trace, channel) in self.scope_view_channels().0.into_iter().enumerate() {
                        if !self.enabled[trace] {
                            continue;
                        }
                        let Some(value) = frame.get(channel) else {
                            continue;
                        };
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
            "F {:.6} Hz · {:.2} {}\nCH {} · {}..{} · α 1/{}",
            reading.frequency_hz,
            reading.level_db,
            window.db_unit(),
            window.channel + 1,
            window.start,
            window.end,
            window.settings.averages
        );
        cursor_note(ui, rect, 0, &text, YELLOW);
        response.clone().on_hover_text(format!("Nearest bin: {:.6e} {}. Latest window: samples {}..{} (exclusive end), CH {}, {} Hz, {} points, {}, {}. EMA α = 1/{}; {} processed windows, contribution envelope {}..{} (exponential weights). Input generation {}; missing windows {}.{}", reading.value, window.linear_unit(), window.start, window.end, window.channel + 1, window.sample_rate, window.settings.size, window.settings.window.name(), window.settings.precision.name(), window.settings.averages, reading.average.updates, reading.average.start, reading.average.end, self.input_generation, self.spectrum_info.missing_windows, times));
        response
            .clone()
            .on_hover_text(spectrum_calibration_description(
                self.analyzer.calibration(),
            ));
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
                        self.xy_view_settings(),
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
                self.xy_capture.channels.values(self.history.get(sample)?)
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
            && let Some(point) = self.xy_capture.channels.values(frame)
        {
            let at = position(point);
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
                    "{} X {} {:+.4} FS · Y {} {:+.4} FS\n{detail}",
                    cursor_name(index),
                    channel::name(self.xy_capture.channels.0[0]),
                    point[0],
                    channel::name(self.xy_capture.channels.0[1]),
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
            xy::CursorMode::TraceSnap => "Trace Snap: selects the nearest actual pair from the assigned X/Y channels and keeps its sample offset from the XY trigger. Uses Scope's trigger source, edge and level. Without a crossing, the reference moves with the latest window. Overlapping points select the latest sample; Stop freezes the capture.",
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
        let before_channels = self.xy_settings.channels;
        setting_label(ui, "X SOURCE");
        channel_select(
            ui,
            "xy_x_source",
            &mut self.xy_settings.channels.0[0],
            self.channels,
        );
        setting_label(ui, "Y SOURCE");
        channel_select(
            ui,
            "xy_y_source",
            &mut self.xy_settings.channels.0[1],
            self.channels,
        );
        if self.xy_settings.channels != before_channels {
            if self.running()
                && let Some(core) = &self.core
            {
                core.configure_xy(self.xy_settings.channels);
            }
            self.xy_dirty = true;
        }
        if !self.running() && self.xy_settings.channels != self.xy_view_settings().channels {
            ui.label(
                RichText::new("Source changes apply on Start. Held XY keeps its channels.")
                    .small()
                    .color(YELLOW),
            );
        }
        ui.label(
            RichText::new("X/Y use the same input frame.")
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
            self.xy_settings = xy::Settings {
                channels: self.xy_settings.channels,
                ..xy::Settings::default()
            };
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
            self.xy_view_settings(),
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
                self.xy_view_settings(),
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
                        "X: {} · {:.3} FS/div   Y: {} · {:.3} FS/div",
                        channel::name(self.xy_view_settings().channels.0[0]),
                        self.xy_settings.x_fs_per_div,
                        channel::name(self.xy_view_settings().channels.0[1]),
                        self.xy_settings.y_fs_per_div
                    ))
                    .small()
                    .color(PURPLE),
                );
                let (outer, response) =
                    ui.allocate_exact_size(plot_size(ui), egui::Sense::click_and_drag());
                if response.double_clicked() {
                    self.xy_settings = xy::Settings {
                        channels: self.xy_settings.channels,
                        ..xy::Settings::default()
                    };
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
                        } else if !self
                            .xy_view_settings()
                            .channels
                            .available(self.channels as usize)
                        {
                            "XY unavailable: assigned channel missing"
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
                // Use the same footer row height reserved by plot_size for the other plots.
                ui.horizontal(|ui| {
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
            });
    }

    fn workspace_controls(&mut self, ui: &mut egui::Ui) {
        setting_label(ui, "HELD MEASUREMENT RESULTS");
        ui.label(RichText::new("Stop input, then export Scope samples and statistics, Spectrum bins and their captured conditions to JSON.").small().color(MUTED));
        ui.add_enabled(
            !self.export_pending,
            egui::TextEdit::singleline(&mut self.export_path)
                .hint_text("Results JSON file path")
                .desired_width(f32::INFINITY),
        );
        if ui.add_enabled(!self.export_pending && self.can_export(), egui::Button::new("Export held results"))
            .on_hover_text("Exports the retained Scope interval and the independently timed Spectrum result. Missing samples stay null. Spectrogram, XY and cursors are not included.")
            .clicked() {
            self.request_export();
        }
        if let Some(status) = &self.export_status {
            ui.label(RichText::new(status).small().color(if self.export_error {
                YELLOW
            } else {
                MUTED
            }));
        }
        ui.separator();
        setting_label(ui, "MEASUREMENT SETTINGS");
        ui.label(RichText::new("Save the queued input, channels, analysis and calibration for the next Start. Restore while stopped; then start input explicitly.").small().color(MUTED));
        ui.add_enabled(
            self.settings_task.is_none(),
            egui::TextEdit::singleline(&mut self.settings_path)
                .hint_text("Settings JSON file path")
                .desired_width(f32::INFINITY),
        );
        ui.horizontal(|ui| {
            if ui
                .add_enabled(
                    self.settings_task.is_none() && !self.busy && self.source == Source::Live,
                    egui::Button::new("Save settings"),
                )
                .clicked()
            {
                self.request_settings(SettingsTask::Save);
            }
            if ui
                .add_enabled(
                    self.settings_task.is_none() && self.can_restore_settings(),
                    egui::Button::new("Restore settings"),
                )
                .clicked()
            {
                self.request_settings(SettingsTask::Restore);
            }
        });
        if let Some(status) = &self.settings_status {
            ui.label(RichText::new(status).small().color(if self.settings_error {
                YELLOW
            } else {
                MUTED
            }));
        }
        ui.separator();
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
        ui.label(RichText::new("Raw amplitude is digital full scale (FS). Channel calibration applies to Scope readouts and Spectrum. Spectrum uses bin peak amplitude or PSD in unit²/Hz; band integration gives unit² and RMS unit. Uncalibrated Spectrum uses dBFS or FS²/Hz. Δf is Fs / N; RBW is the window's equivalent noise bandwidth.").small().color(MUTED));
        ui.label(
            RichText::new("Audio input uses the selected nominal device sample rate.")
                .small()
                .color(MUTED),
        );
    }

    fn can_restore_settings(&self) -> bool {
        (self.source == Source::Live || self.source == Source::Software)
            && !self.running()
            && !self.busy
            && self.pending_stop.is_none()
            && self.pending_scope.is_none()
    }

    fn can_export(&self) -> bool {
        !self.running()
            && !self.busy
            && self.pending_stop.is_none()
            && self.pending_scope.is_none()
            && self.settings_task != Some(SettingsTask::Restore)
            && self.held_input.is_some()
            && (!self.history.is_empty() || self.analyzer.window().is_some())
    }

    fn capture_results(&self) -> Result<export::Document, String> {
        if !self.can_export() {
            return Err("Stop input and wait for the held measurement results".into());
        }
        let input = self.held_input.clone().ok_or("No held input conditions")?;
        if input.generation != self.input_generation {
            return Err("Held input generation does not match results".into());
        }
        let mut document = export::Document::capture(
            input,
            export::ScopeView {
                history: self.scope_history(),
                settings: self.core_scope,
                sweep: Sweep {
                    range: self.scope_range.clone(),
                    triggered: self.triggered,
                    sample_offset: self.scope_sample_offset,
                },
                calibrations: &self.calibration.captured,
                measurements: self.measurements,
                readings: self.scope_readings,
            },
            &self.analyzer,
            &self.spectrum_info,
            [
                self.band_min_hz,
                if self.band_max_hz == 0.0 {
                    self.sample_rate as f64 / 2.0
                } else {
                    self.band_max_hz
                },
            ],
            export::Loss {
                capture_dropped_samples: self.dropped,
                scope_missing_samples: self.scope_missing,
                display_snapshots_skipped_since_worker_start: self
                    .core
                    .as_ref()
                    .map_or(0, |core| {
                        core.metrics.display_skipped.load(Ordering::Relaxed)
                    }),
                input_failed: self.input_failed,
            },
        )?;
        if self.lockin_result.settings.enabled {
            document.lockin = Some(export::Lockin::capture(
                self.lockin_result.clone(),
                &self.calibration.captured,
            ));
        }
        Ok(document)
    }

    fn request_export(&mut self) {
        let result = (|| {
            if self.export_pending {
                return Err("An export is already in progress".into());
            }
            if self.export_path.trim().is_empty() {
                return Err("Enter a results file path".into());
            }
            let document = self.capture_results()?;
            self.export_worker
                .submit(std::path::PathBuf::from(&self.export_path), document)
        })();
        self.export_error = result.is_err();
        self.export_status = Some(match result {
            Ok(()) => {
                self.export_pending = true;
                "Exporting held results…".into()
            }
            Err(error) => error,
        });
    }

    fn poll_export(&mut self) {
        while let Ok(event) = self.export_worker.events.try_recv() {
            self.export_pending = false;
            let result = match event {
                export::Event::Saved(path) => Ok(format!("Results exported: {}", path.display())),
                export::Event::Error(error) => Err(error),
            };
            self.export_error = result.is_err();
            self.export_status = Some(result.unwrap_or_else(|error| error));
        }
    }

    fn capture_settings(&self) -> Result<settings::Document, String> {
        let input = if self.source == Source::Software {
            settings::Input {
                device_id: "measurelab:software-loopback".into(),
                device_name: "Software Loopback".into(),
                channels: 2,
                device_default_sample_rate: 48000,
                sample_rate: self.requested_sample_rate,
            }
        } else {
            let device = self
                .devices
                .get(self.selected)
                .ok_or("Select an input device first")?;
            settings::Input::from_device(device, self.requested_sample_rate)?
        };
        let document = settings::Document {
            version: settings::VERSION,
            measurement: settings::Measurement {
                software_loopback: (self.source == Source::Software)
                    .then(|| self.loopback_settings.clone()),
                lockin: self.lockin_settings,
                input,
                scope: settings::Scope {
                    mode: self.acquisition_mode,
                    channels: self.scope_channels,
                    ms_per_div: self.ms_per_div,
                    trigger: self.trigger,
                },
                spectrum: settings::Spectrum {
                    channel: self.spectrum_channel,
                    analysis: self.spectrum_settings,
                    mode: self.spectrum_mode,
                    band_min_hz: self.band_min_hz,
                    band_max_hz: self.band_max_hz,
                },
                spectrogram: settings::Spectrogram {
                    channel: self.spectrogram_channel,
                    analysis: self.spectrogram_settings,
                },
                xy: settings::Xy {
                    channels: self.xy_settings.channels,
                    milliseconds: self.xy_settings.milliseconds,
                },
                calibrations: settings::ChannelCalibration::capture(&self.calibration.pending),
            },
            workspace: settings::Workspace {
                visible: self.visible,
                lockin_visible: self.lockin_visible,
                lockin_display: self.lockin_display,
                layout: self.plot_layout,
                sidebar_visible: self.sidebar.visible,
                scope_enabled: self.enabled,
                scope_fs_per_div: self.fs_per_div,
                spectrum_scale: self.frequency_scale,
                spectrum_min_hz: self.spectrum_min_hz,
                spectrum_max_hz: self.span_hz,
                spectrum_floor_db: self.floor_db,
                spectrum_ceiling_db: self.spectrum_ceiling_db,
                spectrum_show_hold: self.show_hold,
                spectrogram_scale: self.spectrogram_scale,
                spectrogram_min_hz: self.spectrogram_min_hz,
                spectrogram_max_hz: self.spectrogram_max_hz,
                spectrogram_floor_db: self.spectrogram_floor,
                spectrogram_ceiling_db: self.spectrogram_ceiling,
                spectrogram_seconds: self.spectrogram_seconds,
                xy_x_fs_per_div: self.xy_settings.x_fs_per_div,
                xy_y_fs_per_div: self.xy_settings.y_fs_per_div,
                xy_cursor_mode: self.xy_cursor_mode,
            },
        };
        document.validate()?;
        if document.measurement.software_loopback.is_none() {
            document.measurement.input.resolve(&self.devices)?;
        }
        if self.capture.is_some()
            && (document.measurement.input.channels != self.channels
                || document.measurement.input.expected_sample_rate() != self.sample_rate)
        {
            return Err(
                "Active input differs from the device list; stop and refresh before saving".into(),
            );
        }
        Ok(document)
    }

    /// Transactional restoration: all checks precede mutation, and only queued
    /// conditions/display preferences change. Captured data keeps its metadata.
    fn restore_settings(&mut self, document: settings::Document) -> Result<(), String> {
        if !self.can_restore_settings() {
            return Err("Stop input and wait for pending operations before restoring".into());
        }
        let calibrations = document.validate()?;
        let selected = if document.measurement.software_loopback.is_some() {
            self.selected
        } else {
            document.measurement.input.resolve(&self.devices)?
        };
        for channel in 0..crate::signal::MAX_CHANNELS {
            if let Some(new) = calibrations.get(channel) {
                for known in [&self.calibration.pending, &self.calibration.captured] {
                    for old_channel in 0..crate::signal::MAX_CHANNELS {
                        if let Some(old) = known.get(old_channel)
                            && old.id() == new.id()
                            && old.revision() == new.revision()
                            && old != new
                        {
                            return Err(
                                "Saved calibration conflicts with an existing ID/revision".into()
                            );
                        }
                    }
                }
            }
        }
        let m = document.measurement;
        let w = document.workspace;
        self.selected = selected;
        self.requested_sample_rate = m.input.sample_rate;
        self.source = if m.software_loopback.is_some() {
            Source::Software
        } else {
            Source::Live
        };
        if let Some(software) = m.software_loopback {
            self.loopback_settings = software;
        }
        self.lockin_settings = m.lockin;
        self.restored_input = (self.source == Source::Live).then_some(m.input);
        self.acquisition_mode = m.scope.mode;
        self.scope_channels = m.scope.channels;
        self.ms_per_div = m.scope.ms_per_div;
        self.trigger = m.scope.trigger;
        self.spectrum_channel = m.spectrum.channel;
        self.spectrum_settings = m.spectrum.analysis;
        self.spectrum_mode = m.spectrum.mode;
        self.band_min_hz = m.spectrum.band_min_hz;
        self.band_max_hz = m.spectrum.band_max_hz;
        self.spectrogram_channel = m.spectrogram.channel;
        self.spectrogram_settings = m.spectrogram.analysis;
        self.xy_settings.channels = m.xy.channels;
        self.xy_settings.milliseconds = m.xy.milliseconds;
        self.calibration.pending = calibrations;
        self.calibration.select();
        self.visible = w.visible;
        self.lockin_visible = w.lockin_visible;
        self.lockin_display = w.lockin_display;
        self.plot_layout = w.layout;
        self.previous_view = None;
        self.sidebar.visible = w.sidebar_visible;
        self.enabled = w.scope_enabled;
        self.fs_per_div = w.scope_fs_per_div;
        self.frequency_scale = w.spectrum_scale;
        self.spectrum_min_hz = w.spectrum_min_hz;
        self.span_hz = w.spectrum_max_hz;
        self.floor_db = w.spectrum_floor_db;
        self.spectrum_ceiling_db = w.spectrum_ceiling_db;
        self.show_hold = w.spectrum_show_hold;
        self.spectrogram_scale = w.spectrogram_scale;
        self.spectrogram_min_hz = w.spectrogram_min_hz;
        self.spectrogram_max_hz = w.spectrogram_max_hz;
        self.spectrogram_floor = w.spectrogram_floor_db;
        self.spectrogram_ceiling = w.spectrogram_ceiling_db;
        self.spectrogram_seconds = w.spectrogram_seconds;
        self.xy_settings.x_fs_per_div = w.xy_x_fs_per_div;
        self.xy_settings.y_fs_per_div = w.xy_y_fs_per_div;
        self.xy_cursor_mode = w.xy_cursor_mode;
        self.dirty = true;
        self.xy_dirty = true;
        self.spectrum_dirty = true;
        Ok(())
    }

    fn request_settings(&mut self, task: SettingsTask) {
        let result = (|| {
            if self.settings_path.trim().is_empty() {
                return Err("Enter a settings file path".to_owned());
            }
            let operation = match task {
                SettingsTask::Save => settings::Operation::Save(Box::new(self.capture_settings()?)),
                SettingsTask::Restore if self.can_restore_settings() => {
                    settings::Operation::Restore
                }
                SettingsTask::Restore => return Err("Stop input before restoring settings".into()),
            };
            self.settings_worker
                .submit(std::path::PathBuf::from(&self.settings_path), operation)
        })();
        self.settings_error = result.is_err();
        match result {
            Ok(()) => {
                self.settings_task = Some(task);
                self.settings_status = Some("Working…".into());
            }
            Err(error) => self.settings_status = Some(error),
        }
    }

    fn poll_settings(&mut self) {
        while let Ok(event) = self.settings_worker.events.try_recv() {
            self.settings_task = None;
            let result = match event {
                settings::Event::Saved(path) => Ok(format!("Settings saved: {}", path.display())),
                settings::Event::Restored(path, document) => self.restore_settings(*document)
                    .map(|()| format!("Settings restored: {}. Input stays stopped; press Start input to measure.", path.display())),
                settings::Event::Error(error) => Err(error),
            };
            self.settings_error = result.is_err();
            self.settings_status =
                Some(result.unwrap_or_else(|error| format!("Settings failed: {error}")));
        }
    }

    fn select_view(&mut self, visible: [bool; 4]) {
        if self.visible == visible && !self.lockin_visible {
            return;
        }
        self.previous_view
            .get_or_insert((self.visible, self.lockin_visible, self.plot_layout));
        self.visible = visible;
        self.lockin_visible = false;
        self.plot_layout = PlotLayout::Auto;
    }

    fn restore_view(&mut self) {
        if let Some((visible, lockin, layout)) = self.previous_view.take() {
            self.visible = visible;
            self.lockin_visible = lockin;
            self.plot_layout = layout;
        }
    }

    fn view_menu(&mut self, ui: &mut egui::Ui) {
        ui.menu_button("View", |ui| {
            for (title, visible) in [
                ("Scope only", [true, false, false, false]),
                ("Spectrum only", [false, true, false, false]),
                ("Scope + Spectrum", [true, true, false, false]),
                ("All monitors", [true; 4]),
            ] {
                if ui.selectable_label(self.visible == visible && !self.lockin_visible, title).clicked() {
                    self.select_view(visible);
                    ui.close();
                }
            }
            for (title, scope) in [("Lock-in only", false), ("Scope + Lock-in", true)] {
                if ui.selectable_label(self.lockin_visible && self.visible == [scope, false, false, false], title).clicked() {
                    self.select_lockin_view(scope);
                    ui.close();
                }
            }
            if ui.add_enabled(self.previous_view.is_some(), egui::Button::new("Restore previous view")).clicked() {
                self.restore_view();
                ui.close();
            }
            ui.separator();
            for layout in [PlotLayout::Auto, PlotLayout::Columns, PlotLayout::Rows] {
                if ui.selectable_value(&mut self.plot_layout, layout, layout.name()).clicked() {
                    ui.close();
                }
            }
        }).response.on_hover_text("Switch display and arrangement. Hidden instruments continue measuring; Restore returns to the view before the first switch.");
    }

    fn adjust_menu(&mut self, ui: &mut egui::Ui, section: SettingsSection) {
        let response = ui
            .add_enabled(
                self.settings_task != Some(SettingsTask::Restore),
                egui::Button::new("Adjust").small(),
            )
            .on_hover_text("Adjust this instrument here, or open its sidebar settings");
        #[cfg(feature = "qa")]
        if self.smoke {
            let requested = std::env::var("MEASURELAB_UI_SMOKE_ADJUST");
            if matches!(
                (section, requested.as_deref()),
                (SettingsSection::Scope, Ok("scope"))
                    | (SettingsSection::Spectrum, Ok("spectrum" | "analysis"))
            ) {
                egui::Popup::open_id(ui.ctx(), egui::Popup::default_response_id(&response));
            }
        }
        egui::Popup::menu(&response)
            .close_behavior(egui::PopupCloseBehavior::CloseOnClickOutside)
            .show(|ui| {
                ui.set_width(300.0);
                // Use distinct widget IDs from the simultaneously visible sidebar.
                ui.push_id(("plot_adjust", section), |ui| {
                    ui.spacing_mut().item_spacing = vec2(6.0, 5.0);
                    ui.spacing_mut().slider_width = 150.0;
                    if section == SettingsSection::Spectrum {
                        ui.horizontal(|ui| {
                            ui.selectable_value(
                                &mut self.spectrum_adjust_analysis,
                                false,
                                "Display",
                            );
                            ui.selectable_value(
                                &mut self.spectrum_adjust_analysis,
                                true,
                                "Analysis",
                            );
                        });
                        ui.separator();
                    }
                    egui::ScrollArea::vertical()
                        .max_height((ui.ctx().content_rect().height() - 160.0).max(200.0))
                        .show(ui, |ui| match section {
                            SettingsSection::Scope => self.scope_controls(ui),
                            SettingsSection::Spectrum if self.spectrum_adjust_analysis => {
                                self.spectrum_analysis_controls(ui)
                            }
                            SettingsSection::Spectrum => {
                                self.spectrum_display_controls(ui);
                                self.spectrum_band_controls(ui);
                            }
                            _ => unreachable!(),
                        });
                    ui.separator();
                    if ui.button("Open sidebar settings").clicked() {
                        self.sidebar.reveal(section);
                        ui.close();
                    }
                });
            });
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
                        self.adjust_menu(ui, SettingsSection::Scope);
                        ui.label(
                            RichText::new(if self.trigger.edge != Edge::Free && !channel::available(self.trigger.channel, self.channels as usize) {
                                "TRIGGER SOURCE UNAVAILABLE"
                            } else if self.core_scope.mode != acquisition::Mode::Auto {
                                match self.acquisition_state {
                                    acquisition::State::Waiting => "WAITING FOR TRIGGER",
                                    acquisition::State::Acquiring => "ACQUIRING POST-TRIGGER",
                                    acquisition::State::WaitingWithCapture => "WAITING · PREVIOUS CAPTURE",
                                    acquisition::State::Complete => if self.pending_stop.is_some() { "FINISHING" } else { "SINGLE COMPLETE" },
                                }
                            } else if self.triggered {
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
                            "Raw trace · {} ms/div · {} FS/div",
                            self.scope_display_ms_per_div(), self.fs_per_div
                        ))
                        .small()
                        .color(MUTED),
                    );
                    for (index, color) in [GREEN, BLUE].into_iter().enumerate() {
                        if !self.enabled[index] {
                            continue;
                        }
                        let channel = self.scope_view_channels().0[index];
                        let unit = self.calibration.captured.unit(channel);
                        let reading = self.scope_readings[index];
                        ui.label(
                            RichText::new(format!(
                                "T{} · {}  {}",
                                index + 1, channel::name(channel),
                                match reading {
                                    Reading::Unavailable => "unavailable".into(),
                                    Reading::NonFinite => "invalid value".into(),
                                    Reading::Valid(m) => format!("RMS {:.3} · P-P {:.3} {unit}", m.rms, m.peak_to_peak),
                                }
                            ))
                            .monospace()
                            .small()
                            .color(color),
                        )
                        .on_hover_text(match reading {
                            Reading::Valid(m) => format!("Peak {:.5} {unit} · {} acquired samples · interval {}..{} (exclusive end) · generation {} · nominal {} Hz. {}. Trace coordinates and trigger level are in raw FS.", m.peak, m.samples, self.scope_range.start, self.scope_range.end, self.input_generation, self.sample_rate, calibration_description(&self.calibration.captured, channel)),
                            Reading::Unavailable => "No acquired samples for this channel and interval".into(),
                            Reading::NonFinite => "An acquired or calibrated value or statistic is nonfinite; no valid numeric readout".into(),
                        });
                    }
                });
                if self.scope_missing > 0 {
                    ui.label(
                        RichText::new(format!(
                            "Partial interval · {} missing samples",
                            self.scope_missing
                        ))
                        .small()
                        .color(YELLOW),
                    );
                }
                self.plot(ui);
            });
    }

    fn spectrum_view(&self) -> View {
        let mut view = View::full(self.sample_rate, self.frequency_scale, self.floor_db);
        view.ceiling_db = self.spectrum_ceiling_db.max(self.floor_db + 6.0);
        if self.span_hz > 0.0 {
            view.max_hz = self.span_hz.min(view.max_hz);
        }
        // Preserve a finite interval under edited ranges or a changed input Fs.
        let minimum_span = (self.analyzer.bin_hz() * 0.01).max(0.001);
        view.max_hz = view.max_hz.max(minimum_span * 2.0);
        view.min_hz = self
            .spectrum_min_hz
            .max(view.min_hz.min(view.max_hz * 0.1))
            .min(view.max_hz - minimum_span);
        view
    }

    fn refresh_spectrum_readouts(&mut self, view: View) {
        let upper = if self.band_max_hz == 0.0 {
            self.analyzer.nyquist() as f64
        } else {
            self.band_max_hz
        };
        let key = (view.min_hz, view.max_hz, self.band_min_hz, upper);
        if self.spectrum_numeric_key != Some(key) {
            self.spectrum_peak = self.analyzer.peak(view);
            self.spectrum_band = self.analyzer.band(self.band_min_hz, upper);
            self.spectrum_numeric_key = Some(key);
        }
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
                        self.adjust_menu(ui, SettingsSection::Spectrum);
                        ui.label(
                            RichText::new(format!(
                                "CH {} · {}",
                                self.analyzer
                                    .window()
                                    .map_or(self.spectrum_channel, |window| window.channel)
                                    + 1,
                                self.analyzer.db_unit()
                            ))
                            .small()
                            .color(YELLOW),
                        );
                    });
                });
                let view = self.spectrum_view();
                self.refresh_spectrum_readouts(view);
                if let Some(peak) = self.spectrum_peak {
                    ui.label(
                        RichText::new(format!(
                            "Peak bin  {:.4} Hz · {:.2} {}    Δf {:.6} Hz",
                            peak.frequency,
                            peak.level_db,
                            self.analyzer.db_unit(),
                            self.analyzer.bin_hz()
                        ))
                        .monospace()
                        .small()
                        .color(YELLOW),
                    );
                } else {
                    ui.label(
                        RichText::new(
                            format!("{} · {}", self.analyzer.settings().quantity.name(), self.analyzer.db_unit()),
                        )
                        .small()
                        .color(MUTED),
                    );
                }
                if self.analyzer.settings().quantity == Quantity::Psd {
                    if let Some(band) = &self.spectrum_band {
                        ui.label(RichText::new(format!(
                            "Band {:.1}–{:.1} Hz · {:.4e} {} · {:.5e} RMS {}",
                            band.first_hz, band.last_hz, band.power, self.analyzer.power_unit(), band.rms, self.analyzer.unit()
                        )).monospace().small().color(YELLOW))
                        .on_hover_text(format!(
                            "Requested {}–{} Hz, inclusive centres of bins {}..={}. Sum of f64 PSD × Δf; full weight at DC/Nyquist. CH {}, generation {}, {} processed windows, contribution envelope {}..{}. Input loss {}; missing windows {}. Windowed mean-square after optional DC removal; not the Scope observation interval.",
                            band.requested_hz[0], band.requested_hz[1], band.first_bin, band.last_bin,
                            band.window.channel + 1, self.input_generation, band.average.updates,
                            band.average.start, band.average.end, self.dropped, self.spectrum_info.missing_windows,
                        ));
                    } else {
                        ui.label(RichText::new("Band power unavailable · invalid window, range or nonfinite sum").small().color(MUTED));
                    }
                }
                if let Some(c) = self.analyzer.calibration() {
                    ui.label(RichText::new(format!("Calibration {} · rev {}", c.id(), c.revision())).small().color(MUTED))
                        .on_hover_text(spectrum_calibration_description(Some(c)));
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
        for db in (view.floor_db as i32..=view.ceiling_db as i32).filter(|db| db % 20 == 0) {
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
                .map(|i| {
                    (
                        view.min_hz + (view.max_hz - view.min_hz) * i as f32 / 5.0,
                        true,
                    )
                })
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
                if let Some(window) = self.analyzer.window() {
                    profile.record_spectrum(self.input_generation, window.end);
                }
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
        if let Some(peak) = self.spectrum_peak {
            let x = rect.left() + view.x(peak.frequency as f32) * rect.width();
            painter.line_segment(
                [pos2(x, rect.top()), pos2(x, rect.top() + 10.0)],
                Stroke::new(2.0, YELLOW),
            );
        }
        if !self.analyzer.is_ready() {
            painter.text(
                rect.center(),
                egui::Align2::CENTER_CENTER,
                if self.analyzer.validity() == spectrum::Validity::NonFinite {
                    "Invalid FFT window · nonfinite value"
                } else if self.running() {
                    "Collecting a complete FFT window…"
                } else if self.acquisition_state == acquisition::State::Complete {
                    "Single complete · FFT window was not filled"
                } else {
                    "Start input to begin acquisition"
                },
                egui::FontId::proportional(16.0),
                MUTED,
            );
        }
        if let Some(position) = response.hover_pos().filter(|p| rect.contains(*p)) {
            let hz = view.frequency((position.x - rect.left()) / rect.width());
            painter.line_segment(
                [
                    pos2(position.x, rect.top()),
                    pos2(position.x, rect.bottom()),
                ],
                Stroke::new(1.0, Color32::from_white_alpha(65)),
            );
            if let Some(reading) = self.analyzer.cursor(hz as f64) {
                painter.text(
                    rect.right_top() + vec2(-10.0, 10.0),
                    egui::Align2::RIGHT_TOP,
                    format!(
                        "{:.1} Hz · {:.2} {}",
                        reading.frequency_hz,
                        reading.level_db,
                        reading.window.db_unit()
                    ),
                    egui::FontId::monospace(11.0),
                    YELLOW,
                );
            }
        }
        self.spectrum_cursors(ui, &response, rect, view);
        ui.horizontal(|ui| {
            ui.label(RichText::new(self.analyzer.db_unit()).small().color(MUTED));
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
                format!("{:.1}", (x as f32 - 2.0) * self.scope_display_ms_per_div()),
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
            build_sweep_lines(
                self.scope_capture.as_ref().unwrap_or(&self.history),
                &Sweep {
                    range: self.scope_range.clone(),
                    triggered: self.triggered,
                    sample_offset: self.scope_sample_offset,
                },
                pixels,
                self.fs_per_div,
                self.enabled,
                self.scope_view_channels(),
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

impl Drop for ScopeApp {
    fn drop(&mut self) {
        self.core.take();
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
        self.check_ui_stall();
        #[cfg(feature = "qa")]
        let input_started = Instant::now();
        self.poll_audio();
        self.poll_measurement();
        self.poll_settings();
        self.poll_export();
        self.poll_workspace();
        self.compare_window(&ctx);
        if self.settings_task.is_some()
            || self.export_pending
            || self.workspace_pending
            || self.autoset_pending.is_some()
        {
            ctx.request_repaint_after(Duration::from_millis(25));
        }
        if self.pending_stop.is_some() || self.pending_scope.is_some() {
            ctx.request_repaint_after(Duration::from_millis(10));
        }
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
            self.check_large_fft_lifecycle(&ctx);
            self.check_lifecycle(&ctx, elapsed);
            self.check_input_lifecycle(&ctx);
            let running = self.running();
            if let Some(profile) = &mut self.profile {
                profile.record(elapsed, running, frame.info().cpu_usage);
                if profile.progress_due()
                    && let Some(core) = &self.core
                {
                    println!(
                        "QA progress: {} input frames, {} capture loss, {} FFT windows, demo poll interval max {:.3} ms, demo suspension gaps {}",
                        core.metrics.input_frames.load(Ordering::Relaxed),
                        self.dropped,
                        core.spectrum.metrics.windows.load(Ordering::Relaxed),
                        core.metrics.demo_interval_max_nanos.load(Ordering::Relaxed) as f64 / 1e6,
                        core.metrics.demo_suspensions.load(Ordering::Relaxed)
                    );
                }
                if profile.finished() {
                    assert!(self.error.is_none(), "UI QA input failed: {:?}", self.error);
                    if std::env::var_os("MEASURELAB_PROFILE_LIFECYCLE").is_some() {
                        assert_eq!(self.lifecycle_stage, 8, "UI lifecycle did not finish");
                    }
                    if std::env::var_os("MEASURELAB_PROFILE_INPUT_LIFECYCLE").is_some() {
                        assert_eq!(self.lifecycle_stage, 6, "input lifecycle did not finish");
                    }
                    if std::env::var_os("MEASURELAB_PROFILE_LARGE_LIFECYCLE").is_some() {
                        assert_eq!(
                            self.lifecycle_stage, 5,
                            "large FFT lifecycle did not complete"
                        );
                    }
                    // Terminal QA barrier fixes the finite endpoint before the
                    // report. This wait is outside the UI timing interval.
                    let finished = self.core.as_ref().map(|core| core.stop());
                    if let Some(snapshot) = &finished {
                        let result = &snapshot.spectrum;
                        if result.is_ready() {
                            let average = result.average().unwrap();
                            let seconds =
                                (average.end - average.start - result.settings().size as u64)
                                    as f64
                                    / snapshot.sample_rate as f64;
                            println!(
                                "Spectrum final: {} Hz, {} ch, CH {}, N {}, {:?}, {:?}, updates {}, missing windows {}, input missing {}, missed observations {}, latest end {}, acquired end {}, observed rate {:.3} Hz",
                                snapshot.sample_rate,
                                snapshot.history.channels(),
                                result.window().unwrap().channel + 1,
                                result.settings().size,
                                result.settings().quantity,
                                snapshot.spectrum_info.mode,
                                average.updates,
                                snapshot.spectrum_info.missing_windows,
                                snapshot.spectrum_info.input_missing,
                                snapshot.spectrum_info.missed_observations,
                                result.window().unwrap().end,
                                snapshot.history.range().end,
                                if seconds > 0.0 {
                                    (average.updates - 1) as f64 / seconds
                                } else {
                                    0.0
                                }
                            );
                            if std::env::var_os("MEASURELAB_PROFILE_DEMO_BIN_TONE").is_some() {
                                assert_eq!(snapshot.input_dropped, 0);
                                assert_eq!(snapshot.spectrum_info.input_missing, 0);
                                assert_eq!(snapshot.spectrum_info.missing_windows, 0);
                                if snapshot.spectrum_info.mode == SpectrumMode::Continuous {
                                    assert_eq!(
                                        average.updates,
                                        1 + (snapshot.history.range().end
                                            - result.settings().size as u64)
                                            / (result.settings().size / 4) as u64
                                    );
                                }
                                match result.settings().quantity {
                                    Quantity::Amplitude => assert!(
                                        (result.cursor(750.0).unwrap().value - 0.125).abs() < 1e-12
                                    ),
                                    Quantity::Psd => assert!(
                                        (result
                                            .band(0.0, snapshot.sample_rate as f64 / 2.0)
                                            .unwrap()
                                            .power
                                            - 0.0078125)
                                            .abs()
                                            < 1e-12
                                    ),
                                }
                                println!(
                                    "Known demo Spectrum OK: 750 Hz, 0.125 FS peak, no noise, 2ch / 90 degrees"
                                );
                            }
                        }
                    }
                    if let Some((_, failed)) = &self.known_output {
                        assert!(
                            !failed.load(Ordering::Relaxed),
                            "BlackHole fixture output failed"
                        );
                        let snapshot = finished.as_ref().unwrap();
                        assert_eq!(snapshot.input_dropped, 0);
                        assert_eq!(snapshot.spectrum_info.input_missing, 0);
                        assert_eq!(snapshot.spectrum_info.missing_windows, 0);
                        let result = &snapshot.spectrum;
                        let bin = (32 + self.spectrum_channel * 7) * result.settings().size / 8192;
                        let hz =
                            bin as f64 * self.sample_rate as f64 / result.settings().size as f64;
                        match result.settings().quantity {
                            Quantity::Amplitude => {
                                assert!((result.cursor(hz).unwrap().value - 0.125).abs() < 3e-8)
                            }
                            Quantity::Psd => assert!(
                                (result
                                    .band(0.0, self.sample_rate as f64 / 2.0)
                                    .unwrap()
                                    .power
                                    - 0.0078125)
                                    .abs()
                                    < 1e-8
                            ),
                        }
                        let end = snapshot.history.range().end;
                        if self.spectrum_mode == SpectrumMode::Continuous {
                            assert_eq!(
                                snapshot.spectrum_info.updates,
                                1 + (end - result.settings().size as u64)
                                    / (result.settings().size / 4) as u64
                            );
                        }
                        let average = result.average().unwrap();
                        let seconds = (average.end - average.start - result.settings().size as u64)
                            as f64
                            / self.sample_rate as f64;
                        println!(
                            "Known Spectrum OK: {} Hz, {} ch, CH {}, N {}, {:?}, {:?}, {} windows, latest end {}, acquired end {}, observed rate {:.3} Hz",
                            self.sample_rate,
                            self.channels,
                            self.spectrum_channel + 1,
                            result.settings().size,
                            result.settings().quantity,
                            self.spectrum_mode,
                            average.updates,
                            result.window().unwrap().end,
                            end,
                            (average.updates - 1) as f64 / seconds
                        );
                    }
                    if let Some(path) = std::env::var_os("MEASURELAB_PROFILE_EXPORT") {
                        // Terminal QA uses the same immutable finite Stop result;
                        // this I/O is outside the UI performance measurement.
                        let snapshot = finished.as_ref().expect("export QA needs a finite result");
                        let document = export::Document::capture(
                            self.held_input.clone().expect("captured input identity"),
                            export::ScopeView {
                                history: &snapshot.history,
                                settings: snapshot.scope_settings,
                                sweep: snapshot.sweep.clone(),
                                calibrations: &snapshot.calibrations,
                                measurements: snapshot.measurements,
                                readings: snapshot.scope_readings,
                            },
                            &snapshot.spectrum,
                            &snapshot.spectrum_info,
                            [0.0, snapshot.sample_rate as f64 / 2.0],
                            export::Loss {
                                capture_dropped_samples: snapshot.input_dropped,
                                scope_missing_samples: snapshot.scope_missing,
                                display_snapshots_skipped_since_worker_start: self
                                    .core
                                    .as_ref()
                                    .unwrap()
                                    .metrics
                                    .display_skipped
                                    .load(Ordering::Relaxed),
                                input_failed: snapshot.failed,
                            },
                        )
                        .expect("capture finite export result");
                        let expected = serde_json::to_value(&document).unwrap();
                        let path = std::path::PathBuf::from(path);
                        let worker = export::Worker::default();
                        worker.submit(path.clone(), document).unwrap();
                        match worker.events.recv_timeout(Duration::from_secs(30)).unwrap() {
                            export::Event::Saved(saved) => assert_eq!(saved, path),
                            export::Event::Error(error) => panic!("Export QA failed: {error}"),
                        }
                        let saved: serde_json::Value =
                            serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
                        assert_eq!(
                            saved, expected,
                            "result file does not match finite Stop snapshot"
                        );
                        println!(
                            "Finite result export OK: {} / generation {} / {} Hz / {} ch / Scope {:?} / Spectrum CH {:?}",
                            path.display(),
                            snapshot.generation,
                            snapshot.sample_rate,
                            snapshot.history.channels(),
                            snapshot.sweep.range,
                            snapshot.spectrum.window().map(|w| w.channel + 1)
                        );
                    }
                    profile.report(self.dropped);
                    if let Some(core) = &self.core {
                        println!(
                            "Spectrum transport: input dropped {}, high water {} / {}, skipped publications {}, FFT p95 {:.3} ms, FFT max {:.3} ms, planning max {:.3} ms, acquisition poll max {:.3} ms, Spectrum CPU {:.3} ms",
                            core.spectrum.metrics.input_dropped.load(Ordering::Relaxed),
                            core.spectrum
                                .metrics
                                .input_high_water
                                .load(Ordering::Relaxed),
                            crate::spectrum_worker::INPUT_BLOCKS,
                            core.spectrum
                                .metrics
                                .display_skipped
                                .load(Ordering::Relaxed),
                            core.spectrum.metrics.fft_p95_ms(),
                            core.spectrum.metrics.fft_max_nanos.load(Ordering::Relaxed) as f64
                                / 1e6,
                            core.spectrum
                                .metrics
                                .planning_max_nanos
                                .load(Ordering::Relaxed) as f64
                                / 1e6,
                            core.metrics.input_poll_max_nanos.load(Ordering::Relaxed) as f64 / 1e6,
                            core.spectrum
                                .metrics
                                .processing_nanos
                                .load(Ordering::Relaxed) as f64
                                / 1e6
                        );
                        println!(
                            "Measurement worker: {} input frames, {} FFT windows, {} skipped display updates, CPU {:.3} ms total",
                            core.metrics.input_frames.load(Ordering::Relaxed),
                            core.spectrum.metrics.windows.load(Ordering::Relaxed),
                            core.metrics.display_skipped.load(Ordering::Relaxed),
                            core.metrics.processing_nanos.load(Ordering::Relaxed) as f64 / 1e6
                        );
                        println!(
                            "Demo source: poll interval max {:.3} ms, suspension gaps {}",
                            core.metrics.demo_interval_max_nanos.load(Ordering::Relaxed) as f64
                                / 1e6,
                            core.metrics.demo_suspensions.load(Ordering::Relaxed)
                        );
                    }
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
                    if std::env::var_os("MEASURELAB_PROFILE_DEMO_BIN_TONE").is_some() {
                        let snapshot = finished.as_ref().expect("known demo finite endpoint");
                        assert_eq!(snapshot.input_dropped, 0, "known demo acquisition loss");
                        assert!(snapshot.spectrum.is_ready(), "known demo incomplete FFT");
                    }
                    self.profile = None;
                    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                }
                if running || std::env::var_os("MEASURELAB_PROFILE_IDLE").is_none() {
                    ctx.request_repaint();
                }
                if std::env::var_os("MEASURELAB_PROFILE_SCREENSHOT").is_some()
                    && !self.screenshot_requested
                    && self.created.elapsed().as_secs_f64()
                        > (self.spectrum_settings.size as f64 / self.sample_rate as f64 + 1.0)
                            .max(3.0)
                {
                    self.screenshot_requested = true;
                    ctx.send_viewport_cmd(egui::ViewportCommand::Screenshot(Default::default()));
                }
            }
        }
        // Validate active input independently of the expanded settings panel.
        // Stopped selections describe the next device, not the held topology.
        if self.running() {
            let last_channel = self.channels.max(1) as usize - 1;
            if self.spectrum_channel > last_channel {
                self.spectrum_channel = last_channel;
                self.reset_analysis();
            }
        }
        #[cfg(feature = "qa")]
        if self.smoke || self.profile.is_some() {
            if self.smoke && std::env::var_os("MEASURELAB_UI_SMOKE_SETTINGS_RESTORE").is_some() {
                assert_eq!(self.spectrum_channel, 15);
                assert_eq!(self.spectrogram_channel, 15);
                assert!(!self.running());
            }
            let screenshot = ctx.input(|input| {
                input.events.iter().find_map(|event| {
                    if let egui::Event::Screenshot { image, .. } = event {
                        Some(image.clone())
                    } else {
                        None
                    }
                })
            });
            if let Some(image) = screenshot {
                match save_screenshot(&image) {
                    Ok(()) => self.screenshot_received = true,
                    Err(error) => eprintln!("UI screenshot failed: {error}"),
                }
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
                self.file_menu(ui);
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if let Some(status) = &self.export_status
                        && ui
                            .small_button(if self.export_error {
                                "Export error"
                            } else {
                                "Export status"
                            })
                            .on_hover_text(status)
                            .clicked()
                    {
                        self.sidebar.reveal(SettingsSection::Workspace);
                    }
                    self.transport(ui);
                    ui.separator();
                    ui.label(
                        RichText::new(if self.pending_stop.is_some() {
                            "FINISHING ANALYSIS…"
                        } else if self.busy {
                            "OPENING DEVICE…"
                        } else if self.smoke {
                            "UI TEST FIXTURE"
                        } else if self.source.is_demo() {
                            if self.demo_running {
                                "● DEMO SIGNAL (QA)"
                            } else {
                                "DEMO SIGNAL (QA) · HELD"
                            }
                        } else if self.software_running {
                            "● SOFTWARE LOOPBACK"
                        } else if self.capture.is_some() {
                            "● LIVE INPUT"
                        } else {
                            "○ STOPPED"
                        })
                        .monospace()
                        .color(if self.source.is_demo() {
                            YELLOW
                        } else if self.running() {
                            GREEN
                        } else {
                            MUTED
                        }),
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
                    if let Some(status) = &self.settings_status
                        && ui
                            .small_button(if self.settings_error {
                                "Settings error"
                            } else {
                                "Settings status"
                            })
                            .on_hover_text(status)
                            .clicked()
                    {
                        self.sidebar.reveal(SettingsSection::Workspace);
                    }
                    ui.menu_button(RichText::new("Performance").small(), |ui| {
                        ui.label(RichText::new(&self.adapter).small().color(MUTED));
                        ui.separator();
                        ui.label(format!("UI {:.0} fps", self.fps));
                        ui.label(format!("Scope prep {:.2} ms", self.build_ms));
                        ui.label(format!("Worker FFT {:.2} ms", self.fft_ms));
                        ui.label(format!(
                            "Spectrum {:?} · {} windows · missing {}",
                            self.spectrum_info.mode,
                            self.spectrum_info.updates,
                            self.spectrum_info.missing_windows
                        ));
                        if let Some(core) = &self.core {
                            ui.label(format!(
                                "Display updates skipped {}",
                                core.metrics.display_skipped.load(Ordering::Relaxed)
                            ));
                        }
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
                    let enabled = self.visible.iter().filter(|v| **v).count()
                        + usize::from(self.lockin_visible)
                        > 1
                        || !self.visible[index];
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
                if ui
                    .add_enabled(
                        self.visible.contains(&true) || !self.lockin_visible,
                        egui::Button::new("Lock-in").selected(self.lockin_visible),
                    )
                    .clicked()
                {
                    self.lockin_visible = !self.lockin_visible;
                }
                self.view_menu(ui);
                if self.visible.contains(&true) {
                    self.cursor_controls(ui);
                }
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
            .chain(self.lockin_visible.then_some(Instrument::Lockin))
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
                                    Instrument::Lockin => self.lockin_panel(ui),
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
                ctx.send_viewport_cmd(egui::ViewportCommand::Focus);
                ctx.send_viewport_cmd(egui::ViewportCommand::Screenshot(Default::default()));
                // Slow first-frame GPU preparation must not request Screenshot
                // and Close together. Allow a fresh readback interval.
                self.created = Instant::now();
            }
            #[cfg(feature = "qa")]
            let ready_to_close =
                self.screenshot_received || self.created.elapsed() > Duration::from_secs(10);
            #[cfg(not(feature = "qa"))]
            let ready_to_close = true;
            if ready_to_close {
                println!("UI OK: {}", self.adapter);
                ctx.send_viewport_cmd(egui::ViewportCommand::Close);
            } else {
                // Keep QA readback moving even when idle-window timers are
                // coalesced by the desktop event loop; VSync still paces it.
                ctx.request_repaint();
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

fn spectrum_calibration_description(calibration: Option<&Calibration>) -> String {
    match calibration {
        Some(c) => format!(
            "Calibration {} · rev {} · y = {} × FS + {} {} · {}",
            c.id(),
            c.revision(),
            c.gain(),
            c.offset(),
            c.unit(),
            c.conditions()
        ),
        None => "Uncalibrated · FS".into(),
    }
}

fn calibration_description(set: &calibration::Set, channel: ChannelId) -> String {
    match set.get(channel) {
        Some(c) => format!(
            "{} · revision {} · y = {:.6e} × FS + {:.6e} {} · {}",
            c.id(),
            c.revision(),
            c.gain(),
            c.offset(),
            c.unit(),
            c.conditions()
        ),
        None => "Uncalibrated · FS".into(),
    }
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

fn channel_select(ui: &mut egui::Ui, id: &str, selected: &mut ChannelId, channels: u16) {
    egui::ComboBox::from_id_salt(id)
        .width(ui.available_width())
        .selected_text(if channel::available(*selected, channels as usize) {
            channel::name(*selected)
        } else {
            format!("{} · unavailable", channel::name(*selected))
        })
        .show_ui(ui, |ui| {
            for channel in 0..channels as usize {
                ui.selectable_value(selected, channel, channel::name(channel));
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
