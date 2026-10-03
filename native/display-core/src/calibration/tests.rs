use super::*;
use crate::tests::{request, wait};
use serde_json::Value;

fn profiles(config: &Request) -> Vec<ChannelCalibration> {
    (0..config.format.input_ids.len() - 1)
        .rev()
        .map(|index| ChannelCalibration {
            channel_id: config.format.input_ids[index].clone(),
            revision: format!("diagnostic.{index}"),
            device_binding: DeviceBinding {
                device: config.calibration_device(),
                port: config.format.input_ports[index] as u32,
            },
            is_calibrated: index != config.format.input_ids.len() - 2,
            v_per_fs: 1. + index as f64 / 4.,
        })
        .collect()
}

#[test]
fn channel_bound_calibration_normal_trigger_and_profile_restart_are_immutable() {
    for precision in [Precision::F32, Precision::F64] {
        for channels in [4, 8] {
            let mut config = request(precision, channels, false);
            let path = config.input.clone().unwrap();
            config.format.input_ports.reverse();
            config.calibration = profiles(&config);
            config.validate().unwrap();
            let mut display = Display::with_request(config.clone());
            display.subscribe();
            display.subscribe();
            config.format.generation = display.start(false, |_| true).unwrap();
            let submission = json!({"revision": 1, "request": {
                "request_id": "calibration.trigger", "pre": config.n / 2, "post": config.n / 2,
                "event": {"id": "event.1", "stream_id": config.format.stream_id,
                    "generation": config.format.generation, "timebase_id": config.format.timebase_id,
                    "sample": {"numerator": config.n + 1, "denominator": 2},
                    "source": "test.manual", "kind": "edge", "polarity": "rising",
                    "condition_revision": "test.v1", "validity": [], "received_host_seconds": null}
            }}).to_string();
            assert!(display.request_trigger(&submission));
            wait(&display, |s| {
                s.produced >= 1 && s.trigger.as_ref().is_some_and(|r| r.frame.is_none())
            });
            assert!(display.retry_trigger(config.format.generation, 1));
            wait(&display, |s| {
                s.trigger.as_ref().is_some_and(|r| r.frame.is_some())
            });
            let normal = display.peek().frame.unwrap();
            let trigger = display.peek().trigger.unwrap().frame.clone().unwrap();
            let held = trigger.result.to_value();
            for frame in [&normal, &trigger] {
                let document = frame.result.to_value();
                let projection: Value = serde_json::from_str(&frame.projection).unwrap();
                assert_eq!(projection["calibration"], "partial");
                assert_eq!(projection["channel_calibration"], document["calibration"]);
                assert_eq!(projection["rms_v"], document["columns"]["rms_v"]);
                for index in 0..channels {
                    let c = &document["calibration"][index];
                    assert_eq!(c["channel_id"], config.format.input_ids[index]);
                    if index < channels - 1 {
                        assert_eq!(c["profile"]["applied_interval"], document["interval"]);
                        assert_eq!(c["profile"]["device_binding"]["port"], channels - 1 - index);
                    } else {
                        assert!(c["profile"].is_null());
                    }
                    if index < channels - 2 {
                        let expected = (channels - index) as f64 / 32. / 2_f64.sqrt()
                            * (1. + index as f64 / 4.);
                        assert!(
                            (projection["rms_v"]["values"][index].as_f64().unwrap() - expected)
                                .abs()
                                < 1e-7
                        );
                    } else {
                        assert!(projection["rms_v"]["values"][index].is_null());
                        assert_eq!(projection["rms_v"]["reasons"][index], "uncalibrated");
                    }
                }
            }
            display.shutdown();
            let json = path.with_extension("json");
            save_result(&trigger.result, &json, &config).unwrap();
            let csv = json.with_extension("csv");
            for (file, format) in [(&json, Format::Json), (&csv, Format::Csv)] {
                assert_eq!(
                    held,
                    MeasurementResult::load(file, format).unwrap().to_value()
                );
                std::fs::remove_file(file).unwrap();
            }
            config.calibration[0].v_per_fs = 100.;
            config.calibration[0].revision = "replacement".into();
            display.request = Some(config);
            let generation = display.start(false, |_| true).unwrap();
            wait(&display, |s| s.generation == generation && s.produced >= 1);
            display.shutdown();
            assert_eq!(held, trigger.result.to_value());
            drop(display);
            assert_eq!(held, trigger.result.to_value());
            std::fs::remove_file(path).unwrap();
        }
    }
}

