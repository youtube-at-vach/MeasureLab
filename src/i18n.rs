//! Desktop display boundary. No locale state enters audio or measurement workers.
//!
//! Fixed text is borrowed from a finite, pre-resolved catalog. Dynamic messages
//! retain only the last arguments/result per catalog key on the GUI thread.
use eframe::egui;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    borrow::Cow,
    cell::RefCell,
    collections::{BTreeMap, BTreeSet, HashMap},
    sync::{Arc, LazyLock},
};

mod embedded {
    rust_i18n::i18n!("locales", fallback = "en-US");
}

const STORAGE_KEY: &str = "measurelab.locale";

/// Supported identifiers are independent of the progress of each translation.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Locale {
    #[default]
    English,
    Japanese,
    French,
    German,
    Spanish,
    Portuguese,
    Russian,
    Chinese,
    Korean,
}

impl Locale {
    pub const ALL: [Self; 9] = [
        Self::English,
        Self::Japanese,
        Self::French,
        Self::German,
        Self::Spanish,
        Self::Portuguese,
        Self::Russian,
        Self::Chinese,
        Self::Korean,
    ];

    pub const fn id(self) -> &'static str {
        match self {
            Self::English => "en-US",
            Self::Japanese => "ja",
            Self::French => "fr",
            Self::German => "de",
            Self::Spanish => "es",
            Self::Portuguese => "pt",
            Self::Russian => "ru",
            Self::Chinese => "zh",
            Self::Korean => "ko",
        }
    }

    /// Native language names are stable proper names, not translated messages.
    pub const fn native_name(self) -> &'static str {
        match self {
            Self::English => "English",
            Self::Japanese => "日本語",
            Self::French => "Français",
            Self::German => "Deutsch",
            Self::Spanish => "Español",
            Self::Portuguese => "Português",
            Self::Russian => "Русский",
            Self::Chinese => "中文",
            Self::Korean => "한국어",
        }
    }

    pub fn from_id(id: &str) -> Self {
        Self::ALL
            .into_iter()
            .find(|locale| locale.id() == id)
            .unwrap_or_default()
    }
}

#[derive(Deserialize)]
struct Record {
    source: String,
    source_hash: String,
    translation_hash: String,
}

#[derive(Deserialize)]
struct Metadata {
    version: u32,
    translations: BTreeMap<String, BTreeMap<String, Record>>,
}

type Texts = HashMap<Cow<'static, str>, Cow<'static, str>>;

struct Catalog {
    // Every table contains English fallback entries, so a frame needs one lookup.
    resolved: [Texts; 9],
}

fn digest(text: &str) -> String {
    format!("{:x}", Sha256::digest(text.as_bytes()))
}

fn variables(mut text: &str) -> Option<BTreeSet<&str>> {
    let mut names = BTreeSet::new();
    while let Some((_, tail)) = text.split_once("%{") {
        let (name, rest) = tail.split_once('}')?;
        let mut chars = name.chars();
        if !chars.next().is_some_and(|c| c.is_ascii_lowercase())
            || !chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
        {
            return None;
        }
        names.insert(name);
        text = rest;
    }
    Some(names)
}

impl Catalog {
    fn new(backend: &'static dyn rust_i18n::Backend, metadata: &str) -> Self {
        let english: Texts = backend
            .messages_for_locale("en-US")
            .unwrap_or_default()
            .into_iter()
            .collect();
        // Invalid/missing metadata must never make an unreviewed translation live.
        let metadata = serde_json::from_str::<Metadata>(metadata)
            .ok()
            .filter(|m| m.version == 1);
        let resolved = std::array::from_fn(|index| {
            let locale = Locale::ALL[index];
            let mut texts = english.clone();
            if locale == Locale::English {
                return texts;
            }
            for (key, translated) in backend.messages_for_locale(locale.id()).unwrap_or_default() {
                let Some(source) = english.get(&key) else {
                    continue;
                };
                let record = metadata
                    .as_ref()
                    .and_then(|m| m.translations.get(locale.id()))
                    .and_then(|r| r.get(key.as_ref()));
                let current = record.is_some_and(|record| {
                    !translated.trim().is_empty()
                        && record.source == *source
                        && record.source_hash == digest(source)
                        && record.translation_hash == digest(&translated)
                        && variables(source).is_some()
                        && variables(source) == variables(&translated)
                });
                if current {
                    texts.insert(key, translated);
                }
            }
            texts
        });
        Self { resolved }
    }

