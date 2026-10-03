use super::*;
use serde_json::Value;
use std::time::Instant;

pub(super) fn request(precision: Precision, channels: usize, invalid: bool) -> Request {
    let id = TOKEN.fetch_add(1, Ordering::SeqCst);
    let path = std::env::temp_dir().join(format!(
        "measurelab-display-{}-{id}.bin",
        std::process::id()
    ));
    let n = 256;
    let mut bytes = Vec::new();
    for i in 0..n {
        for c in 0..channels {
            let value = if invalid && c == 0 {
                f64::NAN
            } else {
                (c + 1) as f64 / 32.
                    * (std::f64::consts::TAU * (7 + c) as f64 * i as f64 / n as f64).cos()
            };
            if precision == Precision::F32 {
                bytes.extend((value as f32).to_le_bytes());
            } else {
                bytes.extend(value.to_le_bytes());
            }
        }
    }
    std::fs::write(&path, bytes).unwrap();
    Request {
        format: IoFormat {
            stream_id: "saved.input".into(),
            generation: 1,
            timebase_id: "saved.clock".into(),
            clock_domain: "saved.unverified".into(),
            rate: [48000, 1],
            input_ids: (0..channels).map(|c| format!("input.{c}")).collect(),
            input_ports: (0..channels).collect(),
            output_ids: vec![],
            output_ports: vec![],
        },
        precision,
        n,
        window: WindowSpec::Boxcar,
        input: Some(path),
        live: None,
        evidence: None,
        save_input_evidence: false,
        save_diagnostic_delay_ms: 0,
        calibration: vec![],
    }
}
pub(super) fn wait(display: &Display, condition: impl Fn(&Snapshot) -> bool) {
    let deadline = Instant::now() + Duration::from_secs(5);
    while !condition(&display.peek()) {
        assert!(
            Instant::now() < deadline,
            "timeout: {:?} {}",
            display.peek().state,
            display.peek().error
        );
        thread::sleep(Duration::from_millis(2));
    }
}
#[test]
fn saved_precision_channel_ids_projection_sharing_and_held_result() {
    for precision in [Precision::F32, Precision::F64] {
        for channels in [4, 8] {
            let request = request(precision, channels, false);
            let path = request.input.clone().unwrap();
            let mut display = Display::with_request(request);
            display.subscribe();
            display.subscribe();
            let generation = display.start(false, |_| true).unwrap();
            wait(&display, |s| s.produced >= 2);
            let held = display.take(generation).unwrap().frame.unwrap();
            let document = held.result.to_value();
            let projection: Value = serde_json::from_str(&held.projection).unwrap();
            assert_eq!(projection["peak_fs"], document["columns"]["peak_fs"]);
            assert_eq!(projection["frequency_hz"], document["axis"]["corrected"]);
            assert_eq!(
                projection["source"]["channel_ids"]
                    .as_array()
                    .unwrap()
                    .len(),
                channels
            );
            assert!(projection["source"]["timebase"]["origin_seconds"].is_null());
            for c in 0..channels {
                let amplitude = projection["peak_fs"]["values"][(7 + c) * channels + c]
                    .as_f64()
                    .unwrap();
                assert!((amplitude - (c + 1) as f64 / 32.).abs() < 1e-7);
            }
            let before = display.peek().produced;
            wait(&display, |s| s.produced > before + 2);
            assert!(display.peek().shared && display.peek().coalesced > 0);
            display.shutdown();
            assert!(display.peek().reclaimed);
            assert_eq!(document, held.result.to_value());
            std::fs::remove_file(path).unwrap();
        }
    }
}
#[test]
fn real_graph_demand_session_restart_and_stale_notification() {
    let request = request(Precision::F64, 4, false);
    let path = request.input.clone().unwrap();
    let mut display = Display::with_request(request);
    assert!(display.start(false, |_| true).is_none());
    let first = display.subscribe();
    let second = display.subscribe();
    let session = display.subscribe();
    let old = display.start(false, |_| true).unwrap();
    assert!(display.start(false, |_| true).is_none());
    wait(&display, |s| s.produced >= 2);
    display.unsubscribe(first);
    display.unsubscribe(second);
    assert_eq!(display.subscribers(), 1);
    let before = display.peek().produced;
    wait(&display, |s| s.produced > before);
    assert!(display.unsubscribe(session));
    assert!(!display.unsubscribe(session));
    display.shutdown();
    assert!(display.peek().reclaimed);
    display.subscribe();
    let current = display.start(false, |_| true).unwrap();
    wait(&display, |s| s.produced >= 1);
    assert!(display.take(old).is_none());
    assert!(display.mailbox.lock().unwrap().pending);
    assert_eq!(display.take(current).unwrap().generation, current);
    display.shutdown();
    std::fs::remove_file(path).unwrap();
}
#[test]
fn invalid_values_are_null_with_reason_never_a_normal_zero() {
    let request = request(Precision::F64, 4, true);
    let path = request.input.clone().unwrap();
    let mut display = Display::with_request(request);
    display.subscribe();
    display.start(false, |_| true).unwrap();
    wait(&display, |s| s.frame.is_some());
    let value: Value = serde_json::from_str(&display.peek().frame.unwrap().projection).unwrap();
    assert!(!value["validity"].as_array().unwrap().is_empty());
    assert!(value["peak_fs"]["values"][0].is_null());
    assert!(value["peak_fs"]["reasons"][0].as_str().is_some());
    display.shutdown();
    std::fs::remove_file(path).unwrap();
}
#[test]
fn cancel_failure_bad_input_and_disconnected_gui_reclaim() {
    let request = request(Precision::F32, 4, false);
    let path = request.input.clone().unwrap();
    let mut display = Display::with_request(request);
    display.subscribe();
    display.start(false, |_| true).unwrap();
    display.shutdown();
    assert_eq!(display.peek().outcome, 2);
    display.start(true, |_| true).unwrap();
    wait(&display, |s| s.state == State::Failed);
    display.shutdown();
    assert_eq!(display.peek().outcome, 3);
    display.start(false, |_| false).unwrap();
    wait(&display, |s| s.outcome == 1);
    display.shutdown();
    assert!(display.peek().reclaimed);
    std::fs::write(&path, [0]).unwrap();
    display.start(false, |_| true).unwrap();
    wait(&display, |s| s.state == State::Failed);
    display.shutdown();
    assert_eq!(display.peek().error, "display_input_shape");
    std::fs::remove_file(path).unwrap();
}
#[test]
fn demand_is_bounded_and_foreign_tokens_rejected() {
    let mut display = Display::default();
    let mut other = Display::default();
    assert!(!display.unsubscribe(other.subscribe()));
    for _ in 0..MAX_DEMAND {
        assert_ne!(display.subscribe(), 0);
    }
    assert_eq!(display.subscribe(), 0);
    assert_eq!(display.subscribers(), MAX_DEMAND);
}

