use super::*;
use crate::tests::{request, wait};
use graph_core::result::DeviceBinding;

#[test]
fn fixed_filter_requires_explicit_precision_and_rate_before_opening_input() {
    for precision in [Precision::F32, Precision::F64] {
        let mut config = request(precision, 2, false);
        let input = config.input.clone().unwrap();
        config.filter = Some(FilterRequest {
            input_conversion: Some(InputConversion::F32ToF64Exact),
        });
        assert_eq!(config.validate().is_ok(), precision == Precision::F32);
        config.filter.as_mut().unwrap().input_conversion = None;
        assert_eq!(config.validate().is_ok(), precision == Precision::F64);
        config.format.rate = [44100, 1];
        assert!(config.validate().is_err());
        std::fs::remove_file(input).unwrap();
    }
}

#[test]
fn derived_views_trigger_calibration_codecs_and_restart_keep_owned_snapshots() {
    for precision in [Precision::F32, Precision::F64] {
        for channels in [2, 4, 8] {
            let mut config = request(precision, channels, false);
            let input = config.input.clone().unwrap();
            config.n /= 2; // The replay fixture contains twice as many parent frames.
            config.format.input_ports.reverse();
            config.filter = Some(FilterRequest {
                input_conversion: (precision == Precision::F32)
                    .then_some(InputConversion::F32ToF64Exact),
            });
            config.calibration = vec![ChannelCalibration {
                channel_id: config.format.input_ids[0].clone(),
                revision: "filter.profile".into(),
                device_binding: DeviceBinding {
                    device: config.calibration_device(),
                    port: config.format.input_ports[0] as u32,
                },
                is_calibrated: true,
                v_per_fs: 2.,
            }];
            let mut display = Display::with_request(config.clone());
            let a = display.subscribe();
            display.subscribe();
            let generation = display.start(false, |_| true).unwrap();
            wait(&display, |s| s.produced >= 2);
            let snapshot = display.take(generation).unwrap();
            let normal = snapshot.frame.as_ref().unwrap();
            assert_eq!(normal.result.source().precision, Precision::F64);
            assert_eq!(normal.result.source().timebase.rate.numerator, 24000);
            assert!(normal.result.validity().is_empty());
            let document = normal.result.to_value();
            assert_eq!(
                document["conditions"]["filter"]["parent"]["precision"],
                json!(precision)
            );
            assert_eq!(
                document["conditions"]["filter"]["parent"]["timebase"]["rate"]["numerator"],
                48000
            );
            let peaks = &document["columns"]["peak_fs"]["values"];
            for c in 0..channels {
                let port = channels - c - 1;
                let bin = 7 + port;
                let expected = (port + 1) as f64 / 32.
                    * (std::f64::consts::PI * bin as f64 / 256.).cos().powi(2);
                assert!((peaks[bin * channels + c].as_f64().unwrap() - expected).abs() < 1e-8);
            }
            let source = normal.result.source();
            let start = normal.result.interval()[0];
            let submission = json!({"revision": 1, "request": {"request_id": "filtered.manual", "pre": config.n / 2, "post": config.n / 2,
                "event": {"id": "derived.event", "stream_id": source.stream_id, "timebase_id": source.timebase.id, "generation": generation,
                    "sample": {"numerator": (start + config.n as u64 / 2) * 2 + 1, "denominator": 2},
                    "source": "manual", "kind": "manual", "polarity": "none", "condition_revision": "v1", "validity": [], "received_host_seconds": null}}}).to_string();
            assert!(display.request_trigger(&submission));
            wait(&display, |s| {
                s.trigger.as_ref().is_some_and(|r| r.frame.is_some())
            });
            let snapshot = display.take(generation).unwrap();
            let held = snapshot
                .trigger
                .as_ref()
                .unwrap()
                .frame
                .as_ref()
                .unwrap()
                .result
                .clone();
            let expected = held.to_value();
            assert_eq!(held.interval(), [start, start + config.n as u64]);
            assert_eq!(
                expected["conditions"]["filter"],
                document["conditions"]["filter"]
            );
            for format in [Format::Json, Format::Csv] {
                assert_eq!(
                    MeasurementResult::decode(&held.encode(format).unwrap(), format)
                        .unwrap()
                        .to_value(),
                    expected
                );
            }
            let mut tampered = expected.clone();
            tampered["conditions"]["filter"]["parent"]["generation"] = json!(generation + 1);
            assert!(
                MeasurementResult::decode(&serde_json::to_vec(&tampered).unwrap(), Format::Json)
                    .is_err()
            );
            tampered = expected.clone();
            tampered["conditions"]["filter"]["signal_delay_output_samples"]["numerator"] = json!(0);
            assert!(
                MeasurementResult::decode(&serde_json::to_vec(&tampered).unwrap(), Format::Json)
                    .is_err()
            );
            display.present(&snapshot);
            assert!(display.pin_result(generation, &held.capture().result_id));
            assert!(display.unsubscribe(a));
            let before = display.peek().produced;
            wait(&display, |s| s.produced > before + 2);
            display.shutdown();
            assert!(display.peek().reclaimed);
            let next = display.start(false, |_| true).unwrap();
            assert!(!display.request_trigger(&submission));
            wait(&display, |s| s.produced >= 2 && s.generation == next);
            display.shutdown();
            assert_eq!(held.to_value(), expected);
            std::fs::remove_file(input).unwrap();
        }
    }
}