    fn lookup<'a>(&'a self, locale: Locale, key: &'a str) -> &'a str {
        self.resolved[locale as usize]
            .get(key)
            .map_or(key, |text| text.as_ref())
    }
}

static CATALOG: LazyLock<Catalog> = LazyLock::new(|| {
    Catalog::new(
        embedded::_rust_i18n_backend(),
        include_str!("../i18n/source-hashes.json"),
    )
});

#[derive(Default)]
struct State {
    locale: Locale,
    messages: HashMap<&'static str, Message>,
}

struct Message {
    args: Vec<(&'static str, String)>,
    text: Arc<str>,
}

impl State {
    fn select(&mut self, locale: Locale) -> bool {
        if self.locale == locale {
            return false;
        }
        self.locale = locale;
        self.messages.clear();
        true
    }

    fn format(
        &mut self,
        catalog: &Catalog,
        key: &'static str,
        args: &[(&'static str, &str)],
    ) -> Arc<str> {
        if let Some(cached) = self.messages.get(key)
            && cached.args.len() == args.len()
            && cached
                .args
                .iter()
                .zip(args)
                .all(|((a, b), (c, d))| a == c && b == d)
        {
            return cached.text.clone();
        }
        // Every locale table contains exactly the English keys. Do not admit
        // arbitrary keys to the cache; source checks reject those calls too.
        let Some(template) = catalog.resolved[self.locale as usize].get(key) else {
            return Arc::from(key);
        };
        let names: Vec<_> = args.iter().map(|(name, _)| *name).collect();
        let values: Vec<_> = args.iter().map(|(_, value)| (*value).to_owned()).collect();
        let text: Arc<str> = rust_i18n::replace_patterns(template, &names, &values).into();
        self.messages.insert(
            key,
            Message {
                args: args
                    .iter()
                    .map(|(name, value)| (*name, (*value).to_owned()))
                    .collect(),
                text: text.clone(),
            },
        );
        text
    }
}

thread_local! {
    static STATE: RefCell<State> = RefCell::new(State::default());
}

pub fn locale() -> Locale {
    STATE.with_borrow(|state| state.locale)
}

/// Fixed labels borrow embedded storage and allocate nothing during a frame.
pub fn text(key: &'static str) -> &'static str {
    CATALOG.lookup(locale(), key)
}

/// At most one dynamic result/argument set is retained per defined English key.
/// Pass `result.as_ref()` to egui; a cache hit only clones the Arc.
pub fn format(key: &'static str, args: &[(&'static str, &str)]) -> Arc<str> {
    STATE.with_borrow_mut(|state| state.format(&CATALOG, key, args))
}

pub fn set_locale(ctx: &egui::Context, id: &str) -> bool {
    let selected = Locale::from_id(id);
    if !STATE.with_borrow_mut(|state| state.select(selected)) {
        return false;
    }
    ctx.set_fonts(fonts(selected));
    ctx.request_repaint();
    true
}

/// Restore display preferences only. Does not restore or start input/output.
pub fn initialize(ctx: &egui::Context, storage: Option<&dyn eframe::Storage>) {
    let selected = storage
        .and_then(|s| s.get_string(STORAGE_KEY))
        .map(|id| Locale::from_id(&id))
        .unwrap_or_default();
    STATE.with_borrow_mut(|state| {
        state.select(selected);
    });
    LazyLock::force(&CATALOG);
    ctx.set_fonts(fonts(selected));
}

pub fn save(storage: &mut dyn eframe::Storage) {
    storage.set_string(STORAGE_KEY, locale().id().into());
}

fn fonts(locale: Locale) -> egui::FontDefinitions {
    let mut fonts = egui::FontDefinitions::default();
    let mut cjk =
        egui::FontData::from_static(include_bytes!("../assets/fonts/NotoSansCJK-Regular.ttc"));
    // Regional glyph shapes: JP, KR, simplified Chinese. Other languages use JP.
    cjk.index = match locale {
        Locale::Korean => 1,
        Locale::Chinese => 2,
        _ => 0,
    };
    fonts
        .font_data
        .insert("measurelab-cjk".into(), Arc::new(cjk));
    for family in [egui::FontFamily::Proportional, egui::FontFamily::Monospace] {
        fonts
            .families
            .entry(family)
            .or_default()
            .push("measurelab-cjk".into());
    }
    fonts
}

#[cfg(test)]
mod tests {
    use super::*;

