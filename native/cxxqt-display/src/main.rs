mod backend;
use cxx_qt_lib::{QGuiApplication, QQmlApplicationEngine, QUrl};
fn main() {
    let language = display_core::locale::selected_language().expect("valid --language required");
    println!("DISPLAY_LANGUAGE {language}");
    let mut app = QGuiApplication::new();
    let mut engine = QQmlApplicationEngine::new();
    engine.pin_mut().load(&QUrl::from(&format!(
        "file://{}",
        display_core::qml_path().display()
    )));
    let code = app.pin_mut().exec();
    drop(engine);
    drop(app);
    display_core::finish_saves();
    assert_eq!(display_core::live_workers(), 0);
    assert_eq!(display_core::live_models(), 0);
    println!("DISPLAY_TEARDOWN workers=0 models=0");
    std::process::exit(code);
}