#[test]
fn source_choice_precision_and_live_ports_are_validated_without_opening() {
    let mut request = request(Precision::F32, 4, false);
    let path = request.input.clone().unwrap();
    request.validate().unwrap();
    request.live = Some(LiveRequest {
        device: "BlackHole 16ch".into(),
        device_channels: 16,
    });
    assert!(request.validate().is_err()); // two sources
    request.input = None;
    assert!(request.validate().is_err()); // clock domain must identify exact device
    request.format.clock_domain = "cpal.device:BlackHole 16ch".into();
    request.format.input_ports = vec![15, 13, 11, 9];
    request.validate().unwrap();
    request.precision = Precision::F64;
    assert!(request.validate().is_err());
    request.precision = Precision::F32;
    request.format.input_ports[0] = 16;
    assert!(request.validate().is_err());
    request.live = None;
    assert!(request.validate().is_err()); // no source
    std::fs::remove_file(path).unwrap();
}

#[test]
fn unavailable_live_input_fails_and_reclaims_instead_of_replaying() {
    let mut request = request(Precision::F32, 2, false);
    let path = request.input.take().unwrap();
    let name = "MeasureLab deliberately unavailable evaluation device";
    request.live = Some(LiveRequest {
        device: name.into(),
        device_channels: 2,
    });
    request.format.clock_domain = format!("cpal.device:{name}");
    let mut display = Display::with_request(request);
    display.subscribe();
    display.start(false, |_| true).unwrap();
    wait(&display, |s| s.state == State::Failed);
    display.shutdown();
    let state = display.peek();
    assert!(state.reclaimed && state.frame.is_none() && state.produced == 0);
    #[cfg(feature = "live-audio")]
    assert_eq!(state.error, "live_exact_device_not_unique");
    #[cfg(not(feature = "live-audio"))]
    assert_eq!(state.error, "display_live_feature_disabled");
    std::fs::remove_file(path).unwrap();
}

#[test]
fn slow_save_diagnostics_require_live_evidence_and_bound_latency() {
    let mut request = request(Precision::F32, 2, false);
    let path = request.input.clone().unwrap();
    request.save_diagnostic_delay_ms = 250;
    assert!(request.validate().is_err());
    request.save_input_evidence = true;
    assert!(request.validate().is_err());
    request.input = None;
    request.live = Some(LiveRequest {
        device: "diagnostic".into(),
        device_channels: 2,
    });
    request.format.clock_domain = "cpal.device:diagnostic".into();
    assert!(request.validate().is_err());
    request.evidence = Some(path.with_extension("evidence"));
    request.validate().unwrap();
    request.save_diagnostic_delay_ms = 501;
    assert!(request.validate().is_err());
    std::fs::remove_file(path).unwrap();
}