    mod fixture {
        rust_i18n::i18n!("tests/fixtures/i18n/locales", fallback = "en-US");
    }

    fn catalog() -> Catalog {
        Catalog::new(
            fixture::_rust_i18n_backend(),
            include_str!("../tests/fixtures/i18n/source-hashes.json"),
        )
    }

    #[test]
    fn split_yaml_merges_and_only_reviewed_current_translations_are_live() {
        let catalog = catalog();
        assert_eq!(
            catalog.lookup(Locale::Japanese, "common.ready"),
            "QA準備完了"
        );
        assert_eq!(catalog.lookup(Locale::Japanese, "shell.title"), "QA shell");
        for key in [
            "common.stale",
            "common.empty",
            "common.unreviewed",
            "common.tampered",
            "common.variables",
            "common.removed_value",
        ] {
            assert_eq!(
                catalog.lookup(Locale::Japanese, key),
                catalog.lookup(Locale::English, key)
            );
        }
        assert!(!catalog.resolved[Locale::Japanese as usize].contains_key("common.obsolete"));
        for locale in Locale::ALL.into_iter().filter(|l| *l != Locale::Japanese) {
            assert_eq!(catalog.lookup(locale, "common.ready"), "Ready for QA");
        }
        assert_eq!(
            catalog.lookup(Locale::Japanese, "undefined.key"),
            "undefined.key"
        );
    }

    #[test]
    fn malformed_or_unversioned_metadata_falls_back_without_trusting_translations() {
        for metadata in ["", "{}", r#"{"version":2,"translations":{}}"#] {
            let catalog = Catalog::new(fixture::_rust_i18n_backend(), metadata);
            assert_eq!(
                catalog.lookup(Locale::Japanese, "common.ready"),
                "Ready for QA"
            );
        }
        assert_eq!(
            digest("Hello"),
            "185f8db32271fe25f561a6fc938b2e264306ec304eda518007d1764826381969"
        );
    }

    #[test]
    fn variable_validation_and_substitution_preserve_literal_external_details() {
        assert_eq!(
            variables("%{a} %{b} %{a}").unwrap(),
            BTreeSet::from(["a", "b"])
        );
        for invalid in ["%{", "%{}", "%{Name}", "%{a-b}", "%{a %{b}"] {
            assert!(variables(invalid).is_none(), "{invalid}");
        }
        let catalog = catalog();
        let mut state = State::default();
        state.select(Locale::Japanese);
        assert_eq!(
            state
                .format(
                    &catalog,
                    "common.greeting",
                    &[("name", "DUT %{channel}"), ("channel", "2")]
                )
                .as_ref(),
            "DUT %{channel}、入力2"
        );
        state.select(Locale::German);
        assert_eq!(
            state
                .format(
                    &catalog,
                    "common.greeting",
                    &[("name", "DUT"), ("channel", "2")]
                )
                .as_ref(),
            "Hello, DUT; input 2"
        );
    }

    #[test]
    fn fixed_and_dynamic_text_cache_is_bounded_and_invalidated_on_switch() {
        let catalog = catalog();
        let mut state = State::default();
        let first = state.format(
            &catalog,
            "common.greeting",
            &[("name", "DUT"), ("channel", "1")],
        );
        for _ in 0..1000 {
            let cached = state.format(
                &catalog,
                "common.greeting",
                &[("name", "DUT"), ("channel", "1")],
            );
            assert!(Arc::ptr_eq(&first, &cached));
            assert!(std::ptr::eq(
                catalog.lookup(Locale::English, "common.ready"),
                catalog.lookup(Locale::English, "common.ready")
            ));
        }
        for channel in 0..1000 {
            state.format(
                &catalog,
                "common.greeting",
                &[("name", "DUT"), ("channel", &channel.to_string())],
            );
        }
        assert_eq!(state.messages.len(), 1);
        state.format(&catalog, "undefined.key", &[]);
        assert_eq!(state.messages.len(), 1);
        assert!(state.select(Locale::Japanese));
        assert!(state.messages.is_empty());
        assert!(!state.select(Locale::Japanese));
        assert_eq!(
            state
                .format(
                    &catalog,
                    "common.greeting",
                    &[("name", "DUT"), ("channel", "2")]
                )
                .as_ref(),
            "DUT、入力2"
        );
        // Old borrowed/Arc text remains valid across a switch without leaking new storage.
        assert_eq!(first.as_ref(), "Hello, DUT; input 1");
    }

