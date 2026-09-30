//! Validate diagnostic requests before any device is opened.
#![forbid(unsafe_code)]
use audio_core::{MAX_CHANNELS, Route};
use serde_json::Value;

pub struct RequestFormat {
    pub input_channels: usize,
    pub output_channels: usize,
    pub source_ids: Vec<String>,
    pub route: Route,
    pub mute: [usize; 2],
    pub duration: f64,
}
impl RequestFormat {
    pub fn parse(request: &Value) -> Result<Self, &'static str> {
        if request["schema_version"] != 1 {
            return Err("unsupported schema");
        }
        let channels = |key| -> Result<usize, &'static str> {
            let count = match request.get(key) {
                None => 2,
                Some(value) => usize::try_from(value.as_u64().ok_or("channel count")?)
                    .map_err(|_| "channel count")?,
            };
            if !(1..=MAX_CHANNELS).contains(&count) {
                return Err("channel count");
            }
            Ok(count)
        };
        let input_channels = channels("input_channels")?;
        let output_channels = channels("output_channels")?;
        let source_ids = match request.get("source_ids") {
            Some(value) => {
                serde_json::from_value::<Vec<String>>(value.clone()).map_err(|_| "source_ids")?
            }
            None => vec!["generator.L".into()],
        };
        let route = match request.get("route") {
            Some(value) => serde_json::from_value::<Route>(value.clone()).map_err(|_| "route")?,
            None => Route {
                inputs: vec!["generator.L".into()],
                outputs: vec!["output.L".into(), "output.R".into()],
                gains: vec![vec![1.], vec![0.]],
                revision: "L-only.1".into(),
            },
        };
        route.compile(&source_ids)?;
        if route.outputs.len() != output_channels {
            return Err("route/output channel mismatch");
        }
        let duration = request["duration_seconds"].as_f64().ok_or("duration")?;
        if !duration.is_finite() || !(1.0..=60.0).contains(&duration) {
            return Err("duration must be in 1..60 seconds");
        }
        let mute: [usize; 2] = match request.get("mute_interval") {
            Some(value) => serde_json::from_value(value.clone()).map_err(|_| "mute interval")?,
            None => [108032, 132096],
        };
        if mute[0] >= mute[1] {
            return Err("mute interval");
        }
        Ok(Self {
            input_channels,
            output_channels,
            source_ids,
            route,
            mute,
            duration,
        })
    }

    pub fn validate_signal(&self, signal: &[f32]) -> Result<(), &'static str> {
        if signal.len() != (self.duration * 48000.) as usize * self.source_ids.len()
            || signal.iter().any(|v| !v.is_finite() || v.abs() > 0.05)
        {
            return Err("invalid signal length/amplitude");
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn old_uac232_request_preserves_mapping() {
        let format =
            RequestFormat::parse(&json!({"schema_version":1,"duration_seconds":4})).unwrap();
        assert_eq!(format.input_channels, 2);
        assert_eq!(format.output_channels, 2);
        assert_eq!(format.source_ids, ["generator.L"]);
        assert_eq!(format.route.gains, [vec![1.], vec![0.]]);
        assert_eq!(format.mute, [108032, 132096]);
        format.validate_signal(&vec![0.; 192000]).unwrap();
    }

    fn multi() -> Value {
        json!({"schema_version":1,"duration_seconds":1,"input_channels":16,"output_channels":3,
            "source_ids":["a","b"],"mute_interval":[10,20],
            "route":{"inputs":["b","a"],"outputs":["x","y","z"],
                "gains":[[1.,0.],[0.,1.],[0.5,0.5]],"revision":"route.1"}})
    }
    #[test]
    fn explicit_asymmetric_multichannel_route() {
        let format = RequestFormat::parse(&multi()).unwrap();
        assert_eq!(format.input_channels, 16);
        let route = format.route.compile(&format.source_ids).unwrap();
        let mut out = [0.; 3];
        route.process_into(&[0.01, 0.03], &mut out).unwrap();
        assert_eq!(out, [0.03, 0.01, 0.02]);
    }
    #[test]
    fn invalid_request_rejected_before_device_io() {
        for (key, value) in [
            ("input_channels", json!(0)),
            ("output_channels", json!(17)),
            ("input_channels", json!(null)),
            ("input_channels", json!(2.5)),
            ("duration_seconds", json!(0)),
            ("mute_interval", json!([20, 10])),
            ("source_ids", json!(["a", "a"])),
            ("source_ids", json!([])),
        ] {
            let mut request = multi();
            request[key] = value;
            assert!(RequestFormat::parse(&request).is_err(), "{key}");
        }
        let mut request = multi();
        request["route"]["gains"] = json!([[1.], [0.], [1.]]);
        assert!(RequestFormat::parse(&request).is_err());
        request = multi();
        request["output_channels"] = json!(2);
        assert!(RequestFormat::parse(&request).is_err());
    }
    #[test]
    fn bad_signal_shape_and_nonfinite_rejected() {
        let format = RequestFormat::parse(&multi()).unwrap();
        assert!(format.validate_signal(&vec![0.; 48000]).is_err());
        let mut signal = vec![0.; 96000];
        format.validate_signal(&signal).unwrap();
        signal[1] = f32::NAN;
        assert!(format.validate_signal(&signal).is_err());
        signal[1] = 1.;
        assert!(format.validate_signal(&signal).is_err());
    }
}
