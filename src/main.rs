use eframe::{egui, egui_wgpu::wgpu};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(feature = "qa")]
    measurelab::qa::init_logging();
    #[cfg(not(feature = "qa"))]
    if std::env::var_os("MEASURELAB_PROFILE_SECONDS").is_some() {
        return Err("UI profiling requires --features qa".into());
    }
    let mut low_latency = false;
    let mut smoke = false;
    let mut demo = false;
    let mut compact = false;
    let mut audio_smoke = false;
    let mut stft_smoke = false;
    let mut multichannel_smoke = false;
    let mut lockin_smoke = false;
    let mut physical_lockin_smoke = false;
    let mut gpu_smoke = false;
    let mut list_devices = false;
    let mut new_instance = false;
    let mut input_device = None;
    let mut sample_rate = None;
    let mut channel = 0;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--audio-smoke" => audio_smoke = true,
            "--stft-smoke" => stft_smoke = true,
            "--multichannel-smoke" => multichannel_smoke = true,
            "--lockin-smoke" => {
                if !cfg!(feature = "qa") {
                    return Err("--lockin-smoke requires --features qa".into());
                }
                lockin_smoke = true;
            }
            "--physical-lockin-smoke" => {
                if !cfg!(feature = "qa") {
                    return Err("--physical-lockin-smoke requires --features qa".into());
                }
                physical_lockin_smoke = true;
            }
            "--new-instance" => new_instance = true,
            "--input-device" => {
                input_device = Some(args.next().ok_or("--input-device requires a name")?)
            }
            "--sample-rate" => {
                let rate = args
                    .next()
                    .ok_or("--sample-rate requires a rate in Hz")?
                    .parse()?;
                measurelab::audio::validate_sample_rate(rate)?;
                sample_rate = Some(rate);
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
            "--ui-smoke" => {
                if !cfg!(feature = "qa") {
                    return Err("--ui-smoke requires --features qa".into());
                }
                smoke = true;
            }
            "--demo" => {
                if !cfg!(feature = "qa") {
                    return Err("--demo requires --features qa".into());
                }
                demo = true;
            }
            "--compact" => compact = true,
            "--help" | "-h" => {
                println!(
                    "MeasureLab — GPU audio measurement lab\n\nOptions:\n  --new-instance Explicitly allow another application or audio-check instance\n  --compact     Start in a smaller window with responsive instrument views\n  --low-latency Disable VSync (higher GPU usage)\n  --list-devices List CPAL input devices\n  --audio-smoke Capture input for two seconds and report every channel\n  --stft-smoke  Validate continuous STFT window order for two seconds\n  --input-device NAME  Choose a device for --audio-smoke / --stft-smoke\n  --sample-rate HZ  Input rate for --audio-smoke / --stft-smoke (up to 768000)\n  --channel N   Source channel for --stft-smoke (1-based, default 1)\n  --gpu-smoke   Validate independent GPU plots with offscreen readback\n  --help       Show this help"
                );
                #[cfg(feature = "qa")]
                println!(
                    "\nQA options:\n  --demo        Enable and start an internal demo signal (no audio output)\n  --ui-smoke    Check instrument navigation and capture the test UI briefly, then close\n  --multichannel-smoke Validate 16 distinct BlackHole tones\n  --lockin-smoke Validate synchronous REF/response through BlackHole (default 2ch, 48000 Hz)\n  --physical-lockin-smoke Explicitly drive ZOOM UAC-232 stereo loopback at 0.1 FS peak; requires --input-device NAME"
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
        lockin_smoke,
        physical_lockin_smoke,
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
    if ((input_device.is_some() || sample_rate.is_some())
        && !audio_smoke
        && !stft_smoke
        && !lockin_smoke
        && !physical_lockin_smoke)
        || (channel != 0 && !stft_smoke)
    {
        return Err(
            "--input-device / --sample-rate require an audio or Lock-in smoke check; --channel requires --stft-smoke"
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
            if audio_smoke
                || stft_smoke
                || multichannel_smoke
                || lockin_smoke
                || physical_lockin_smoke
                || smoke
            {
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
    #[cfg(feature = "qa")]
    if physical_lockin_smoke {
        return measurelab::qa::physical_lockin::smoke_test(
            input_device
                .as_deref()
                .ok_or("--physical-lockin-smoke requires --input-device NAME")?,
            sample_rate.unwrap_or(48000),
        );
    }
    #[cfg(feature = "qa")]
    if lockin_smoke {
        return measurelab::qa::lockin::smoke_test(
            input_device.as_deref().unwrap_or("BlackHole 2ch"),
            sample_rate.unwrap_or(48000),
        );
    }
    if audio_smoke {
        return measurelab::audio::smoke_test(input_device.as_deref(), sample_rate)
            .map_err(Into::into);
    }
    if stft_smoke {
        return measurelab::stft::smoke_test(input_device.as_deref(), channel, sample_rate)
            .map_err(Into::into);
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
    let surface_skips = std::sync::Arc::new(std::sync::atomic::AtomicU64::new(0));
    #[cfg(feature = "qa")]
    if smoke {
        let on_surface_status = options.wgpu_options.on_surface_status.clone();
        let skipped = surface_skips.clone();
        options.wgpu_options.on_surface_status = std::sync::Arc::new(move |status| {
            let count = skipped.fetch_add(1, std::sync::atomic::Ordering::Relaxed) + 1;
            if count <= 4 {
                eprintln!("QA surface acquisition skipped #{count}: {status:?}");
            }
            on_surface_status(status)
        });
        // Metal skips frame acquisition for fully covered windows, so a smoke
        // capture must remain visible while Codex or a terminal has focus.
        // The alternate levels are opt-in diagnostics for reproducing this.
        match std::env::var("MEASURELAB_UI_SMOKE_FOREGROUND").as_deref() {
            Ok("0") => {}
            Ok("bottom") => {
                options.viewport = options
                    .viewport
                    .with_window_level(egui::WindowLevel::AlwaysOnBottom);
            }
            _ => options.viewport = options.viewport.with_always_on_top(),
        }
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
    if smoke {
        println!(
            "QA skipped surface acquisitions: {}",
            surface_skips.load(std::sync::atomic::Ordering::Relaxed)
        );
    }
    #[cfg(feature = "qa")]
    if smoke
        && std::env::var_os("MEASURELAB_UI_SMOKE_ASSERTIONS_ONLY").is_none()
        && !std::path::Path::new("dist/ui-smoke.png").exists()
    {
        return Err("UI screenshot was not received".into());
    }
    Ok(())
}
