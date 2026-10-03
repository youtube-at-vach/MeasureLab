use cxx_qt::{CxxQtType, Threading};
use cxx_qt_lib::{QByteArray, QHash, QHashPair_i32_QByteArray, QModelIndex, QString, QVariant};
use probe_core::{Probe, Snapshot};
use std::pin::Pin;

#[cxx_qt::bridge]
mod ffi {
    unsafe extern "C++" {
        include!(<QAbstractListModel>);
        type QAbstractListModel;
        include!("cxx-qt-lib/qmodelindex.h");
        type QModelIndex = cxx_qt_lib::QModelIndex;
        include!("cxx-qt-lib/qvariant.h");
        type QVariant = cxx_qt_lib::QVariant;
        include!("cxx-qt-lib/qstring.h");
        type QString = cxx_qt_lib::QString;
        include!("cxx-qt-lib/qhash.h");
        type QHash_i32_QByteArray = cxx_qt_lib::QHash<cxx_qt_lib::QHashPair_i32_QByteArray>;
    }
    extern "RustQt" {
        #[qobject]
        #[qml_element]
        #[base = QAbstractListModel]
        #[qproperty(i32, state)]
        #[qproperty(i32, outcome)]
        #[qproperty(u64, generation)]
        #[qproperty(u64, produced)]
        #[qproperty(u64, coalesced)]
        #[qproperty(bool, testing)]
        type Backend = super::BackendRust;

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

        #[cxx_override]
        #[cxx_name = "rowCount"]
        fn row_count(&self, parent: &QModelIndex) -> i32;
        #[cxx_override]
        fn data(&self, index: &QModelIndex, role: i32) -> QVariant;
        #[cxx_override]
        #[cxx_name = "roleNames"]
        fn role_names(&self) -> QHash_i32_QByteArray;

        #[inherit]
        #[cxx_name = "beginResetModel"]
        unsafe fn begin_reset_model(self: Pin<&mut Self>);
        #[inherit]
        #[cxx_name = "endResetModel"]
        unsafe fn end_reset_model(self: Pin<&mut Self>);
    }
    impl cxx_qt::Threading for Backend {}
}

pub struct BackendRust {
    probe: Probe,
    state: i32,
    outcome: i32,
    generation: u64,
    produced: u64,
    coalesced: u64,
    testing: bool,
    rows: Vec<QString>,
}

impl Default for BackendRust {
    fn default() -> Self {
        Self {
            probe: Probe::default(),
            state: 0,
            outcome: 0,
            generation: 0,
            produced: 0,
            coalesced: 0,
            testing: std::env::args().any(|arg| arg == "--self-test"),
            rows: vec![QString::from("0"), QString::from("0")],
        }
    }
}

impl ffi::Backend {
    fn apply(mut self: Pin<&mut Self>, snapshot: Snapshot) {
        // Balanced reset on the GUI thread; construct rows before entering reset.
        let rows = vec![
            QString::from(&snapshot.generation.to_string()),
            QString::from(&snapshot.produced.to_string()),
        ];
        unsafe { self.as_mut().begin_reset_model() };
        self.as_mut().rust_mut().rows = rows;
        unsafe { self.as_mut().end_reset_model() };
        self.as_mut().set_generation(snapshot.generation);
        self.as_mut().set_produced(snapshot.produced);
        self.as_mut().set_coalesced(snapshot.coalesced);
        self.as_mut().set_outcome(snapshot.outcome);
        self.as_mut().set_state(snapshot.state.code());
    }

    fn start(mut self: Pin<&mut Self>, fail: bool) -> bool {
        let thread = self.qt_thread();
        let generation = self
            .as_mut()
            .rust_mut()
            .probe
            .start(fail, move |generation| {
                thread
                    .queue(move |backend| backend.deliver(generation))
                    .is_ok()
            });
        if generation.is_some() {
            let snapshot = self.probe.peek();
            self.apply(snapshot);
            true
        } else {
            false
        }
    }

    fn stop(mut self: Pin<&mut Self>) {
        self.as_mut().rust_mut().probe.stop();
        let snapshot = self.probe.peek();
        self.apply(snapshot);
    }

    fn deliver(self: Pin<&mut Self>, generation: u64) {
        if let Some(snapshot) = self.probe.take(generation) {
            self.apply(snapshot);
        }
    }

    fn stall(&self) -> i32 {
        let before = self.probe.peek().produced;
        std::thread::sleep(std::time::Duration::from_millis(160));
        (self.probe.peek().produced - before) as i32
    }

    fn workers(&self) -> i32 {
        probe_core::live_workers() as i32
    }

    fn subscribe(mut self: Pin<&mut Self>) -> u64 {
        self.as_mut().rust_mut().probe.subscribe()
    }

    fn unsubscribe(mut self: Pin<&mut Self>, token: u64) -> bool {
        let removed = self.as_mut().rust_mut().probe.unsubscribe(token);
        let snapshot = self.probe.peek();
        self.apply(snapshot);
        removed
    }

    fn subscribers(&self) -> i32 {
        self.probe.subscribers() as i32
    }

    fn row_count(&self, parent: &QModelIndex) -> i32 {
        if parent.is_valid() {
            0
        } else {
            self.rows.len() as i32
        }
    }

    fn data(&self, index: &QModelIndex, role: i32) -> QVariant {
        if !index.is_valid() || index.column() != 0 || role != 256 {
            return QVariant::default();
        }
        self.rows
            .get(index.row() as usize)
            .map_or_else(QVariant::default, QVariant::from)
    }

    fn role_names(&self) -> QHash<QHashPair_i32_QByteArray> {
        let mut roles = QHash::default();
        roles.insert(256, QByteArray::from("value"));
        roles
    }
}
