use super::*;
use crate::{
    Average, FftKey, Graph, Limits, Presentation, Samples, SignalBlock, Timebase, WindowSpec,
};
use std::sync::Arc;

fn source() -> Source {
    Source {
        stream_id: "input".into(),
        generation: 3,
        channel_ids: vec!["b".into(), "a".into()],
        precision: Precision::F64,
        timebase: Timebase {
            id: "time".into(),
            revision: 0,
            clock_domain: "virtual".into(),
            generation: 3,
            rate: Rational {
                numerator: 48000,
                denominator: 1,
            },
            nominal_rate: Rational {
                numerator: 48000,
                denominator: 1,
            },
            origin_sample: 0,
            origin_seconds: None,
            origin_kind: "unknown".into(),
            uncertainty_seconds: None,
        },
        route_revision: "route.1".into(),
        tap: Tap::InputRaw,
        filter_state_revision: "none".into(),
        calibration_revision: "FS".into(),
    }
}
fn capture() -> Capture {
    Capture {
        result_id: "capture.1".into(),
        trigger_id: Some("trigger.1".into()),
        acquired_host_seconds: None,
        result_host_seconds: Some(Rational {
            numerator: 11,
            denominator: 1,
        }),
        trigger: None,
        clock_mapping: None,
    }
}
fn profiles() -> BTreeMap<String, Profile> {
    [(
        "a".into(),
        Profile {
            revision: "profile.1".into(),
            device_binding: DeviceBinding {
                device: "virtual,\"device\"\nα".into(),
                port: 0,
            },
            is_calibrated: true,
            v_per_fs: 2.0,
            applied_interval: [0, 4096],
        },
    )]
    .into()
}
fn tone() -> MeasurementResult {
    MeasurementResult::coherent_tone(
        &source(),
        [0, 16],
        capture(),
        &[0.5, 0.25],
        &profiles(),
        vec![1000., 2000.],
        1.0001,
    )
    .unwrap()
}

