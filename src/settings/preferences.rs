//! Local startup preferences. Explicit measurement files remain user-owned.
use super::*;
use std::sync::{Arc, Condvar, Mutex};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Preferences {
    pub version: u32,
    /// Absent when no input with a stable identity has been selected yet.
    pub measurement: Option<Measurement>,
    pub workspace: Workspace,
    pub sidebar_compact: bool,
    pub separate_io_rates: bool,
    pub locale: String,
}

impl Preferences {
    fn validate(&self) -> Result<(), String> {
        if self.version != VERSION {
            return Err(format!(
                "Unsupported startup preferences version: {}",
                self.version
            ));
        }
        self.workspace.validate()?;
        bounded_text(&self.locale, 32, "locale")?;
        if let Some(measurement) = &self.measurement {
            Document {
                version: self.version,
                measurement: measurement.clone(),
                workspace: self.workspace.clone(),
            }
            .validate()?;
        }
        Ok(())
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, String> {
        if bytes.len() > MAX_BYTES {
            return Err("Startup preferences exceed 64 KiB".into());
        }
        let mut preferences: Self = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
        preferences.validate()?;
        preferences.workspace.presentation.repair();
        Ok(preferences)
    }

    fn encode(&self) -> Result<Vec<u8>, String> {
        self.validate()?;
        let mut bytes = serde_json::to_vec_pretty(self).map_err(|e| e.to_string())?;
        bytes.push(b'\n');
        if bytes.len() > MAX_BYTES {
            return Err("Startup preferences exceed 64 KiB".into());
        }
        Ok(bytes)
    }
}

pub fn default_path() -> Result<PathBuf, String> {
    // Device identities belong to this computer, including on roaming Windows
    // accounts. dirs uses the Windows Known Folder API and the XDG base dirs.
    dirs::config_local_dir()
        .filter(|base| base.is_absolute())
        .map(|base| base.join("MeasureLab/startup-preferences.json"))
        .ok_or_else(|| "User startup preferences directory is unavailable".into())
}

fn load(path: &Path) -> Result<Option<Preferences>, String> {
    let file = match File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.to_string()),
    };
    let mut bytes = Vec::new();
    file.take(MAX_BYTES as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    Preferences::decode(&bytes).map(Some)
}

pub enum Event {
    Loaded(Result<Option<Box<Preferences>>, String>),
    Saved(Result<(), String>),
}

#[derive(Default)]
struct Pending {
    latest: Option<Preferences>,
    closing: bool,
}

/// A single replaceable pending snapshot bounds memory even on a slow disk.
/// The lock covers the mailbox only; disk I/O and encoding run outside it.
pub struct Worker {
    pending: Arc<(Mutex<Pending>, Condvar)>,
    pub events: mpsc::Receiver<Event>,
    handle: Option<JoinHandle<()>>,
}

impl Worker {
    pub fn new(path: PathBuf) -> Self {
        let pending = Arc::new((Mutex::new(Pending::default()), Condvar::new()));
        let mailbox = pending.clone();
        let (events, responses) = mpsc::channel();
        let handle = thread::spawn(move || {
            let _ = events.send(Event::Loaded(load(&path).map(|p| p.map(Box::new))));
            loop {
                let (lock, wake) = &*mailbox;
                let mut pending = lock.lock().unwrap();
                while pending.latest.is_none() && !pending.closing {
                    pending = wake.wait(pending).unwrap();
                }
                let Some(snapshot) = pending.latest.take() else {
                    break;
                };
                drop(pending);
                let result = snapshot.encode().and_then(|bytes| {
                    crate::file_io::atomic_write(&path, |file| file.write_all(&bytes))
                });
                let _ = events.send(Event::Saved(result));
            }
        });
        Self {
            pending,
            events: responses,
            handle: Some(handle),
        }
    }

