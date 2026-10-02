use qtbridge::{QApp, QmlElement, qobject};

#[qobject(Base = QListModel, NoQmlElement)]
mod backend {
    use probe_core::{Probe, Snapshot};
    use qtbridge::{QListModel, QListModelBase, QmlObject, invoke_method};

    pub struct Backend {
        probe: Probe,
        state: i32,
        outcome: i32,
        generation: u64,
        produced: u64,
        coalesced: u64,
        testing: bool,
        rows: Vec<String>,
    }

    impl Default for Backend {
        fn default() -> Self {
            Self {
                probe: Probe::default(),
                state: 0,
                outcome: 0,
                generation: 0,
                produced: 0,
                coalesced: 0,
                testing: std::env::args().any(|arg| arg == "--self-test"),
                rows: vec!["0".into(), "0".into()],
            }
        }
    }

    impl QListModel for Backend {
        type Item = String;
        fn len(&self) -> usize {
            self.rows.len()
        }
        fn get(&self, index: usize) -> Option<&String> {
            self.rows.get(index)
        }
        fn reset_unnotified(&mut self) {
            self.rows.clear();
        }
        fn push_unnotified(&mut self, value: String) {
            self.rows.push(value);
        }
    }

    impl Backend {
        qproperty!("state", Member = state, Notify = changed);
        qproperty!("outcome", Member = outcome, Notify = changed);
        qproperty!("generation", Member = generation, Notify = changed);
        qproperty!("produced", Member = produced, Notify = changed);
        qproperty!("coalesced", Member = coalesced, Notify = changed);
        qproperty!("testing", Member = testing, Constant);

        #[qsignal]
        fn changed(&mut self);

        fn apply(&mut self, snapshot: Snapshot) {
            self.reset();
            self.push(snapshot.generation.to_string());
            self.push(snapshot.produced.to_string());
            self.generation = snapshot.generation;
            self.produced = snapshot.produced;
            self.coalesced = snapshot.coalesced;
            self.outcome = snapshot.outcome;
            self.state = snapshot.state.code();
            self.changed();
        }

        #[qslot]
        fn start(&mut self, fail: bool) -> bool {
            let invoker = self.get_qml_method_invoker();
            if self
                .probe
                .start(fail, move |generation| {
                    invoke_method!(invoker, "deliver", generation)
                })
                .is_some()
            {
                self.apply(self.probe.peek());
                true
            } else {
                false
            }
        }

        #[qslot]
        fn stop(&mut self) {
            self.probe.stop();
            self.apply(self.probe.peek());
        }

        #[qslot]
        fn deliver(&mut self, generation: u64) {
            if let Some(snapshot) = self.probe.take(generation) {
                self.apply(snapshot);
            }
        }

        #[qslot]
        fn stall(&self) -> i32 {
            let before = self.probe.peek().produced;
            std::thread::sleep(std::time::Duration::from_millis(160));
            (self.probe.peek().produced - before) as i32
        }

        #[qslot]
        fn workers(&self) -> i32 {
            probe_core::live_workers() as i32
        }

        #[qslot]
        fn subscribe(&mut self) -> u64 {
            self.probe.subscribe()
        }

        #[qslot]
        fn unsubscribe(&mut self, token: u64) -> bool {
            let removed = self.probe.unsubscribe(token);
            self.apply(self.probe.peek());
            removed
        }

        #[qslot]
        fn subscribers(&self) -> i32 {
            self.probe.subscribers() as i32
        }
    }
}

impl QmlElement for backend::Backend {
    const URI: &str = "BridgeProbe";
    const ELEMENT_NAME: &str = "Backend";
    const MAJOR_VERSION: u8 = 1;
    const MINOR_VERSION: u8 = 0;
    const IS_SINGLETON: bool = false;
}

fn main() {
    let mut app = QApp::new();
    app.register::<backend::Backend>()
        .load_qml_from_file(&format!("file://{}", probe_core::qml_path().display()));
    let code = app.run();
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
