use crate::{
    audio::{AudioWorker, Capture, Command, DeviceInfo, Event},
    demo::{Demo, Waveform},
    gpu::{COLORS, PlotId, Segment, TraceCallback, TraceRenderer},
    signal::{Edge, History, Line, Measurement, Trigger, build_lines},
    spectrum::{self, Analyzer, FFT_SIZES, FrequencyScale, Settings, View, Window},
    stft::{self, RowInfo},
};
use eframe::{
    egui::{self, Color32, RichText, Stroke, pos2, vec2},
    egui_wgpu,
};
use std::{
    sync::{Arc, atomic::Ordering},
    time::{Duration, Instant},
};

const GREEN: Color32 = Color32::from_rgb(56, 242, 173);
const BLUE: Color32 = Color32::from_rgb(87, 166, 255);
const YELLOW: Color32 = Color32::from_rgb(255, 211, 66);
const HOLD: Color32 = Color32::from_rgb(179, 135, 65);
const MUTED: Color32 = Color32::from_rgb(128, 147, 161);
const BORDER: Color32 = Color32::from_rgb(48, 70, 82);

#[derive(Clone, Copy, PartialEq, Eq)]
enum Source {
    Live,
    Demo,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Workspace {
    Both,
    Scope,
    Spectrum,
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

#[derive(Clone, Copy, PartialEq, Eq)]
enum SettingsSection {
    Input,
    Scope,
    Spectrum,
    Workspace,
}

impl SettingsSection {
    const ALL: [Self; 4] = [Self::Input, Self::Scope, Self::Spectrum, Self::Workspace];

    fn title(self) -> &'static str {
        match self {
            Self::Input => "Input source",
            Self::Scope => "Oscilloscope",
            Self::Spectrum => "Spectrum analyzer",
            Self::Workspace => "Workspace & help",
        }
    }

    fn color(self) -> Color32 {
        match self {
            Self::Input | Self::Workspace => Color32::from_rgb(192, 207, 217),
            Self::Scope => GREEN,
            Self::Spectrum => YELLOW,
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
    workspace: Workspace,
    plot_layout: PlotLayout,
    sidebar: Sidebar,
    demo: Demo,
    demo_running: bool,
    demo_clock: Instant,
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
    spectrum_segments: Arc<Vec<Segment>>,
    spectrum_revision: u64,
    last_spectrum: Instant,
    fft_ms: f64,
    spectrum_build_ms: f64,
    stft: stft::Worker,
    last_stft: Option<RowInfo>,
    audio: AudioWorker,
    devices: Vec<DeviceInfo>,
    selected: usize,
    capture: Option<Capture>,
    busy: bool,
    error: Option<String>,
    history: History,
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
            style.spacing.item_spacing = vec2(10.0, 10.0);
            style.spacing.button_padding = vec2(12.0, 7.0);
        });
        let mut app = Self {
            source: if demo || smoke {
                Source::Demo
            } else {
                Source::Live
            },
            workspace: Workspace::Both,
            plot_layout: PlotLayout::Auto,
            sidebar: Sidebar::default(),
            demo: Demo::default(),
            demo_running: demo && !smoke,
            demo_clock: Instant::now(),
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
            spectrum_segments: Arc::new(Vec::with_capacity(8192)),
            spectrum_revision: 0,
            last_spectrum: Instant::now() - Duration::from_secs(1),
            fft_ms: 0.0,
            spectrum_build_ms: 0.0,
            stft: stft::Worker::new(),
            last_stft: None,
            audio: AudioWorker::new(),
            devices: Vec::new(),
            selected: 0,
            capture: None,
            busy: true,
            error: None,
            history: History::new(96_000),
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
            profile: crate::qa::Profile::from_env(),
        };
        if demo || smoke {
            app.channels = 2;
            app.format = if smoke { "QA fixture" } else { "Internal demo" }.into();
            app.reset_analysis();
            app.demo.append_with(
                &mut app.history,
                16384,
                app.sample_rate,
                |sequence, samples| {
                    app.stft.submit(sequence, samples);
                },
            );
            app.stft.flush();
        }
        #[cfg(feature = "qa")]
        if smoke {
            // Render every inspector with the same deterministic signal fixture.
            match std::env::var("MEASURELAB_UI_SMOKE_SETTINGS").as_deref() {
                Ok("scope") => app.sidebar.section = Some(SettingsSection::Scope),
                Ok("spectrum") => app.sidebar.section = Some(SettingsSection::Spectrum),
                Ok("workspace") => app.sidebar.section = Some(SettingsSection::Workspace),
                Ok("collapsed") => app.sidebar.section = None,
                Ok("hidden") => app.sidebar.visible = false,
                _ => {}
            }
        }
        Ok(app)
    }

