//! Deferred GUI notices retain data so changing language also updates held notices.
use crate::i18n;
use std::{path::PathBuf, sync::Arc};

#[derive(Debug)]
pub(super) enum Status {
    Detail(String),
    Working,
    Exporting,
    SelectingFile,
    Cancelled,
    Restored,
    ReferenceLoaded,
    Saved(PathBuf),
    SettingsSaved(PathBuf),
    SettingsRestored(PathBuf),
    SettingsFailed(String),
    ResultsExported(PathBuf),
    Autoset { frequency_hz: f64, held: bool },
}

pub(super) enum Rendered<'a> {
    Borrowed(&'a str),
    Formatted(Arc<str>),
}

impl AsRef<str> for Rendered<'_> {
    fn as_ref(&self) -> &str {
        match self {
            Self::Borrowed(s) => s,
            Self::Formatted(s) => s,
        }
    }
}

impl From<String> for Status {
    fn from(detail: String) -> Self {
        Self::Detail(detail)
    }
}

impl From<&str> for Status {
    fn from(detail: &str) -> Self {
        Self::Detail(detail.into())
    }
}

impl Status {
    pub(super) fn render(&self) -> Rendered<'_> {
        use Rendered::{Borrowed, Formatted};
        match self {
            Self::Detail(s) => Borrowed(s),
            Self::Working => Borrowed(i18n::text("common.working")),
            Self::Exporting => Borrowed(i18n::text("common.exporting_results")),
            Self::SelectingFile => Borrowed(i18n::text("common.selecting_file")),
            Self::Cancelled => Borrowed(i18n::text("common.file_selection_cancelled")),
            Self::Restored => Borrowed(i18n::text("common.settings_restored_input_stopped")),
            Self::ReferenceLoaded => Borrowed(i18n::text(
                "common.reference_loaded_captured_input_conditions_preserved",
            )),
            Self::Saved(path) => Formatted(i18n::format(
                "common.saved",
                &[("display", &path.display().to_string())],
            )),
            Self::SettingsSaved(path) => Formatted(i18n::format(
                "common.settings_saved",
                &[("path", &path.display().to_string())],
            )),
            Self::SettingsRestored(path) => Formatted(i18n::format(
                "common.settings_restored",
                &[("path", &path.display().to_string())],
            )),
            Self::SettingsFailed(detail) => Formatted(i18n::format(
                "common.settings_failed",
                &[("detail", detail)],
            )),
            Self::ResultsExported(path) => Formatted(i18n::format(
                "common.results_exported",
                &[("path", &path.display().to_string())],
            )),
            Self::Autoset {
                frequency_hz,
                held: false,
            } => Formatted(i18n::format(
                "oscilloscope.autoset_frequency",
                &[("frequency", &format!("{frequency_hz:.3}"))],
            )),
            Self::Autoset {
                frequency_hz,
                held: true,
            } => Formatted(i18n::format(
                "oscilloscope.autoset_held",
                &[("frequency", &format!("{frequency_hz:.3}"))],
            )),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn held_notices_keep_their_arguments_and_reuse_the_localized_message() {
        let ctx = eframe::egui::Context::default();
        i18n::set_locale(&ctx, "en-US");
        let notice = Status::SettingsSaved(PathBuf::from("capture α.json"));
        let Rendered::Formatted(first) = notice.render() else {
            panic!("dynamic notice")
        };
        let Rendered::Formatted(second) = notice.render() else {
            panic!("dynamic notice")
        };
        assert!(Arc::ptr_eq(&first, &second));
        assert_eq!(first.as_ref(), "Settings saved: capture α.json");
        // Resolve the selected catalog without losing the held path or old text.
        i18n::set_locale(&ctx, "ja");
        let Rendered::Formatted(after) = notice.render() else {
            panic!("dynamic notice")
        };
        assert_eq!(
            after,
            i18n::format("common.settings_saved", &[("path", "capture α.json")])
        );
        assert!(!Arc::ptr_eq(&after, &first));
        assert_eq!(first.as_ref(), "Settings saved: capture α.json");
        i18n::set_locale(&ctx, "en-US");
        assert_eq!(
            Status::Autoset {
                frequency_hz: 750.1254,
                held: true
            }
            .render()
            .as_ref(),
            "Held capture amplitude fitted; time/trigger apply on next Start (750.125 Hz)"
        );
        let detail = Status::Detail("CoreAudio: original external detail".into());
        assert_eq!(
            detail.render().as_ref(),
            "CoreAudio: original external detail"
        );
        i18n::set_locale(&ctx, "en-US");
    }
}
