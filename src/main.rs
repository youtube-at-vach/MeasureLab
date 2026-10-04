use eframe::{egui, egui_wgpu::wgpu};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut low_latency = false;
    let mut smoke = false;
    let mut demo = false;
    let mut compact = false;
    let mut audio_smoke = false;
    let mut stft_smoke = false;
    let mut multichannel_smoke = false;
    let mut gpu_smoke = false;
    let mut list_devices = false;
    let mut new_instance = false;
    let mut input_device = None;
    let mut channel = 0;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--audio-smoke" => audio_smoke = true,
            "--stft-smoke" => stft_smoke = true,
            "--multichannel-smoke" => multichannel_smoke = true,
            "--new-instance" => new_instance = true,
            "--input-device" => {
                input_device = Some(args.next().ok_or("--input-device requires a name")?)
            }
            "--channel" => {
                channel = args
                    .next()
                    .ok_or("--channel requires a one-based channel number")?
                    .parse::<usize>()?
                    .checked_sub(1)
                    .ok_or("Channel numbers start at 1")?;
            }
            "--gpu-smoke" => gpu_smoke = true,
            "--list-devices" => list_devices = true,
            "--low-latency" => low_latency = true,
            "--ui-smoke" => smoke = true,
            "--demo" => demo = true,
            "--compact" => compact = true,
            "--help" | "-h" => {
                println!(
                    "MeasureLab — GPU audio measurement lab\n\nOptions:\n  --demo        Start with an internal signal (no microphone or audio output)\n  --new-instance Explicitly allow another application or audio-check instance\n  --compact     Start in a smaller window with stacked plots\n  --low-latency Disable VSync (higher GPU usage)\n  --list-devices List CPAL input devices\n  --audio-smoke Capture input for two seconds and report every channel\n  --stft-smoke  Validate continuous STFT window order for two seconds\n  --multichannel-smoke Validate 16 distinct BlackHole tones (requires qa)\n  --input-device NAME  Choose a device for --audio-smoke / --stft-smoke\n  --channel N   Source channel for --stft-smoke (1-based, default 1)\n  --gpu-smoke   Validate independent GPU plots with offscreen readback\n  --ui-smoke    Open the scope + spectrum UI briefly, then close\n  --help       Show this help"
                );
                return Ok(());
            }
            other => return Err(format!("Unknown option: {other}").into()),
        }
    }
    if [
        audio_smoke,
        stft_smoke,
        multichannel_smoke,
        gpu_smoke,
        list_devices,
        smoke,
    ]
    .iter()
    .filter(|&&selected| selected)
    .count()
        > 1
    {
        return Err("Choose one smoke check or --list-devices".into());
    }
    if (input_device.is_some() && !audio_smoke && !stft_smoke) || (channel != 0 && !stft_smoke) {
        return Err(
            "--input-device requires --audio-smoke / --stft-smoke; --channel requires --stft-smoke"
                .into(),
        );
    }
    if list_devices {
        use cpal::traits::HostTrait;
        for (index, device) in cpal::default_host().input_devices()?.enumerate() {
            println!("{index}: {device}");
        }
        return Ok(());
    }
    if gpu_smoke {
        return measurelab::gpu::smoke_test();
    }
    #[cfg(not(feature = "qa"))]
    if multichannel_smoke {
        return Err("--multichannel-smoke requires --features qa".into());
    }
    let _instance = match measurelab::instance::Instance::acquire()? {
        Some(instance) => Some(instance),
        None if new_instance => None,
        None => {
            let message = "MeasureLab is already running. Close it first, or use --new-instance to open another instance.";
            if audio_smoke || stft_smoke || multichannel_smoke || smoke {
                return Err(message.into());
            }
            println!("{message}");
            return Ok(());
        }
    };
    #[cfg(feature = "qa")]
    if multichannel_smoke {
        return measurelab::qa::multichannel_smoke_test();
    }
    if audio_smoke {
        return measurelab::audio::smoke_test(input_device.as_deref()).map_err(Into::into);
    }
    if stft_smoke {
        return measurelab::stft::smoke_test(input_device.as_deref(), channel).map_err(Into::into);
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
