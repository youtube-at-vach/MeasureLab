use cxx_qt::{CxxQtType, Threading};
use cxx_qt_lib::QString;
use display_core::{Display, Snapshot};
use std::pin::Pin;

#[cxx_qt::bridge]
mod ffi {
    unsafe extern "C++" {
        include!("cxx-qt-lib/qstring.h");
        type QString = cxx_qt_lib::QString;
    }
    extern "RustQt" {
        #[qobject]
        #[qml_element]
        #[qproperty(i32, state)]
        #[qproperty(i32, outcome)]
        #[qproperty(u64, generation)]
        #[qproperty(u64, produced)]
        #[qproperty(u64, coalesced)]
        #[qproperty(bool, shared)]
        #[qproperty(bool, reclaimed)]
        #[qproperty(QString, payload)]
        #[qproperty(QString, capture)]
        #[qproperty(QString, calibration)]
        #[qproperty(QString, saves)]
        #[qproperty(QString, imports)]
        #[qproperty(QString, error)]
        #[qproperty(bool, testing)]
        #[qproperty(QString, translations)]
        type DisplayBackend = super::DisplayBackendRust;
        #[qinvokable]
        fn start(self: Pin<&mut Self>, fail: bool) -> bool;
        #[qinvokable]
        fn stop(self: Pin<&mut Self>);
        #[qinvokable]
        fn deliver(self: Pin<&mut Self>, generation: u64);
        #[qinvokable]
        fn stall(&self) -> i32;
        #[qinvokable]
        fn workers(&self) -> i32;
        #[qinvokable]
        fn subscribe(self: Pin<&mut Self>) -> u64;
        #[qinvokable]
        fn unsubscribe(self: Pin<&mut Self>, token: u64) -> bool;
        #[qinvokable]
        fn subscribers(&self) -> i32;
        #[qinvokable]
        fn pin_result(self: Pin<&mut Self>, generation: u64, result_id: &QString) -> bool;
        #[qinvokable]
        fn release_save_result(self: Pin<&mut Self>);
        #[qinvokable]
        fn save_result(self: Pin<&mut Self>, encoded: &QString) -> bool;
        #[qinvokable]
        fn poll_saves(self: Pin<&mut Self>);
        #[qinvokable]
        fn cancel_save(self: Pin<&mut Self>, operation_id: u64) -> bool;
        #[qinvokable]
        fn close_saves(self: Pin<&mut Self>);
        #[qinvokable]
        fn import_product(self: Pin<&mut Self>, encoded: &QString) -> bool;
        #[qinvokable]
        fn poll_imports(self: Pin<&mut Self>);
        #[qinvokable]
        fn cancel_import(self: Pin<&mut Self>, operation_id: u64) -> bool;
        #[qinvokable]
        fn close_imports(self: Pin<&mut Self>);
        #[qinvokable]
        fn apply_calibration(self: Pin<&mut Self>, encoded: &QString) -> bool;
        #[qinvokable]
        fn request_trigger(self: Pin<&mut Self>, encoded: &QString) -> bool;
        #[qinvokable]
        fn retry_trigger(self: Pin<&mut Self>, generation: u64, revision: u64) -> bool;
        #[qinvokable]
        fn release_trigger(self: Pin<&mut Self>, generation: u64, revision: u64) -> bool;
    }
    impl cxx_qt::Threading for DisplayBackend {}
}
pub struct DisplayBackendRust {
    display: Display,
    state: i32,
    outcome: i32,
    generation: u64,
    produced: u64,
    coalesced: u64,
    shared: bool,
    reclaimed: bool,
    payload: QString,
    capture: QString,
    calibration: QString,
    saves: QString,
    imports: QString,
    error: QString,
    testing: bool,
    translations: QString,
}
impl Default for DisplayBackendRust {
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
            payload: QString::default(),
            capture: QString::default(),
            calibration: QString::default(),
            saves: QString::default(),
            imports: QString::default(),
            error: QString::default(),
            testing: std::env::args().any(|arg| arg == "--self-test"),
            translations: QString::from(&display_core::locale::selected_catalog()),
        }
    }
}
impl ffi::DisplayBackend {
    fn apply(mut self: Pin<&mut Self>, snapshot: Snapshot) {
        self.as_mut().rust_mut().display.present(&snapshot);
        self.as_mut().set_generation(snapshot.generation);
        self.as_mut().set_produced(snapshot.produced);
        self.as_mut().set_coalesced(snapshot.coalesced);
        self.as_mut().set_shared(snapshot.shared);
        self.as_mut().set_reclaimed(snapshot.reclaimed);
        self.as_mut().set_error(QString::from(&snapshot.error));
        self.as_mut().set_outcome(snapshot.outcome);
        self.as_mut().set_state(snapshot.state.code());
        self.as_mut()
            .set_calibration(QString::from(&snapshot.calibration));
        self.as_mut().set_capture(QString::from(
            snapshot.trigger.as_ref().map_or("", |r| r.encoded.as_str()),
        ));
        self.set_payload(QString::from(
            snapshot
                .frame
                .as_ref()
                .map_or("", |f| f.projection.as_str()),
        ));
    }
    fn start(mut self: Pin<&mut Self>, fail: bool) -> bool {
        let thread = self.qt_thread();
        if self
            .as_mut()
            .rust_mut()
            .display
            .start(fail, move |generation| {
                thread
                    .queue(move |backend| backend.deliver(generation))
                    .is_ok()
            })
            .is_some()
        {
            let snapshot = self.display.peek();
            self.apply(snapshot);
            true
        } else {
            false
        }
    }
    fn stop(mut self: Pin<&mut Self>) {
        self.as_mut().rust_mut().display.stop();
        let s = self.display.peek();
        self.apply(s);
    }
    fn deliver(self: Pin<&mut Self>, generation: u64) {
        if let Some(s) = self.display.take(generation) {
            self.apply(s);
        }
    }
    fn stall(&self) -> i32 {
        let before = self.display.peek().produced;
        std::thread::sleep(std::time::Duration::from_millis(320));
        (self.display.peek().produced - before) as i32
    }
    fn workers(&self) -> i32 {
        display_core::live_workers() as i32
    }
    fn subscribe(mut self: Pin<&mut Self>) -> u64 {
        self.as_mut().rust_mut().display.subscribe()
    }
    fn unsubscribe(mut self: Pin<&mut Self>, token: u64) -> bool {
        self.as_mut().rust_mut().display.unsubscribe(token)
    }
    fn subscribers(&self) -> i32 {
        self.display.subscribers() as i32
    }
    fn pin_result(mut self: Pin<&mut Self>, generation: u64, result_id: &QString) -> bool {
        self.as_mut()
            .rust_mut()
            .display
            .pin_result(generation, &result_id.to_string())
    }
    fn release_save_result(mut self: Pin<&mut Self>) {
        self.as_mut().rust_mut().display.release_save_result();
    }
    fn save_result(mut self: Pin<&mut Self>, encoded: &QString) -> bool {
        let accepted = self
            .as_mut()
            .rust_mut()
            .display
            .save_result(&encoded.to_string());
        self.poll_saves();
        accepted
    }
    fn poll_saves(self: Pin<&mut Self>) {
        let encoded = self.display.poll_saves();
        self.set_saves(QString::from(&encoded));
    }
    fn cancel_save(mut self: Pin<&mut Self>, operation_id: u64) -> bool {
        let cancelled = self.display.cancel_save(operation_id);
        self.as_mut().poll_saves();
        cancelled
    }
    fn close_saves(mut self: Pin<&mut Self>) {
        self.as_mut().rust_mut().display.close_saves();
        self.poll_saves();
    }
    fn import_product(mut self: Pin<&mut Self>, encoded: &QString) -> bool {
        let accepted = self
            .as_mut()
            .rust_mut()
            .display
            .import_product(&encoded.to_string());
        self.poll_imports();
        accepted
    }
    fn poll_imports(self: Pin<&mut Self>) {
        let encoded = self.display.poll_imports();
        self.set_imports(QString::from(&encoded));
    }
    fn cancel_import(mut self: Pin<&mut Self>, operation_id: u64) -> bool {
        let cancelled = self.display.cancel_import(operation_id);
        self.as_mut().poll_imports();
        cancelled
    }
    fn close_imports(mut self: Pin<&mut Self>) {
        self.as_mut().rust_mut().display.close_imports();
        self.poll_imports();
    }
    fn apply_calibration(mut self: Pin<&mut Self>, encoded: &QString) -> bool {
        let accepted = self
            .as_mut()
            .rust_mut()
            .display
            .apply_calibration(&encoded.to_string());
        let snapshot = self.display.peek();
        self.apply(snapshot);
        accepted
    }
    fn request_trigger(mut self: Pin<&mut Self>, encoded: &QString) -> bool {
        let accepted = self
            .as_mut()
            .rust_mut()
            .display
            .request_trigger(&encoded.to_string());
        let s = self.display.peek();
        self.apply(s);
        accepted
    }
    fn retry_trigger(mut self: Pin<&mut Self>, generation: u64, revision: u64) -> bool {
        let accepted = self
            .as_mut()
            .rust_mut()
            .display
            .retry_trigger(generation, revision);
        let s = self.display.peek();
        self.apply(s);
        accepted
    }
    fn release_trigger(mut self: Pin<&mut Self>, generation: u64, revision: u64) -> bool {
        let accepted = self
            .as_mut()
            .rust_mut()
            .display
            .release_trigger(generation, revision);
        let s = self.display.peek();
        self.apply(s);
        accepted
    }
}
