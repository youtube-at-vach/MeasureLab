//! Localized names belong to the desktop boundary; core names and serialized values stay stable.
use crate::i18n;

pub(super) trait DisplayName {
    fn display_name(&self) -> &'static str;
}

impl DisplayName for crate::presentation::InstrumentId {
    fn display_name(&self) -> &'static str {
        match self {
            Self::Scope => i18n::text("shell.instrument_names.scope"),
            Self::Spectrum => i18n::text("shell.instrument_names.spectrum"),
            Self::Spectrogram => i18n::text("shell.instrument_names.spectrogram"),
            Self::Xy => i18n::text("shell.instrument_names.xy"),
            Self::Lockin => i18n::text("shell.instrument_names.lockin"),
            Self::Comparison => i18n::text("shell.instrument_names.comparison"),
            Self::Generator => i18n::text("shell.instrument_names.generator"),
        }
    }
}

impl DisplayName for crate::presentation::Layout {
    fn display_name(&self) -> &'static str {
        match self {
            Self::Columns => i18n::text("shell.layout_names.columns"),
            Self::Rows => i18n::text("shell.layout_names.rows"),
            Self::Grid => i18n::text("shell.layout_names.grid"),
            Self::Tabs => i18n::text("shell.layout_names.tabs"),
        }
    }
}

impl DisplayName for crate::spectrum::Window {
    fn display_name(&self) -> &'static str {
        match self {
            Self::Rectangular => i18n::text("common.window_names.rectangular"),
            Self::Hann => i18n::text("common.window_names.hann"),
            Self::BlackmanHarris => i18n::text("common.window_names.blackman_harris"),
        }
    }
}

impl DisplayName for crate::spectrum::Precision {
    fn display_name(&self) -> &'static str {
        match self {
            Self::F64 => i18n::text("common.precision.f64"),
            Self::F32 => i18n::text("common.precision.f32"),
        }
    }
}

impl DisplayName for crate::spectrum::Quantity {
    fn display_name(&self) -> &'static str {
        match self {
            Self::Amplitude => i18n::text("spectrum.quantity.amplitude"),
            Self::Psd => i18n::text("spectrum.quantity.psd"),
            Self::Esd => i18n::text("spectrum.quantity.esd"),
        }
    }
}

impl DisplayName for crate::spectrogram::ColorMap {
    fn display_name(&self) -> &'static str {
        match self {
            Self::Blue => i18n::text("spectrogram.color_maps.blue"),
            Self::Heat => i18n::text("spectrogram.color_maps.heat"),
            Self::Grayscale => i18n::text("spectrogram.color_maps.grayscale"),
            Self::Turbo => i18n::text("spectrogram.color_maps.turbo"),
            Self::Viridis => i18n::text("spectrogram.color_maps.viridis"),
            Self::Inferno => i18n::text("spectrogram.color_maps.inferno"),
            Self::Magma => i18n::text("spectrogram.color_maps.magma"),
            Self::Hot => i18n::text("spectrogram.color_maps.hot"),
            Self::Copper => i18n::text("spectrogram.color_maps.copper"),
        }
    }
}

impl DisplayName for crate::stft::Overlap {
    fn display_name(&self) -> &'static str {
        match self {
            Self::Half => i18n::text("spectrogram.overlap.half"),
            Self::ThreeQuarters => i18n::text("spectrogram.overlap.three_quarters"),
            Self::SevenEighths => i18n::text("spectrogram.overlap.seven_eighths"),
        }
    }
}

impl DisplayName for crate::generator::Waveform {
    fn display_name(&self) -> &'static str {
        match self {
            Self::Sine => i18n::text("generator.waveform_names.sine"),
            Self::Square => i18n::text("generator.waveform_names.square"),
            Self::Triangle => i18n::text("generator.waveform_names.triangle"),
            Self::Noise => i18n::text("generator.waveform_names.noise"),
        }
    }
}

pub(super) trait InstrumentText {
    fn display_purpose(self) -> &'static str;
    fn display_group(self) -> &'static str;
}
impl InstrumentText for crate::presentation::InstrumentId {
    fn display_purpose(self) -> &'static str {
        match self {
            Self::Scope => i18n::text("shell.purpose.waveform_over_time"),
            Self::Spectrum => i18n::text("shell.purpose.frequency_levels_and_power"),
            Self::Spectrogram => i18n::text("shell.purpose.frequency_changes_over_time"),
            Self::Xy => i18n::text("shell.purpose.two_channel_x_y_relationship"),
            Self::Lockin => i18n::text("shell.purpose.tone_amplitude_and_phase_vs_ref"),
            Self::Comparison => i18n::text("shell.purpose.ref_sig_gain_phase_and_delay"),
            Self::Generator => i18n::text("shell.purpose.generate_signals_on_output_channels"),
        }
    }
    fn display_group(self) -> &'static str {
        match self {
            Self::Scope | Self::Spectrum | Self::Spectrogram | Self::Xy => {
                i18n::text("shell.group.monitor")
            }
            Self::Lockin | Self::Comparison => i18n::text("shell.group.analysis"),
            Self::Generator => i18n::text("shell.group.signal"),
        }
    }
}

