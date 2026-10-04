use eframe::{egui, egui_wgpu::wgpu};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut low_latency = false;
    let mut smoke = false;
    let mut demo = false;
    let mut compact = false;
    for arg in std::env::args().skip(1) {
        match arg.as_str() {
            "--audio-smoke" => return measurelab::audio::smoke_test().map_err(Into::into),
            "--gpu-smoke" => return measurelab::gpu::smoke_test(),
            "--list-devices" => {
                use cpal::traits::HostTrait;
                for (index, device) in cpal::default_host().input_devices()?.enumerate() {
                    println!("{index}: {device}");
                }
                return Ok(());
            }
            "--low-latency" => low_latency = true,
            "--ui-smoke" => smoke = true,
            "--demo" => demo = true,
            "--compact" => compact = true,
            "--help" | "-h" => {
                println!(
                    "MeasureLab — GPU audio measurement lab\n\nOptions:\n  --demo        Start with an internal signal (no microphone or audio output)\n  --compact     Start in a smaller window with stacked plots\n  --low-latency Disable VSync (higher GPU usage)\n  --list-devices List CPAL input devices\n  --audio-smoke Capture the default input for two seconds\n  --gpu-smoke   Validate independent GPU plots with offscreen readback\n  --ui-smoke    Open the scope + spectrum UI briefly, then close\n  --help       Show this help"
                );
                return Ok(());
            }
            other => return Err(format!("Unknown option: {other}").into()),
        }
    }
    let mut options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size(if compact {
                [1040.0, 780.0]
            } else {
                [1440.0, 860.0]
            })
            .with_min_inner_size([900.0, 660.0])
            .with_app_id("dev.measurelab.app"),
        renderer: eframe::Renderer::Wgpu,
        ..Default::default()
    };
    options.wgpu_options.surface.present_mode = if low_latency {
        wgpu::PresentMode::AutoNoVsync
    } else {
        wgpu::PresentMode::AutoVsync
    };
    if low_latency {
        options.wgpu_options.surface.desired_maximum_frame_latency = Some(1);
    }
    #[cfg(feature = "qa")]
    if smoke {
        let _ = std::fs::remove_file("dist/ui-smoke.png");
    }
    eframe::run_native(
        "MeasureLab · Audio Measurement Lab",
        options,
        Box::new(move |cc| Ok(Box::new(measurelab::app::ScopeApp::new(cc, smoke, demo)?))),
    )?;
    #[cfg(feature = "qa")]
    if smoke && !std::path::Path::new("dist/ui-smoke.png").exists() {
        return Err("UI screenshot was not received".into());
    }
    Ok(())
}