    fn running(&self) -> bool {
        self.capture.is_some() || self.demo_running
    }

    fn reset_analysis(&mut self) {
        self.spectrum_channel = self.spectrum_channel.min(self.channels.max(1) as usize - 1);
        self.analyzer = Analyzer::new(self.spectrum_settings, self.sample_rate);
        self.spectrum_dirty = true;
        self.last_spectrum = Instant::now() - Duration::from_secs(1);
        self.last_stft = None;
        if self.running() {
            self.stft
                .configure(stft::Config {
                    sample_rate: self.sample_rate,
                    channels: self.channels as usize,
                    channel: self.spectrum_channel,
                    size: self.spectrum_settings.size,
                    hop: self.spectrum_settings.size / 4,
                    window: self.spectrum_settings.window,
                    remove_dc: self.spectrum_settings.remove_dc,
                })
                .expect("validated acquisition and FFT settings");
        } else {
            self.stft.pause();
        }
    }

    fn poll_demo(&mut self) {
        let now = Instant::now();
        let elapsed = now.duration_since(self.demo_clock).as_secs_f64();
        self.demo_clock = now;
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
    }

    fn start(&mut self) {
        if self.source == Source::Demo {
            self.sample_rate = 48000;
            self.channels = 2;
            self.format = "Internal demo".into();
            self.history = History::new(96000);
            self.demo_fraction = 0.0;
            self.demo_clock = Instant::now();
            self.demo_running = true;
            self.dropped = 0;
            self.error = None;
            self.dirty = true;
            self.reset_analysis();
            return;
        }
        if self.devices.is_empty() || self.busy {
            return;
        }
        self.error = None;
        self.busy = true;
        self.audio.send(Command::Start(self.selected));
    }

