//! MIG-004-A synthetic worker. No audio, DSP, graph or Qt dependencies.
//! A capacity-one latest-snapshot mailbox coalesces GUI updates. It is not an
//! acquisition queue and its mutex must never be copied into an audio callback.

use std::collections::HashSet;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;

static GENERATION: AtomicU64 = AtomicU64::new(0);
static TOKEN: AtomicU64 = AtomicU64::new(0);
static LIVE_WORKERS: AtomicUsize = AtomicUsize::new(0);
static LIVE_MODELS: AtomicUsize = AtomicUsize::new(0);

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum State {
    #[default]
    Idle,
    Preparing,
    Running,
    Stopping,
    Failed,
}

impl State {
    pub fn code(self) -> i32 {
        match self {
            Self::Idle => 0,
            Self::Preparing => 1,
            Self::Running => 2,
            Self::Stopping => 3,
            Self::Failed => 4,
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct Snapshot {
    pub generation: u64,
    pub state: State,
    pub produced: u64,
    pub coalesced: u64,
    // 0: no outcome, 1: stopped, 2: cancelled during preparation, 3: failed.
    pub outcome: i32,
}

#[derive(Default)]
struct Mailbox {
    snapshot: Snapshot,
    pending: bool,
}

pub struct Probe {
    mailbox: Arc<Mutex<Mailbox>>,
    stop: Arc<AtomicBool>,
    worker: Option<JoinHandle<()>>,
    subscriptions: HashSet<u64>,
}

impl Default for Probe {
    fn default() -> Self {
        LIVE_MODELS.fetch_add(1, Ordering::SeqCst);
        Self {
            mailbox: Arc::default(),
            stop: Arc::default(),
            worker: None,
            subscriptions: HashSet::new(),
        }
    }
}

impl Probe {
    /// Demand tokens model the Qt boundary only, not Analysis Graph nodes.
    pub fn subscribe(&mut self) -> u64 {
        let token = TOKEN.fetch_add(1, Ordering::SeqCst) + 1;
        self.subscriptions.insert(token);
        token
    }

    pub fn unsubscribe(&mut self, token: u64) -> bool {
        if !self.subscriptions.remove(&token) {
            return false;
        }
        if self.subscriptions.is_empty() {
            self.stop();
        }
        true
    }

    pub fn subscribers(&self) -> usize {
        self.subscriptions.len()
    }

    /// Returns the accepted generation; Running is acknowledged by the worker.
    pub fn start(
        &mut self,
        fail: bool,
        notify: impl Fn(u64) -> bool + Send + 'static,
    ) -> Option<u64> {
        if self.subscriptions.is_empty() {
            return None;
        }
        if let Some(worker) = &self.worker
            && !worker.is_finished()
        {
            return None;
        }
        self.join();
        let generation = GENERATION.fetch_add(1, Ordering::SeqCst) + 1;
        self.stop.store(false, Ordering::Release);
        *self.mailbox.lock().unwrap() = Mailbox {
            snapshot: Snapshot {
                generation,
                state: State::Preparing,
                ..Snapshot::default()
            },
            pending: false,
        };
        let mailbox = self.mailbox.clone();
        let stop = self.stop.clone();
        self.worker = Some(thread::spawn(move || {
            LIVE_WORKERS.fetch_add(1, Ordering::SeqCst);
            let publish = |state, outcome, produced| {
                let enqueue = {
                    let mut slot = mailbox.lock().unwrap();
                    // Stop may race with the worker just before publish. Never
                    // regress an acknowledged Stopping state back to Running.
                    if state == State::Running && stop.load(Ordering::Acquire) {
                        return true;
                    }
                    slot.snapshot.state = state;
                    slot.snapshot.outcome = outcome;
                    slot.snapshot.produced = produced;
                    if slot.pending {
                        slot.snapshot.coalesced += 1;
                        false
                    } else {
                        slot.pending = true;
                        true
                    }
                };
                // No mailbox lock is held across either bridge's queue call.
                !enqueue || notify(generation)
            };
            let mut cancelled = false;
            for _ in 0..16 {
                if stop.load(Ordering::Acquire) {
                    cancelled = true;
                    break;
                }
                thread::sleep(Duration::from_millis(5));
            }
            if cancelled || stop.load(Ordering::Acquire) {
                publish(State::Idle, 2, 0);
            } else if fail {
                publish(State::Failed, 3, 0);
            } else {
                let mut produced = 0;
                while !stop.load(Ordering::Acquire) {
                    produced += 1;
                    if !publish(State::Running, 0, produced) {
                        break;
                    }
                    thread::sleep(Duration::from_millis(5));
                }
                publish(State::Idle, 1, produced);
            }
            LIVE_WORKERS.fetch_sub(1, Ordering::SeqCst);
        }));
        Some(generation)
    }

    pub fn stop(&mut self) {
        self.stop.store(true, Ordering::Release);
        let mut slot = self.mailbox.lock().unwrap();
        if matches!(slot.snapshot.state, State::Preparing | State::Running) {
            slot.snapshot.state = State::Stopping;
        }
    }

    /// Stale notifications must neither mutate a view nor clear a new pending bit.
    pub fn take(&self, generation: u64) -> Option<Snapshot> {
        let mut slot = self.mailbox.lock().unwrap();
        if slot.snapshot.generation != generation {
            return None;
        }
        slot.pending = false;
        Some(slot.snapshot.clone())
    }

    pub fn peek(&self) -> Snapshot {
        self.mailbox.lock().unwrap().snapshot.clone()
    }

    fn join(&mut self) {
        if let Some(worker) = self.worker.take() {
            worker.join().expect("synthetic worker panicked");
        }
    }

    pub fn shutdown(&mut self) {
        self.stop();
        self.join();
    }
}

impl Drop for Probe {
    fn drop(&mut self) {
        self.shutdown();
        LIVE_MODELS.fetch_sub(1, Ordering::SeqCst);
    }
}

pub fn live_workers() -> usize {
    LIVE_WORKERS.load(Ordering::SeqCst)
}

pub fn live_models() -> usize {
    LIVE_MODELS.load(Ordering::SeqCst)
}

/// Both executables load the very same file, without embedding it at compile time.
pub fn qml_path() -> std::path::PathBuf {
    let path = resolve_qml_path(
        std::env::var_os("MEASURELAB_PROBE_QML"),
        &std::env::current_exe().expect("executable location"),
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")),
    )
    .canonicalize()
    .expect("QML file must exist");
    println!("PROBE_QML {}", path.display());
    path
}

fn resolve_qml_path(
    explicit: Option<std::ffi::OsString>,
    executable: &std::path::Path,
    development: &std::path::Path,
) -> std::path::PathBuf {
    if let Some(path) = explicit {
        return path.into();
    }
    if let Some(directory) = executable.parent() {
        // A missing package resource must fail, never fall back to the developer checkout.
        if directory.file_name().is_some_and(|name| name == "MacOS") {
            return directory.join("../Resources/Main.qml");
        }
        if directory.file_name().is_some_and(|name| name == "bin") {
            return directory.join("../share/measurelab-evaluation/Main.qml");
        }
    }
    development.join("../qml/Main.qml")
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc;
    use std::time::Instant;

    #[test]
    fn packaged_qml_never_depends_on_the_developer_checkout() {
        use std::path::{Path, PathBuf};
        let development = Path::new("/developer/native/probe-core");
        let executable = Path::new("/relocated/Evaluation.app/Contents/MacOS/probe");
        assert_eq!(
            resolve_qml_path(None, executable, development),
            PathBuf::from("/relocated/Evaluation.app/Contents/MacOS/../Resources/Main.qml")
        );
        assert_eq!(
            resolve_qml_path(
                None,
                Path::new("/relocated/Evaluation/bin/probe"),
                development
            ),
            PathBuf::from("/relocated/Evaluation/bin/../share/measurelab-evaluation/Main.qml")
        );
        assert_eq!(
            resolve_qml_path(Some("/explicit/Main.qml".into()), executable, development),
            PathBuf::from("/explicit/Main.qml")
        );
        assert_eq!(
            resolve_qml_path(
                None,
                Path::new("/developer/target/debug/probe"),
                development
            ),
            development.join("../qml/Main.qml")
        );
    }

    fn wait_for(probe: &Probe, predicate: impl Fn(&Snapshot) -> bool) {
        let deadline = Instant::now() + Duration::from_secs(3);
        while !predicate(&probe.peek()) {
            assert!(
                Instant::now() < deadline,
                "worker timeout: {:?}",
                probe.peek()
            );
            thread::sleep(Duration::from_millis(2));
        }
    }

    #[test]
    fn slow_consumer_coalesces_without_blocking_producer_and_preserves_latest() {
        let mut probe = Probe::default();
        probe.subscribe();
        let (sender, receiver) = mpsc::channel();
        let generation = probe.start(false, move |g| sender.send(g).is_ok()).unwrap();
        assert_eq!(
            receiver.recv_timeout(Duration::from_secs(2)).unwrap(),
            generation
        );
        wait_for(&probe, |s| s.produced >= 12);
        assert!(
            receiver.try_recv().is_err(),
            "at most one notification pending"
        );
        let latest = probe.take(generation).unwrap();
        assert!(latest.coalesced >= 11);
        assert!(latest.produced >= 12);
        assert_eq!(
            receiver.recv_timeout(Duration::from_secs(2)).unwrap(),
            generation
        );
        probe.shutdown();
        assert_eq!(probe.take(generation).unwrap().state, State::Idle);
    }

    #[test]
    fn cancel_failure_restart_and_old_generation_are_distinct() {
        let mut probe = Probe::default();
        probe.subscribe();
        let old = probe.start(false, |_| true).unwrap();
        assert!(probe.start(false, |_| true).is_none());
        probe.stop();
        probe.stop();
        probe.shutdown();
        assert_eq!(probe.peek().outcome, 2);
        let current = probe.start(true, |_| true).unwrap();
        assert!(current > old);
        wait_for(&probe, |s| s.state == State::Failed);
        assert!(probe.take(old).is_none());
        assert!(probe.mailbox.lock().unwrap().pending);
        assert_eq!(probe.take(current).unwrap().outcome, 3);
        probe.shutdown();
        assert_eq!(probe.peek().state, State::Failed);
    }

    #[test]
    fn disconnected_view_and_drop_join_worker() {
        let mut probe = Probe::default();
        probe.subscribe();
        probe.start(false, |_| false).unwrap();
        wait_for(&probe, |s| s.outcome == 1);
        probe.shutdown();
        assert!(probe.worker.is_none());
        probe.start(false, |_| true).unwrap();
        // Drop cancels even during preparation, and joins before freeing state.
        drop(probe);
    }

    #[test]
    fn two_views_and_session_hold_worker_until_last_subscription() {
        let mut probe = Probe::default();
        assert!(probe.start(false, |_| true).is_none());
        let view1 = probe.subscribe();
        let view2 = probe.subscribe();
        let session = probe.subscribe();
        let mut unrelated = Probe::default();
        let foreign_token = unrelated.subscribe();
        assert!(!probe.unsubscribe(foreign_token));
        assert_eq!(probe.subscribers(), 3);
        probe.start(false, |_| true).unwrap();
        wait_for(&probe, |s| s.produced >= 2);
        assert!(probe.unsubscribe(view1));
        let before = probe.peek().produced;
        wait_for(&probe, |s| s.produced > before);
        assert!(probe.unsubscribe(view2));
        assert!(!probe.unsubscribe(view2));
        assert_eq!(probe.subscribers(), 1);
        let before = probe.peek().produced;
        wait_for(&probe, |s| s.produced > before);
        assert!(probe.unsubscribe(session));
        assert_eq!(probe.subscribers(), 0);
        probe.shutdown();
        assert_eq!(probe.peek().state, State::Idle);
        assert_eq!(probe.peek().outcome, 1);
    }
}