#[test]
fn wrong_device_port_channel_duplicate_or_invalid_factor_fails_before_acquisition() {
    let mut config = request(Precision::F32, 4, false);
    let path = config.input.clone().unwrap();
    config.calibration = profiles(&config);
    for fault in 0..8 {
        let mut broken = config.clone();
        match fault {
            0 => broken.calibration[0].device_binding.device = "other".into(),
            1 => broken.calibration[0].device_binding.port = 0,
            2 => broken.calibration[0].channel_id = "unknown".into(),
            3 => broken.calibration.push(broken.calibration[0].clone()),
            4 => broken.calibration[0].v_per_fs = 0.,
            5 => broken.calibration[0].v_per_fs = f64::INFINITY,
            6 => broken.calibration[0].revision = " ".into(),
            _ => broken.calibration[0].revision = "x".repeat(257),
        }
        assert!(broken.validate().is_err());
        let mut display = Display::with_request(broken);
        display.subscribe();
        display.start(false, |_| true).unwrap();
        wait(&display, |s| s.state == State::Failed);
        display.shutdown();
        assert!(display.peek().reclaimed);
        assert_eq!(display.peek().produced, 0);
        assert!(display.peek().frame.is_none());
    }
    // Retargeting to a live device requires explicit new bindings, before stream open.
    config.input = None;
    config.live = Some(LiveRequest {
        backend: Backend::Cpal,
        library: None,
        device: "BlackHole 16ch".into(),
        device_channels: 16,
    });
    config.format.clock_domain = "cpal.device:BlackHole 16ch".into();
    assert!(config.validate().is_err());
    config.calibration = profiles(&config);
    config.validate().unwrap();
    std::fs::remove_file(path).unwrap();
}

#[test]
fn live_csv_is_deferred_reads_full_snapshot_and_reports_no_clobber_failure() {
    let mut config = request(Precision::F64, 4, false);
    let input = config.input.clone().unwrap();
    config.calibration = profiles(&config);
    let mut display = Display::with_request(config.clone());
    display.subscribe();
    config.format.generation = display.start(false, |_| true).unwrap();
    wait(&display, |s| s.frame.is_some());
    let frame = display.peek().frame.unwrap();
    display.shutdown();
    // No hardware is needed to check the diagnostic writer's lifetime boundary.
    let directory = input.with_extension("evidence");
    std::fs::create_dir(&directory).unwrap();
    config.evidence = Some(directory.clone());
    config.live = Some(LiveRequest {
        backend: Backend::Cpal,
        library: None,
        device: "diagnostic".into(),
        device_channels: 4,
    });
    let json = directory.join(format!("generation-{}.json", config.format.generation));
    save_result(&frame.result, &json, &config).unwrap();
    let csv = json.with_extension("csv");
    assert!(!csv.exists());
    config.calibration.clear(); // final session state cannot discard saved calibration
    finish_live_evidence(&config).unwrap();
    assert_eq!(
        frame.result.to_value(),
        MeasurementResult::load(&csv, Format::Csv)
            .unwrap()
            .to_value()
    );
    let previous = std::fs::read(&csv).unwrap();
    assert!(finish_live_evidence(&config).is_err());
    assert_eq!(previous, std::fs::read(&csv).unwrap());
    std::fs::remove_dir_all(directory).unwrap();
    std::fs::remove_file(input).unwrap();
}

fn edit(config: &Request, generation: u64, revision: u64) -> String {
    json!({"generation": generation, "revision": revision, "profiles": config.calibration})
        .to_string()
}