    fn stop(&mut self) {
        self.stft.pause();
        self.last_spectrum = Instant::now() - Duration::from_secs(1);
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
                        }
                        if std::env::var("MEASURELAB_PROFILE_SETTINGS").as_deref() == Ok("spectrum")
                        {
                            self.sidebar.section = Some(SettingsSection::Spectrum);
                        }
                    }
                    self.dirty = true;
                    self.reset_analysis();
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
                    .id_salt(("settings", section.title()))
                    .open(Some(open))
                    .show_unindented(ui, |ui| {
                        ui.spacing_mut().slider_width = (ui.available_width() - 140.0).max(75.0);
                        ui.add_space(4.0);
                        match section {
                            SettingsSection::Input => self.input_controls(ui),
                            SettingsSection::Scope => self.scope_controls(ui),
                            SettingsSection::Spectrum => self.spectrum_controls(ui),
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
                self.format.clear();
                self.expected_sequence = None;
                self.dropped = 0;
            }
            self.dirty = true;
            self.error = None;
            self.reset_analysis();
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
            if before
                != (
                    self.demo.waveform,
                    self.demo.frequency,
                    self.demo.amplitude,
                    self.demo.noise,
                )
            {
                self.history.clear();
                self.demo.append(
                    &mut self.history,
                    self.spectrum_settings.size,
                    self.sample_rate,
                );
                self.dirty = true;
                self.reset_analysis();
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
                .fold(0.0_f32, f32::max);
            self.fs_per_div = (peak / 3.5).clamp(0.001, 0.5);
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
        if before != (self.spectrum_settings, self.spectrum_channel) {
            self.reset_analysis();
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
                self.spectrum_settings.size as f32 / self.sample_rate as f32 * 1000.0
            ))
            .small()
            .color(MUTED),
        );
    }

    fn workspace_controls(&mut self, ui: &mut egui::Ui) {
        setting_label(ui, "TWO-INSTRUMENT LAYOUT");
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
            .inner_margin(10.0)
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    ui.label(RichText::new("Oscilloscope").size(18.0).strong());
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
        if self.last_spectrum.elapsed() >= Duration::from_secs_f64(1.0 / 30.0) {
            let started = Instant::now();
            if self.analyzer.update(&self.history, self.spectrum_channel) {
                self.fft_ms = started.elapsed().as_secs_f64() * 1000.0;
                self.spectrum_dirty = true;
                self.last_spectrum = Instant::now();
            }
        }
        egui::Frame::new()
            .fill(Color32::from_rgb(17, 27, 35))
            .stroke(Stroke::new(1.0, Color32::from_rgb(48, 70, 82)))
            .inner_margin(10.0)
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    ui.label(RichText::new("Spectrum Analyzer").size(18.0).strong());
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
                            RichText::new(format!("CH {} · dBFS", self.spectrum_channel + 1))
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
        let (outer, response) = ui.allocate_exact_size(plot_size(ui), egui::Sense::hover());
        let rect =
            egui::Rect::from_min_max(outer.min + vec2(38.0, 14.0), outer.max - vec2(18.0, 28.0));
        let painter = ui.painter();
        painter.rect_filled(rect, 0.0, Color32::from_rgb(7, 14, 19));
        for db in (view.floor_db as i32..=0).filter(|db| db % 20 == 0) {
            let y = rect.top()
                + (view.ceiling_db - db as f32) / (view.ceiling_db - view.floor_db) * rect.height();
            painter.line_segment(
                [pos2(rect.left(), y), pos2(rect.right(), y)],
                Stroke::new(1.0, Color32::from_rgb(24, 39, 47)),
            );
            painter.text(
                pos2(rect.left() - 7.0, y),
                egui::Align2::RIGHT_CENTER,
                db.to_string(),
                egui::FontId::monospace(10.0),
                MUTED,
            );
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
                    pos2(x, rect.bottom() + 10.0),
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
            spectrum::build_lines(
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
        ui.horizontal(|ui| {
            ui.label(RichText::new("Amplitude / dBFS").small().color(MUTED));
            if self.show_hold {
                ui.label(RichText::new("Peak hold").small().color(HOLD));
            }
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                ui.label(RichText::new("Frequency / Hz").small().color(MUTED));
            });
        });
    }

    fn plot(&mut self, ui: &mut egui::Ui) {
        let (outer, response) =
            ui.allocate_exact_size(plot_size(ui), egui::Sense::click_and_drag());
        let rect =
            egui::Rect::from_min_max(outer.min + vec2(44.0, 14.0), outer.max - vec2(18.0, 28.0));
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
                pos2(px, rect.bottom() + 10.0),
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
            painter.text(
                pos2(rect.left() - 8.0, py),
                egui::Align2::RIGHT_CENTER,
                format!("{:.3}", (4.0 - y as f32) * self.fs_per_div),
                egui::FontId::monospace(10.0),
                MUTED,
            );
        }
        let ppp = ui.ctx().pixels_per_point();
        let pixels = (rect.width() * ppp).ceil().max(1.0) as usize;
        self.dirty |= pixels != self.pixels;
        self.pixels = pixels;
        if self.dirty {
            let started = Instant::now();
            let count = (self.ms_per_div * 0.01 * self.sample_rate as f32)
                .round()
                .max(2.0) as usize;
            let sweep = self.history.sweep(count, self.trigger);
            let ready = self.history.len() >= count;
            self.triggered = ready && sweep.triggered;
            self.measurements = build_lines(
                &self.history,
                if ready { sweep.range } else { 0..0 },
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
                Stroke::new(2.0, GREEN),
            );
            painter.text(
                pos2(tx, rect.top() + 17.0),
                egui::Align2::CENTER_TOP,
                "T",
                egui::FontId::monospace(11.0),
                GREEN,
            );
            let ty = rect.center().y - self.trigger.level / (self.fs_per_div * 8.0) * rect.height();
            if rect.y_range().contains(ty) {
                painter.line_segment(
                    [pos2(rect.right() - 12.0, ty), pos2(rect.right(), ty)],
                    Stroke::new(2.0, GREEN),
                );
            }
        }
        if self.segments.is_empty()
            && self.history.len()
                < (self.ms_per_div * 0.01 * self.sample_rate as f32)
                    .round()
                    .max(2.0) as usize
        {
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
            let time = ((position.x - rect.left()) / rect.width() - 0.2) * self.ms_per_div * 10.0;
            let amplitude = (rect.center().y - position.y) / rect.height() * self.fs_per_div * 8.0;
            painter.text(
                rect.right_top() + vec2(-10.0, 10.0),
                egui::Align2::RIGHT_TOP,
                format!("{time:+.3} ms  {amplitude:+.4} FS"),
                egui::FontId::monospace(11.0),
                MUTED,
            );
        }
        ui.horizontal(|ui| {
            ui.label(RichText::new("FS").small().color(MUTED));
            ui.label(RichText::new("10 × 8 divisions").small().color(MUTED));
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                ui.label(RichText::new("time / ms").small().color(MUTED));
            });
        });
    }
}