pub(super) fn output_target(target: &crate::output::Target) -> &str {
    match target {
        crate::output::Target::Internal => i18n::text("io.internal_loopback"),
        crate::output::Target::Audio { device_name, .. } => device_name,
    }
}

#[cfg(feature = "qa")]
impl DisplayName for crate::demo::Waveform {
    fn display_name(&self) -> &'static str {
        match self {
            Self::Sine => i18n::text("generator.waveform_names.sine"),
            Self::Harmonics => i18n::text("io.demo_harmonics"),
            Self::Square => i18n::text("io.demo_square"),
        }
    }
}

impl DisplayName for crate::comparison::State {
    fn display_name(&self) -> &'static str {
        match self {
            Self::Disabled => i18n::text("comparison.state_names.disabled"),
            Self::Unavailable => i18n::text("comparison.state_names.unavailable"),
            Self::Filling => i18n::text("comparison.state_names.filling"),
            Self::Averaging => i18n::text("comparison.state_names.averaging"),
            Self::Valid => i18n::text("comparison.state_names.valid"),
            Self::Missing => i18n::text("comparison.state_names.missing"),
            Self::NonFinite => i18n::text("comparison.state_names.non_finite"),
        }
    }
}

impl DisplayName for crate::comparison::BinState {
    fn display_name(&self) -> &'static str {
        match self {
            Self::ReferenceLost => i18n::text("comparison.bin_states.reference_lost"),
            Self::ResponseLost => i18n::text("comparison.bin_states.response_lost"),
            Self::Averaging => i18n::text("comparison.bin_states.averaging"),
            Self::Incoherent => i18n::text("comparison.bin_states.incoherent"),
            Self::Valid => i18n::text("comparison.bin_states.valid"),
        }
    }
}

impl DisplayName for crate::measurement::SpectrumMode {
    fn display_name(&self) -> &'static str {
        match self {
            Self::Live => i18n::text("spectrum.mode_names.live"),
            Self::Continuous => i18n::text("spectrum.mode_names.continuous"),
            Self::Latest => i18n::text("spectrum.mode_names.latest"),
        }
    }
}

impl DisplayName for crate::acquisition::Mode {
    fn display_name(&self) -> &'static str {
        match self {
            Self::Auto => i18n::text("oscilloscope.mode_names.auto"),
            Self::Normal => i18n::text("oscilloscope.mode_names.normal"),
            Self::Single => i18n::text("oscilloscope.mode_names.single"),
        }
    }
}

impl DisplayName for crate::signal::Edge {
    fn display_name(&self) -> &'static str {
        match self {
            Self::Free => i18n::text("oscilloscope.edge_names.free"),
            Self::Rising => i18n::text("oscilloscope.edge_names.rising"),
            Self::Falling => i18n::text("oscilloscope.edge_names.falling"),
        }
    }
}

impl DisplayName for crate::export::State {
    fn display_name(&self) -> &'static str {
        match self {
            Self::Waiting => i18n::text("common.result_states.waiting"),
            Self::Unavailable => i18n::text("common.result_states.unavailable"),
            Self::NonFinite => i18n::text("common.result_states.non_finite"),
            Self::Partial => i18n::text("common.result_states.partial"),
            Self::Valid => i18n::text("common.result_states.valid"),
        }
    }
}

impl DisplayName for crate::lockin::State {
    fn display_name(&self) -> &'static str {
        match self {
            Self::Disabled => i18n::text("lockin.state_names.disabled"),
            Self::Unavailable => i18n::text("lockin.state_names.unavailable"),
            Self::Settling => i18n::text("lockin.state_names.settling"),
            Self::Valid => i18n::text("lockin.state_names.valid"),
            Self::ReferenceLost => i18n::text("lockin.state_names.reference_lost"),
            Self::ReferenceUnstable => i18n::text("lockin.state_names.reference_unstable"),
            Self::Missing => i18n::text("lockin.state_names.missing"),
            Self::NonFinite => i18n::text("lockin.state_names.non_finite"),
        }
    }
}