#[test]
fn editing_running_profiles_preserves_relative_values_held_results_and_restart_config() {
    for precision in [Precision::F32, Precision::F64] {
        for channels in [4, 8] {
            let mut config = request(precision, channels, false);
            let path = config.input.clone().unwrap();
            config.format.input_ports.reverse();
            config.calibration = profiles(&config);
            let mut display = Display::with_request(config.clone());
            display.subscribe();
            display.subscribe();
            let generation = display.start(false, |_| true).unwrap();
            wait(&display, |s| s.produced >= 1);
            let held = display.peek().frame.unwrap();
            let before = held.result.to_value();
            for p in &mut config.calibration {
                p.revision = "edited".into();
                p.v_per_fs *= 3.;
            }
            assert!(display.apply_calibration(&edit(&config, generation, 1)));
            wait(&display, |s| {
                s.frame.as_ref().is_some_and(|f| {
                    f.result.to_value()["calibration"][0]["profile"]["revision"] == "edited"
                })
            });
            let after = display.peek().frame.unwrap().result.to_value();
            assert_eq!(after["source"], before["source"]);
            assert_eq!(after["columns"]["peak_fs"], before["columns"]["peak_fs"]);
            for index in 0..channels - 2 {
                let initial = before["columns"]["rms_v"]["values"][index]
                    .as_f64()
                    .unwrap();
                let current = after["columns"]["rms_v"]["values"][index].as_f64().unwrap();
                assert!((current / initial - 3.).abs() < 1e-8);
            }
            assert_eq!(held.result.to_value(), before);
            assert!(!display.apply_calibration(&edit(&config, generation - 1, 2)));
            assert!(!display.apply_calibration(&edit(&config, generation, 1)));
            display.shutdown();
            assert!(!display.apply_calibration(&edit(&config, generation, 2)));
            let next = display.start(false, |_| true).unwrap();
            wait(&display, |s| s.generation == next && s.frame.is_some());
            assert_ne!(
                display.peek().frame.unwrap().result.to_value()["calibration"][0]["profile"]["revision"],
                "edited"
            );
            display.shutdown();
            drop(display);
            assert_eq!(held.result.to_value(), before);
            std::fs::remove_file(path).unwrap();
        }
    }
}

#[test]
fn bounded_edit_mailbox_rejects_busy_stale_invalid_and_stopped_without_partial_update() {
    let mut config = request(Precision::F64, 4, false);
    let path = config.input.clone().unwrap();
    config.calibration = profiles(&config);
    let mut display = Display::with_request(config.clone());
    let owner = Owner {
        mailbox: display.mailbox.clone(),
        stop: display.stop.clone(),
    };
    initialize(&owner, &config);
    {
        let mut slot = display.mailbox.lock().unwrap();
        slot.snapshot.state = State::Running;
        slot.snapshot.generation = config.format.generation;
    }
    assert!(!display.apply_calibration(&" ".repeat(MAX_EDIT_BYTES + 1)));
    assert!(!display.apply_calibration("{\"generation\":1}"));
    let original = serde_json::to_value(&config.calibration).unwrap();
    for fault in 0..7 {
        let mut changed = config.clone();
        changed.calibration[0].v_per_fs = 99.; // must not apply even this valid part
        match fault {
            0 => changed.calibration[1].channel_id = "unknown".into(),
            1 => changed.calibration[1].device_binding.port = 99,
            2 => changed.calibration[1].device_binding.device = "other".into(),
            3 => changed.calibration[1].v_per_fs = 0.,
            4 => changed.calibration[1].revision = " ".into(),
            5 => changed.calibration[1].revision = "x".repeat(257),
            _ => changed.calibration.push(changed.calibration[0].clone()),
        }
        let revision = fault + 1;
        assert!(display.apply_calibration(&edit(&changed, 1, revision)));
        assert!(!display.apply_calibration(&edit(&changed, 1, revision + 1)));
        process(&owner, &|_| true, &mut config).unwrap();
        let receipt: Value = serde_json::from_str(&display.peek().calibration).unwrap();
        assert_eq!(receipt["status"], "rejected");
        assert_eq!(receipt["profiles"], original);
        assert_eq!(serde_json::to_value(&config.calibration).unwrap(), original);
    }
    assert!(display.apply_calibration(&edit(&config, 1, 8)));
    display.stop();
    process(&owner, &|_| true, &mut config).unwrap();
    let receipt: Value = serde_json::from_str(&display.peek().calibration).unwrap();
    assert_eq!(receipt["status"], "cancelled");
    assert_eq!(receipt["profiles"], original);
    std::fs::remove_file(path).unwrap();
}