#[test]
fn id_bound_calibration_unknowns_and_profile_changes() {
    let mut p = profiles();
    let mut s = source();
    let old = MeasurementResult::coherent_tone(
        &s,
        [0, 16],
        capture(),
        &[0.5, 0.25],
        &p,
        vec![1000.],
        1.0001,
    )
    .unwrap();
    let bytes = old.encode(Format::Json).unwrap();
    let v = old.to_value();
    assert!(v["columns"]["rms_v"]["values"][0].is_null());
    assert_eq!(v["columns"]["rms_v"]["reasons"][0], "uncalibrated");
    assert_eq!(
        v["columns"]["rms_v"]["values"][1].as_f64().unwrap(),
        0.5 / 2.0_f64.sqrt()
    );
    assert!(v["source"]["timebase"]["origin_seconds"].is_null());
    p.get_mut("a").unwrap().v_per_fs = 4.0;
    p.get_mut("a").unwrap().revision = "profile.2".into();
    s.channel_ids.reverse();
    let new = MeasurementResult::coherent_tone(
        &s,
        [0, 16],
        capture(),
        &[0.25, 0.5],
        &p,
        vec![1000.],
        1.0,
    )
    .unwrap();
    assert_eq!(
        new.to_value()["columns"]["rms_v"]["values"][0]
            .as_f64()
            .unwrap(),
        1.0 / 2.0_f64.sqrt()
    );
    assert_eq!(old.encode(Format::Json).unwrap(), bytes);
}
#[test]
fn zero_nonfinite_and_overflow_have_reasons() {
    let mut p = profiles();
    p.get_mut("a").unwrap().v_per_fs = f64::MAX;
    for (peaks, reason) in [
        ([0.0, 0.0], "nonpositive"),
        ([f64::NAN, f64::INFINITY], "nonfinite"),
        ([1., 4.], "nonfinite"),
    ] {
        let r =
            MeasurementResult::coherent_tone(&source(), [0, 16], capture(), &peaks, &p, vec![], 1.)
                .unwrap();
        assert_eq!(r.to_value()["columns"]["dbv"]["reasons"][1], reason);
        for fmt in [Format::Json, Format::Csv] {
            assert_eq!(
                MeasurementResult::decode(&r.encode(fmt).unwrap(), fmt)
                    .unwrap()
                    .to_value(),
                r.to_value()
            );
        }
    }
}
#[test]
fn json_csv_roundtrip_keeps_all_values_metadata_and_quoting() {
    let r = tone();
    for fmt in [Format::Json, Format::Csv] {
        let bytes = r.encode(fmt).unwrap();
        let reread = MeasurementResult::decode(&bytes, fmt).unwrap();
        assert_eq!(r.to_value(), reread.to_value());
        assert_eq!(bytes, reread.encode(fmt).unwrap());
    }
}
#[test]
fn rejects_corrupt_schema_identity_shape_axis_precision_and_uncalibrated() {
    let original = tone().to_value();
    for field in [
        "schema",
        "generation",
        "shape",
        "reason",
        "axis",
        "calibration",
        "unknown",
        "precision",
        "unit",
        "rational",
        "inventory",
    ] {
        let mut v = original.clone();
        match field {
            "schema" => v["schema_version"] = json!(2),
            "generation" => v["source"]["generation"] = json!(4),
            "shape" => v["columns"]["rms_fs"]["shape"] = json!([1]),
            "reason" => v["columns"]["rms_v"]["reasons"][0] = Value::Null,
            "axis" => v["axis"]["corrected"][0] = json!(1000),
            "calibration" => {
                v["columns"]["rms_v"]["values"][0] = json!(0.1);
                v["columns"]["rms_v"]["reasons"][0] = Value::Null;
            }
            "unknown" => v["unknown"] = json!(true),
            "precision" => v["columns"]["rms_fs"]["precision"] = json!("F32"),
            "unit" => v["columns"]["rms_fs"]["unit"] = json!("V"),
            "rational" => v["capture"]["result_host_seconds"]["denominator"] = json!(0),
            _ => {
                v["columns"].as_object_mut().unwrap().remove("spl");
            }
        }
        assert!(
            MeasurementResult::decode(&serde_json::to_vec(&v).unwrap(), Format::Json).is_err(),
            "{field}"
        );
    }
}
#[test]
fn invalid_profiles_and_mixed_absolute_units_are_rejected() {
    for fault in [
        "unknown",
        "negative",
        "nonfinite",
        "interval",
        "empty",
        "mixed",
    ] {
        let mut p = profiles();
        let mut s = source();
        match fault {
            "unknown" => {
                p.insert("unknown".into(), p["a"].clone());
            }
            "negative" => p.get_mut("a").unwrap().v_per_fs = -1.,
            "nonfinite" => p.get_mut("a").unwrap().v_per_fs = f64::NAN,
            "interval" => p.get_mut("a").unwrap().applied_interval = [1, 10],
            "empty" => p.get_mut("a").unwrap().revision.clear(),
            _ => s.tap = Tap::OutputMixed,
        }
        assert!(
            MeasurementResult::coherent_tone(&s, [0, 16], capture(), &[0.5, 0.25], &p, vec![], 1.)
                .is_err()
        );
    }
}
#[test]
fn csv_rejects_truncation_extra_duplicate_nonfinite_and_missing_rows() {
    let r = tone();
    let bytes = r.encode(Format::Csv).unwrap();
    let text = String::from_utf8(bytes).unwrap();
    let mut rows = csv_decode(&text).unwrap();
    let last = rows.pop().unwrap();
    for data in [
        text[..text.len() - 1].to_owned(),
        text.clone() + &csv_encode(&[last]),
        csv_encode(&rows),
        text.replace("\"0.5\"", "\"NaN\""),
    ] {
        assert!(MeasurementResult::decode(data.as_bytes(), Format::Csv).is_err());
    }
}
#[test]
fn graph_snapshot_survives_generation_shutdown_and_invalid_windows() {
    for precision in [Precision::F32, Precision::F64] {
        for invalid in [false, true] {
            let mut source = source();
            source.precision = precision;
            let graph = Graph::new(Limits::default()).unwrap();
            let key = FftKey {
                source: source.clone(),
                n: 16,
                hop: 16,
                alignment: 0,
                window: WindowSpec::Boxcar,
                remove_dc: false,
                input_gains: vec![],
            };
            let sub = graph
                .subscribe(
                    key,
                    Average::None,
                    Presentation {
                        color: "blue".into(),
                        unit: "FS".into(),
                    },
                )
                .unwrap();
            let values: Vec<_> = (0..32).map(|i| (i as f64 / 17.).sin()).collect();
            let samples = match precision {
                Precision::F32 => Samples::F32(values.iter().map(|v| *v as f32).collect()),
                Precision::F64 => Samples::F64(values.clone()),
            };
            let validity = if invalid {
                vec![InvalidSpan {
                    start: 3,
                    end: 5,
                    channel_id: Some("a".into()),
                    reason: "gap".into(),
                    origin: "input".into(),
                }]
            } else {
                vec![]
            };
            let block = Arc::new(SignalBlock::new(source, 0, samples, validity).unwrap());
            for job in graph.schedule(block).unwrap() {
                assert!(job.run());
            }
            let raw = sub.take_latest().unwrap();
            let r = MeasurementResult::from_fft(raw.raw(), capture(), &profiles(), 1.0001).unwrap();
            let bytes = r.encode(Format::Json).unwrap();
            graph.retire_stream_before("input", 4).unwrap();
            drop(sub);
            graph.shutdown();
            assert_eq!(r.encode(Format::Json).unwrap(), bytes);
            for fmt in [Format::Json, Format::Csv] {
                assert_eq!(
                    MeasurementResult::decode(&r.encode(fmt).unwrap(), fmt)
                        .unwrap()
                        .to_value(),
                    r.to_value()
                );
            }
            if invalid {
                assert!(
                    r.to_value()["columns"]["fft_over_n"]["values"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .all(Value::is_null)
                );
            }
            assert_eq!(graph.stats().nodes, 0);
        }
    }
}
struct Failing {
    mode: u8,
}
impl Write for Failing {
    fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
        if self.mode == 0 {
            Ok(0)
        } else if self.mode == 1 {
            Err(std::io::Error::other("late write failure"))
        } else {
            Ok(1)
        }
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Err(std::io::Error::other("flush failure"))
    }
}
#[test]
fn write_zero_write_error_and_flush_error_never_succeed() {
    for mode in 0..3 {
        for fmt in [Format::Json, Format::Csv] {
            assert!(tone().write_to(&mut Failing { mode }, fmt).is_err());
        }
    }
}
#[test]
fn atomic_publish_rejects_existing_paths_and_cleans_temp() {
    let dir = std::env::temp_dir().join(format!(
        "migration-result-test-{}-{}",
        std::process::id(),
        NEXT_TEMP.fetch_add(1, Ordering::Relaxed)
    ));
    fs::create_dir(&dir).unwrap();
    for (name, fmt) in [("result.json", Format::Json), ("result.csv", Format::Csv)] {
        let path = dir.join(name);
        let r = tone();
        r.save_new(&path, fmt).unwrap();
        let bytes = fs::read(&path).unwrap();
        assert!(r.save_new(&path, fmt).is_err());
        assert_eq!(fs::read(&path).unwrap(), bytes);
        assert_eq!(
            MeasurementResult::load(&path, fmt).unwrap().to_value(),
            r.to_value()
        );
        assert!(r.save_new(&dir.join("missing/result"), fmt).is_err());
        assert!(r.save_new(&dir, fmt).is_err());
    }
    assert_eq!(fs::read_dir(&dir).unwrap().count(), 2);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn exact_trigger_mapping_and_unknown_uncertainty_survive_roundtrip() {
    let mut c = capture();
    c.trigger = Some(crate::history::TriggerEvent {
        id: "trigger.1".into(),
        stream_id: "input".into(),
        generation: 3,
        timebase_id: "time".into(),
        sample: Rational {
            numerator: 3,
            denominator: 2,
        },
        source: "synthetic".into(),
        kind: "threshold".into(),
        polarity: "rising".into(),
        condition_revision: "trigger.condition.1".into(),
        validity: vec![],
        received_host_seconds: Some(Rational {
            numerator: 11,
            denominator: 1,
        }),
    });
    c.clock_mapping = Some(crate::time::ClockMapping {
        from: ("time".into(), 3),
        to: ("reference.time".into(), 7),
        offset: Rational {
            numerator: 1,
            denominator: 3,
        },
        ratio: Rational {
            numerator: 10001,
            denominator: 10000,
        },
        valid_interval: [-10, 4000],
        method: "synthetic-exact".into(),
        uncertainty_samples: None,
    });
    let r = MeasurementResult::coherent_tone(
        &source(),
        [0, 16],
        c.clone(),
        &[0.5, 0.25],
        &profiles(),
        vec![1000.],
        1.,
    )
    .unwrap();
    for fmt in [Format::Json, Format::Csv] {
        assert_eq!(
            MeasurementResult::decode(&r.encode(fmt).unwrap(), fmt)
                .unwrap()
                .to_value(),
            r.to_value()
        );
    }
    assert!(r.to_value()["capture"]["clock_mapping"]["uncertainty_samples"].is_null());
    c.trigger.as_mut().unwrap().generation = 4;
    assert!(
        MeasurementResult::coherent_tone(
            &source(),
            [0, 16],
            c.clone(),
            &[0.5, 0.25],
            &profiles(),
            vec![1000.],
            1.
        )
        .is_err()
    );
    c.trigger.as_mut().unwrap().generation = 3;
    c.clock_mapping.as_mut().unwrap().valid_interval = [1, 10];
    assert!(
        MeasurementResult::coherent_tone(
            &source(),
            [0, 16],
            c,
            &[0.5, 0.25],
            &profiles(),
            vec![1000.],
            1.
        )
        .is_err()
    );
}
#[test]
fn duplicate_keys_and_nonfinite_json_are_rejected_at_every_depth() {
    for payload in [
        b"{\"a\":1,\"a\":1}".as_slice(),
        b"{\"a\":{\"b\":1,\"b\":1}}",
        b"{\"a\":NaN}",
        b"{\"a\":1e400}",
    ] {
        assert!(unique_json(payload).is_err());
    }
}
#[test]
fn oversized_fft_is_rejected_before_allocating_snapshot_columns() {
    let raw = FftResult {
        id: crate::ResultId {
            graph: 1,
            serial: 1,
        },
        key: FftKey {
            source: source(),
            n: 1_000_000,
            hop: 1,
            alignment: 0,
            window: WindowSpec::Boxcar,
            remove_dc: false,
            input_gains: vec![],
        },
        start: 0,
        numeric: None,
        validity: vec![],
        error: None,
    };
    assert!(MeasurementResult::from_fft(&raw, capture(), &BTreeMap::new(), 1.).is_err());
}