pub(super) fn generator_error(error: crate::generator::Error) -> String {
    use crate::generator::Error;
    match error {
        Error::SignalCount => i18n::text("generator.error_reason.signal_count").into(),
        Error::SignalIdentity => i18n::text("generator.error_reason.signal_identity").into(),
        Error::SampleRate => i18n::text("generator.error_reason.sample_rate").into(),
        Error::ChannelCount => i18n::text("generator.error_reason.channel_count").into(),
        Error::DuplicateRouting => i18n::text("generator.error_reason.duplicate_routing").into(),
        Error::RoutingWhileActive => {
            i18n::text("generator.error_reason.routing_while_active").into()
        }
        Error::NoEnabledSignals => i18n::text("generator.error_reason.no_enabled_signals").into(),
        Error::AlreadyActive => i18n::text("generator.error_reason.already_active").into(),
        Error::Stopping => i18n::text("generator.error_reason.stopping").into(),
        Error::Revision => i18n::text("generator.error_reason.revision").into(),
        Error::CounterExhausted => i18n::text("generator.error_reason.counter_exhausted").into(),
        Error::NonFiniteOutput => i18n::text("generator.error_reason.non_finite_output").into(),
        Error::OutputRange => i18n::text("generator.error_reason.output_range").into(),
        Error::ProducerSuspended => i18n::text("generator.error_reason.producer_suspended").into(),
        Error::OutputStream => i18n::text("generator.error_reason.output_stream").into(),
        Error::CallbackStalled => i18n::text("generator.error_reason.callback_stalled").into(),
        Error::Waveform(index) => i18n::format(
            "generator.error_reason.waveform",
            &[("position", &(index + 1).to_string())],
        )
        .to_string(),
        Error::Frequency(index) => i18n::format(
            "generator.error_reason.frequency",
            &[("position", &(index + 1).to_string())],
        )
        .to_string(),
        Error::Amplitude(index) => i18n::format(
            "generator.error_reason.amplitude",
            &[("position", &(index + 1).to_string())],
        )
        .to_string(),
        Error::Phase(index) => i18n::format(
            "generator.error_reason.phase",
            &[("position", &(index + 1).to_string())],
        )
        .to_string(),
        Error::Routing(index) => i18n::format(
            "generator.error_reason.routing",
            &[("position", &(index + 1).to_string())],
        )
        .to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        generator,
        presentation::{InstrumentId, Layout},
        spectrogram::ColorMap,
        spectrum::{Precision, Quantity, Window},
        stft::Overlap,
    };

    #[test]
    fn localized_enum_names_preserve_english_and_the_core_identifiers() {
        let ctx = eframe::egui::Context::default();
        i18n::set_locale(&ctx, "en-US");
        let core_instruments = InstrumentId::ALL.map(|instrument| {
            (
                serde_json::to_string(&instrument).unwrap(),
                instrument.name(),
                instrument.purpose(),
                instrument.group(),
            )
        });
        for instrument in InstrumentId::ALL {
            assert_eq!(instrument.display_name(), instrument.name());
            assert_eq!(instrument.display_purpose(), instrument.purpose());
            assert_eq!(instrument.display_group(), instrument.group());
        }
        for layout in Layout::ALL {
            assert_eq!(layout.display_name(), layout.name());
        }
        for window in [Window::Rectangular, Window::Hann, Window::BlackmanHarris] {
            assert_eq!(window.display_name(), window.name());
        }
        for precision in [Precision::F32, Precision::F64] {
            assert_eq!(precision.display_name(), precision.name());
        }
        for quantity in [Quantity::Amplitude, Quantity::Psd, Quantity::Esd] {
            assert_eq!(quantity.display_name(), quantity.name());
        }
        for map in ColorMap::ALL {
            assert_eq!(map.display_name(), map.name());
        }
        for overlap in Overlap::ALL {
            assert_eq!(overlap.display_name(), overlap.name());
        }
        for waveform in generator::Waveform::ALL {
            assert_eq!(waveform.display_name(), waveform.label());
        }
        assert_eq!(
            generator_error(generator::Error::Frequency(15)),
            generator::Error::Frequency(15).to_string()
        );
        assert_eq!(
            generator_error(generator::Error::CallbackStalled),
            generator::Error::CallbackStalled.to_string()
        );
        for locale in i18n::Locale::ALL {
            i18n::set_locale(&ctx, locale.id());
            assert_eq!(
                InstrumentId::ALL.map(|instrument| {
                    (
                        serde_json::to_string(&instrument).unwrap(),
                        instrument.name(),
                        instrument.purpose(),
                        instrument.group(),
                    )
                }),
                core_instruments
            );
        }
        i18n::set_locale(&ctx, "en-US");
    }
}
