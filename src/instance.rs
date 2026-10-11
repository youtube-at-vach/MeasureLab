//! Process-level launch policy, kept separate from acquisition and analysis.
use std::{
    fs::{File, OpenOptions, TryLockError},
    io,
    path::{Path, PathBuf},
};

pub struct Instance {
    // The OS releases the lock when this handle closes, including process exit.
    // Keep the file itself: unlinking it permits different processes to lock
    // different inodes at the same path.
    _file: File,
}

impl Instance {
    pub fn acquire() -> io::Result<Option<Self>> {
        Self::at(&lock_path()?)
    }

    fn at(path: &Path) -> io::Result<Option<Self>> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path)?;
        match file.try_lock() {
            Ok(()) => Ok(Some(Self { _file: file })),
            Err(TryLockError::WouldBlock) => Ok(None),
            Err(TryLockError::Error(error)) => Err(error),
        }
    }
}

fn lock_path() -> io::Result<PathBuf> {
    #[cfg(target_os = "windows")]
    let directory = std::env::var_os("LOCALAPPDATA").map(PathBuf::from);
    #[cfg(not(target_os = "windows"))]
    let directory = std::env::var_os("HOME").map(|home| {
        let home = PathBuf::from(home);
        #[cfg(target_os = "macos")]
        {
            home.join("Library/Application Support")
        }
        #[cfg(not(target_os = "macos"))]
        {
            std::env::var_os("XDG_STATE_HOME")
                .map_or_else(|| home.join(".local/state"), PathBuf::from)
        }
    });
    directory
        .map(|base| base.join("MeasureLab/instance.lock"))
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::NotFound,
                "User application data directory is unavailable",
            )
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exclusive_lock_is_released_without_deleting_the_file() {
        let path = std::env::temp_dir().join(format!(
            "measurelab-instance-test-{}.lock",
            std::process::id()
        ));
        let first = Instance::at(&path).unwrap().unwrap();
        assert!(Instance::at(&path).unwrap().is_none());
        drop(first);
        let next = Instance::at(&path).unwrap().unwrap();
        drop(next);
        std::fs::remove_file(path).unwrap();
    }
}