    pub fn save(&self, preferences: Preferences) {
        let (lock, wake) = &*self.pending;
        lock.lock().unwrap().latest = Some(preferences);
        wake.notify_one();
    }
}

impl Drop for Worker {
    fn drop(&mut self) {
        let (lock, wake) = &*self.pending;
        lock.lock().unwrap().closing = true;
        wake.notify_one();
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> Preferences {
        let document = super::super::tests::fixture();
        Preferences {
            version: VERSION,
            measurement: Some(document.measurement),
            workspace: document.workspace,
            sidebar_compact: true,
            separate_io_rates: true,
            locale: "ja".into(),
        }
    }

    #[test]
    fn preferences_keep_measurement_precision_and_work_without_an_input() {
        let mut preferences = fixture();
        assert_eq!(
            Preferences::decode(&preferences.encode().unwrap()).unwrap(),
            preferences
        );
        preferences.measurement = None;
        assert_eq!(
            Preferences::decode(&preferences.encode().unwrap()).unwrap(),
            preferences
        );
        preferences.workspace.scope_selected = 16;
        assert!(preferences.encode().is_err());
        let mut future = fixture();
        future.version += 1;
        assert!(Preferences::decode(&serde_json::to_vec(&future).unwrap()).is_err());
        assert!(Preferences::decode(&vec![b' '; MAX_BYTES + 1]).is_err());
        assert!(Preferences::decode(br#"{"audio":{"input_device":0}}"#).is_err());
        let mut invalid = fixture();
        invalid.measurement.as_mut().unwrap().input.channels = 0;
        assert!(invalid.encode().is_err());
    }

    #[test]
    fn restart_unicode_paths_final_flush_and_invalid_writes_preserve_previous_file() {
        let directory =
            std::env::temp_dir().join(format!("measurelab-startup-{}-設定", std::process::id()));
        std::fs::create_dir_all(&directory).unwrap();
        let path = directory.join("startup-preferences.json");
        let manual = directory.join("measurement-settings.json");
        super::super::save(&manual, &super::super::tests::fixture()).unwrap();
        let manual_before = std::fs::read(&manual).unwrap();
        let worker = Worker::new(path.clone());
        assert!(matches!(
            worker.events.recv().unwrap(),
            Event::Loaded(Ok(None))
        ));
        let mut expected = fixture();
        for index in 0..100 {
            expected.workspace.scope_horizontal_position = index as f32 / 100.0;
            worker.save(expected.clone());
        }
        drop(worker); // Shutdown flushes the latest coalesced snapshot.
        assert_eq!(load(&path).unwrap().unwrap(), expected);
        let before = std::fs::read(&path).unwrap();
        let worker = Worker::new(path.clone());
        let Event::Loaded(Ok(Some(restored))) = worker.events.recv().unwrap() else {
            panic!("restart load")
        };
        assert_eq!(*restored, expected);
        let mut invalid = expected;
        invalid.workspace.scope_vertical[0].offset = f64::NAN;
        worker.save(invalid);
        drop(worker);
        assert_eq!(std::fs::read(&path).unwrap(), before);
        assert_eq!(std::fs::read(&manual).unwrap(), manual_before);
        std::fs::write(&path, b"damaged JSON").unwrap();
        let worker = Worker::new(path.clone());
        assert!(matches!(
            worker.events.recv().unwrap(),
            Event::Loaded(Err(_))
        ));
        drop(worker);
        assert_eq!(std::fs::read(&path).unwrap(), b"damaged JSON");
        assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 2);
        std::fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn default_paths_use_absolute_os_directories_and_distinct_files() {
        if let Some(base) = dirs::config_local_dir() {
            assert_eq!(
                default_path().unwrap(),
                base.join("MeasureLab/startup-preferences.json")
            );
            assert!(default_path().unwrap().is_absolute());
            assert_ne!(
                default_path().unwrap(),
                super::super::default_path().unwrap()
            );
        }
    }
}
