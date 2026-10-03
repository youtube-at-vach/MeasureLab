mod backend;

use cxx_qt_lib::{QGuiApplication, QQmlApplicationEngine, QUrl};

fn main() {
    let mut app = QGuiApplication::new();
    let mut engine = QQmlApplicationEngine::new();
    engine.pin_mut().load(&QUrl::from(&format!(
        "file://{}",
        probe_core::qml_path().display()
    )));
    let code = app.pin_mut().exec();
    drop(engine);
    drop(app);
    assert_eq!(
        probe_core::live_workers(),
        0,
        "worker leak after engine destruction"
    );
    assert_eq!(
        probe_core::live_models(),
        0,
        "model leak after engine destruction"
    );
    println!("PROBE_TEARDOWN workers=0 models=0");
    std::process::exit(code);
}