    #[derive(Default)]
    struct Storage(BTreeMap<String, String>);

    impl eframe::Storage for Storage {
        fn get_string(&self, key: &str) -> Option<String> {
            self.0.get(key).cloned()
        }
        fn set_string(&mut self, key: &str, value: String) {
            self.0.insert(key.into(), value);
        }
        fn remove_string(&mut self, key: &str) {
            self.0.remove(key);
        }
        fn flush(&mut self) {}
    }

    #[test]
    fn display_preference_roundtrip_defaults_and_unknown_locale_do_not_touch_other_state() {
        let ctx = egui::Context::default();
        let qa_catalog = catalog();
        let mut storage = Storage::default();
        storage
            .0
            .insert("measurement-sentinel".into(), "unchanged".into());
        initialize(&ctx, None);
        assert_eq!(locale(), Locale::English);
        for selected in Locale::ALL {
            set_locale(&ctx, selected.id());
            let selected_label = text("shell.language");
            save(&mut storage);
            initialize(&ctx, None);
            assert_eq!(locale(), Locale::English);
            initialize(&ctx, Some(&storage));
            assert_eq!(locale(), selected);
            assert_eq!(
                qa_catalog.lookup(locale(), "common.ready"),
                if selected == Locale::Japanese {
                    "QA準備完了"
                } else {
                    "Ready for QA"
                }
            );
            assert_eq!(text("shell.language"), selected_label);
            assert_eq!(storage.0["measurement-sentinel"], "unchanged");
            assert_eq!(storage.0.len(), 2);
        }
        for unknown in ["", "unknown", "ja-JP", "old-locale"] {
            storage.0.insert(STORAGE_KEY.into(), unknown.into());
            initialize(&ctx, Some(&storage));
            assert_eq!(locale(), Locale::English);
            assert_eq!(Locale::from_id(unknown), Locale::English);
        }
    }

    #[test]
    fn bundled_fonts_cover_native_names_cjk_cyrillic_accents_and_units() {
        let ctx = egui::Context::default();
        for locale in Locale::ALL {
            ctx.set_fonts(fonts(locale));
            let output = ctx.run_ui(Default::default(), |ui| {
                ui.ctx().fonts_mut(|fonts| {
                    for family in [egui::FontFamily::Proportional, egui::FontFamily::Monospace] {
                        let id = egui::FontId::new(14.0, family);
                        for sample in Locale::ALL.into_iter().map(Locale::native_name).chain([
                            "入力停止 測定準備 输入停止 测量 준비 측정 정지",
                            "Амплитуда частота Français Español Português äöüß éèà µΩ°− 48 kHz FS",
                        ]).chain(CATALOG.resolved[locale as usize].values().map(|text| text.as_ref())) {
                            // egui 0.36's has_glyph compares the owning face to
                            // the replacement face, rejecting valid Latin from
                            // that same face. glyph_width returns zero when the
                            // requested character has no actual glyph.
                            // Line breaks/tabs are layout controls, not font glyphs.
                            for glyph in sample.chars().filter(|c| !matches!(c, '\n' | '\r' | '\t')) {
                                assert!(
                                    fonts.glyph_width(&id, glyph) > 0.0,
                                    "Missing glyph in {locale:?}: {glyph} ({sample})"
                                );
                            }
                        }
                        assert_eq!(fonts.glyph_width(&id, '\u{10ffff}'), 0.0);
                    }
                });
            });
            output.drop_without_applying_deltas();
        }
    }

    #[test]
    fn stable_edit_id_and_focus_survive_language_and_font_switches() {
        let ctx = egui::Context::default();
        initialize(&ctx, None);
        let id = egui::Id::new("i18n_focus_fixture");
        let mut draft = "unchanged".to_owned();
        let output = ctx.run_ui(Default::default(), |ui| {
            ui.add(egui::TextEdit::singleline(&mut draft).id(id));
        });
        output.drop_without_applying_deltas();
        ctx.memory_mut(|memory| memory.request_focus(id));
        for locale in Locale::ALL {
            set_locale(&ctx, locale.id());
            let output = ctx.run_ui(Default::default(), |ui| {
                let response = ui.add(egui::TextEdit::singleline(&mut draft).id(id));
                assert_eq!(response.id, id);
                assert!(response.has_focus());
            });
            output.drop_without_applying_deltas();
            assert_eq!(draft, "unchanged");
        }
    }
}
