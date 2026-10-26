//! One in-flight PNG write. Readback callbacks never encode or touch disk on the UI.
use eframe::egui::{ColorImage, Context};
use std::{
    sync::{Arc, mpsc},
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

pub struct Writer {
    readback_sender: mpsc::SyncSender<Arc<ColorImage>>,
    readbacks: mpsc::Receiver<Arc<ColorImage>>,
    requests: Option<mpsc::SyncSender<Arc<ColorImage>>>,
    results: mpsc::Receiver<Result<Duration, String>>,
    handle: Option<JoinHandle<()>>,
    pending: bool,
}

impl Default for Writer {
    fn default() -> Self {
        Self::with_encoder(|image| {
            std::fs::create_dir_all("dist").map_err(|e| e.to_string())?;
            let file = std::fs::File::create("dist/ui-smoke.png").map_err(|e| e.to_string())?;
            let mut encoder = png::Encoder::new(file, image.width() as u32, image.height() as u32);
            encoder.set_color(png::ColorType::Rgba);
            encoder.set_depth(png::BitDepth::Eight);
            encoder
                .write_header()
                .and_then(|mut writer| writer.write_image_data(image.as_raw()))
                .map_err(|e| e.to_string())
        })
    }
}

impl Writer {
    fn with_encoder(
        mut encode: impl FnMut(Arc<ColorImage>) -> Result<(), String> + Send + 'static,
    ) -> Self {
        let (readback_sender, readbacks) = mpsc::sync_channel(1);
        let (requests, incoming) = mpsc::sync_channel(1);
        let (results, outgoing) = mpsc::sync_channel(1);
        let handle = thread::Builder::new()
            .name("measurelab-screenshot".into())
            .spawn(move || {
                while let Ok(image) = incoming.recv() {
                    let started = Instant::now();
                    let result = encode(image).map(|()| started.elapsed());
                    if results.send(result).is_err() {
                        break;
                    }
                }
            })
            .expect("screenshot writer");
        Self {
            readback_sender,
            readbacks,
            requests: Some(requests),
            results: outgoing,
            handle: Some(handle),
            pending: false,
        }
    }

    pub fn pending(&self) -> bool {
        self.pending
    }

    pub fn request(&self, ctx: &Context) {
        let sender = self.readback_sender.clone();
        let repaint = ctx.clone();
        ctx.request_screenshot(move |image| {
            // Retry callbacks may arrive together; retain at most one image.
            let _ = sender.try_send(image);
            repaint.request_repaint();
        });
    }

    pub fn submit(&mut self, image: Arc<ColorImage>) -> bool {
        if self.pending || self.requests.as_ref().unwrap().try_send(image).is_err() {
            return false;
        }
        self.pending = true;
        true
    }

    pub fn poll(&mut self) -> Option<Result<Duration, String>> {
        if let Ok(image) = self.readbacks.try_recv() {
            self.submit(image);
        }
        let result = self.results.try_recv().ok()?;
        self.pending = false;
        Some(result)
    }
}

impl Drop for Writer {
    fn drop(&mut self) {
        self.requests.take();
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn screenshot_callbacks_bound_readbacks_and_encode_only_on_worker() {
        let ui_thread = thread::current().id();
        let (encoded, observed) = mpsc::sync_channel(1);
        let mut writer = Writer::with_encoder(move |_| {
            encoded.send(thread::current().id()).unwrap();
            Ok(())
        });
        let ctx = Context::default();
        let output = ctx.run_ui(Default::default(), |ui| {
            for _ in 0..3 {
                writer.request(ui.ctx());
            }
        });
        let image = Arc::new(ColorImage::filled([1, 1], eframe::egui::Color32::BLACK));
        let mut requests = 0;
        for command in &output.viewport_output[&eframe::egui::ViewportId::ROOT].commands {
            if let eframe::egui::ViewportCommand::Screenshot(callback) = command {
                callback.clone().complete(image.clone());
                requests += 1;
            }
        }
        output.drop_without_applying_deltas();
        assert_eq!(requests, 3);
        assert_eq!(Arc::strong_count(&image), 2);
        assert!(observed.try_recv().is_err());
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            if let Some(result) = writer.poll() {
                result.unwrap();
                break;
            }
            assert!(Instant::now() < deadline);
            thread::yield_now();
        }
        assert_ne!(observed.recv().unwrap(), ui_thread);
        assert!(!writer.pending());
    }

    #[test]
    fn slow_write_never_blocks_ui_or_accumulates_images_and_failure_can_retry() {
        let (started, began) = mpsc::sync_channel(1);
        let (finish, resume) = mpsc::sync_channel(1);
        let mut writer = Writer::with_encoder(move |_| {
            started.send(()).unwrap();
            resume.recv().unwrap();
            Err("disk unavailable".into())
        });
        let image = Arc::new(ColorImage::filled([1, 1], eframe::egui::Color32::BLACK));
        for _ in 0..2 {
            assert!(writer.submit(image.clone()));
            began.recv_timeout(Duration::from_secs(5)).unwrap();
            assert!(writer.pending());
            assert!(writer.poll().is_none());
            assert!(!writer.submit(image.clone()));
            assert!(Arc::strong_count(&image) <= 2);
            finish.send(()).unwrap();
            let deadline = Instant::now() + Duration::from_secs(5);
            let result = loop {
                if let Some(result) = writer.poll() {
                    break result;
                }
                assert!(Instant::now() < deadline);
                thread::yield_now();
            };
            assert_eq!(result.unwrap_err(), "disk unavailable");
            assert!(!writer.pending());
        }
    }
}
