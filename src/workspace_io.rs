//! Dialogs and I/O own copies; the measurement workers continue independently.
use crate::{export, results, settings};
use std::{path::PathBuf, sync::mpsc, thread};

#[derive(Clone, Copy)]
pub enum Format {
    Json,
    Csv,
    Png,
}
pub enum Task {
    SaveSettings(Box<settings::Document>),
    RestoreSettings,
    SaveResult(Box<export::Document>, Format),
    LoadResult,
}
pub enum Event {
    Saved(PathBuf),
    Settings(Box<settings::Document>),
    Reference(Box<export::Document>, PathBuf),
    Cancelled,
    Error(String),
}
pub struct Worker {
    commands: Option<mpsc::SyncSender<Task>>,
    pub events: mpsc::Receiver<Event>,
    handle: Option<thread::JoinHandle<()>>,
}
impl Default for Worker {
    fn default() -> Self {
        let (commands, requests) = mpsc::sync_channel(1);
        let (responses, events) = mpsc::channel();
        let handle = thread::Builder::new()
            .name("measurelab-workspace-io".into())
            .spawn(move || {
                while let Ok(task) = requests.recv() {
                    let event = execute(task).unwrap_or_else(Event::Error);
                    if responses.send(event).is_err() {
                        break;
                    }
                }
            })
            .expect("workspace IO worker");
        Self {
            commands: Some(commands),
            events,
            handle: Some(handle),
        }
    }
}
impl Worker {
    pub fn submit(&self, task: Task) -> Result<(), String> {
        self.commands
            .as_ref()
            .unwrap()
            .try_send(task)
            .map_err(|e| format!("Workspace worker unavailable: {e}"))
    }
}
impl Drop for Worker {
    fn drop(&mut self) {
        self.commands.take();
        if let Some(h) = self.handle.take() {
            let _ = h.join();
        }
    }
}
fn execute(task: Task) -> Result<Event, String> {
    let extension = match &task {
        Task::SaveResult(_, Format::Csv) => "csv",
        Task::SaveResult(_, Format::Png) => "png",
        _ => "json",
    };
    let dialog = rfd::FileDialog::new().add_filter("MeasureLab", &[extension]);
    let open = matches!(task, Task::LoadResult | Task::RestoreSettings);
    let path = if open {
        dialog.pick_file()
    } else {
        dialog
            .set_file_name(match task {
                Task::SaveSettings(_) => "measurement-settings.json",
                _ => match extension {
                    "png" => "measurement-results.png",
                    "csv" => "measurement-results.csv",
                    _ => "measurement-results.json",
                },
            })
            .save_file()
    };
    let Some(path) = path else {
        return Ok(Event::Cancelled);
    };
    match task {
        Task::SaveSettings(doc) => settings::save(&path, &doc)?,
        Task::RestoreSettings => return Ok(Event::Settings(Box::new(settings::load(&path)?))),
        Task::LoadResult => return Ok(Event::Reference(Box::new(results::load(&path)?), path)),
        Task::SaveResult(doc, format) => match format {
            Format::Json => {
                doc.validate()?;
                export::save(&path, &doc)?;
            }
            Format::Csv => results::save_csv(&path, &doc)?,
            Format::Png => crate::result_image::save(&path, &doc)?,
        },
    }
    Ok(Event::Saved(path))
}
