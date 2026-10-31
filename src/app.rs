#[cfg(feature = "qa")]
use crate::demo::{Demo, Waveform};
use crate::{
    acquisition,
    audio::{AudioWorker, Command, DeviceInfo, Event},
    calibration::{self, Calibration, Reading},
    channel::{self, ChannelId, Pair, SCOPE_CHANNELS, ScopeChannels},
    comparison,
    cursor::{self, Cursors},
    export,
    gpu::{COLORS, PlotId, Segment, TraceCallback, TraceRenderer},
    i18n, lockin, loopback,
    measurement::{self, ScopeSettings, SpectrumMode},
    output,
    presentation::{Action, Console, InstrumentId as Instrument, Layout, Presentation, Screen},
    settings,
    signal::{
        Edge, History, Line, Measurement, Sweep, Trigger, Vertical, build_scaled_sweep_lines,
    },
    spectrogram, spectrogram_gpu,
    spectrum::{
        self, Analyzer, FFT_SIZES, FrequencyScale, Precision, Quantity, STFT_SIZES, Settings, View,
        Window,
    },
    stft::{self, RowInfo},
    workspace_io, xy,
};
#[cfg(feature = "qa")]
use eframe::egui_wgpu::wgpu;
use eframe::{
    egui::{self, Color32, RichText, Stroke, pos2, vec2},
    egui_wgpu,
};
use std::{
    sync::{Arc, Mutex, atomic::Ordering},
    time::{Duration, Instant},
};
mod comparison_panel;
mod display;
mod status_text;
use status_text::Status as UiStatus;
mod text;
use text::{DisplayName, InstrumentText};
mod cepstrogram_controls;
mod generator_panel;
#[cfg(feature = "qa")]
mod gui_qa;
mod io_panel;
mod lockin_panel;
mod monitor_controls;
mod plot_labels;
mod preferences;
mod scope_controls;
mod shell;
mod spectrogram_controls;
mod spectrum_controls;
mod spectrum_history;
mod workspace;
mod xy_controls;

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
    Generator,
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
            Self::Live | Self::Software | Self::Generator => false,
            #[cfg(feature = "qa")]
            Self::Demo => true,
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum SettingsTask {
    Save,
    Restore,
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
            .ok_or(i18n::text("common.calibration_revision_exhausted"))?;
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
    generator: generator_panel::GeneratorUi,
    generator_output: Option<output::Timeline>,
    external_output: Option<output::history::ExternalOutput>,
    #[cfg(feature = "qa")]
    input_callback_metrics: Option<Arc<crate::audio::Metrics>>,
    source: Source,
    software_running: bool,
    loopback_settings: loopback::Settings,
    comparison_settings: comparison::Settings,
    comparison_result: Arc<comparison::Result>,
    comparison_frequency_hz: f64,
    comparison_display: comparison_panel::ComparisonDisplay,
    lockin_settings: lockin::Settings,
    lockin_result: lockin::Result,
    lockin_display: settings::LockinDisplay,
    workspace_io: workspace_io::Worker,
    workspace_pending: bool,
    workspace_restoring: bool,
    workspace_status: Option<UiStatus>,
    reference: Option<Box<export::Document>>,
    reference_label: String,
    compare_open: bool,
    comparison_current: Option<Box<export::Document>>,
    presentation: Presentation,
    shell: shell::Shell,
    #[cfg(feature = "qa")]
    qa_previous_presentation: Option<Presentation>,
    #[cfg(feature = "qa")]
    demo: Demo,
    #[cfg(feature = "qa")]
    demo_enabled: bool,
    demo_running: bool,
    core: Option<measurement::Worker>,
    pending_stop: Option<measurement::PendingSnapshot>,
    pending_scope: Option<measurement::PendingSnapshot>,
    #[cfg(feature = "qa")]
    known_output: Option<crate::qa::output::Fixture>,
    start_after_stop: bool,
    spectrum_publication: (u64, u64),
    #[cfg(feature = "qa")]
    spectrum_timing: Option<crate::spectrum_worker::Timing>,
    input_generation: u64,
    snapshot_revision: u64,
    core_scope: ScopeSettings,
    acquisition_mode: acquisition::Mode,
    acquisition_state: acquisition::State,
    scope_capture: Option<History>,
    autoset_pending: Option<std::sync::mpsc::Receiver<Result<acquisition::Autoset, String>>>,
    autoset_status: Option<UiStatus>,
    scope_channels: ScopeChannels,
    xy_channels: Pair,
    spectrum_mode: SpectrumMode,
    spectrum_info: measurement::SpectrumInfo,
    stft_generation: u64,
    stft_applied: bool,
    spectrum_settings: Settings,
    analyzer: spectrum::Result,
    spectrum_display: settings::SpectrumDisplay,
    spectrum_overlays: [spectrum::Result; 3],
    spectrum_overlay_info: [measurement::SpectrumInfo; 3],
    spectrum_overlay_publication: [(u64, u64); 3],
    spectrum_last_view: Option<View>,
    spectrum_channel: ChannelId,
    frequency_scale: FrequencyScale,
    floor_db: f32,
    spectrum_ceiling_db: f32,
    span_hz: f32,
    spectrum_min_hz: f32,
    spectrum_numeric_key: Option<(f32, f32, f64, f64)>,
    spectrum_peak: Option<spectrum::Peak>,
    spectrum_peaks: [Option<spectrum::Peak>; 4],
    spectrum_band: Option<spectrum::BandReading>,
    spectrum_energy: Option<f64>,
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
    stft_history: spectrogram::history::Collector,
    last_stft: Option<RowInfo>,
    spectrogram_history: Arc<Mutex<spectrogram::History>>,
    spectrogram_settings: Settings,
    spectrogram_mode: stft::Analysis,
    cepstrum_log_floor_db: i16,
    cepstrogram_display: settings::CepstrogramDisplay,
    spectrogram_overlap: stft::Overlap,
    spectrum_history: spectrum_history::HistorySpectrum,
    spectrogram_channel: ChannelId,
    spectrogram_scale: FrequencyScale,
    spectrogram_min_hz: f32,
    spectrogram_max_hz: f32,
    spectrogram_floor: f32,
    spectrogram_ceiling: f32,
    spectrogram_seconds: f64,
    spectrogram_color_map: spectrogram::ColorMap,
    spectrogram_auto_color: bool,
    spectrogram_view_worker: spectrogram::viewport::Worker,
    spectrogram_snapshot: Arc<spectrogram::history::Snapshot>,
    spectrogram_hold: Option<Arc<spectrogram::history::Snapshot>>,
    spectrogram_hold_anchor: Option<u64>,
    spectrogram_anchor: u64,
    spectrogram_scroll: spectrogram::ScrollClock,
    spectrogram_selected: [Option<Arc<spectrogram::history::Frame>>; 2],
    spectrogram_auto_result: spectrogram::ColorRange,
    spectrogram_prepared_id: u64,
    spectrogram_pending_click: Option<spectrogram_controls::PendingClick>,
    spectrogram_unavailable_selection: [bool; 2],
    spectrogram_color_error: bool,
    spectrogram_drag_cursor: Option<usize>,
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
    enabled: [bool; SCOPE_CHANNELS],
    ms_per_div: f32,
    scope_vertical: [Vertical; SCOPE_CHANNELS],
    scope_common_vertical: Option<Vertical>,
    scope_selected: usize,
    scope_horizontal_position: f32,
    scope_trigger_display: settings::TriggerDisplay,
    scope_trigger_level_edit_frame: Option<u64>,
    trigger: Trigger,
    triggered: bool,
    lines: Vec<Line>,
    segments: Arc<Vec<Segment>>,
    measurements: [Measurement; SCOPE_CHANNELS],
    scope_readings: [Reading; SCOPE_CHANNELS],
    calibration: CalibrationEditor,
    preferences: preferences::State,
    settings_worker: settings::Worker,
    settings_path: String,
    settings_task: Option<SettingsTask>,
    settings_status: Option<UiStatus>,
    settings_error: bool,
    restored_input: Option<settings::Input>,
    held_input: Option<export::Input>,
    input_failed: bool,
    input_error: Option<String>,
    export_worker: export::Worker,
    export_path: String,
    export_pending: bool,
    export_status: Option<UiStatus>,
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
    menu_review: Option<gui_qa::menus::Review>,
    #[cfg(feature = "qa")]
    created: Instant,
    #[cfg(feature = "qa")]
    screenshot_requested: bool,
    #[cfg(feature = "qa")]
    smoke_focused: bool,
    #[cfg(feature = "qa")]
    screenshot_attempts: u8,
    #[cfg(feature = "qa")]
    screenshot_received: bool,
    #[cfg(feature = "qa")]
    screenshot_writer: crate::qa::screenshot::Writer,
    #[cfg(feature = "qa")]
    screenshot_requested_at: Option<Instant>,
    #[cfg(feature = "qa")]
    screenshot_device: wgpu::Device,
    #[cfg(feature = "qa")]
    profile: Option<crate::qa::Profile>,
    #[cfg(feature = "qa")]
    spectrogram_profile: spectrogram_controls::HistoryProfile,
    #[cfg(feature = "qa")]
    dpi_stage: u8,
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
    lifecycle_calibration_held: Option<(calibration::Set, [Reading; SCOPE_CHANNELS], String)>,
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
        #[cfg(feature = "qa")]
        if smoke {
            println!("QA framebuffer format: {:?}", render.target_format);
        }
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
        i18n::initialize(&cc.egui_ctx, if smoke { None } else { cc.storage });
        let mut stft = stft::Worker::new();
        let stft_history = spectrogram::history::Collector::new(stft.take_results());
        let core = (!smoke).then(|| measurement::Worker::new(stft.take_feeder()));
        let mut app = Self {
            generator: generator_panel::GeneratorUi::default(),
            generator_output: None,
            external_output: None,
            #[cfg(feature = "qa")]
            input_callback_metrics: None,
            source,
            software_running: false,
            loopback_settings: loopback::Settings::default(),
            comparison_settings: comparison::Settings::default(),
            comparison_result: Arc::new(comparison::Result::empty(
                comparison::Settings::default(),
                48000,
                0,
                0,
                2,
            )),
            comparison_frequency_hz: 1000.0,
            comparison_display: comparison_panel::ComparisonDisplay::default(),
            lockin_settings: lockin::Settings::default(),
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
            presentation: Presentation::default(),
            shell: shell::Shell::from_storage(if smoke { None } else { cc.storage }),
            #[cfg(feature = "qa")]
            qa_previous_presentation: None,
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
            #[cfg(feature = "qa")]
            spectrum_timing: None,
            input_generation: 1,
            snapshot_revision: 0,
            core_scope: ScopeSettings::default(),
            acquisition_mode: acquisition::Mode::Auto,
            acquisition_state: acquisition::State::Waiting,
            scope_capture: None,
            autoset_pending: None,
            autoset_status: None,
            scope_channels: ScopeChannels::default(),
            xy_channels: Pair::<2>::default(),
            spectrum_mode: SpectrumMode::Live,
            spectrum_info: measurement::SpectrumInfo {
                mode: SpectrumMode::Live,
                observation_ms: crate::spectrum_worker::LIVE_INTERVAL
                    .as_micros()
                    .div_ceil(1000) as u32,
                ..Default::default()
            },
            stft_generation: 0,
            stft_applied: false,
            spectrum_settings: Settings::default(),
            analyzer: spectrum::Result::empty(Settings::default(), 48000),
            spectrum_channel: 0,
            spectrum_display: settings::SpectrumDisplay::default(),
            spectrum_overlays: std::array::from_fn(|_| {
                spectrum::Result::empty(Settings::default(), 48000)
            }),
            spectrum_overlay_info: std::array::from_fn(|_| measurement::SpectrumInfo::default()),
            spectrum_overlay_publication: [(0, 0); 3],
            spectrum_last_view: None,
            frequency_scale: FrequencyScale::Log,
            floor_db: -120.0,
            spectrum_ceiling_db: 6.0,
            span_hz: 0.0,
            spectrum_min_hz: 0.0,
            spectrum_numeric_key: None,
            spectrum_peak: None,
            spectrum_peaks: [None; 4],
            spectrum_band: None,
            spectrum_energy: None,
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
            stft_history,
            last_stft: None,
            spectrogram_history: Arc::new(Mutex::new(spectrogram::History::default())),
            spectrogram_settings: Settings {
                averages: 1,
                ..Settings::default()
            },
            spectrogram_mode: stft::Analysis::Spectrogram,
            cepstrum_log_floor_db: crate::cepstrum::DEFAULT_LOG_FLOOR_DB,
            cepstrogram_display: Default::default(),
            spectrogram_channel: 0,
            spectrogram_scale: FrequencyScale::Log,
            spectrogram_min_hz: 20.0,
            spectrogram_max_hz: 0.0,
            spectrogram_floor: -120.0,
            spectrogram_ceiling: 0.0,
            spectrogram_seconds: 5.0,
            spectrogram_color_map: spectrogram::ColorMap::default(),
            spectrogram_auto_color: false,
            spectrogram_view_worker: spectrogram::viewport::Worker::default(),
            spectrogram_snapshot: Arc::default(),
            spectrogram_hold: None,
            spectrogram_hold_anchor: None,
            spectrogram_anchor: 0,
            spectrogram_scroll: spectrogram::ScrollClock::default(),
            spectrogram_overlap: stft::Overlap::default(),
            spectrum_history: spectrum_history::HistorySpectrum::default(),
            spectrogram_selected: [None, None],
            spectrogram_auto_result: spectrogram::ColorRange::default(),
            spectrogram_prepared_id: 0,
            spectrogram_pending_click: None,
            spectrogram_unavailable_selection: [false; 2],
            spectrogram_color_error: false,
            spectrogram_drag_cursor: None,
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
            enabled: [true; SCOPE_CHANNELS],
            ms_per_div: 1.0,
            scope_vertical: [Vertical::default(); SCOPE_CHANNELS],
            scope_common_vertical: None,
            scope_selected: 0,
            scope_horizontal_position: 0.0,
            scope_trigger_display: settings::TriggerDisplay::default(),
            scope_trigger_level_edit_frame: None,
            trigger: Trigger::default(),
            triggered: false,
            lines: Vec::with_capacity(8192),
            segments: Arc::new(Vec::with_capacity(8192)),
            measurements: [Measurement::default(); SCOPE_CHANNELS],
            scope_readings: [Reading::Unavailable; SCOPE_CHANNELS],
            calibration: CalibrationEditor::default(),
            preferences: preferences::State::new(
                !smoke && !demo && std::env::var_os("MEASURELAB_PROFILE_SECONDS").is_none(),
            ),
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
            input_error: None,
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
            menu_review: None,
            #[cfg(feature = "qa")]
            smoke_focused: false,
            #[cfg(feature = "qa")]
            screenshot_attempts: 0,
            #[cfg(feature = "qa")]
            screenshot_received: false,
            #[cfg(feature = "qa")]
            screenshot_writer: crate::qa::screenshot::Writer::default(),
            #[cfg(feature = "qa")]
            screenshot_requested_at: None,
            #[cfg(feature = "qa")]
            screenshot_device: render.device.clone(),
            #[cfg(feature = "qa")]
            profile: crate::qa::Profile::from_env()?,
            #[cfg(feature = "qa")]
            spectrogram_profile: spectrogram_controls::HistoryProfile::default(),
            #[cfg(feature = "qa")]
            dpi_stage: 0,
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
            if let Ok(mode) = std::env::var("MEASURELAB_PROFILE_SPECTROGRAM") {
                if !matches!(mode.as_str(), "live" | "stress") {
                    return Err("MEASURELAB_PROFILE_SPECTROGRAM must be live or stress".into());
                }
                app.presentation
                    .apply(Action::OpenSingle(Instrument::Spectrogram));
                app.spectrogram_seconds = 60.0;
                app.spectrogram_auto_color = true;
            }
            if std::env::var_os("MEASURELAB_PROFILE_SPECTRUM_ONLY").is_some() {
                app.select_view([false, true, false, false]);
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
            if std::env::var_os("MEASURELAB_PROFILE_CEPSTROGRAM").is_some() {
                app.spectrogram_mode = stft::Analysis::Cepstrogram;
            }
            app.spectrum_settings.size = size;
            app.spectrogram_settings.size = std::env::var("MEASURELAB_PROFILE_STFT_SIZE")
                .ok()
                .and_then(|s| s.parse().ok())
                .filter(|s| STFT_SIZES.contains(s))
                .unwrap_or(size.min(32768));
            app.spectrogram_overlap = match std::env::var("MEASURELAB_PROFILE_STFT_OVERLAP")
                .as_deref()
            {
                Ok("50") => stft::Overlap::Half,
                Ok("75") | Err(_) => stft::Overlap::ThreeQuarters,
                Ok("87.5") => stft::Overlap::SevenEighths,
                _ => return Err("MEASURELAB_PROFILE_STFT_OVERLAP must be 50, 75 or 87.5".into()),
            };
            app.spectrum_mode = match std::env::var("MEASURELAB_PROFILE_SPECTRUM_MODE").as_deref() {
                Ok("latest") => SpectrumMode::Latest,
                Ok("continuous") => SpectrumMode::Continuous,
                _ => SpectrumMode::Live,
            };
            app.reset_analysis();
        }
        #[cfg(feature = "qa")]
        if let Some(profile) = &app.profile
            && std::env::var_os("MEASURELAB_PROFILE_SOFTWARE_LOOPBACK").is_some()
        {
            if demo || smoke || profile.device.is_some() {
                return Err("Software Loopback profile requires its own input route".into());
            }
            app.source = Source::Software;
            app.requested_sample_rate = profile.sample_rate;
            app.loopback_settings.frequency_hz = 750.0;
            app.spectrum_channel = 1;
            app.spectrogram_channel = 1;
            app.start();
        }
        #[cfg(feature = "qa")]
        if let Some(profile) = &app.profile
            && std::env::var_os("MEASURELAB_PROFILE_GENERATOR_INTERNAL").is_some()
        {
            if demo || smoke || profile.device.is_some() {
                return Err("Internal Generator profile requires its own input route".into());
            }
            app.source = Source::Generator;
            let rate = profile.sample_rate.unwrap_or(48000);
            let mut settings = crate::generator::Settings::default();
            for signal in &mut settings.signals {
                signal.enabled = true;
                signal.frequency_hz = 750.0;
                signal.amplitude_dbfs = -20.0;
            }
            app.generator
                .select(output::Target::Internal, rate, settings)?;
        }
        #[cfg(feature = "qa")]
        if std::env::var_os("MEASURELAB_SPECTRUM_PSD").is_some() {
            app.spectrum_settings.quantity = Quantity::Psd;
            app.reset_analysis();
        }
        #[cfg(feature = "qa")]
        if std::env::var_os("MEASURELAB_PROFILE_KNOWN_OUTPUT").is_some()
            || std::env::var_os("MEASURELAB_PROFILE_PHYSICAL_OUTPUT").is_some()
        {
            let name = app
                .profile
                .as_ref()
                .and_then(|p| p.device.as_deref())
                .ok_or("Known-output QA requires a BlackHole profile device")?;
            app.known_output = Some(crate::qa::output::Fixture::new(
                name,
                app.profile.as_ref().and_then(|p| p.sample_rate),
                std::env::var_os("MEASURELAB_PROFILE_PHYSICAL_OUTPUT").is_some(),
            )?);
            if app.known_output.as_ref().unwrap().physical {
                app.lockin_settings.enabled = true;
                app.lockin_settings.frequency_hz = 1000.0;
                app.lockin_settings.reference_channel = 1;
                app.lockin_settings.response_channel = 0;
                app.spectrum_channel = 0;
            }
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
                    app.select_view([false, false, false, true]);
                }
                if std::env::var_os("MEASURELAB_UI_SMOKE_SCOPE_ONLY").is_some() {
                    app.select_view([true, false, false, false]);
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
            app.stft_history.freeze();
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
                app.cursors.set_frequency(0, app.demo.frequency as f64);
                match std::env::var("MEASURELAB_UI_SMOKE_CURSOR_VIEW").as_deref() {
                    Ok("spectrum") => {
                        app.cursors
                            .set_frequency(1, app.demo.frequency as f64 * 2.0);
                    }
                    Ok("spectrogram") => {
                        app.spectrogram_seconds = 1.0;
                        let row = app.last_stft.unwrap();
                        for (index, age) in [0.2, 0.4].into_iter().enumerate() {
                            if let Some(sample) =
                                cursor::sample_at_age(row.end, age, row.config.sample_rate)
                            {
                                app.cursors.set_spectrogram_sample(index, sample);
                            }
                        }
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
            if std::env::var_os("MEASURELAB_UI_SMOKE_SCOPE4").is_some()
                || std::env::var_os("MEASURELAB_UI_SMOKE_SPECTRUM4").is_some()
            {
                app.channels = 4;
                app.held_input.as_mut().unwrap().channels = 4;
                app.history = History::with_channels(96000, 4);
                app.scope_channels = ScopeChannels::default();
                app.scope_selected = 2;
                app.scope_vertical[2].fs_per_div = 0.125;
                app.scope_vertical[3].offset = -0.25;
                for n in 0..16384 {
                    let p = std::f64::consts::TAU * n as f64 / 48.0;
                    app.history.push([
                        0.375 * p.sin(),
                        0.25 * p.cos(),
                        0.125 * (p + 0.8).sin(),
                        0.0625 * (p - 0.4).cos(),
                    ]);
                }
            }
            if std::env::var_os("MEASURELAB_UI_SMOKE_SPECTRUM4").is_some() {
                app.spectrum_display.enabled = [true; 4];
                app.spectrum_display.selected = 1;
                app.spectrum_display.auto_level = true;
                app.spectrum_settings.averages = 16;
                app.spectrum_display.average_weight = 16;
                app.frequency_scale = FrequencyScale::Linear;
                app.span_hz = 5000.0;
                app.history.clear_at(0);
                for n in 0..16384 {
                    let samples: [f64; 4] = std::array::from_fn(|ch| {
                        0.5_f64.powi(ch as i32 + 1)
                            * (std::f64::consts::TAU * (128 * (ch + 1)) as f64 * n as f64 / 8192.0)
                                .sin()
                    });
                    app.history.push(samples);
                }
            }
            // Render every inspector with the same deterministic signal fixture.
            if std::env::var_os("MEASURELAB_UI_SMOKE_ROUTING").is_some() {
                app.channels = 16;
                app.history = History::with_channels(96000, 16);
                app.scope_channels = Pair([15, 7]).scope();
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
                Ok("input" | "output" | "io") => {
                    app.shell.io = Some(shell::IoTab::Connections);
                }
                Ok("generator") => {
                    app.presentation
                        .apply(Action::OpenSingle(Instrument::Generator));
                    app.presentation.details_visible = true;
                }
                Ok("calibration") => app.shell.io = Some(shell::IoTab::Calibration),
                Ok("scope") => {
                    app.presentation
                        .apply(Action::OpenSingle(Instrument::Scope));
                    app.presentation.details_visible = true;
                }
                Ok("spectrum") => {
                    app.presentation
                        .apply(Action::OpenSingle(Instrument::Spectrum));
                    app.presentation.details_visible = true;
                }
                Ok("spectrogram") => {
                    app.presentation
                        .apply(Action::OpenSingle(Instrument::Spectrogram));
                    app.presentation.details_visible = true;
                }
                Ok("xy") => {
                    app.presentation.apply(Action::OpenSingle(Instrument::Xy));
                    app.presentation.details_visible = true;
                }
                Ok("lockin") => {
                    app.presentation
                        .apply(Action::OpenSingle(Instrument::Lockin));
                    app.presentation.details_visible = true;
                }
                Ok("workspace") => app.shell.file_paths = true,
                Ok("collapsed") => app.presentation.details_visible = false,
                Ok("hidden") => app.presentation.details_visible = false,
                _ => {}
            }
            match std::env::var("MEASURELAB_UI_SMOKE_VIEW").as_deref() {
                Ok("scope") => app.select_view([true, false, false, false]),
                Ok("spectrum") => app.select_view([false, true, false, false]),
                Ok("spectrogram") => app
                    .presentation
                    .apply(Action::OpenSingle(Instrument::Spectrogram)),
                Ok("xy") => app.presentation.apply(Action::OpenSingle(Instrument::Xy)),
                Ok("lockin") => app
                    .presentation
                    .apply(Action::OpenSingle(Instrument::Lockin)),
                Ok("comparison") => app
                    .presentation
                    .apply(Action::OpenSingle(Instrument::Comparison)),
                Ok("generator") => app
                    .presentation
                    .apply(Action::OpenSingle(Instrument::Generator)),
                Ok("pair") => app.select_view([true, true, false, false]),
                Ok("all") => app.select_view([true; 4]),
                Ok("console") => {
                    for i in Instrument::ALL {
                        app.presentation.apply(Action::AddToConsole(i));
                    }
                    app.presentation.console.layout = Layout::Grid;
                    app.presentation.apply(Action::FocusPane(Instrument::Scope));
                }
                Ok("empty") => app.presentation.apply(Action::OpenConsole),
                _ => {}
            }
            if let Ok(layout) = std::env::var("MEASURELAB_UI_SMOKE_LAYOUT") {
                app.presentation.console.layout = match layout.as_str() {
                    "columns" => Layout::Columns,
                    "rows" => Layout::Rows,
                    "grid" => Layout::Grid,
                    "tabs" => Layout::Tabs,
                    _ => return Err("QA layout must be columns, rows, grid or tabs".into()),
                };
            }
            match std::env::var("MEASURELAB_UI_SMOKE_ADJUST").as_deref() {
                Ok("scope") => {
                    app.presentation
                        .apply(Action::OpenSingle(Instrument::Scope));
                    app.presentation.details_visible = true;
                }
                Ok("spectrum" | "analysis") => {
                    app.presentation
                        .apply(Action::OpenSingle(Instrument::Spectrum));
                    app.presentation.details_visible = true;
                }
                _ => {}
            }
        }
        if smoke {
            app.update_spectrum(true);
            #[cfg(feature = "qa")]
            if std::env::var_os("MEASURELAB_UI_SMOKE_ESD").is_some() {
                app.check_esd_ui()?;
            }
            #[cfg(feature = "qa")]
            if std::env::var_os("MEASURELAB_UI_SMOKE_SETTINGS_RESTORE").is_some() {
                app.check_settings_restore()?;
            }
            #[cfg(feature = "qa")]
            if std::env::var_os("MEASURELAB_UI_SMOKE_STARTUP_PREFERENCES").is_some() {
                app.check_startup_preferences(&cc.egui_ctx)?;
            }
            #[cfg(feature = "qa")]
            if std::env::var_os("MEASURELAB_UI_SMOKE_EXPORT").is_some() {
                app.refresh_scope_range();
                app.check_results_export()?;
            }
        }
        #[cfg(feature = "qa")]
        if smoke
            && (std::env::var_os("MEASURELAB_UI_SMOKE_STAGE3F").is_some()
                || std::env::var_os("MEASURELAB_UI_SMOKE_BLACKHOLE").is_some()
                || std::env::var_os("MEASURELAB_UI_SMOKE_PHYSICAL").is_some())
        {
            app.check_stage3f()?;
        }
        #[cfg(feature = "qa")]
        if smoke && let Ok(mode) = std::env::var("MEASURELAB_UI_SMOKE_LOCKIN") {
            app.check_lockin_ui(&mode)?;
        }
        #[cfg(feature = "qa")]
        if smoke && let Ok(mode) = std::env::var("MEASURELAB_UI_SMOKE_GENERATOR") {
            app.check_generator_ui(&mode)?;
            if mode == "narrow" {
                cc.egui_ctx
                    .send_viewport_cmd(egui::ViewportCommand::InnerSize(vec2(900.0, 660.0)));
            }
        }
        #[cfg(feature = "qa")]
        if smoke && let Ok(mode) = std::env::var("MEASURELAB_UI_SMOKE_COMPARISON") {
            app.check_comparison_ui(&mode)?;
        }
        #[cfg(feature = "qa")]
        if app.profile.is_some()
            && let Ok(name) = std::env::var("MEASURELAB_PROFILE_GENERATOR_DEVICE")
        {
            let rate = app
                .profile
                .as_ref()
                .and_then(|p| p.sample_rate)
                .unwrap_or(48000);
            if app.profile.as_ref().and_then(|p| p.device.as_deref()) != Some(name.as_str()) {
                return Err(
                    "Generator profile requires the same explicit input/output device name".into(),
                );
            }
            app.lockin_settings = lockin::Settings {
                enabled: true,
                frequency_hz: 750.0,
                time_constant_seconds: 0.005,
                ..Default::default()
            };
            app.spectrum_channel = 1;
            app.spectrum_settings.window = Window::Rectangular;
            app.spectrum_settings.averages = 1;
            app.ms_per_div = 512.0 / 480.0;
            app.scope_vertical.fill(Vertical {
                fs_per_div: 0.05,
                offset: 0.0,
            });
            app.qa_show(Instrument::Lockin);
            app.setup_generator_device(&name, rate, false)?;
            if std::env::var_os("MEASURELAB_PROFILE_COMPARISON").is_some() {
                app.comparison_settings = comparison::Settings {
                    enabled: true,
                    size: 8192,
                    averages: 4,
                    response_channel: app.lockin_settings.response_channel,
                    ..Default::default()
                };
                app.comparison_frequency_hz = 750.0;
                app.select_view([true, false, false, false]);
                app.qa_show(Instrument::Comparison);
            }
        }
        #[cfg(feature = "qa")]
        if let Ok(zoom) = std::env::var("MEASURELAB_UI_SMOKE_ZOOM") {
            let zoom = zoom.parse::<f32>().map_err(|e| e.to_string())?;
            if !zoom.is_finite() || !(0.5..=2.0).contains(&zoom) {
                return Err("QA zoom must be 0.5..=2.0".into());
            }
            cc.egui_ctx.set_zoom_factor(zoom);
        }
        #[cfg(feature = "qa")]
        if smoke && std::env::var_os("MEASURELAB_UI_SMOKE_IDLE").is_some() {
            app.source = Source::Live;
            app.demo_enabled = false;
            app.core = None;
            app.channels = 0;
            app.format.clear();
            app.held_input = None;
            app.history = History::with_channels(96000, 1);
            app.scope_range = 0..0;
            app.scope_capture = None;
            app.scope_readings = [Reading::Unavailable; SCOPE_CHANNELS];
            app.analyzer = spectrum::Result::empty(app.spectrum_settings, app.sample_rate);
            app.spectrum_peak = None;
            app.spectrum_band = None;
            app.spectrum_energy = None;
            app.spectrum_numeric_key = None;
            app.last_stft = None;
            app.spectrogram_history = Arc::new(Mutex::new(spectrogram::History::default()));
            app.xy_capture = xy::Capture::default();
            app.dirty = true;
        }
        #[cfg(feature = "qa")]
        if smoke && std::env::var_os("MEASURELAB_UI_SMOKE_GENERATOR_COLLAPSED").is_some() {
            app.generator.controls_expanded = false;
        }
        #[cfg(feature = "qa")]
        if smoke && std::env::var_os("MEASURELAB_UI_SMOKE_DETAILS").is_some() {
            app.presentation.details_visible = true;
            app.shell.narrow_details = true;
        }
        #[cfg(feature = "qa")]
        if smoke && let Ok(mode) = std::env::var("MEASURELAB_UI_SMOKE_TRIGGER_DISPLAY") {
            app.scope_trigger_display = match mode.as_str() {
                "markers" => settings::TriggerDisplay::Markers,
                "guides" => settings::TriggerDisplay::Guides,
                "off" => settings::TriggerDisplay::Off,
                _ => return Err("QA trigger display must be markers, guides or off".into()),
            };
        }
        #[cfg(feature = "qa")]
        if smoke {
            app.check_redesign_navigation()?;
            if std::env::var_os("MEASURELAB_UI_SMOKE_CEPSTROGRAM").is_some() {
                app.check_cepstrogram_interactions()?;
            }
            if std::env::var_os("MEASURELAB_UI_SMOKE_LANGUAGE").is_some() {
                app.check_language_controls()?;
            }
            if std::env::var_os("MEASURELAB_UI_SMOKE_SPECTROGRAM_DISPLAY").is_some() {
                app.check_spectrogram_display_interactions()?;
            }
            if std::env::var_os("MEASURELAB_UI_SMOKE_INTERACTIONS").is_some() {
                app.check_redesign_interactions()?;
                app.check_common_io_interactions()?;
                if std::env::var_os("MEASURELAB_UI_SMOKE_IDLE").is_some() {
                    app.check_input_guidance()?;
                    app.check_analysis_guidance()?;
                }
            }
            if let Ok(mode) = std::env::var("MEASURELAB_UI_SMOKE_SCOPE_FLOW") {
                app.check_scope_workflow(&mode)?;
            }
            app.shell.sidebar_compact =
                std::env::var("MEASURELAB_UI_SMOKE_SIDEBAR").as_deref() == Ok("compact");
            if let Ok(locale) = std::env::var("MEASURELAB_UI_SMOKE_LOCALE") {
                if !i18n::Locale::ALL.iter().any(|value| value.id() == locale) {
                    return Err("QA locale must be a supported identifier".into());
                }
                i18n::set_locale(&cc.egui_ctx, &locale);
            }
            app.qa_previous_presentation = None;
            app.menu_review = gui_qa::menus::Review::from_env(&mut app)?;
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
        self.scope_channels = Pair([15, 7]).scope();
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
        ])
        .scope();
        self.export_status = Some("Export QA passed; captured conditions preserved".into());
        self.shell.file_paths = true;
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
        document.measurement.scope.channels = Pair([15, 7]).scope();
        document.measurement.spectrum.channel = 15;
        document.measurement.spectrum.analysis.size = 1024;
        document.measurement.spectrum.analysis.quantity = Quantity::Psd;
        document.measurement.spectrum.mode = SpectrumMode::Latest;
        document.measurement.spectrogram.channel = 15;
        document.measurement.xy.channels = Pair([15, 7]);
        document.measurement.input.sample_rate = Some(96_000);
        document.workspace.presentation.details_visible = true;
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
        self.shell.file_paths = true;
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
                let original_view = self.presentation.clone();
                self.qa_previous_presentation = None;
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
                assert_eq!(self.presentation.clone(), original_view);
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
                    Quantity::Psd | Quantity::Esd => Quantity::Amplitude,
                };
                self.spectrum_channel = 0;
                self.frequency_scale = FrequencyScale::Linear;
                self.floor_db = -100.0;
                self.spectrum_dirty = true;
                self.select_view([false, false, false, true]);
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
                self.select_view([false, false, true, false]);
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
                self.select_view([true; 4]);
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
                let frame = self.stft_history.snapshot().latest().unwrap().clone();
                self.cursors.set_spectrogram_sample(0, frame.info.end - 1);
                self.lifecycle_scope_samples = self.cursor_samples();
                assert!(self.lifecycle_scope_samples.iter().all(Option::is_some));
                self.select_view([false, false, true, false]);
                self.lifecycle_stage = 7;
            }
            7 if elapsed > 3.5 => {
                self.xy_dirty = true;
                self.rebuild_xy();
                let samples = self.cursor_samples();
                for (index, sample) in samples.into_iter().enumerate() {
                    if index == 0 {
                        assert_eq!(sample, self.lifecycle_scope_samples[index]);
                    } else {
                        assert!(sample.unwrap() > self.lifecycle_scope_samples[index].unwrap());
                    }
                }
                assert_eq!(
                    self.cursors.times[0].unwrap().spectrogram_sample(),
                    self.lifecycle_scope_samples[0]
                );
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
                self.select_view([true; 4]);
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
            self.error.is_none() && self.input_error.is_none(),
            "input lifecycle error: {:?} / {:?}",
            self.error,
            self.input_error
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
                self.scope_channels = Pair([self.channels as usize - 1, 0]).scope();
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
                self.scope_channels = Pair([0, self.channels as usize - 1]).scope();
                self.xy_settings.channels = Pair([self.channels as usize - 1, 0]);
                self.dirty = true;
                self.xy_dirty = true;
                self.select_view([false, false, true, false]);
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
                    Pair([self.channels as usize - 1, 0]).scope()
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
                self.select_view([true; 4]);
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

    fn input_failure_message(&self) -> &'static str {
        if self.source == Source::Generator {
            i18n::text("io.generator_input_stopped_check_output_status_stop_input_and")
        } else {
            i18n::text("io.audio_stream_stopped_check_device_connection_and_microphone_permission")
        }
    }

    fn running(&self) -> bool {
        self.capture.is_some() || self.demo_running || self.software_running
    }

    fn fail_input(&mut self, error: String) {
        self.input_error = Some(error);
        self.stop();
    }

    fn begin_observation(&mut self) {
        self.autoset_pending = None;
        self.autoset_status = None;
        self.error = None;
        self.generator_output = None;
        self.external_output = None;
        self.cursors.new_epoch();
        self.input_generation += 1;
        self.held_input = None;
        self.comparison_result = Arc::new(comparison::Result::empty(
            self.comparison_settings,
            self.sample_rate,
            self.input_generation,
            0,
            self.channels as usize,
        ));
        self.lockin_result = lockin::Analyzer::new(self.lockin_settings, self.sample_rate)
            .result()
            .clone();
        self.input_failed = false;
        self.input_error = None;
        self.core_scope.channels = self.scope_channels;
        self.xy_channels = self.xy_settings.channels;
        self.history.clear_at(0);
        self.scope_capture = None;
        self.scope_range = 0..0;
        self.scope_sample_offset = 0.0;
        self.xy_capture = xy::Capture::default();
        self.xy_trace_range = 0..0;
        self.measurements = [Measurement::default(); SCOPE_CHANNELS];
        self.scope_readings = [Reading::Unavailable; SCOPE_CHANNELS];
        self.calibration.captured = self.calibration.pending.clone();
        self.scope_missing = 0;
        self.dirty = true;
        self.xy_dirty = true;
        // The new device topology is not known until Started. Preparing the
        // old topology here used to clamp queued CH 16 back to CH 1 at startup.
        self.analyzer = spectrum::Result::empty(self.spectrum_settings, self.sample_rate);
        self.clear_spectrum_overlays();
        #[cfg(feature = "qa")]
        {
            self.spectrum_timing = None;
        }
        self.spectrum_numeric_key = None;
        self.spectrum_info = measurement::SpectrumInfo {
            mode: self.spectrum_mode,
            ..Default::default()
        };
        self.spectrum_dirty = true;
        self.stft_history.freeze();
        self.stft.pause();
        self.last_stft = None;
        self.clear_spectrogram_view();
        self.stft_history.clear();
        self.spectrogram_history.lock().unwrap().clear();
    }

    fn core_config(&self) -> measurement::Config {
        measurement::Config {
            comparison: self.comparison_settings,
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
        self.generator_output.clone_from(&snapshot.generator_output);
        self.external_output.clone_from(&snapshot.external_output);
        self.comparison_current = None;
        let samples_changed = self.history.range() != snapshot.history.range();
        self.dirty |= self.core_scope != snapshot.scope_settings;
        self.xy_dirty |= self.xy_channels != snapshot.xy_channels;
        self.comparison_result = snapshot.comparison.clone();
        self.lockin_result = snapshot.lockin.clone();
        self.sample_rate = snapshot.sample_rate;
        std::mem::swap(&mut self.history, &mut snapshot.history);
        if snapshot.has_spectrum {
            for (index, result, info) in snapshot.spectrum_overlays.drain(..) {
                self.spectrum_overlays[index] = result;
                self.spectrum_overlay_info[index] = info;
            }
            std::mem::swap(&mut self.analyzer, &mut snapshot.spectrum);
            self.spectrum_info = snapshot.spectrum_info.clone();
            self.fft_ms = snapshot.fft_ms;
            #[cfg(feature = "qa")]
            {
                self.spectrum_timing = snapshot.spectrum_timing;
            }
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
            self.fail_input(self.input_failure_message().into());
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
                    if self.scope_common_vertical.is_some() {
                        self.fit_scope_amplitude();
                    } else {
                        for (index, channel) in self.scope_view_channels().0.into_iter().enumerate()
                        {
                            if channel == result.trigger.channel {
                                self.scope_vertical[index] = Vertical {
                                    fs_per_div: result.fs_per_div as f32,
                                    offset: 0.0,
                                };
                            }
                        }
                    }
                    self.scope_horizontal_position = 0.0;
                    self.ms_per_div = result.samples as f32 * 100.0 / self.sample_rate as f32;
                    self.trigger = result.trigger;
                    if self.running() || self.acquisition_mode == acquisition::Mode::Auto {
                        self.ms_per_div = result.samples as f32 * 100.0 / self.sample_rate as f32;
                        self.trigger = result.trigger;
                        self.dirty = true;
                        UiStatus::Autoset {
                            frequency_hz: result.frequency_hz,
                            held: false,
                        }
                    } else {
                        UiStatus::Autoset {
                            frequency_hz: result.frequency_hz,
                            held: true,
                        }
                    }
                }
                Err(error) => error.into(),
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
            self.receive_spectrum_overlays();
            let publication = self
                .core
                .as_mut()
                .and_then(|core| core.spectrum.take_latest());
            if let Some(mut publication) = publication {
                if publication.generation == self.input_generation
                    && self.spectrum_display.enabled[0]
                    && publication.channel == self.spectrum_channel
                    && publication.result.settings() == self.spectrum_settings
                    && publication.info.mode == self.spectrum_mode
                    && (publication.epoch, publication.revision) > self.spectrum_publication
                {
                    self.spectrum_publication = (publication.epoch, publication.revision);
                    std::mem::swap(&mut self.analyzer, &mut publication.result);
                    self.spectrum_info.clone_from(&publication.info);
                    self.fft_ms = publication.fft_ms;
                    #[cfg(feature = "qa")]
                    {
                        self.spectrum_timing = publication.timing;
                    }
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
            self.fail_input(self.input_failure_message().into());
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
        // For Generator QA, suspend UI only after both I/O paths are running.
        // The old input-only gate stalled before Start output and never tested
        // whether signal generation survives a paused feedback consumer.
        let output_frames = if std::env::var_os("MEASURELAB_PROFILE_GENERATOR_DEVICE").is_some() {
            let Some(frames) = self.generator.profile_stall_frames() else {
                return;
            };
            Some(frames)
        } else {
            None
        };
        self.ui_stall_checked = true;
        let core = self.core.as_ref().unwrap();
        let frames = core.metrics.input_frames.load(Ordering::Relaxed);
        let windows = core.spectrum.metrics.windows.load(Ordering::Relaxed);
        let stft_rows = self.stft_history.metrics.collected.load(Ordering::Relaxed);
        let stft_end = self
            .stft_history
            .snapshot()
            .latest()
            .map(|frame| frame.info.end);
        let stft_dropped = self.stft.metrics.result_dropped.load(Ordering::Relaxed);
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
        let stft_rows = self.stft_history.metrics.collected.load(Ordering::Relaxed) - stft_rows;
        if let Some(before) = stft_end
            && stall.as_secs_f64() > self.stft_config().hop as f64 / self.sample_rate as f64 + 0.04
        {
            assert!(stft_rows > 0, "UI stall stopped STFT history collection");
            assert!(self.stft_history.snapshot().latest().unwrap().info.end > before);
            assert_eq!(
                self.stft.metrics.result_dropped.load(Ordering::Relaxed),
                stft_dropped,
                "UI stall exhausted STFT result storage"
            );
        }
        assert!(core.metrics.display_skipped.load(Ordering::Relaxed) > 0);
        if let Some(before) = output_frames {
            let after = self
                .generator
                .profile_stall_frames()
                .expect("Generator output failed during UI stall");
            let advanced = after.saturating_sub(before);
            assert!(
                advanced > self.generator.rate as u64 / 2,
                "UI stall stopped output callbacks"
            );
            println!("Generator UI stall output: {advanced} PCM frames continued");
        }
        let mut snapshot = core.scope(self.core_config().scope);
        assert_eq!(snapshot.input_dropped, 0, "UI stall lost measurement input");
        assert_eq!(snapshot.spectrum_info.missing_windows, 0);
        assert_eq!(snapshot.spectrum_info.input_missing, 0);
        // Internal Generator retains its absolute output sample origin. Its
        // finite profile barrier checks counts relative to that origin.
        if self.spectrum_mode == SpectrumMode::Continuous && self.source != Source::Generator {
            assert_eq!(
                snapshot.spectrum_info.updates,
                1 + (snapshot.history.range().end - self.spectrum_settings.size as u64)
                    / (self.spectrum_settings.size / 4) as u64
            );
        }
        self.accept_snapshot(&mut snapshot);
        println!(
            "UI stall OK: {:.3} ms without UI updates; {frames} input frames, {windows} FFT windows and {stft_rows} collected STFT frames continued",
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
                self.presentation
                    .apply(Action::OpenSingle(Instrument::Scope));
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
                self.qa_show(Instrument::Spectrum);
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
            for index in 0..3 {
                if self.spectrum_display.enabled[index + 1]
                    && self.spectrum_display.overlay_channels[index] < self.history.channels()
                {
                    let mut analyzer = Analyzer::new(self.spectrum_settings, self.sample_rate);
                    analyzer.set_calibration(
                        self.calibration
                            .captured
                            .get(self.spectrum_display.overlay_channels[index])
                            .cloned()
                            .map(Arc::new),
                    );
                    analyzer.update(&self.history, self.spectrum_display.overlay_channels[index]);
                    analyzer.copy_result(&mut self.spectrum_overlays[index]);
                    if let Some(average) = self.spectrum_overlays[index].average() {
                        self.spectrum_overlay_info[index].updates = average.updates;
                        self.spectrum_overlay_info[index].contributing = average.start..average.end;
                    }
                }
            }
            self.spectrum_dirty = true;
            self.spectrum_numeric_key = None;
        }
    }

    fn cursor_samples(&self) -> [Option<u64>; 2] {
        self.cursors.times.map(|time| {
            let time = time?;
            if time.trace_offset().is_some() {
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

    fn scope_view_channels(&self) -> ScopeChannels {
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

    fn cursor_controls(&mut self, ui: &mut egui::Ui, instrument: Instrument) {
        ui.label(i18n::text("common.place_cursor"));
        for (index, title) in ["A", "B"].into_iter().enumerate() {
            ui.selectable_value(&mut self.active_cursor, index, title)
                .on_hover_text(i18n::text(
                    "common.choose_which_cursor_the_next_plot_click_or_drag",
                ));
        }
        if ui
            .small_button(i18n::text("common.clear_cursors"))
            .on_hover_text(i18n::text(
                "common.clear_both_a_b_time_cursors_spectrum_spectrogram_frequency",
            ))
            .clicked()
        {
            self.cursors.clear();
            self.spectrogram_selected = [None, None];
            self.spectrogram_unavailable_selection = [false; 2];
            self.spectrogram_pending_click = None;
            ui.ctx().request_repaint();
        }
        let placed = if instrument == Instrument::Xy && self.xy_cursor_mode == xy::CursorMode::Free
        {
            self.cursors.xy_points.map(|point| point.is_some())
        } else {
            self.cursors.times.map(|time| time.is_some())
        };
        ui.label(
            RichText::new(cursor_placement_label(placed))
                .small()
                .color(MUTED),
        )
        .on_hover_text(i18n::text(
            "common.stored_cursor_positions_for_this_view_readings_can_be",
        ));
        let mut text = String::new();
        for (index, time) in self.cursors.times.into_iter().enumerate() {
            let Some(time) = time else { continue };
            if time.scope_x().is_some() {
                if let Some(seconds) = self.cursor_samples()[index]
                    .and_then(|sample| self.scope_cursor_seconds(sample))
                {
                    text.push_str(
                        i18n::format(
                            "common.ms",
                            &[
                                ("index", (cursor_name(index))),
                                ("seconds", &format!("{:+.3}", seconds * 1000.0)),
                            ],
                        )
                        .as_ref(),
                    );
                }
            } else if let Some(offset) = time.trace_offset() {
                text.push_str(
                    i18n::format(
                        "common.t_ms_2",
                        &[
                            ("index", (cursor_name(index))),
                            (
                                "sample_rate",
                                &format!(
                                    "{:+.3}",
                                    offset as f64 * 1000.0 / self.sample_rate as f64
                                ),
                            ),
                        ],
                    )
                    .as_ref(),
                );
            } else if let Some(sample) = self.cursors.sample(time, self.scope_range.clone()) {
                text.push_str(&format!("{} #{sample}  ", cursor_name(index)));
            }
        }
        if let [Some(a), Some(b)] = self.cursor_samples()
            && self.sample_rate > 0
        {
            let delta = cursor::signed_distance(b, a) / self.sample_rate as f64;
            text.push_str(
                i18n::format(
                    "common.t_ms",
                    &[("delta", &format!("{:+.3}", delta * 1000.0))],
                )
                .as_ref(),
            );
        }
        if !text.is_empty() {
            ui.label(RichText::new(text).small().color(MUTED));
        }
    }

    fn reset_analysis(&mut self) {
        self.spectrum_channel = self.spectrum_channel.min(self.channels.max(1) as usize - 1);
        self.analyzer = spectrum::Result::empty(self.spectrum_settings, self.sample_rate);
        self.clear_spectrum_overlays();
        #[cfg(feature = "qa")]
        {
            self.spectrum_timing = None;
        }
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
        self.configure_spectrum_display();
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
        self.stft_applied |= self.running();
        self.clear_spectrogram_view();
        self.spectrogram_channel = self
            .spectrogram_channel
            .min(self.channels.max(1) as usize - 1);
        let config = self.stft_config();
        let generation = self
            .stft
            .configure(config)
            .expect("validated STFT settings");
        self.stft_generation = generation;
        self.stft_history
            .configure(self.input_generation, generation, config);
        if let Some(core) = &self.core {
            core.configure_stft(generation, config);
        }
        self.spectrogram_history.lock().unwrap().clear();
        self.last_stft = None;
        if !self.running() && !self.smoke {
            self.stft_history.freeze();
            self.stft.pause();
        }
    }

    fn stft_config(&self) -> stft::Config {
        stft::Config {
            analysis: self.spectrogram_mode,
            log_floor_db: if self.spectrogram_mode == stft::Analysis::Cepstrogram {
                self.cepstrum_log_floor_db
            } else {
                crate::cepstrum::DEFAULT_LOG_FLOOR_DB
            },
            sample_rate: self.sample_rate,
            channels: self.channels.max(1) as usize,
            channel: self.spectrogram_channel,
            size: self.spectrogram_settings.size,
            hop: self.spectrogram_overlap.hop(self.spectrogram_settings.size),
            window: self.spectrogram_settings.window,
            remove_dc: self.spectrogram_settings.remove_dc,
            precision: if self.spectrogram_mode == stft::Analysis::Cepstrogram {
                Precision::F64
            } else {
                self.spectrogram_settings.precision
            },
        }
    }

    fn start(&mut self) {
        if self.preferences.loading
            || self.settings_task == Some(SettingsTask::Restore)
            || self.workspace_restoring
        {
            return;
        }
        if self.pending_stop.is_some() {
            self.start_after_stop = true;
            return;
        }
        if self.source == Source::Generator {
            if self.generator.target != output::Target::Internal {
                self.input_error = Some(
                    i18n::text("common.select_an_audio_input_to_observe_audio_device_output")
                        .into(),
                );
                return;
            }
            let rate = self.generator.status.nominal_sample_rate;
            if self.generator.pending || rate != self.generator.rate {
                self.input_error =
                    Some(i18n::text("common.wait_for_the_generator_settings_to_be_applied").into());
                return;
            }
            if let Err(e) = self.lockin_settings.validate(rate) {
                self.input_error = Some(e);
                return;
            }
            let capture = match self.generator.worker.capture() {
                Ok(c) => c,
                Err(e) => {
                    self.input_error = Some(e);
                    return;
                }
            };
            self.begin_observation();
            self.sample_rate = rate;
            self.channels = 2;
            self.format = "Generator internal loopback · f64".into();
            self.held_input = Some(export::Input {
                generation: self.input_generation,
                source: export::Source::Generator,
                nominal_sample_rate_hz: rate,
                channels: 2,
            });
            self.history = History::with_channels((rate as usize * 2).max(32768), 2);
            self.input_error = None;
            self.dropped = 0;
            self.dirty = true;
            self.xy_dirty = true;
            // reset_stft pauses a stopped input. Mark this start before
            // configuring its worker, as the audio/demo paths already do.
            self.software_running = true;
            self.reset_analysis();
            self.reset_stft();
            if let Err(error) = self.core.as_ref().unwrap().start_generator(
                self.input_generation,
                capture,
                rate,
                self.core_config(),
            ) {
                self.stop();
                self.input_error = Some(error);
            }
            return;
        }
        if self.source == Source::Software {
            let rate = self.requested_sample_rate.unwrap_or(48000);
            if let Err(e) = self
                .loopback_settings
                .validate(rate)
                .and_then(|()| self.lockin_settings.validate(rate))
            {
                self.input_error = Some(e);
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
            self.input_error = None;
            self.software_running = true;
            self.reset_analysis();
            self.reset_stft();
            if let Err(error) = self.core.as_ref().unwrap().start_loopback(
                self.input_generation,
                self.loopback_settings.clone(),
                rate,
                self.core_config(),
            ) {
                self.stop();
                self.input_error = Some(error);
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
            self.input_error = None;
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
        if self.devices.get(self.selected).is_none() || self.busy {
            return;
        }
        if let Some(input) = &self.restored_input {
            match input.resolve(&self.devices) {
                Ok(index) if index == self.selected => {}
                Ok(_) => {
                    self.input_error = Some(
                        i18n::text(
                            "common.restored_input_selection_changed_restore_settings_again",
                        )
                        .into(),
                    );
                    return;
                }
                Err(error) => {
                    self.input_error = Some(error);
                    return;
                }
            }
        }
        self.input_error = None;
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
        self.stft_history.freeze();
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

    fn accept_devices(&mut self, devices: Vec<DeviceInfo>) {
        let remembered = self.restored_input.clone().or_else(|| {
            (self.source == Source::Live)
                .then(|| self.devices.get(self.selected))
                .flatten()
                .and_then(|device| {
                    settings::Input::from_device(device, self.requested_sample_rate).ok()
                })
        });
        self.selected = devices.iter().position(|d| d.is_default).unwrap_or(0);
        self.devices = devices;
        if self.source == Source::Live {
            if let Some(input) = remembered {
                match input.resolve(&self.devices) {
                    Ok(index) => {
                        self.selected = index;
                        self.input_error = None;
                    }
                    Err(error) => {
                        self.selected = usize::MAX;
                        self.input_error = Some(error);
                    }
                }
                self.requested_sample_rate = input.sample_rate;
                self.restored_input = Some(input);
            } else {
                self.calibration.clear_input();
                self.requested_sample_rate = None;
            }
        }
    }

    fn poll_audio(&mut self) {
        while let Ok(event) = self.audio.events.try_recv() {
            self.busy = false;
            match event {
                Event::Devices(devices) => {
                    self.accept_devices(devices);
                    #[cfg(feature = "qa")]
                    if let Some(name) = self.profile.as_ref().and_then(|p| p.device.as_ref()) {
                        if let Some(index) = self.devices.iter().position(|d| &d.name == name) {
                            self.selected = index;
                            self.requested_sample_rate =
                                self.profile.as_ref().and_then(|p| p.sample_rate);
                            if let Some(fixture) = &self.known_output
                                && let Err(error) = fixture.start()
                            {
                                self.input_error = Some(error);
                                continue;
                            }
                            if std::env::var_os("MEASURELAB_PROFILE_GENERATOR_DEVICE").is_none() {
                                self.start();
                            }
                        } else {
                            self.input_error = Some(format!("QA input device not found: {name}"));
                        }
                    }
                }
                Event::Started(capture) => {
                    #[cfg(feature = "qa")]
                    {
                        self.input_callback_metrics = Some(capture.metrics.clone());
                    }
                    if self.restored_input.as_ref().is_some_and(|input| {
                        input.channels != capture.channels
                            || input.expected_sample_rate() != capture.sample_rate
                    }) {
                        self.audio.send(Command::Stop);
                        self.busy = true;
                        self.input_error = Some(i18n::text("common.input_conditions_changed_since_restoration_refresh_devices_and_restore").into());
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
                            Ok("input") => self.shell.io = Some(shell::IoTab::Connections),
                            Ok("spectrum") => {
                                self.presentation
                                    .apply(Action::OpenSingle(Instrument::Spectrum));
                                self.presentation.details_visible = true
                            }
                            _ => {}
                        }
                    }
                    self.dirty = true;
                    self.reset_analysis();
                    self.reset_stft();
                    self.core.as_ref().unwrap().start_capture_observed(
                        self.input_generation,
                        capture,
                        self.core_config(),
                        Some(&self.generator.worker.history),
                    );
                }
                Event::Stopped => {}
                Event::Error(error) => {
                    self.fail_input(error);
                }
            }
        }
    }

    fn input_transport_enabled(&self) -> bool {
        !self.preferences.loading
            && !self.busy
            && self.settings_task != Some(SettingsTask::Restore)
            && !self.workspace_restoring
            && self.pending_stop.is_none()
            && (self.source.is_demo()
                || matches!(self.source, Source::Software | Source::Generator)
                || self.devices.get(self.selected).is_some())
    }

    fn transport(&mut self, ui: &mut egui::Ui) {
        if ui
            .add_enabled(
                self.input_transport_enabled(),
                egui::Button::new(
                    RichText::new(if self.running() {
                        i18n::text("io.stop_input")
                    } else if self.source.is_demo() {
                        i18n::text("io.start_input_demo")
                    } else {
                        i18n::text("io.start_input")
                    })
                    .color(if self.running() {
                        Color32::from_rgb(255, 170, 116)
                    } else {
                        GREEN
                    }),
                ),
            )
            .on_hover_text(i18n::text(
                "io.start_or_stop_the_shared_input_for_all_instruments",
            ))
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
        self.autoset_pending = None;
        self.autoset_status = None;
        self.restored_input = None;
        self.calibration.clear_input();
        self.cursors.new_epoch();
        self.scope_capture = None;
        self.scope_range = 0..0;
        self.scope_sample_offset = 0.0;
        self.xy_dirty = true;
        self.stop();
        self.input_generation += 1;
        self.comparison_result = Arc::new(comparison::Result::empty(
            self.comparison_settings,
            self.sample_rate,
            self.input_generation,
            0,
            self.channels as usize,
        ));
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
        self.measurements = [Measurement::default(); SCOPE_CHANNELS];
        self.scope_readings = [Reading::Unavailable; SCOPE_CHANNELS];
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
        self.input_error = None;
        self.reset_analysis();
        self.reset_stft();
    }

    fn input_rate_label(&self) -> String {
        self.requested_sample_rate.map_or_else(
            || {
                if self.capture.is_some() {
                    i18n::format(
                        "io.device_default_khz",
                        &[(
                            "sample_rate",
                            &(self.sample_rate as f64 / 1000.0).to_string(),
                        )],
                    )
                    .to_string()
                } else {
                    i18n::text("io.device_default").into()
                }
            },
            |rate| {
                i18n::format("io.khz", &[("rate", &(rate as f64 / 1000.0).to_string())]).to_string()
            },
        )
    }

    fn calibration_controls(&mut self, ui: &mut egui::Ui) {
        ui.label(
            RichText::new(i18n::text(
                "io.scope_readouts_and_spectrum_use_y_gain_fs_offset",
            ))
            .small()
            .color(MUTED),
        );
        ui.label(
            RichText::new(i18n::text(
                "io.queued_definitions_apply_on_the_next_start_source_device",
            ))
            .small()
            .color(MUTED),
        );
        setting_label(ui, i18n::text("io.input_channel"));
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
        if self
            .scope_input_channels()
            .is_some_and(|count| !channel::available(channel, count as usize))
        {
            ui.label(
                RichText::new(i18n::text("io.channel_unavailable_in_the_current_input"))
                    .small()
                    .color(YELLOW),
            );
        }
        setting_label(ui, i18n::text("io.captured_readout_condition"));
        ui.label(
            RichText::new(calibration_description(&self.calibration.captured, channel))
                .small()
                .color(MUTED),
        );
        setting_label(ui, i18n::text("io.queued_for_next_start"));
        ui.label(
            RichText::new(calibration_description(&self.calibration.pending, channel))
                .small()
                .color(MUTED),
        );
        ui.horizontal(|ui| {
            ui.label(i18n::text("io.gain"));
            ui.add(
                egui::DragValue::new(&mut self.calibration.gain)
                    .speed(0.01)
                    .max_decimals(15)
                    .range(-f64::MAX..=f64::MAX),
            );
            ui.label(i18n::text("io.unit_fs"));
        });
        ui.horizontal(|ui| {
            ui.label(i18n::text("io.offset"));
            ui.add(
                egui::DragValue::new(&mut self.calibration.offset)
                    .speed(0.001)
                    .max_decimals(15)
                    .range(-f64::MAX..=f64::MAX),
            );
            ui.label(i18n::text("io.unit"));
        });
        setting_label(ui, i18n::text("io.physical_unit_e_g_v_a_pa"));
        ui.add(
            egui::TextEdit::singleline(&mut self.calibration.unit)
                .desired_width(f32::INFINITY)
                .char_limit(24),
        );
        setting_label(ui, i18n::text("io.reference_conditions"));
        ui.add(
            egui::TextEdit::singleline(&mut self.calibration.conditions)
                .desired_width(f32::INFINITY)
                .char_limit(1024)
                .hint_text(i18n::text("io.reference_device_range_date_uncertainty")),
        );
        if ui.button(i18n::text("io.queue_calibration")).clicked()
            && let Err(error) = self.calibration.apply()
        {
            self.calibration.error = Some(error.into());
        }
        if ui.button(i18n::text("io.queue_uncalibrated_fs")).clicked() {
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

    fn spectrogram_panel(&mut self, ui: &mut egui::Ui) {
        egui::Frame::new()
            .fill(Color32::from_rgb(17, 27, 35))
            .stroke(Stroke::new(1.0, BORDER))
            .inner_margin(5.0)
            .show(ui, |ui| {
                compact_plot_style(ui);
                ui.horizontal_wrapped(|ui| {
                    ui.label(RichText::new(self.spectrogram_title()).size(13.0).strong());
                    display::activity_label(
                        ui,
                        self.running(),
                        self.pending_stop.is_some(),
                        self.last_stft.is_some(),
                    );
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        let channel = self
                            .last_stft
                            .map_or(self.spectrogram_channel, |r| r.config.channel);
                        ui.label(
                            RichText::new(
                                (if self.cepstrogram_applied() {
                                    i18n::format(
                                        "spectrogram.cepstral_channel",
                                        &[("channel", &(channel + 1).to_string())],
                                    )
                                } else {
                                    i18n::format(
                                        "spectrogram.ch_dbfs",
                                        &[("channel", &(channel + 1).to_string())],
                                    )
                                })
                                .as_ref(),
                            )
                            .small()
                            .color(BLUE),
                        );
                    });
                });
                if let Some(row) = self.spectrogram_snapshot.latest() {
                    let snapshot = &self.spectrogram_snapshot;
                    ui.label(
                        RichText::new(
                            i18n::format(
                                "spectrogram.end_s_s_retained_n_hop",
                                &[
                                    (
                                        "live",
                                        (if self.spectrogram_hold.is_some() {
                                            if self.running() {
                                                i18n::text("spectrogram.hold_input_running")
                                            } else {
                                                i18n::text("spectrogram.hold_input_stopped")
                                            }
                                        } else {
                                            i18n::text("spectrogram.live")
                                        }),
                                    ),
                                    (
                                        "sample_rate",
                                        &format!(
                                            "{:.3}",
                                            self.spectrogram_anchor as f64
                                                / row.info.config.sample_rate as f64
                                        ),
                                    ),
                                    (
                                        "retained_seconds",
                                        &format!("{:.2}", snapshot.retained_seconds()),
                                    ),
                                    ("size", &(row.info.config.size).to_string()),
                                    ("hop", &(row.info.config.hop).to_string()),
                                    (
                                        "else",
                                        (if snapshot.capacity_limited {
                                            i18n::text("spectrogram.history_limited_by_capacity")
                                        } else {
                                            ""
                                        }),
                                    ),
                                ],
                            )
                            .as_ref(),
                        )
                        .small()
                        .color(MUTED),
                    );
                    if snapshot.retained_seconds() < self.spectrogram_seconds {
                        ui.label(
                            RichText::new(
                                i18n::format(
                                    "spectrogram.history_available_s_unavailable_time_stays_blank",
                                    &[
                                        (
                                            "retained_seconds",
                                            &format!("{:.2}", snapshot.retained_seconds()),
                                        ),
                                        (
                                            "spectrogram_seconds",
                                            &format!("{:.0}", self.spectrogram_seconds),
                                        ),
                                    ],
                                )
                                .as_ref(),
                            )
                            .small()
                            .color(MUTED),
                        );
                    }
                }
                self.spectrogram_primary(ui);
                let (outer, response) =
                    ui.allocate_exact_size(plot_size(ui), egui::Sense::click_and_drag());
                let rect = egui::Rect::from_min_max(
                    // Keep the color-bar unit and top tick below wrapped controls.
                    outer.min + vec2(42.0, 16.0),
                    outer.max - vec2(70.0, 18.0),
                );
                self.spectrogram_interaction(ui, &response, rect);
                let ready = self.request_spectrogram_view(rect, ui.ctx().pixels_per_point());
                if !ready {
                    ui.ctx().request_repaint_after(Duration::from_millis(20));
                }
                let view = self.spectrogram_display_view(ui);
                let time_axis = {
                    let latest = self.spectrogram_history.lock().unwrap().latest();
                    spectrogram::TimeAxis::new(
                        if self.spectrogram_snapshot.latest().is_some() {
                            self.spectrogram_anchor
                        } else {
                            latest.map_or(0, |row| row.end)
                        },
                        latest.map_or(self.sample_rate, |row| row.config.sample_rate),
                        self.spectrogram_seconds,
                    )
                };
                let painter = ui.painter();
                painter.rect_filled(rect, 0.0, Color32::from_rgb(7, 14, 19));
                if ready {
                    painter.add(egui_wgpu::Callback::new_paint_callback(
                        rect,
                        spectrogram_gpu::Callback {
                            quefrency: self.cepstrogram_applied().then(|| self.quefrency_range()),
                            history: self.spectrogram_history.clone(),
                            anchor: self.spectrogram_anchor,
                            view,
                            seconds: self.spectrogram_seconds,
                            color_map: self.spectrogram_active_colors().2,
                            width: rect.width() * ui.ctx().pixels_per_point(),
                        },
                    ));
                }
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
                                -time_axis.age_at(i as f64 / age_divisions as f64)
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
                        if self.cepstrogram_applied() {
                            format!("{:.2}", self.quefrency_range().at(x as f64) * 1000.0)
                        } else {
                            frequency_label(view.frequency(x))
                        },
                        egui::FontId::monospace(10.0),
                        MUTED,
                    );
                }
                self.spectrogram_color_bar(ui, rect, view);
                self.spectrogram_cursors(ui, &response, rect, view);
                let history = self.spectrogram_history.lock().unwrap();
                if !ready || history.is_empty() {
                    painter.text(
                        rect.center(),
                        egui::Align2::CENTER_CENTER,
                        if !ready {
                            i18n::text("spectrogram.preparing_history_view")
                        } else if self.running() {
                            i18n::text("spectrogram.collecting_a_complete_stft_window")
                        } else {
                            i18n::text("spectrogram.start_input_to_begin_acquisition")
                        },
                        egui::FontId::proportional(14.0),
                        MUTED,
                    );
                }
                if let Some(position) = response.hover_pos().filter(|p| rect.contains(*p)) {
                    let age =
                        time_axis.age_at((position.y - rect.top()) as f64 / rect.height() as f64);
                    let fraction = (position.x - rect.left()) / rect.width();
                    let hz = view.frequency(fraction);
                    let sample =
                        cursor::sample_at_age(time_axis.anchor_end, age, time_axis.sample_rate);
                    let text = if let Some(frame) =
                        sample.and_then(|sample| self.spectrogram_snapshot.at_sample(sample))
                    {
                        let row = frame.info;
                        if self.cepstrogram_applied() {
                            self.cepstral_readout(frame, self.quefrency_range().at(fraction as f64))
                        } else {
                            let bin = cursor::nearest_bin(
                                hz as f64,
                                row.config.size,
                                row.config.sample_rate,
                            )
                            .unwrap_or(0);
                            if !frame.power()[bin].is_finite() {
                                i18n::format(
                                    "spectrogram.invalid_stft_window_non_finite_input_samples",
                                    &[
                                        ("start", &(row.start).to_string()),
                                        ("end", &(row.end).to_string()),
                                    ],
                                )
                                .to_string()
                            } else {
                                i18n::format(
                                    "spectrogram.hz_dbfs_samples",
                                    &[
                                        (
                                            "size",
                                            &format!(
                                                "{:.1}",
                                                bin as f64 * row.config.sample_rate as f64
                                                    / row.config.size as f64
                                            ),
                                        ),
                                        ("bin", &format!("{:.6}", frame.level_db(bin).unwrap())),
                                        ("start", &(row.start).to_string()),
                                        ("end", &(row.end).to_string()),
                                    ],
                                )
                                .to_string()
                            }
                        }
                    } else {
                        i18n::text("spectrogram.no_stft_data_at_this_time_gap_or_unavailable")
                            .into()
                    };
                    response
                        .clone()
                        .on_hover_text(format!("{text}\n{}", spectrogram_controls::gestures()));
                }
                drop(history);
                ui.horizontal(|ui| {
                    ui.label(
                        RichText::new(i18n::text("spectrogram.age_s"))
                            .small()
                            .color(MUTED),
                    );
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.label(
                            RichText::new(if self.cepstrogram_applied() {
                                i18n::text("spectrogram.quefrency_ms")
                            } else {
                                i18n::text("spectrogram.frequency_hz")
                            })
                            .small()
                            .color(MUTED),
                        );
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
                        text.push_str(
                            i18n::format(
                                "common.cursor_channel_invalid",
                                &[("channel", &(channel::name(channel)).to_string())],
                            )
                            .as_ref(),
                        );
                    }
                } else {
                    text.push_str(
                        i18n::format(
                            "common.unavailable_2",
                            &[("channel", &(channel::name(channel)).to_string())],
                        )
                        .as_ref(),
                    );
                }
            }
            text
        } else {
            i18n::format(
                "common.raw_sample_unavailable",
                &[("sample", &(sample).to_string())],
            )
            .to_string()
        }
    }

    fn scope_cursors(&mut self, ui: &egui::Ui, response: &egui::Response, rect: egui::Rect) {
        if let Some(position) = cursor_pointer(response, rect)
            && (0.0..=1.0).contains(
                &((position.x - rect.left()) / rect.width()
                    - self.scope_horizontal_position / 10.0),
            )
        {
            self.cursors.set_scope_time(
                self.active_cursor,
                ((position.x - rect.left()) / rect.width() - self.scope_horizontal_position / 10.0)
                    as f64,
            );
            ui.ctx().request_repaint();
        }
        let raw = self
            .cursor_samples()
            .into_iter()
            .enumerate()
            .filter_map(|(index, sample)| {
                let sample = sample?;
                let frame = self.scope_history().get(sample)?;
                let values: Vec<_> = self
                    .scope_view_channels()
                    .0
                    .into_iter()
                    .enumerate()
                    .filter_map(|(trace, channel)| {
                        if !self.enabled[trace] {
                            return None;
                        }
                        let raw = frame.get(channel)?;
                        let value = self.calibration.captured.value(channel, *raw)?;
                        Some(
                            i18n::format(
                                "oscilloscope.fs",
                                &[
                                    ("channel", &(channel::name(channel)).to_string()),
                                    ("raw", &(display::number(Some(*raw))).to_string()),
                                    ("value", &(display::number(Some(value))).to_string()),
                                    ("channel_2", (self.calibration.captured.unit(channel))),
                                ],
                            )
                            .to_string(),
                        )
                    })
                    .collect();
                Some(
                    i18n::format(
                        "oscilloscope.cursor",
                        &[
                            ("index", (cursor_name(index))),
                            ("join", &(values.join(" · ")).to_string()),
                        ],
                    )
                    .to_string(),
                )
            })
            .collect::<Vec<_>>()
            .join("\n");
        if !raw.is_empty() {
            response.clone().on_hover_text(raw);
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
                let x = x + self.scope_horizontal_position as f64 / 10.0;
                if (0.0..=1.0).contains(&x) {
                    cursor_line(ui, rect, x as f32, true, cursor_color(index));
                }
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
                            rect.top()
                                + self.scope_display_vertical(trace).y(*value) * rect.height(),
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
                    i18n::format(
                        "oscilloscope.ms",
                        &[
                            ("index", (cursor_name(index))),
                            ("seconds", &format!("{:+.3}", seconds * 1000.0)),
                            ("sample", &(self.sample_text(sample)).to_string()),
                        ],
                    )
                    .to_string()
                } else {
                    i18n::format(
                        "oscilloscope.waiting_for_sweep",
                        &[("index", (cursor_name(index)))],
                    )
                    .to_string()
                }
            } else if let Some(sample) = sample {
                i18n::format(
                    "oscilloscope.outside_sweep",
                    &[
                        ("index", (cursor_name(index))),
                        ("sample", &(sample).to_string()),
                    ],
                )
                .to_string()
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
        let active = if self.spectrum_history.linked {
            self.spectrum_history.frequency_cursor
        } else {
            self.active_cursor
        };
        if let Some(position) = cursor_pointer(response, rect) {
            self.cursors.set_frequency(
                active,
                view.frequency((position.x - rect.left()) / rect.width()) as f64,
            );
            ui.ctx().request_repaint();
        }
        let readings = self
            .cursors
            .spectrum_frequencies_hz
            .map(|frequency| frequency.and_then(|hz| self.shown_selected_spectrum().cursor(hz)));
        for (index, reading) in readings.iter().enumerate() {
            let Some(frequency) = self.cursors.spectrum_frequencies_hz[index] else {
                continue;
            };
            let color = cursor_color(index);
            let hz = reading.as_ref().map_or(frequency, |r| r.frequency_hz) as f32;
            if hz >= view.min_hz && hz <= view.max_hz {
                cursor_line(ui, rect, view.x(hz), true, color);
                ui.painter().text(
                    pos2(
                        rect.left() + view.x(hz) * rect.width() + 4.0,
                        rect.top() + 3.0,
                    ),
                    egui::Align2::LEFT_TOP,
                    cursor_name(index),
                    egui::FontId::monospace(11.0),
                    color,
                );
            }
            let Some(reading) = reading else {
                cursor_note(
                    ui,
                    rect,
                    index,
                    i18n::format(
                        "spectrum.hz_no_complete_window",
                        &[
                            ("index", (cursor_name(index))),
                            ("frequency", &format!("{:.3}", frequency)),
                        ],
                    )
                    .as_ref(),
                    color,
                );
                continue;
            };
            let window = &reading.window;
            let text = i18n::format(
                "spectrum.hz_ch_samples",
                &[
                    ("index", (cursor_name(index))),
                    ("frequency_hz", &format!("{:.6}", reading.frequency_hz)),
                    ("level_db", &format!("{:.2}", reading.level_db)),
                    ("db_unit", &(window.db_unit()).to_string()),
                    ("channel", &(window.channel + 1).to_string()),
                    ("start", &(window.start).to_string()),
                    ("end", &(window.end).to_string()),
                ],
            )
            .to_string();
            cursor_note(ui, rect, index, &text, color);
            if index == active {
                if self.spectrum_history.linked {
                    response.clone().on_hover_text(
                        i18n::format(
                            "spectrum.time_nearest_bin_acquired_samples_hz_points_no_average",
                            &[
                                ("selected", (cursor_name(self.spectrum_history.selected))),
                                ("value", &format!("{:.6e}", reading.value)),
                                ("linear_unit", &(window.linear_unit()).to_string()),
                                ("start", &(window.start).to_string()),
                                ("end", &(window.end).to_string()),
                                ("sample_rate", &(window.sample_rate).to_string()),
                                ("size", &(window.settings.size).to_string()),
                                ("name", (window.settings.window.display_name())),
                                ("name_2", (window.settings.precision.display_name())),
                            ],
                        )
                        .as_ref(),
                    );
                    continue;
                }
                let mut times = String::new();
                for (index, sample) in self.cursor_samples().into_iter().enumerate() {
                    if let Some(sample) = sample {
                        let status = if (window.start..window.end).contains(&sample) {
                            i18n::format(
                                "spectrum.time_cursor_inside_fft_window",
                                &[("index", cursor_name(index))],
                            )
                        } else {
                            i18n::format(
                                "spectrum.time_cursor_outside_fft_window",
                                &[("index", cursor_name(index))],
                            )
                        };
                        times.push_str(&status);
                    }
                }
                response.clone().on_hover_text(
                    i18n::format(
                        "spectrum.cursor_nearest_bin_latest_window_samples_exclusive_end_ch",
                        &[
                            ("index", (cursor_name(index))),
                            ("value", &format!("{:.6e}", reading.value)),
                            ("linear_unit", &(window.linear_unit()).to_string()),
                            ("start", &(window.start).to_string()),
                            ("end", &(window.end).to_string()),
                            ("channel", &(window.channel + 1).to_string()),
                            ("sample_rate", &(window.sample_rate).to_string()),
                            ("size", &(window.settings.size).to_string()),
                            ("name", (window.settings.window.display_name())),
                            ("name_2", (window.settings.precision.display_name())),
                            ("averages", &(window.settings.averages).to_string()),
                            ("updates", &(reading.average.updates).to_string()),
                            ("start_2", &(reading.average.start).to_string()),
                            ("end_2", &(reading.average.end).to_string()),
                            ("input_generation", &(self.input_generation).to_string()),
                            (
                                "missing_windows",
                                &(self.selected_spectrum_info().missing_windows).to_string(),
                            ),
                            ("times", &(times).to_string()),
                        ],
                    )
                    .as_ref(),
                );
                response
                    .clone()
                    .on_hover_text(spectrum_calibration_description(
                        self.shown_selected_spectrum().calibration(),
                    ));
            }
        }
        if let [Some(a), Some(b)] = readings {
            let delta_db = b.level_db - a.level_db;
            let delta_level = if delta_db.is_nan() {
                "—".into()
            } else {
                format!("{delta_db:+.2}")
            };
            cursor_note(
                ui,
                rect,
                2,
                i18n::format(
                    "spectrum.f_hz_l_db",
                    &[
                        (
                            "frequency_hz",
                            &format!("{:+.6}", b.frequency_hz - a.frequency_hz),
                        ),
                        ("delta_level", &(delta_level).to_string()),
                    ],
                )
                .as_ref(),
                YELLOW,
            );
        }
    }

    fn spectrogram_cursors(
        &mut self,
        ui: &egui::Ui,
        response: &egui::Response,
        rect: egui::Rect,
        view: View,
    ) {
        if response.double_clicked() || response.drag_started() {
            self.spectrogram_pending_click = None;
        }
        if let Some(position) = response.interact_pointer_pos().filter(|p| {
            response.clicked()
                && !response.double_clicked()
                && rect.contains(*p)
                && self.spectrogram_prepared_id == self.spectrogram_view_worker.current_id()
        }) {
            self.spectrogram_pending_click = Some(spectrogram_controls::PendingClick {
                snapshot: self.spectrogram_snapshot.clone(),
                anchor: self.spectrogram_anchor,
                sample: self.spectrogram_snapshot.config.and_then(|config| {
                    cursor::sample_at_age(
                        self.spectrogram_anchor,
                        (position.y - rect.top()) as f64 / rect.height() as f64
                            * self.spectrogram_seconds,
                        config.sample_rate,
                    )
                }),
                frequency: view.frequency((position.x - rect.left()) / rect.width()) as f64,
                quefrency: self.cepstrogram_applied().then(|| {
                    self.quefrency_range()
                        .at(((position.x - rect.left()) / rect.width()) as f64)
                }),
                index: self.active_cursor,
                time: ui.input(|i| i.time),
            });
        }
        if self
            .spectrogram_pending_click
            .as_ref()
            .is_some_and(|click| {
                ui.input(|i| i.time) - click.time
                    > ui.ctx().options(|o| o.input_options.max_double_click_delay)
            })
        {
            let click = self.spectrogram_pending_click.take().unwrap();
            if click.snapshot.latest().is_some() {
                self.spectrogram_hold = Some(click.snapshot);
                self.spectrogram_hold_anchor = Some(click.anchor);
                if let Some(sample) = click.sample {
                    self.select_spectrogram_sample(click.index, sample);
                } else {
                    self.spectrogram_unavailable_selection[click.index] = true;
                    self.cursors.times[click.index] = None;
                    self.spectrogram_selected[click.index] = None;
                }
                if let Some(seconds) = click.quefrency {
                    self.cursors.quefrency_seconds[click.index] = Some(seconds);
                } else {
                    self.cursors.set_frequency(click.index, click.frequency);
                }
            }
            ui.ctx().request_repaint();
        } else if self.spectrogram_pending_click.is_some() {
            ui.ctx().request_repaint_after(Duration::from_millis(20));
        }
        let mut samples = self.cursor_samples();
        if self.cursors.times.iter().all(Option::is_none)
            && (if self.cepstrogram_applied() {
                self.cursors.quefrency_seconds.iter().any(Option::is_some)
            } else {
                self.cursors.frequency_hz.is_some()
            })
            && self.spectrogram_unavailable_selection == [false; 2]
        {
            samples[self.active_cursor] = self.spectrogram_anchor.checked_sub(1);
        }
        let latest = self
            .spectrogram_snapshot
            .latest()
            .map(|f| f.info)
            .or(self.last_stft);
        if !self.cepstrogram_applied()
            && let (Some(hz), Some(latest)) = (self.cursors.frequency_hz, latest)
            && let Some(bin) =
                cursor::nearest_bin(hz, latest.config.size, latest.config.sample_rate)
        {
            let hz = bin as f32 * latest.config.sample_rate as f32 / latest.config.size as f32;
            if hz >= view.min_hz && hz <= view.max_hz {
                cursor_line(ui, rect, view.x(hz), true, YELLOW);
            }
        }
        for (index, sample) in samples.into_iter().enumerate() {
            if self.spectrogram_unavailable_selection[index] {
                cursor_note(
                    ui,
                    rect,
                    index,
                    i18n::format(
                        "spectrogram.no_stft_row_before_input_began",
                        &[("index", (cursor_name(index)))],
                    )
                    .as_ref(),
                    cursor_color(index),
                );
                continue;
            }
            let (Some(sample), Some(latest)) = (sample, latest) else {
                continue;
            };
            let anchor = if self.spectrogram_snapshot.latest().is_some() {
                self.spectrogram_anchor
            } else {
                latest.end
            };
            let age = cursor::signed_distance(anchor.saturating_sub(1), sample)
                / latest.config.sample_rate as f64;
            if (0.0..=self.spectrogram_seconds).contains(&age) {
                cursor_line(
                    ui,
                    rect,
                    (age / self.spectrogram_seconds) as f32,
                    false,
                    cursor_color(index),
                );
            }
            let frame = self.spectrogram_selected[index]
                .as_ref()
                .filter(|frame| {
                    self.cursors.times[index].and_then(|t| t.spectrogram_sample())
                        == Some(frame.info.end - 1)
                })
                .or_else(|| self.spectrogram_snapshot.at_sample(sample));
            let mut text =
                if let Some(frame) = frame {
                    let row = frame.info;
                    if self.cepstrogram_applied() {
                        if let Some(seconds) = self.cursors.quefrency_seconds[index] {
                            let range = self.quefrency_range();
                            let q = crate::cepstrum::nearest_quefrency(
                                seconds,
                                row.config.size,
                                row.config.sample_rate,
                            )
                            .unwrap();
                            let fraction = range.fraction(q as f64 / row.config.sample_rate as f64);
                            if (0.0..=1.0).contains(&fraction) {
                                cursor_line(ui, rect, fraction as f32, true, cursor_color(index));
                            }
                            format!(
                                "{} {}",
                                cursor_name(index),
                                self.cepstral_readout(frame, seconds)
                            )
                        } else {
                            self.cepstral_status(frame)
                        }
                    } else if !frame.valid() {
                        i18n::format(
                            "spectrogram.invalid_stft_window_non_finite_input",
                            &[
                                ("index", (cursor_name(index))),
                                ("start", &(row.start).to_string()),
                                ("end", &(row.end).to_string()),
                            ],
                        )
                        .to_string()
                    } else if let Some(bin) = self.cursors.frequency_hz.and_then(|hz| {
                        cursor::nearest_bin(hz, row.config.size, row.config.sample_rate)
                    }) {
                        i18n::format(
                            "spectrogram.hz_dbfs_ch",
                            &[
                                ("index", (cursor_name(index))),
                                (
                                    "size",
                                    &format!(
                                        "{:.1}",
                                        bin as f64 * row.config.sample_rate as f64
                                            / row.config.size as f64
                                    ),
                                ),
                                ("bin", &format!("{:.6}", frame.level_db(bin).unwrap())),
                                ("channel", &(row.config.channel + 1).to_string()),
                                ("start", &(row.start).to_string()),
                                ("end", &(row.end).to_string()),
                            ],
                        )
                        .to_string()
                    } else {
                        i18n::format(
                            "spectrogram.s_ch",
                            &[
                                ("index", (cursor_name(index))),
                                ("age", &format!("{:.3}", age)),
                                ("channel", &(row.config.channel + 1).to_string()),
                                ("start", &(row.start).to_string()),
                                ("end", &(row.end).to_string()),
                            ],
                        )
                        .to_string()
                    }
                } else {
                    i18n::format(
                        "spectrogram.s_no_stft_row_gap_or_unavailable",
                        &[
                            ("index", (cursor_name(index))),
                            ("age", &format!("{:.3}", age)),
                        ],
                    )
                    .to_string()
                };
            if !(0.0..=self.spectrogram_seconds).contains(&age) {
                text.push_str(i18n::text("spectrogram.outside_visible_time_range"));
            }
            cursor_note(ui, rect, index, &text, cursor_color(index));
        }
        if self.cepstrogram_applied()
            && let [Some(a), Some(b)] = self.cursors.quefrency_seconds
        {
            let config = self.spectrogram_applied_config();
            let qa =
                crate::cepstrum::nearest_quefrency(a, config.size, config.sample_rate).unwrap();
            let qb =
                crate::cepstrum::nearest_quefrency(b, config.size, config.sample_rate).unwrap();
            ui.painter().text(
                rect.right_top(),
                egui::Align2::RIGHT_TOP,
                format!(
                    "Δτ {:.6} ms",
                    (qb as f64 - qa as f64) / config.sample_rate as f64 * 1000.0
                ),
                egui::FontId::monospace(10.0),
                MUTED,
            );
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
                        i18n::format(
                            "xy.outside_xy_window_or_unavailable",
                            &[("index", (cursor_name(index)))],
                        )
                        .as_ref(),
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
                        i18n::text("xy.free").into()
                    } else {
                        i18n::text("xy.free_outside_plot").into()
                    }
                }
                xy::CursorMode::TraceSnap => {
                    let sample = samples[index].unwrap();
                    let reference = cursor::trigger_sample(self.xy_capture.range.clone()).unwrap();
                    i18n::format(
                        "xy.t_ms",
                        &[
                            (
                                "sample_rate",
                                &format!(
                                    "{:+.3}",
                                    cursor::signed_distance(sample, reference) * 1000.0
                                        / self.sample_rate as f64
                                ),
                            ),
                            ("sample", &(sample).to_string()),
                        ],
                    )
                    .to_string()
                }
            };
            cursor_note(
                ui,
                bounds,
                index,
                i18n::format(
                    "xy.x_fs_y_fs_2",
                    &[
                        ("index", (cursor_name(index))),
                        (
                            "channels",
                            &(channel::name(self.xy_capture.channels.0[0])).to_string(),
                        ),
                        ("point", &format!("{:+.4}", point[0])),
                        (
                            "channels_2",
                            &(channel::name(self.xy_capture.channels.0[1])).to_string(),
                        ),
                        ("point_2", &format!("{:+.4}", point[1])),
                        ("detail", &(detail).to_string()),
                    ],
                )
                .as_ref(),
                cursor_color(index),
            );
        }
        if let [Some(a), Some(b)] = points {
            let delta = [b[0] - a[0], b[1] - a[1]];
            cursor_note(
                ui,
                bounds,
                2,
                i18n::format(
                    "xy.b_a_x_y_fs",
                    &[
                        ("delta", &format!("{:+.4}", delta[0])),
                        ("delta_2", &format!("{:+.4}", delta[1])),
                    ],
                )
                .as_ref(),
                MUTED,
            );
        }
        response.clone().on_hover_text(match self.xy_cursor_mode {
            xy::CursorMode::Free => i18n::text("xy.free_click_or_drag_to_fix_x_y_amplitudes"),
            xy::CursorMode::TraceSnap => {
                i18n::text("xy.trace_snap_selects_the_nearest_actual_pair_from_the")
            }
        });
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
                ui.horizontal_wrapped(|ui| {
                    ui.label(
                        RichText::new(i18n::text("xy.xy_lissajous"))
                            .size(13.0)
                            .strong(),
                    );
                    display::activity_label(
                        ui,
                        self.running(),
                        self.pending_stop.is_some(),
                        !self.xy_capture.range.is_empty(),
                    );
                });
                ui.horizontal_wrapped(|ui| {
                    ui.label(
                        RichText::new(match self.xy_cursor_mode {
                            xy::CursorMode::Free => i18n::text("xy.xy_free_cursor"),
                            xy::CursorMode::TraceSnap => i18n::text("xy.xy_trace_snap_cursor"),
                        })
                        .small()
                        .color(MUTED),
                    );
                    self.cursor_controls(ui, Instrument::Xy);
                });
                ui.label(
                    RichText::new(
                        i18n::format(
                            "xy.x_fs_div_y_fs_div",
                            &[
                                (
                                    "channels",
                                    &(channel::name(self.xy_view_settings().channels.0[0]))
                                        .to_string(),
                                ),
                                (
                                    "x_fs_per_div",
                                    &format!("{:.3}", self.xy_settings.x_fs_per_div),
                                ),
                                (
                                    "channels_2",
                                    &(channel::name(self.xy_view_settings().channels.0[1]))
                                        .to_string(),
                                ),
                                (
                                    "y_fs_per_div",
                                    &format!("{:.3}", self.xy_settings.y_fs_per_div),
                                ),
                            ],
                        )
                        .as_ref(),
                    )
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
                plot_labels::horizontal(
                    painter,
                    egui::Rect::from_min_max(
                        pos2(outer.left(), rect.bottom() + 4.0),
                        outer.right_bottom(),
                    ),
                    (0..=2).map(|i| {
                        (
                            rect.left() + side * i as f32 / 2.0,
                            format!(
                                "{:.3}",
                                (i as f64 - 1.0) * 4.0 * self.xy_settings.x_fs_per_div
                            ),
                        )
                    }),
                );
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
                            i18n::text("xy.xy_unavailable_mono_input")
                        } else if self.channels == 0 {
                            i18n::text("xy.xy_requires_two_input_channels")
                        } else if !self
                            .xy_view_settings()
                            .channels
                            .available(self.channels as usize)
                        {
                            i18n::text("xy.xy_unavailable_assigned_channel_missing")
                        } else {
                            i18n::text("xy.waiting_for_sample_pairs")
                        },
                        egui::FontId::proportional(13.0),
                        MUTED,
                    );
                }
                if let Some(position) = response.hover_pos().filter(|point| rect.contains(*point)) {
                    response.clone().on_hover_text(
                        i18n::format(
                            "xy.x_fs_y_fs",
                            &[
                                (
                                    "x_fs_per_div",
                                    &format!(
                                        "{:+.4}",
                                        (position.x - rect.center().x) as f64 / side as f64
                                            * self.xy_settings.x_fs_per_div
                                            * 8.0
                                    ),
                                ),
                                (
                                    "y_fs_per_div",
                                    &format!(
                                        "{:+.4}",
                                        (rect.center().y - position.y) as f64 / side as f64
                                            * self.xy_settings.y_fs_per_div
                                            * 8.0
                                    ),
                                ),
                            ],
                        )
                        .as_ref(),
                    );
                }
                self.xy_cursors(ui, &response, rect, bounds);
                let capture = &self.xy_capture;
                // Use the same footer row height reserved by plot_size for the other plots.
                ui.horizontal(|ui| {
                    ui.label(
                        RichText::new(
                            i18n::format(
                                "xy.ms_samples",
                                &[
                                    (
                                        "sample_rate",
                                        &format!(
                                            "{:.1}",
                                            (capture.range.end - capture.range.start) as f64
                                                * 1000.0
                                                / self.sample_rate as f64
                                        ),
                                    ),
                                    ("start", &(capture.range.start).to_string()),
                                    ("end", &(capture.range.end).to_string()),
                                    (
                                        "else",
                                        (if capture.limited {
                                            i18n::text("xy.point_limit")
                                        } else {
                                            ""
                                        }),
                                    ),
                                    (
                                        "auto_no_crossing",
                                        (if self.xy_cursor_mode == xy::CursorMode::Free {
                                            ""
                                        } else if capture.triggered {
                                            i18n::text("xy.triggered")
                                        } else if self.trigger.edge == Edge::Free {
                                            i18n::text("xy.free_run_moving_reference")
                                        } else {
                                            i18n::text("xy.auto_no_crossing")
                                        }),
                                    ),
                                ],
                            )
                            .as_ref(),
                        )
                        .small()
                        .color(MUTED),
                    );
                });
            });
    }

    fn workspace_controls(&mut self, ui: &mut egui::Ui) {
        setting_label(ui, i18n::text("common.held_measurement_results"));
        if self.spectrum_history.linked {
            ui.label(
                RichText::new(spectrum_history::export_reason())
                    .small()
                    .color(YELLOW),
            );
        }
        ui.label(
            RichText::new(i18n::text(
                "common.stop_input_then_export_scope_samples_and_statistics_spectrum",
            ))
            .small()
            .color(MUTED),
        );
        ui.add_enabled(
            !self.export_pending,
            egui::TextEdit::singleline(&mut self.export_path)
                .hint_text(i18n::text("common.results_json_file_path"))
                .desired_width(f32::INFINITY),
        );
        if ui
            .add_enabled(
                !self.export_pending && self.can_export(),
                egui::Button::new(i18n::text("common.export_held_results")),
            )
            .on_hover_text(i18n::text(
                "common.exports_the_retained_scope_interval_and_the_independently_timed",
            ))
            .clicked()
        {
            self.request_export();
        }
        if self.spectrum_history.linked
            && ui
                .add_enabled(
                    !self.export_pending && self.can_export_scope(),
                    egui::Button::new(i18n::text("common.export_held_scope_only")),
                )
                .clicked()
        {
            self.request_export();
        }
        if let Some(status) = &self.export_status {
            ui.label(
                RichText::new(status.render().as_ref())
                    .small()
                    .color(if self.export_error { YELLOW } else { MUTED }),
            );
        }
        ui.separator();
        self.preferences_controls(ui);
        ui.separator();
        setting_label(ui, i18n::text("common.measurement_settings"));
        ui.label(
            RichText::new(i18n::text(
                "common.save_the_queued_input_channels_analysis_and_calibration_for",
            ))
            .small()
            .color(MUTED),
        );
        ui.add_enabled(
            self.settings_task.is_none(),
            egui::TextEdit::singleline(&mut self.settings_path)
                .hint_text(i18n::text("common.settings_json_file_path"))
                .desired_width(f32::INFINITY),
        );
        ui.horizontal(|ui| {
            if ui
                .add_enabled(
                    self.settings_task.is_none() && !self.busy && self.source == Source::Live,
                    egui::Button::new(i18n::text("common.save_settings")),
                )
                .clicked()
            {
                self.request_settings(SettingsTask::Save);
            }
            if ui
                .add_enabled(
                    self.settings_task.is_none() && self.can_restore_settings(),
                    egui::Button::new(i18n::text("common.restore_settings")),
                )
                .clicked()
            {
                self.request_settings(SettingsTask::Restore);
            }
        });
        if let Some(status) = &self.settings_status {
            ui.label(
                RichText::new(status.render().as_ref())
                    .small()
                    .color(if self.settings_error { YELLOW } else { MUTED }),
            );
        }
        ui.separator();
    }

    fn can_restore_settings(&self) -> bool {
        !self.preferences.loading
            && (self.source == Source::Live
                || self.source == Source::Software
                || self.source == Source::Generator)
            && self.generator.stopped()
            && !self.running()
            && !self.busy
            && self.pending_stop.is_none()
            && self.pending_scope.is_none()
    }

    fn can_export(&self) -> bool {
        !self.spectrum_history.linked && self.held_results_ready()
    }

    fn can_export_scope(&self) -> bool {
        self.held_results_ready() && !self.scope_range.is_empty()
    }

    fn held_results_ready(&self) -> bool {
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
            if self.spectrum_history.linked {
                return Err(spectrum_history::export_reason().into());
            }
            return Err(
                i18n::text("common.stop_input_and_wait_for_the_held_measurement_results").into(),
            );
        }
        self.capture_held_results(true)
    }

    fn capture_scope_results(&self) -> Result<export::Document, String> {
        if !self.can_export_scope() {
            return Err(i18n::text("common.stop_input_and_wait_for_held_scope_samples").into());
        }
        self.capture_held_results(false)
    }

    fn capture_held_results(&self, include_spectrum: bool) -> Result<export::Document, String> {
        let input = self
            .held_input
            .clone()
            .ok_or(i18n::text("common.no_held_input_conditions"))?;
        if input.generation != self.input_generation {
            return Err(i18n::text("common.held_input_generation_does_not_match_results").into());
        }
        let excluded = (!include_spectrum).then(|| {
            spectrum::Result::empty(
                Settings {
                    size: 1024,
                    averages: 1,
                    ..Settings::default()
                },
                self.sample_rate,
            )
        });
        let excluded_info = measurement::SpectrumInfo::default();
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
            excluded
                .as_ref()
                .unwrap_or_else(|| self.selected_spectrum()),
            if include_spectrum {
                self.selected_spectrum_info()
            } else {
                &excluded_info
            },
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
        document.generator_output = self.generator_output.clone();
        document.external_output = self.external_output.clone();
        if !include_spectrum {
            // Preserve the existing result schema, explicitly excluding every
            // Spectrum value/window. No ordinary or historical FFT is exported.
            document.spectrum.state = export::State::Unavailable;
            return Ok(document);
        }
        if self.lockin_result.settings.enabled {
            document.lockin = Some(export::Lockin::capture(
                self.lockin_result.clone(),
                &self.calibration.captured,
            ));
        }
        if self.comparison_result.settings.enabled {
            document.comparison = Some(export::Comparison::capture(
                (*self.comparison_result).clone(),
                &self.calibration.captured,
            ));
        }
        Ok(document)
    }

    fn request_export(&mut self) {
        let result = (|| {
            if self.export_pending {
                return Err(i18n::text("common.an_export_is_already_in_progress").into());
            }
            if self.export_path.trim().is_empty() {
                return Err(i18n::text("common.enter_a_results_file_path").into());
            }
            let document = if self.spectrum_history.linked {
                self.capture_scope_results()?
            } else {
                self.capture_results()?
            };
            self.export_worker
                .submit(std::path::PathBuf::from(&self.export_path), document)
        })();
        self.export_error = result.is_err();
        self.export_status = Some(match result {
            Ok(()) => {
                self.export_pending = true;
                UiStatus::Exporting
            }
            Err(error) => error.into(),
        });
    }

    fn poll_export(&mut self) {
        while let Ok(event) = self.export_worker.events.try_recv() {
            self.export_pending = false;
            let result = match event {
                export::Event::Saved(path) => Ok(UiStatus::ResultsExported(path)),
                export::Event::Error(error) => Err(UiStatus::Detail(error)),
            };
            self.export_error = result.is_err();
            self.export_status = Some(result.unwrap_or_else(|error| error));
        }
    }

    fn capture_settings(&self) -> Result<settings::Document, String> {
        self.capture_settings_with_policy(false)
    }

    fn capture_settings_with_policy(&self, startup: bool) -> Result<settings::Document, String> {
        let input = if self.source == Source::Live && startup && self.restored_input.is_some() {
            let mut input = self.restored_input.clone().unwrap();
            input.sample_rate = self.requested_sample_rate;
            input
        } else if self.source == Source::Generator {
            settings::Input {
                device_id: "measurelab:generator".into(),
                device_name: "Generator internal loopback".into(),
                channels: 2,
                device_default_sample_rate: self.generator.rate,
                sample_rate: Some(self.generator.rate),
            }
        } else if self.source == Source::Software {
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
                .ok_or(i18n::text("common.select_an_input_device_first"))?;
            settings::Input::from_device(device, self.requested_sample_rate)?
        };
        let document = settings::Document {
            version: settings::VERSION,
            measurement: settings::Measurement {
                generator: Some(output::Saved {
                    target: self.generator.target.clone(),
                    nominal_sample_rate: self.generator.rate,
                    signals: self.generator.settings,
                    use_as_input: self.source == Source::Generator,
                }),
                software_loopback: (self.source == Source::Software)
                    .then(|| self.loopback_settings.clone()),
                comparison: self.comparison_settings,
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
                    mode: self.spectrogram_mode,
                    log_floor_db: self.cepstrum_log_floor_db,
                    channel: self.spectrogram_channel,
                    analysis: self.spectrogram_settings,
                    overlap: self.spectrogram_overlap,
                },
                xy: settings::Xy {
                    channels: self.xy_settings.channels,
                    milliseconds: self.xy_settings.milliseconds,
                },
                calibrations: settings::ChannelCalibration::capture(&self.calibration.pending),
            },
            workspace: self.capture_workspace(),
        };
        document.validate()?;
        if self.source == Source::Live && !startup {
            document.measurement.input.resolve(&self.devices)?;
        }
        if self.capture.is_some()
            && (document.measurement.input.channels != self.channels
                || document.measurement.input.expected_sample_rate() != self.sample_rate)
        {
            return Err(
                i18n::text("common.active_input_differs_from_the_device_list_stop_and").into(),
            );
        }
        Ok(document)
    }

    fn capture_workspace(&self) -> settings::Workspace {
        settings::Workspace {
            cepstrogram: self.cepstrogram_display,
            spectrum_display: self.spectrum_display,
            presentation: self.presentation.clone(),
            lockin_display: self.lockin_display,
            scope_enabled: self.enabled,
            scope_vertical: self.scope_vertical,
            scope_common_vertical: self.scope_common_vertical,
            scope_selected: self.scope_selected,
            scope_horizontal_position: self.scope_horizontal_position,
            scope_trigger_display: self.scope_trigger_display,
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
            spectrogram_color_map: self.spectrogram_color_map,
            spectrogram_auto_color: self.spectrogram_auto_color,
            xy_x_fs_per_div: self.xy_settings.x_fs_per_div,
            xy_y_fs_per_div: self.xy_settings.y_fs_per_div,
            xy_cursor_mode: self.xy_cursor_mode,
        }
    }

    fn apply_workspace(&mut self, w: settings::Workspace) {
        self.presentation = w.presentation.clone();
        self.presentation.repair();
        self.shell.previous_console = None;
        self.lockin_display = w.lockin_display;
        self.enabled = w.scope_enabled;
        self.scope_vertical = w.scope_vertical;
        self.scope_common_vertical = w.scope_common_vertical;
        self.scope_selected = w.scope_selected;
        self.scope_horizontal_position = w.scope_horizontal_position;
        self.scope_trigger_display = w.scope_trigger_display;
        self.scope_trigger_level_edit_frame = None;
        self.frequency_scale = w.spectrum_scale;
        self.spectrum_display = w.spectrum_display;
        if [4, 16, 64].contains(&self.spectrum_settings.averages) {
            self.spectrum_display.average_weight = self.spectrum_settings.averages;
        }
        self.spectrum_min_hz = w.spectrum_min_hz;
        self.span_hz = w.spectrum_max_hz;
        self.floor_db = w.spectrum_floor_db;
        self.spectrum_ceiling_db = w.spectrum_ceiling_db;
        self.show_hold = w.spectrum_show_hold;
        self.cepstrogram_display = w.cepstrogram;
        self.spectrogram_scale = w.spectrogram_scale;
        self.spectrogram_min_hz = w.spectrogram_min_hz;
        self.spectrogram_max_hz = w.spectrogram_max_hz;
        self.spectrogram_floor = w.spectrogram_floor_db;
        self.spectrogram_ceiling = w.spectrogram_ceiling_db;
        self.spectrogram_seconds = w.spectrogram_seconds;
        self.spectrogram_color_map = w.spectrogram_color_map;
        self.spectrogram_auto_color = w.spectrogram_auto_color;
        self.spectrogram_color_error = false;
        self.xy_settings.x_fs_per_div = w.xy_x_fs_per_div;
        self.xy_settings.y_fs_per_div = w.xy_y_fs_per_div;
        self.xy_cursor_mode = w.xy_cursor_mode;
        self.dirty = true;
        self.xy_dirty = true;
        self.spectrum_dirty = true;
    }

    /// Transactional restoration: all checks precede mutation, and only queued
    /// conditions/display preferences change. Captured data keeps its metadata.
    fn restore_settings(&mut self, document: settings::Document) -> Result<(), String> {
        self.restore_settings_with_policy(document, false)
    }

    fn restore_settings_with_policy(
        &mut self,
        document: settings::Document,
        startup: bool,
    ) -> Result<(), String> {
        if !self.can_restore_settings() {
            return Err(
                i18n::text("common.stop_input_and_output_and_wait_for_pending_operations").into(),
            );
        }
        let calibrations = document.validate()?;
        let selected = if document.measurement.software_loopback.is_some()
            || document
                .measurement
                .generator
                .as_ref()
                .is_some_and(|g| g.use_as_input)
        {
            self.selected
        } else {
            match document.measurement.input.resolve(&self.devices) {
                Ok(index) => index,
                Err(error) if startup => {
                    self.input_error = Some(error);
                    usize::MAX
                }
                Err(error) => return Err(error),
            }
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
                            return Err(i18n::text(
                                "common.saved_calibration_conflicts_with_an_existing_id_revision",
                            )
                            .into());
                        }
                    }
                }
            }
        }
        let m = document.measurement;
        let w = document.workspace;
        let generator_input = m.generator.as_ref().is_some_and(|g| g.use_as_input);
        let generator = m.generator.unwrap_or(output::Saved {
            target: output::Target::Internal,
            nominal_sample_rate: 48_000,
            signals: crate::generator::Settings::default(),
            use_as_input: false,
        });
        if startup {
            self.generator.select(
                generator.target,
                generator.nominal_sample_rate,
                generator.signals,
            )?;
        } else {
            self.generator.restore(generator)?;
        }
        self.selected = selected;
        self.requested_sample_rate = m.input.sample_rate;
        self.source = if generator_input {
            Source::Generator
        } else if m.software_loopback.is_some() {
            Source::Software
        } else {
            Source::Live
        };
        if let Some(software) = m.software_loopback {
            self.loopback_settings = software;
        }
        self.lockin_settings = m.lockin;
        self.comparison_settings = m.comparison;
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
        self.spectrogram_mode = m.spectrogram.mode;
        self.cepstrum_log_floor_db = m.spectrogram.log_floor_db;
        self.spectrogram_channel = m.spectrogram.channel;
        self.spectrogram_settings = m.spectrogram.analysis;
        self.spectrogram_overlap = m.spectrogram.overlap;
        self.xy_settings.channels = m.xy.channels;
        self.xy_settings.milliseconds = m.xy.milliseconds;
        self.calibration.pending = calibrations;
        self.calibration.select();
        self.apply_workspace(w);
        Ok(())
    }

    fn request_settings(&mut self, task: SettingsTask) {
        let result = (|| {
            if self.settings_path.trim().is_empty() {
                return Err(i18n::text("common.enter_a_settings_file_path").to_owned());
            }
            let operation = match task {
                SettingsTask::Save => settings::Operation::Save(Box::new(self.capture_settings()?)),
                SettingsTask::Restore if self.can_restore_settings() => {
                    settings::Operation::Restore
                }
                SettingsTask::Restore => {
                    return Err(i18n::text("common.stop_input_before_restoring_settings").into());
                }
            };
            self.settings_worker
                .submit(std::path::PathBuf::from(&self.settings_path), operation)
        })();
        self.settings_error = result.is_err();
        match result {
            Ok(()) => {
                self.settings_task = Some(task);
                self.settings_status = Some(UiStatus::Working);
            }
            Err(error) => self.settings_status = Some(error.into()),
        }
    }

    fn poll_settings(&mut self) {
        while let Ok(event) = self.settings_worker.events.try_recv() {
            self.settings_task = None;
            let result = match event {
                settings::Event::Saved(path) => Ok(UiStatus::SettingsSaved(path)),
                settings::Event::Restored(path, document) => self
                    .restore_settings(*document)
                    .map(|()| UiStatus::SettingsRestored(path)),
                settings::Event::Error(error) => Err(error),
            };
            self.settings_error = result.is_err();
            self.settings_status = Some(result.unwrap_or_else(UiStatus::SettingsFailed));
        }
    }

    fn fit_scope_amplitude(&mut self) {
        let peak = if self.scope_common_vertical.is_some() {
            self.measurements
                .iter()
                .zip(self.enabled)
                .filter(|(_, enabled)| *enabled)
                .map(|(m, _)| m.peak)
                .fold(0.0_f64, f64::max)
        } else {
            self.measurements[self.scope_selected].peak
        };
        *self.scope_selected_vertical_mut() = Vertical {
            fs_per_div: (peak / 3.5).clamp(0.001, 0.5) as f32,
            offset: 0.0,
        };
        self.dirty = true;
    }

    fn scope_panel(&mut self, ui: &mut egui::Ui) {
        egui::Frame::new()
            .fill(Color32::from_rgb(17, 27, 35))
            .stroke(Stroke::new(1.0, BORDER))
            .inner_margin(5.0)
            .show(ui, |ui| {
                compact_plot_style(ui);
                ui.horizontal_wrapped(|ui| {
                    display::activity_label(ui, self.running(), self.pending_stop.is_some(), !self.scope_range.is_empty());
                    self.scope_capture_status(ui);
                    self.cursor_controls(ui, Instrument::Scope);
                });
                if !self.scope_range.is_empty() && !self.running() && (self.core_scope.mode != self.acquisition_mode || self.scope_channels != self.scope_view_channels() || self.calibration.pending != self.calibration.captured) {
                    ui.label(RichText::new(i18n::text("oscilloscope.held_conditions_retained_queued_measurement_settings_apply_on_next")).small().color(YELLOW));
                }
                self.scope_quick_controls(ui);
                // Reserve fixed readout cards independently of their current values.
                let height = (ui.available_height() - monitor_controls::scope_channel_bar_height(ui.available_width()) - ui.spacing().item_spacing.y).max(40.0);
                ui.scope_builder(egui::UiBuilder::new().max_rect(egui::Rect::from_min_size(ui.cursor().min, vec2(ui.available_width(), height))), |ui| self.plot(ui));
                self.scope_channel_bar(ui);
            });
    }

    fn spectrum_view(&self) -> View {
        if self.spectrum_history.linked {
            return self.history_spectrum_view();
        }
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
        if self.spectrum_display.auto_level {
            if !self.spectrum_dirty
                && let Some(cached) = self.spectrum_last_view
                && cached.scale == view.scale
                && cached.min_hz == view.min_hz
                && cached.max_hz == view.max_hz
            {
                view.floor_db = cached.floor_db;
                view.ceiling_db = cached.ceiling_db;
                return view;
            }
            let mut maximum = f32::NEG_INFINITY;
            let mut minimum = f32::INFINITY;
            for index in 0..4 {
                if !self.spectrum_display.enabled[index] {
                    continue;
                }
                let result = self.spectrum_result(index);
                if !result.is_ready() {
                    continue;
                }
                let first = (view.min_hz / result.bin_hz()).ceil() as usize;
                let last = (view.max_hz / result.bin_hz()).floor() as usize;
                if let Some(bins) = result.db().get(first..=last) {
                    for &db in bins {
                        if db.is_finite() {
                            maximum = maximum.max(db);
                            minimum = minimum.min(db);
                        }
                    }
                }
            }
            if maximum.is_finite() {
                view.ceiling_db = ((maximum + 6.0) / 10.0).ceil() * 10.0;
                view.floor_db = ((minimum.max(maximum - 120.0) - 6.0) / 10.0).floor() * 10.0;
                view.floor_db = view.floor_db.min(view.ceiling_db - 20.0);
            }
        }
        view
    }

    fn refresh_spectrum_readouts(&mut self, view: View) {
        let upper = if self.band_max_hz == 0.0 {
            self.shown_selected_spectrum().nyquist() as f64
        } else {
            self.band_max_hz
        };
        let key = (view.min_hz, view.max_hz, self.band_min_hz, upper);
        if self.spectrum_numeric_key != Some(key) {
            self.spectrum_peaks = std::array::from_fn(|i| {
                self.shown_spectrum_enabled(i)
                    .then(|| self.shown_spectrum(i).peak(view))
                    .flatten()
            });
            self.spectrum_peak = self.spectrum_peaks[self.shown_spectrum_index()];
            self.spectrum_band = self.shown_selected_spectrum().band(self.band_min_hz, upper);
            self.spectrum_energy = self.shown_selected_spectrum().energy();
            self.spectrum_numeric_key = Some(key);
        }
    }

    fn spectrum_panel(&mut self, ui: &mut egui::Ui) {
        self.refresh_spectrum_history();
        self.update_spectrum(false);
        let color = self.shown_spectrum_color(self.shown_spectrum_index());
        egui::Frame::new()
            .fill(Color32::from_rgb(17, 27, 35))
            .stroke(Stroke::new(1.0, Color32::from_rgb(48, 70, 82)))
            .inner_margin(5.0)
            .show(ui, |ui| {
                compact_plot_style(ui);
                ui.horizontal_wrapped(|ui| {
                    ui.label(RichText::new(i18n::text("spectrum.spectrum_analyzer")).size(13.0).strong());
                    display::activity_label(ui, self.running() && !self.spectrum_history.linked, self.pending_stop.is_some() && !self.spectrum_history.linked, self.shown_selected_spectrum().window().is_some());

                    if !self.spectrum_history.linked {
                    ui.label(RichText::new(i18n::format("spectrum.ch_input", &[("shown_spectrum_index", &(self.shown_spectrum_index() + 1).to_string()), ("channel", &(self.shown_selected_spectrum().window().map_or(self.spectrum_source(self.shown_spectrum_index()), |window| window.channel)+1).to_string()), ("db_unit", &(self.shown_selected_spectrum().db_unit()).to_string())]).as_ref()).small().color(color));
                    } else {
                        ui.label(RichText::new(i18n::text("spectrum.history_read_only")).small().color(YELLOW));
                    }
                    if !self.spectrum_history.linked
                        && self.presentation.screen == Screen::Console
                        && self.presentation.contains(Instrument::Spectrogram)
                        && ui.add_enabled(!self.cepstrogram_applied(),
                            egui::Button::new(i18n::text("spectrum.time_a_b_from_spectrogram")).small())
                            .on_disabled_hover_text(i18n::text("spectrogram.cepstral_link_disabled")).clicked()
                    {
                        self.link_spectrum_history();
                    }
                });
                self.spectrum_summary(ui);
                let view = self.spectrum_view();
                self.refresh_spectrum_readouts(view);
                if let Some(peak) = self.spectrum_peak {
                    ui.horizontal_wrapped(|ui| {
                        ui.add(egui::Label::new(RichText::new(i18n::format("spectrum.peak_bin_hz", &[("frequency", &format!("{:.2}", peak.frequency))]).as_ref()).monospace().size(15.0).color(color)).wrap());
                        ui.add(egui::Label::new(RichText::new(format!("{:.2} {}", peak.level_db, self.shown_selected_spectrum().db_unit())).monospace().size(15.0).color(color)).wrap());
                        ui.label(RichText::new(i18n::format("spectrum.f_hz", &[("bin_hz", &format!("{:.3}", self.shown_selected_spectrum().bin_hz()))]).as_ref()).small().color(MUTED));
                    });
                } else {
                    ui.label(
                        RichText::new(
                            format!("{} · {}", self.shown_selected_spectrum().settings().quantity.display_name(), self.shown_selected_spectrum().db_unit()),
                        )
                        .small()
                        .color(MUTED),
                    );
                }
                if self.shown_selected_spectrum().settings().quantity == Quantity::Psd {
                    if let Some(band) = &self.spectrum_band {
                        ui.label(RichText::new(i18n::format("spectrum.band_rms", &[("rms", &(display::number(Some(band.rms))).to_string()), ("unit", (self.shown_selected_spectrum().unit()))]).as_ref()).monospace().size(18.0).color(color));
                        let _response = ui.label(RichText::new(i18n::format("spectrum.hz_power", &[("first_hz", &format!("{:.1}", band.first_hz)), ("last_hz", &format!("{:.1}", band.last_hz)), ("power", &(display::number(Some(band.power))).to_string()), ("power_unit", &(self.shown_selected_spectrum().power_unit()).to_string())]).as_ref()).small().color(MUTED))
                        .on_hover_text(i18n::format("spectrum.requested_hz_inclusive_centres_of_bins_sum_of_f64", &[("requested_hz", &(band.requested_hz[0]).to_string()), ("requested_hz_2", &(band.requested_hz[1]).to_string()), ("first_bin", &(band.first_bin).to_string()), ("last_bin", &(band.last_bin).to_string()), ("channel", &(band.window.channel + 1).to_string()), ("input_generation", &(self.input_generation).to_string()), ("updates", &(band.average.updates).to_string()), ("start", &(band.average.start).to_string()), ("end", &(band.average.end).to_string()), ("dropped", &(self.dropped).to_string()), ("missing_windows", &(self.spectrum_info.missing_windows).to_string())]).as_ref());
                        #[cfg(feature = "qa")]
                        ui.ctx().data_mut(|data| {
                            data.insert_temp(egui::Id::unique("qa_spectrum_band"), _response.rect);
                        });
                    } else {
                        ui.label(RichText::new(i18n::text("spectrum.band_power_unavailable_invalid_window_range_or_nonfinite_sum")).small().color(MUTED));
                    }
                }
                if self.shown_selected_spectrum().settings().quantity == Quantity::Esd {
                    let _response = ui.label(RichText::new(i18n::format("spectrum.window_energy_s", &[("spectrum_energy", &(display::number(self.spectrum_energy)).to_string()), ("power_unit", &(self.shown_selected_spectrum().power_unit()).to_string())]).as_ref()).monospace().size(18.0).color(color))
                        .on_hover_text(i18n::text("spectrum.sum_of_f64_esd_f_over_all_bins_including"));
                        #[cfg(feature = "qa")]
                        ui.ctx().data_mut(|data| {
                            data.insert_temp(egui::Id::unique("qa_spectrum_energy"), _response.rect);
                        });
                }
                if let Some(c) = self.shown_selected_spectrum().calibration() {
                    let _response = ui.label(RichText::new(i18n::format("spectrum.calibration_rev", &[("id", (c.id())), ("revision", &(c.revision()).to_string())]).as_ref()).small().color(MUTED))
                        .on_hover_text(spectrum_calibration_description(Some(c)));
                        #[cfg(feature = "qa")]
                        ui.ctx().data_mut(|data| {
                            data.insert_temp(egui::Id::unique("qa_spectrum_calibration"), _response.rect);
                        });
                }
                self.spectrum_plot(ui, view);
                if self.spectrum_history.linked { self.history_spectrum_bar(ui); } else { self.spectrum_channel_bar(ui); }
            });
    }

    fn spectrum_plot(&mut self, ui: &mut egui::Ui, view: View) {
        let (outer, response) = ui.allocate_exact_size(
            vec2(ui.available_width(), (plot_size(ui).y - 46.0).max(120.0)),
            egui::Sense::click_and_drag(),
        );
        let rect =
            egui::Rect::from_min_max(outer.min + vec2(32.0, 4.0), outer.max - vec2(14.0, 18.0));
        #[cfg(feature = "qa")]
        ui.ctx().data_mut(|data| {
            data.insert_temp(egui::Id::unique("qa_spectrum_plot"), rect);
        });
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
        let mut labels = Vec::new();
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
            if labelled {
                labels.push((x, frequency_label(hz)));
            }
        }
        plot_labels::horizontal(
            painter,
            egui::Rect::from_min_max(
                pos2(outer.left(), rect.bottom() + 4.0),
                outer.right_bottom(),
            ),
            labels,
        );
        let ppp = ui.ctx().pixels_per_point();
        let pixels = (rect.width() * ppp).ceil().max(1.0) as usize;
        self.spectrum_dirty |=
            pixels != self.spectrum_pixels || self.spectrum_last_view != Some(view);
        self.spectrum_last_view = Some(view);
        self.spectrum_pixels = pixels;
        if self.spectrum_dirty {
            let started = Instant::now();
            let segments = Arc::make_mut(&mut self.spectrum_segments);
            segments.clear();
            for (index, &trace_color) in COLORS.iter().enumerate() {
                if !(if self.spectrum_history.linked {
                    index < 2
                } else {
                    self.spectrum_display.enabled[index]
                }) {
                    continue;
                }
                let trace_color = if self.spectrum_history.linked {
                    COLORS[if index == 0 { 0 } else { 3 }]
                } else {
                    trace_color
                };
                let result = if self.spectrum_history.linked {
                    &self.spectrum_history.results[index]
                } else if index == 0 {
                    &self.analyzer
                } else {
                    &self.spectrum_overlays[index - 1]
                };
                self.spectrum_line_builder.build(
                    result,
                    view,
                    pixels,
                    self.show_hold && !self.spectrum_history.linked,
                    &mut self.spectrum_lines,
                );
                for trace in [1, 0] {
                    segments.extend(
                        self.spectrum_lines
                            .iter()
                            .filter(|line| line.channel == trace)
                            .map(|line| {
                                let mut color = trace_color;
                                if trace == 1 {
                                    color[3] = 0.35;
                                }
                                Segment {
                                    a: line.a,
                                    b: line.b,
                                    color,
                                }
                            }),
                    );
                }
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
        #[cfg(feature = "qa")]
        if self.running()
            && ui.is_rect_visible(rect)
            && let Some(profile) = &mut self.profile
            && let Some(window) = self.analyzer.window()
            && let Some(timing) = self.spectrum_timing.filter(|t| t.end == window.end)
        {
            // CPU-side submission to egui. GPU execution/scanout need their own
            // timestamps and must not be inferred from this latency.
            profile.record_spectrum_latency(self.input_generation, timing, Instant::now());
        }
        if self.spectrum_display.peak_marker {
            for index in 0..4 {
                if self.shown_spectrum_enabled(index)
                    && let Some(peak) = self.spectrum_peaks[index]
                {
                    let x = rect.left() + view.x(peak.frequency as f32) * rect.width();
                    painter.line_segment(
                        [pos2(x, rect.top()), pos2(x, rect.top() + 10.0)],
                        Stroke::new(2.0, self.shown_spectrum_color(index)),
                    );
                }
            }
        }
        if !(0..4).any(|i| self.shown_spectrum_enabled(i) && self.shown_spectrum(i).is_ready()) {
            painter.text(
                rect.center(),
                egui::Align2::CENTER_CENTER,
                if self.spectrum_history.linked {
                    self.history_spectrum_reason(self.spectrum_history.selected)
                } else if !self.spectrum_display.enabled.iter().any(|enabled| *enabled) {
                    i18n::text("common.all_channels_off")
                } else if self.shown_selected_spectrum().validity() == spectrum::Validity::NonFinite
                {
                    i18n::text("common.invalid_fft_window_nonfinite_value")
                } else if self.running() {
                    i18n::text("common.collecting_a_complete_fft_window")
                } else if self.acquisition_state == acquisition::State::Complete {
                    i18n::text("common.single_complete_fft_window_was_not_filled")
                } else {
                    i18n::text("common.start_input_to_begin_acquisition")
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
            if let Some(reading) = self.shown_selected_spectrum().cursor(hz as f64) {
                painter.text(
                    rect.right_bottom() + vec2(-10.0, -10.0),
                    egui::Align2::RIGHT_BOTTOM,
                    i18n::format(
                        "common.hz_2",
                        &[
                            ("frequency_hz", &format!("{:.1}", reading.frequency_hz)),
                            ("level_db", &format!("{:.2}", reading.level_db)),
                            ("db_unit", &(reading.window.db_unit()).to_string()),
                        ],
                    )
                    .to_string(),
                    egui::FontId::monospace(11.0),
                    self.shown_spectrum_color(self.shown_spectrum_index()),
                );
            }
        }
        self.spectrum_cursors(ui, &response, rect, view);
        ui.horizontal(|ui| {
            ui.label(
                RichText::new(self.shown_selected_spectrum().db_unit())
                    .small()
                    .color(MUTED),
            );
            if self.show_hold && !self.spectrum_history.linked {
                ui.label(
                    RichText::new(i18n::text("common.peak_hold"))
                        .small()
                        .color(HOLD),
                );
            }
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                ui.label(RichText::new("Hz").small().color(MUTED));
            });
        });
    }

    fn plot(&mut self, ui: &mut egui::Ui) {
        let footer = ui.spacing().interact_size.y + ui.spacing().item_spacing.y;
        let size = vec2(
            ui.available_width(),
            (ui.available_height() - footer).max(40.0),
        );
        let (outer, response) = ui.allocate_exact_size(size, egui::Sense::click_and_drag());
        let rect =
            egui::Rect::from_min_max(outer.min + vec2(42.0, 4.0), outer.max - vec2(28.0, 18.0));
        #[cfg(feature = "qa")]
        if self.smoke {
            ui.ctx().data_mut(|data| {
                data.insert_temp(egui::Id::unique("qa_scope_plot"), rect);
            });
        }
        if response.hovered() {
            let (scroll, shift) = ui.input(|i| (i.smooth_scroll_delta.y, i.modifiers.shift));
            if scroll != 0.0 {
                let factor = (-scroll * 0.008).exp();
                if shift {
                    let vertical = self.scope_selected_vertical_mut();
                    vertical.fs_per_div = (vertical.fs_per_div * factor).clamp(0.001, 0.5);
                } else {
                    self.ms_per_div = (self.ms_per_div * factor).clamp(0.05, 100.0);
                }
                self.dirty = true;
            }
        }
        if response.double_clicked() {
            self.ms_per_div = 1.0;
            if let Some(vertical) = &mut self.scope_common_vertical {
                *vertical = Vertical::default();
            } else {
                self.scope_vertical = [Vertical::default(); SCOPE_CHANNELS];
            }
            self.scope_horizontal_position = 0.0;
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
        }
        plot_labels::horizontal(
            painter,
            egui::Rect::from_min_max(
                pos2(outer.left(), rect.bottom() + 4.0),
                outer.right_bottom(),
            ),
            (0..=10).map(|x| {
                (
                    rect.left() + rect.width() * x as f32 / 10.0,
                    format!(
                        "{:.1}",
                        (x as f32 - 2.0 - self.scope_horizontal_position)
                            * self.scope_display_ms_per_div()
                    ),
                )
            }),
        );
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
                    format!(
                        "{:.3}",
                        (4.0 - y as f32) as f64
                            * self.scope_display_vertical(self.scope_selected).fs_per_div as f64
                            + self.scope_display_vertical(self.scope_selected).offset
                    ),
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
            build_scaled_sweep_lines(
                self.scope_capture.as_ref().unwrap_or(&self.history),
                &Sweep {
                    range: self.scope_range.clone(),
                    triggered: self.triggered,
                    sample_offset: self.scope_sample_offset,
                },
                pixels,
                std::array::from_fn(|index| self.scope_display_vertical(index)),
                self.enabled,
                self.scope_view_channels(),
                &mut self.lines,
            );
            let segments = Arc::make_mut(&mut self.segments);
            segments.clear();
            segments.extend(self.lines.iter().map(|line| Segment {
                a: [line.a[0] + self.scope_horizontal_position / 10.0, line.a[1]],
                b: [line.b[0] + self.scope_horizontal_position / 10.0, line.b[1]],
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
        self.scope_trigger_overlay(ui, rect);
        if let Some(position) = response.hover_pos().filter(|p| rect.contains(*p)) {
            painter.line_segment(
                [
                    pos2(position.x, rect.top()),
                    pos2(position.x, rect.bottom()),
                ],
                Stroke::new(1.0, Color32::from_white_alpha(65)),
            );
            let fraction = ((position.x - rect.left()) / rect.width()
                - self.scope_horizontal_position / 10.0) as f64;
            if (0.0..=1.0).contains(&fraction)
                && let Some(sample) = cursor::sample_at_fraction_with_offset(
                    self.scope_range.clone(),
                    fraction,
                    self.scope_sample_offset,
                )
            {
                response.clone().on_hover_text(self.sample_text(sample));
            }
        }
        self.scope_cursors(ui, &response, rect);
        self.scope_notice_ui(ui, rect.shrink(8.0));
        ui.horizontal(|ui| {
            ui.label(RichText::new(self.scope_axis_label().as_ref()).size(12.0))
                .on_hover_text(
                    i18n::format(
                        "common.selected_ch_axis",
                        &[
                            ("scope_selected", &(self.scope_selected + 1).to_string()),
                            ("display", (display::amplitude_help())),
                        ],
                    )
                    .as_ref(),
                );
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                ui.label(RichText::new(i18n::text("common.time_ms")).size(12.0))
                    .on_hover_text(
                        i18n::format(
                            "common.time_relative_to_the_sweep_reference_t_ms",
                            &[("display", (display::sample_rate_help()))],
                        )
                        .as_ref(),
                    );
            });
        });
    }
}

impl Drop for ScopeApp {
    fn drop(&mut self) {
        self.save_preferences();
        self.generator.stop();
        self.core.take();
    }
}

impl eframe::App for ScopeApp {
    fn save(&mut self, storage: &mut dyn eframe::Storage) {
        if !self.smoke {
            self.shell.save_sidebar(storage);
            i18n::save(storage);
            self.save_preferences();
        }
    }

    fn persist_egui_memory(&self) -> bool {
        false
    }

    #[cfg(feature = "qa")]
    fn raw_input_hook(&mut self, ctx: &egui::Context, input: &mut egui::RawInput) {
        if let Some(review) = &mut self.menu_review {
            review.input(input);
            return;
        }
        if self.smoke
            && let Ok(pointer) = std::env::var("MEASURELAB_UI_SMOKE_POINTER")
            && let Some(rect) =
                ctx.data(|data| data.get_temp::<egui::Rect>(egui::Id::unique("qa_scope_plot")))
        {
            input.events.retain(|event| {
                !matches!(
                    event,
                    egui::Event::PointerMoved(_)
                        | egui::Event::PointerGone
                        | egui::Event::PointerButton { .. }
                )
            });
            input.events.push(if pointer == "inside" {
                egui::Event::PointerMoved(rect.lerp_inside(vec2(0.65, 0.6)))
            } else {
                egui::Event::PointerGone
            });
        }
    }

    fn ui(&mut self, ui: &mut egui::Ui, frame: &mut eframe::Frame) {
        #[cfg(not(feature = "qa"))]
        let _ = frame;
        let ctx = ui.ctx().clone();
        let now = Instant::now();
        #[cfg(feature = "qa")]
        if self.profile.is_some() && std::env::var_os("MEASURELAB_PROFILE_DPI").is_some() {
            let seconds = self.created.elapsed().as_secs_f64();
            if self.dpi_stage == 0 && seconds >= 5.0 {
                ctx.set_zoom_factor(1.5);
                self.dpi_stage = 1;
                println!(
                    "GUI DPI QA: zoom 1.0 → 1.5 during running output/input; native pixels per point {}",
                    ctx.native_pixels_per_point().unwrap_or(1.0)
                );
            } else if self.dpi_stage == 1 && seconds >= 10.0 {
                ctx.set_zoom_factor(1.0);
                self.dpi_stage = 2;
                println!(
                    "GUI DPI QA: zoom 1.5 → 1.0; input/output and captured conditions retained"
                );
            }
        }
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
        self.generator.poll();
        self.poll_preferences(&ctx);
        #[cfg(feature = "qa")]
        self.start_generator_profile_input();
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
        // Result collection and raster preparation continue outside this UI.
        self.receive_spectrogram_view();
        self.spectrogram_build_ms = started.elapsed().as_secs_f64() * 1000.0;
        #[cfg(feature = "qa")]
        {
            if self.running()
                && let Some(profile) = &mut self.profile
            {
                profile.record_work(crate::qa::Work::Spectrogram, self.spectrogram_build_ms);
            }
            self.check_large_fft_lifecycle(&ctx);
            self.profile_spectrogram_history();
            self.check_lifecycle(&ctx, elapsed);
            self.check_input_lifecycle(&ctx);
            self.check_generator_edits();
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
                let profile_finished = profile.finished();
                if profile_finished
                    && !self.screenshot_writer.pending()
                    && (!self.screenshot_requested || self.screenshot_received)
                {
                    assert!(
                        self.error.is_none() && self.input_error.is_none(),
                        "UI QA input failed: {:?} / {:?}",
                        self.error,
                        self.input_error
                    );
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
                        assert!(!snapshot.failed, "UI QA finite input failed");
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
                                    Quantity::Esd => assert!(
                                        (result.energy().unwrap()
                                            - 0.0078125
                                                * (0..result.settings().size)
                                                    .map(|i| result
                                                        .settings()
                                                        .window
                                                        .weight(i, result.settings().size)
                                                        .powi(2))
                                                    .sum::<f64>()
                                                / snapshot.sample_rate as f64)
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
                    if let Some(fixture) = &self.known_output {
                        fixture.check().expect("QA output audit failed");
                        let snapshot = finished.as_ref().unwrap();
                        assert_eq!(snapshot.input_dropped, 0);
                        assert_eq!(snapshot.spectrum_info.input_missing, 0);
                        assert_eq!(snapshot.spectrum_info.missing_windows, 0);
                        assert_eq!(self.stft.metrics.input_dropped.load(Ordering::Relaxed), 0);
                        if fixture.physical {
                            crate::qa::physical_lockin::validate_gui(snapshot).unwrap();
                        } else {
                            let result = &snapshot.spectrum;
                            let bin =
                                (32 + self.spectrum_channel * 7) * result.settings().size / 8192;
                            let hz = bin as f64 * self.sample_rate as f64
                                / result.settings().size as f64;
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
                                Quantity::Esd => assert!(
                                    (result.energy().unwrap()
                                        - 0.0078125
                                            * (0..result.settings().size)
                                                .map(|i| result
                                                    .settings()
                                                    .window
                                                    .weight(i, result.settings().size)
                                                    .powi(2))
                                                .sum::<f64>()
                                            / self.sample_rate as f64)
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
                            let seconds =
                                (average.end - average.start - result.settings().size as u64)
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
                    }
                    if let Some(path) = std::env::var_os("MEASURELAB_PROFILE_EXPORT") {
                        // Terminal QA uses the same immutable finite Stop result;
                        // this I/O is outside the UI performance measurement.
                        let snapshot = finished.as_ref().expect("export QA needs a finite result");
                        let mut document = export::Document::capture(
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
                        if snapshot.lockin.settings.enabled {
                            document.lockin = Some(export::Lockin::capture(
                                snapshot.lockin.clone(),
                                &snapshot.calibrations,
                            ));
                        }
                        document.validate().unwrap();
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
                    println!(
                        "STFT transport: high water {} / {}, planning max {:.3} ms",
                        self.stft.metrics.input_high_water.load(Ordering::Relaxed),
                        stft::INPUT_BLOCKS,
                        self.stft.metrics.planning_max_nanos.load(Ordering::Relaxed) as f64 / 1e6,
                    );
                    let history = self.spectrogram_history.lock().unwrap();
                    println!(
                        "Spectrogram profile: {} retained rows, {:.1} MiB CPU storage",
                        history.len(),
                        history.storage_bytes() as f64 / 1048576.0
                    );
                    drop(history);
                    println!(
                        "Cepstrum extra log/inverse CPU: {:.3} ms total",
                        self.stft.metrics.cepstrum_nanos.load(Ordering::Relaxed) as f64 / 1e6
                    );
                    self.finish_spectrogram_profile(finished.as_ref());
                    let numeric = self.stft_history.snapshot();
                    if let Some(render) = &frame.wgpu_render_state()
                        && let Some(renderer) = render
                            .renderer
                            .read()
                            .callback_resources
                            .get::<spectrogram_gpu::Renderer>()
                    {
                        println!(
                            "Spectrogram GPU payload: {} bytes current / {} bytes resize peak, {} uploaded bytes / {} rows",
                            renderer.storage_bytes(),
                            renderer.peak_storage_bytes,
                            renderer.uploaded_bytes,
                            renderer.uploaded_rows,
                        );
                        if std::env::var_os("MEASURELAB_PROFILE_SPECTROGRAM").is_some() {
                            assert!(renderer.peak_storage_bytes <= 32 * 1024 * 1024);
                        }
                    }
                    println!(
                        "STFT history profile: {} retained frames, {:.3} s, {:.1} MiB retained / {:.1} MiB peak frames, {} retired, {} storage dropped, collector CPU {:.3} ms total",
                        numeric.frames().len(),
                        numeric.retained_seconds(),
                        numeric.storage_bytes() as f64 / 1048576.0,
                        self.stft_history.peak_frame_bytes() as f64 / 1048576.0,
                        numeric.retired,
                        self.stft_history
                            .metrics
                            .storage_dropped
                            .load(Ordering::Relaxed),
                        self.stft_history
                            .metrics
                            .processing_nanos
                            .load(Ordering::Relaxed) as f64
                            / 1e6,
                    );
                    if std::env::var_os("MEASURELAB_PROFILE_DEMO_BIN_TONE").is_some() {
                        let snapshot = finished.as_ref().expect("known demo finite endpoint");
                        assert_eq!(snapshot.input_dropped, 0, "known demo acquisition loss");
                        assert!(snapshot.spectrum.is_ready(), "known demo incomplete FFT");
                    }
                    self.busy = true;
                    self.audio.send(Command::Stop);
                    self.qa_wait_audio_idle().expect("QA input did not stop");
                    if std::env::var_os("MEASURELAB_PROFILE_GENERATOR_INTERNAL").is_some() {
                        self.generator.stop();
                        let deadline = Instant::now() + Duration::from_secs(5);
                        while !self.generator.stopped() {
                            self.generator.poll();
                            assert!(Instant::now() < deadline, "internal output Stop timed out");
                            std::thread::sleep(Duration::from_millis(2));
                        }
                        println!("Internal Generator Spectrogram output stopped");
                    }
                    if std::env::var_os("MEASURELAB_PROFILE_GENERATOR_DEVICE").is_some() {
                        self.finish_generator_profile(
                            finished.as_ref().expect("Generator input endpoint"),
                        )
                        .expect("Generator profile audit failed");
                    }
                    if let Some(mut fixture) = self.known_output.take() {
                        fixture.restore().expect("QA input rate restoration failed");
                    }
                    println!("UI QA profile complete: finite result audited and input stopped");
                    self.profile = None;
                    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                }
                if running || std::env::var_os("MEASURELAB_PROFILE_IDLE").is_none() {
                    ctx.request_repaint();
                }
                if std::env::var_os("MEASURELAB_PROFILE_SCREENSHOT").is_some()
                    && !profile_finished
                    && (!self.screenshot_requested
                        || (std::env::var("MEASURELAB_PROFILE_SCREENSHOT").as_deref()
                            == Ok("repeat")
                            && self.screenshot_received
                            && self
                                .screenshot_requested_at
                                .is_some_and(|at| at.elapsed() >= Duration::from_secs(1))))
                    && self.created.elapsed().as_secs_f64()
                        > (self.spectrum_settings.size as f64 / self.sample_rate as f64 + 1.0)
                            .max(3.0)
                {
                    self.screenshot_requested = true;
                    self.screenshot_received = false;
                    self.screenshot_requested_at = Some(Instant::now());
                    self.screenshot_writer.request(&ctx);
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
            if let Some(result) = self.screenshot_writer.poll() {
                if self.profile.is_some() {
                    assert!(result.is_ok(), "UI screenshot failed: {result:?}");
                }
                match result {
                    Ok(duration) => {
                        self.screenshot_received = true;
                        println!(
                            "UI screenshot: dist/ui-smoke.png (worker {:.3} ms)",
                            duration.as_secs_f64() * 1000.0
                        );
                    }
                    Err(error) => eprintln!("UI screenshot failed: {error}"),
                }
            }
            if self.screenshot_requested
                && !self.screenshot_received
                && !self.screenshot_writer.pending()
            {
                // wgpu map_async needs device polling. Submission/presentation
                // alone does not reliably deliver Metal readback callbacks.
                let _ = self.screenshot_device.poll(wgpu::PollType::Poll);
            }
            if self.smoke && std::env::var_os("MEASURELAB_UI_SMOKE_SETTINGS_RESTORE").is_some() {
                assert_eq!(self.spectrum_channel, 15);
                assert_eq!(self.spectrogram_channel, 15);
                assert!(!self.running());
            }
            if self.screenshot_writer.pending() {
                ctx.request_repaint_after(Duration::from_millis(10));
            }
        }
        if shell::input_shortcut(
            &ctx,
            self.input_transport_enabled() && !self.shell.auxiliary_window_open(),
        ) {
            if self.running() {
                self.stop();
            } else {
                self.start();
            }
        }
        self.shell_header(ui);
        egui::Panel::bottom("status").show(ui, |ui| {
            ui.horizontal_wrapped(|ui| {
                for status in [&self.export_status, &self.workspace_status]
                    .into_iter()
                    .flatten()
                {
                    ui.add(
                        egui::Label::new(
                            RichText::new(status.render().as_ref()).small().color(MUTED),
                        )
                        .truncate(),
                    )
                    .on_hover_text(status.render().as_ref());
                }
            });
            ui.horizontal_wrapped(|ui| {
                ui.label(RichText::new(self.input_status_text()).small().color(MUTED))
                    .on_hover_text(display::sample_rate_help());
                ui.separator();
                ui.label(
                    RichText::new(
                        i18n::format(
                            "common.dropped",
                            &[("dropped", &(self.dropped).to_string())],
                        )
                        .as_ref(),
                    )
                    .small()
                    .color(if self.dropped > 0 { YELLOW } else { MUTED }),
                );
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    self.preferences_status(ui);
                    if let Some(status) = &self.settings_status
                        && ui
                            .small_button(if self.settings_error {
                                i18n::text("common.settings_error")
                            } else {
                                i18n::text("common.settings_status")
                            })
                            .on_hover_text(status.render().as_ref())
                            .clicked()
                    {
                        self.shell.file_paths = true;
                    }
                    ui.menu_button(
                        RichText::new(i18n::text("common.performance")).small(),
                        |ui| {
                            ui.label(RichText::new(&self.adapter).small().color(MUTED));
                            ui.separator();
                            ui.label(
                                i18n::format(
                                    "common.ui_fps",
                                    &[("fps", &format!("{:.0}", self.fps))],
                                )
                                .as_ref(),
                            );
                            ui.label(
                                i18n::format(
                                    "common.scope_prep_ms",
                                    &[("build_ms", &format!("{:.2}", self.build_ms))],
                                )
                                .as_ref(),
                            );
                            ui.label(
                                i18n::format(
                                    "common.worker_fft_ms",
                                    &[("fft_ms", &format!("{:.2}", self.fft_ms))],
                                )
                                .as_ref(),
                            );
                            ui.label(
                                i18n::format(
                                    "common.spectrum_windows_missing",
                                    &[
                                        ("mode", self.spectrum_info.mode.display_name()),
                                        ("updates", &(self.spectrum_info.updates).to_string()),
                                        (
                                            "missing_windows",
                                            &(self.spectrum_info.missing_windows).to_string(),
                                        ),
                                    ],
                                )
                                .as_ref(),
                            );
                            if let Some(core) = &self.core {
                                ui.label(
                                    i18n::format(
                                        "common.display_updates_skipped",
                                        &[(
                                            "elaxed",
                                            &(core.metrics.display_skipped.load(Ordering::Relaxed))
                                                .to_string(),
                                        )],
                                    )
                                    .as_ref(),
                                );
                            }
                            ui.label(
                                i18n::format(
                                    "common.spectrum_prep_ms",
                                    &[(
                                        "spectrum_build_ms",
                                        &format!("{:.2}", self.spectrum_build_ms),
                                    )],
                                )
                                .as_ref(),
                            );
                            ui.label(
                                i18n::format(
                                    "common.xy_prep_ms",
                                    &[("xy_build_ms", &format!("{:.2}", self.xy_build_ms))],
                                )
                                .as_ref(),
                            );
                            ui.label(
                                i18n::format(
                                    "common.stft_raster_peak_mib_mib_display_requests_replaced",
                                    &[
                                        (
                                            "peak_cache_bytes",
                                            &format!(
                                                "{:.1}",
                                                self.spectrogram_view_worker.peak_cache_bytes()
                                                    as f64
                                                    / 1048576.0
                                            ),
                                        ),
                                        (
                                            "elaxed",
                                            &(self
                                                .spectrogram_view_worker
                                                .replaced
                                                .load(Ordering::Relaxed))
                                            .to_string(),
                                        ),
                                    ],
                                )
                                .as_ref(),
                            );

                            ui.label(
                                i18n::format(
                                    "common.spectrogram_history_ms",
                                    &[(
                                        "spectrogram_build_ms",
                                        &format!("{:.2}", self.spectrogram_build_ms),
                                    )],
                                )
                                .as_ref(),
                            );
                            let numeric = self.stft_history.snapshot();
                            ui.label(
                                i18n::format(
                                    "common.stft_retention_s_frames_mib_retired",
                                    &[
                                        (
                                            "retained_seconds",
                                            &format!("{:.2}", numeric.retained_seconds()),
                                        ),
                                        ("len", &(numeric.frames().len()).to_string()),
                                        (
                                            "storage_bytes",
                                            &format!(
                                                "{:.1}",
                                                numeric.storage_bytes() as f64 / 1048576.0
                                            ),
                                        ),
                                        ("retired", &(numeric.retired).to_string()),
                                        (
                                            "else",
                                            (if numeric.capacity_limited {
                                                i18n::text("common.capacity_limited")
                                            } else {
                                                ""
                                            }),
                                        ),
                                    ],
                                )
                                .as_ref(),
                            );
                            ui.label(
                                i18n::format(
                                    "common.stft_history_storage_losses_allocated_mib_peak_mib",
                                    &[
                                        (
                                            "elaxed",
                                            &(self
                                                .stft_history
                                                .metrics
                                                .storage_dropped
                                                .load(Ordering::Relaxed))
                                            .to_string(),
                                        ),
                                        (
                                            "allocated_frame_bytes",
                                            &format!(
                                                "{:.1}",
                                                self.stft_history.allocated_frame_bytes() as f64
                                                    / 1048576.0
                                            ),
                                        ),
                                        (
                                            "peak_frame_bytes",
                                            &format!(
                                                "{:.1}",
                                                self.stft_history.peak_frame_bytes() as f64
                                                    / 1048576.0
                                            ),
                                        ),
                                    ],
                                )
                                .as_ref(),
                            );
                            let (history_rows, history_bytes) = {
                                let history = self.spectrogram_history.lock().unwrap();
                                (history.len(), history.storage_bytes())
                            };
                            ui.label(
                                i18n::format(
                                    "common.spectrogram_rows_mib_cpu_storage",
                                    &[
                                        ("len", &history_rows.to_string()),
                                        ("spectrogram", &(spectrogram::ROWS).to_string()),
                                        (
                                            "storage_bytes",
                                            &format!("{:.1}", history_bytes as f64 / 1048576.0),
                                        ),
                                    ],
                                )
                                .as_ref(),
                            );
                            ui.label(
                                i18n::format(
                                    "common.stft_input_dropped_rows_dropped",
                                    &[
                                        (
                                            "elaxed",
                                            &(self
                                                .stft
                                                .metrics
                                                .input_dropped
                                                .load(Ordering::Relaxed))
                                            .to_string(),
                                        ),
                                        (
                                            "elaxed_2",
                                            &(self
                                                .stft
                                                .metrics
                                                .result_dropped
                                                .load(Ordering::Relaxed))
                                            .to_string(),
                                        ),
                                    ],
                                )
                                .as_ref(),
                            );
                            if let Some(row) = self.last_stft {
                                ui.label(
                                    i18n::format(
                                        "common.stft_ch_n_hop_samples",
                                        &[
                                            ("channel", &(row.config.channel + 1).to_string()),
                                            ("size", &(row.config.size).to_string()),
                                            ("hop", &(row.config.hop).to_string()),
                                            ("start", &(row.start).to_string()),
                                            ("end", &(row.end).to_string()),
                                        ],
                                    )
                                    .as_ref(),
                                );
                            }
                            ui.label(
                                i18n::format(
                                    "common.gpu_segments",
                                    &[(
                                        "len",
                                        &(self.segments.len()
                                            + self.spectrum_segments.len()
                                            + self.xy_segments.len())
                                        .to_string(),
                                    )],
                                )
                                .as_ref(),
                            );
                            ui.label(
                                RichText::new(i18n::text(
                                    "common.timings_are_cpu_work_not_gpu_execution",
                                ))
                                .small()
                                .color(MUTED),
                            );
                        },
                    );
                });
            });
        });
        self.shell_sides(ui);
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
        self.shell_central(ui);
        if self.running() || self.busy || !self.generator.stopped() {
            // Let VSync pace acquisition frames without an additional timer.
            ctx.request_repaint();
        }
        if self.smoke {
            #[cfg(feature = "qa")]
            if let Some(mut review) = self.menu_review.take() {
                review.observe(self, &ctx);
                let ready = review.ready();
                self.menu_review = Some(review);
                if !ready {
                    ctx.request_repaint();
                    return;
                }
            }
            #[cfg(feature = "qa")]
            if std::env::var_os("MEASURELAB_UI_SMOKE_ASSERTIONS_ONLY").is_some() {
                println!(
                    "UI assertions only OK: rendered shell bounds checked; screenshot not requested"
                );
                ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                return;
            }
            #[cfg(feature = "qa")]
            if !self.smoke_focused {
                self.smoke_focused = true;
                ctx.send_viewport_cmd(egui::ViewportCommand::Focus);
                self.created = Instant::now();
            } else if !self.screenshot_requested && self.created.elapsed() > Duration::from_secs(1)
            {
                self.screenshot_requested = true;
                self.screenshot_attempts = 1;
                self.screenshot_writer.request(&ctx);
                // Slow first-frame GPU preparation must not request Screenshot
                // and Close together. Allow a fresh readback interval.
                self.created = Instant::now();
            } else if self.screenshot_requested
                && !self.screenshot_received
                && !self.screenshot_writer.pending()
                && self.screenshot_attempts < 4
                && self.created.elapsed() > Duration::from_secs(2 * self.screenshot_attempts as u64)
            {
                self.screenshot_attempts += 1;
                println!(
                    "UI screenshot readback retry {}: {:?}",
                    self.screenshot_attempts,
                    ctx.input(|input| input.viewport().clone())
                );
                ctx.send_viewport_cmd(egui::ViewportCommand::Focus);
                self.screenshot_writer.request(&ctx);
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

fn cursor_placement_label(placed: [bool; 2]) -> &'static str {
    match placed {
        [false, false] => i18n::text("common.placed_none"),
        [true, false] => i18n::text("common.placed_a"),
        [false, true] => i18n::text("common.placed_b"),
        [true, true] => i18n::text("common.placed_a_b"),
    }
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
        (ui.available_height() - footer_height).max(180.0),
    )
}

fn setting_label(ui: &mut egui::Ui, text: &str) {
    ui.label(RichText::new(text).small().color(MUTED));
}

fn spectrum_calibration_description(calibration: Option<&Calibration>) -> String {
    match calibration {
        Some(c) => i18n::format(
            "common.calibration_rev_y_fs",
            &[
                ("id", (c.id())),
                ("revision", &(c.revision()).to_string()),
                ("gain", &(c.gain()).to_string()),
                ("offset", &(c.offset()).to_string()),
                ("unit", (c.unit())),
                ("conditions", (c.conditions())),
            ],
        )
        .to_string(),
        None => i18n::text("common.uncalibrated_fs").into(),
    }
}

fn calibration_description(set: &calibration::Set, channel: ChannelId) -> String {
    match set.get(channel) {
        Some(c) => i18n::format(
            "common.revision_y_fs",
            &[
                ("id", (c.id())),
                ("revision", &(c.revision()).to_string()),
                ("gain", &format!("{:.6e}", c.gain())),
                ("offset", &format!("{:.6e}", c.offset())),
                ("unit", (c.unit())),
                ("conditions", (c.conditions())),
            ],
        )
        .to_string(),
        None => i18n::text("common.uncalibrated_fs").into(),
    }
}

fn fft_precision(ui: &mut egui::Ui, id: &str, precision: &mut Precision) {
    setting_label(ui, i18n::text("common.fft_precision"));
    egui::ComboBox::from_id_salt(id)
        .width(ui.available_width())
        .selected_text(precision.display_name())
        .show_ui(ui, |ui| {
            for mode in [Precision::F64, Precision::F32] {
                ui.selectable_value(precision, mode, mode.display_name());
            }
        })
        .response
        .on_hover_text(i18n::text(
            "common.only_this_instrument_s_fft_changes_precision_input_history",
        ));
}

fn channel_select(ui: &mut egui::Ui, id: &str, selected: &mut ChannelId, channels: u16) {
    let width = if ui.layout().is_horizontal() {
        ui.available_width().min(150.0)
    } else {
        ui.available_width()
    };
    egui::ComboBox::from_id_salt(id)
        .width(width)
        .selected_text(if channel::available(*selected, channels as usize) {
            channel::name(*selected)
        } else {
            i18n::format(
                "common.unavailable",
                &[("selected", &(channel::name(*selected)).to_string())],
            )
            .to_string()
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