impl eframe::App for ScopeApp {
    fn ui(&mut self, ui: &mut egui::Ui, _: &mut eframe::Frame) {
        let ctx = ui.ctx().clone();
        let now = Instant::now();
        let elapsed = now.duration_since(self.last_frame).as_secs_f64();
        self.last_frame = now;
        if elapsed > 0.0 && elapsed < 0.2 {
            self.fps = self.fps * 0.9 + 0.1 / elapsed;
        }
        self.poll_audio();
        self.poll_demo();
        self.stft.drain(|row| self.last_stft = Some(row.info));
        #[cfg(feature = "qa")]
        {
            let running = self.running();
            if let Some(profile) = &mut self.profile {
                profile.record(elapsed, running);
                if profile.finished() {
                    profile.report(self.dropped);
                    println!(
                        "STFT profile: {} Hz, {} ch, CH {}, rows {}, input dropped {}, result dropped {}, worker CPU {:.3} ms total",
                        self.sample_rate,
                        self.channels,
                        self.spectrum_channel + 1,
                        self.stft.metrics.produced.load(Ordering::Relaxed),
                        self.stft.metrics.input_dropped.load(Ordering::Relaxed),
                        self.stft.metrics.result_dropped.load(Ordering::Relaxed),
                        self.stft.metrics.processing_nanos.load(Ordering::Relaxed) as f64 / 1e6
                    );
                    self.profile = None;
                    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                }
                ctx.request_repaint_after(Duration::from_millis(8));
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
            ui.add_space(4.0);
            ui.horizontal(|ui| {
                let mut title = egui::text::LayoutJob::default();
                RichText::new("MeasureLab")
                    .size(26.0)
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
                            self.segments.len() + self.spectrum_segments.len()
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
        egui::CentralPanel::default().show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.selectable_value(&mut self.workspace, Workspace::Both, "Scope + Spectrum");
                ui.selectable_value(&mut self.workspace, Workspace::Scope, "Oscilloscope");
                ui.selectable_value(&mut self.workspace, Workspace::Spectrum, "Spectrum");
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
            match self.workspace {
                Workspace::Scope => self.scope_panel(ui),
                Workspace::Spectrum => self.spectrum_panel(ui),
                Workspace::Both if self.plot_layout.columns(available.x) => {
                    ui.horizontal_top(|ui| {
                        let size = vec2((available.x - 10.0) * 0.5, available.y);
                        ui.allocate_ui_with_layout(
                            size,
                            egui::Layout::top_down(egui::Align::Min),
                            |ui| self.scope_panel(ui),
                        );
                        ui.allocate_ui_with_layout(
                            size,
                            egui::Layout::top_down(egui::Align::Min),
                            |ui| self.spectrum_panel(ui),
                        );
                    });
                }
                Workspace::Both => {
                    let size = vec2(available.x, (available.y - 10.0) * 0.5);
                    ui.allocate_ui_with_layout(
                        size,
                        egui::Layout::top_down(egui::Align::Min),
                        |ui| self.scope_panel(ui),
                    );
                    ui.allocate_ui_with_layout(
                        size,
                        egui::Layout::top_down(egui::Align::Min),
                        |ui| self.spectrum_panel(ui),
                    );
                }
            }
        });
        if self.running() || self.busy {
            ctx.request_repaint_after(Duration::from_millis(8));
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

fn plot_size(ui: &egui::Ui) -> egui::Vec2 {
    // Reserve the same horizontal footer row and spacing for both plots.
    let footer_height = ui.spacing().interact_size.y + ui.spacing().item_spacing.y;
    vec2(
        ui.available_width(),
        (ui.available_height() - footer_height).max(120.0),
    )
}

fn setting_label(ui: &mut egui::Ui, text: &str) {
    ui.label(RichText::new(text).small().color(MUTED));
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
        format!("{}k", hz / 1000.0)
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
