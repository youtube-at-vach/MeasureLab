//! Evaluation UI uses the product translation source, embedded in each binary.
//! No locale, translation, or Qt access occurs in the acquisition worker/callback.
use std::collections::BTreeMap;

pub const LANGUAGES: [&str; 9] = ["en", "de", "es", "fr", "ja", "ko", "pt", "ru", "zh"];
const PREFIX: &str = "migration.display.";

pub fn catalog(language: &str) -> Result<String, String> {
    let data = match language {
        "en" => include_str!("../../../src/assets/lang/en.json"),
        "de" => include_str!("../../../src/assets/lang/de.json"),
        "es" => include_str!("../../../src/assets/lang/es.json"),
        "fr" => include_str!("../../../src/assets/lang/fr.json"),
        "ja" => include_str!("../../../src/assets/lang/ja.json"),
        "ko" => include_str!("../../../src/assets/lang/ko.json"),
        "pt" => include_str!("../../../src/assets/lang/pt.json"),
        "ru" => include_str!("../../../src/assets/lang/ru.json"),
        "zh" => include_str!("../../../src/assets/lang/zh.json"),
        _ => return Err("unsupported_display_language".into()),
    };
    let entries: BTreeMap<String, String> =
        serde_json::from_str(data).map_err(|e| e.to_string())?;
    let entries: BTreeMap<_, _> = entries
        .into_iter()
        .filter(|(key, _)| key.starts_with(PREFIX))
        .collect();
    serde_json::to_string(&entries).map_err(|e| e.to_string())
}

pub fn selected_language() -> Result<String, String> {
    let args: Vec<_> = std::env::args().collect();
    let mut found = args.iter().enumerate().filter(|(_, a)| *a == "--language");
    let language = match found.next() {
        Some((i, _)) => args.get(i + 1).ok_or("missing_display_language")?.clone(),
        None => "en".into(),
    };
    if found.next().is_some() || !LANGUAGES.contains(&language.as_str()) {
        return Err("unsupported_display_language".into());
    }
    Ok(language)
}

pub fn selected_catalog() -> String {
    catalog(&selected_language().expect("display language checked at startup"))
        .expect("embedded display translations")
}

#[cfg(test)]
mod tests {
    use super::*;
    fn entries(language: &str) -> BTreeMap<String, String> {
        serde_json::from_str(&catalog(language).unwrap()).unwrap()
    }
    #[test]
    fn all_languages_preserve_keys_and_qml_placeholders() {
        let english = entries("en");
        assert!(english.len() >= 30);
        for language in LANGUAGES {
            let local = entries(language);
            assert_eq!(
                english.keys().collect::<Vec<_>>(),
                local.keys().collect::<Vec<_>>()
            );
            for (key, text) in &local {
                assert!(!text.trim().is_empty(), "{language}: {key}");
                for field in ["%1", "%2", "%3", "%4"] {
                    assert_eq!(
                        text.matches(field).count(),
                        english[key].matches(field).count(),
                        "{language}: {key}"
                    );
                }
            }
        }
        assert!(catalog("../en").is_err());
        assert!(catalog("xx").is_err());
    }
}
