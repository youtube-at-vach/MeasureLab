use qtbridge::{QApp, QmlElement, qobject};
#[qobject(NoQmlElement)]
mod backend {
    use display_core::{Display, Snapshot};
    use qtbridge::{QmlObject, invoke_method};
    pub struct DisplayBackend {
        display: Display,
        state: i32,
        outcome: i32,
        generation: u64,
        produced: u64,
        coalesced: u64,
        shared: bool,
        reclaimed: bool,
        payload: String,
        capture: String,
        calibration: String,
        saves: String,
        error: String,
        testing: bool,
        translations: String,
    }
    impl Default for DisplayBackend {
        fn default() -> Self {
            Self {
                display: Display::default(),
                state: 0,
                outcome: 0,
                generation: 0,
                produced: 0,
                coalesced: 0,
                shared: false,
                reclaimed: false,
                payload: String::new(),
                capture: String::new(),
                calibration: String::new(),
                saves: String::new(),
                error: String::new(),
                testing: std::env::args().any(|arg| arg == "--self-test"),
                translations: display_core::locale::selected_catalog(),
            }
        }
    }
    impl DisplayBackend {
        qproperty!("state", Member = state, Notify = changed);
        qproperty!("outcome", Member = outcome, Notify = changed);
        qproperty!("generation", Member = generation, Notify = changed);
        qproperty!("produced", Member = produced, Notify = changed);
        qproperty!("coalesced", Member = coalesced, Notify = changed);
        qproperty!("shared", Member = shared, Notify = changed);
        qproperty!("reclaimed", Member = reclaimed, Notify = changed);
        qproperty!("payload", Member = payload, Notify = changed);
        qproperty!("capture", Member = capture, Notify = changed);
        qproperty!("calibration", Member = calibration, Notify = changed);
        qproperty!("saves", Member = saves, Notify = changed);
        qproperty!("error", Member = error, Notify = changed);
        qproperty!("testing", Member = testing, Constant);
        qproperty!("translations", Member = translations, Constant);
        #[qsignal]
        fn changed(&mut self);
        fn apply(&mut self, s: Snapshot) {
            self.display.present(&s);
            self.state = s.state.code();
            self.outcome = s.outcome;
            self.generation = s.generation;
            self.produced = s.produced;
            self.coalesced = s.coalesced;
            self.shared = s.shared;
            self.reclaimed = s.reclaimed;
            self.error = s.error;
            self.calibration = s.calibration;
            self.capture = s
                .trigger
                .as_ref()
                .map_or_else(String::new, |r| r.encoded.clone());
            self.payload = s
                .frame
                .as_ref()
                .map_or_else(String::new, |f| f.projection.clone());
            self.changed();
        }
        #[qslot]
        fn start(&mut self, fail: bool) -> bool {
            let invoker = self.get_qml_method_invoker();
            if self
                .display
                .start(fail, move |generation| {
                    invoke_method!(invoker, "deliver", generation)
                })
                .is_some()
            {
                self.apply(self.display.peek());
                true
            } else {
                false
            }
        }
        #[qslot]
        fn stop(&mut self) {
            self.display.stop();
            self.apply(self.display.peek());
        }
        #[qslot]
        fn deliver(&mut self, generation: u64) {
            if let Some(s) = self.display.take(generation) {
                self.apply(s);
            }
        }
        #[qslot]
        fn stall(&self) -> i32 {
            let before = self.display.peek().produced;
            std::thread::sleep(std::time::Duration::from_millis(320));
            (self.display.peek().produced - before) as i32
        }
        #[qslot]
        fn workers(&self) -> i32 {
            display_core::live_workers() as i32
        }
        #[qslot]
        fn subscribe(&mut self) -> u64 {
            self.display.subscribe()
        }
        #[qslot]
        fn unsubscribe(&mut self, token: u64) -> bool {
            self.display.unsubscribe(token)
        }
        #[qslot]
        fn subscribers(&self) -> i32 {
            self.display.subscribers() as i32
        }
        #[qslot]
        fn pin_result(&mut self, generation: u64, result_id: String) -> bool {
            self.display.pin_result(generation, &result_id)
        }
        #[qslot]
        fn release_save_result(&mut self) {
            self.display.release_save_result();
        }
        #[qslot]
        fn save_result(&mut self, encoded: String) -> bool {
            let accepted = self.display.save_result(&encoded);
            self.poll_saves();
            accepted
        }
        #[qslot]
        fn poll_saves(&mut self) {
            self.saves = self.display.poll_saves();
            self.changed();
        }
        #[qslot]
        fn cancel_save(&mut self, operation_id: u64) -> bool {
            let cancelled = self.display.cancel_save(operation_id);
            self.poll_saves();
            cancelled
        }
        #[qslot]
        fn close_saves(&mut self) {
            self.display.close_saves();
            self.poll_saves();
        }
        #[qslot]
        fn apply_calibration(&mut self, encoded: String) -> bool {
            let accepted = self.display.apply_calibration(&encoded);
            self.apply(self.display.peek());
            accepted
        }
        #[qslot]
        fn request_trigger(&mut self, encoded: String) -> bool {
            let accepted = self.display.request_trigger(&encoded);
            self.apply(self.display.peek());
            accepted
        }
        #[qslot]
        fn retry_trigger(&mut self, generation: u64, revision: u64) -> bool {
            let accepted = self.display.retry_trigger(generation, revision);
            self.apply(self.display.peek());
            accepted
        }
        #[qslot]
        fn release_trigger(&mut self, generation: u64, revision: u64) -> bool {
            let accepted = self.display.release_trigger(generation, revision);
            self.apply(self.display.peek());
            accepted
        }
    }
}
impl QmlElement for backend::DisplayBackend {
    const URI: &str = "DisplayProbe";
    const ELEMENT_NAME: &str = "DisplayBackend";
    const MAJOR_VERSION: u8 = 1;
    const MINOR_VERSION: u8 = 0;
    const IS_SINGLETON: bool = false;
}
fn main() {
    let language = display_core::locale::selected_language().expect("valid --language required");
    println!("DISPLAY_LANGUAGE {language}");
    let mut app = QApp::new();
    app.register::<backend::DisplayBackend>()
        .load_qml_from_file(&format!("file://{}", display_core::qml_path().display()));
    let code = app.run();
    drop(app);
    display_core::finish_saves();
    assert_eq!(display_core::live_workers(), 0);
    assert_eq!(display_core::live_models(), 0);
    println!("DISPLAY_TEARDOWN workers=0 models=0");
    std::process::exit(code);
}
