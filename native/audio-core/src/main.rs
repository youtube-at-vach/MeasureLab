//! Offline fixture adapter; all JSON/allocation stays outside the audio callback.
use audio_core::*;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{error::Error, fs, io::Write, path::Path};

fn parse_route(value: &Value) -> Result<Route, &'static str> {
    if value["gains"].as_array().is_some_and(|rows| {
        rows.iter().any(|row| {
            row.as_array()
                .is_some_and(|r| r.iter().any(|g| !g.is_number()))
        })
    }) {
        return Err("nonfinite_gain");
    }
    serde_json::from_value(value.clone()).map_err(|_| "gain_shape")
}
fn evaluate(case: &Value) -> Result<Value, Box<dyn Error>> {
    let data = &case["input"];
    match case["operation"].as_str().ok_or("operation")? {
        "route" => {
            let input: RouteInput = serde_json::from_value(data.clone())?;
            Ok(match route_owned(&input) {
                Ok(v) => serde_json::to_value(v)?,
                Err(reason) => json!({"status":"rejected","reason":reason}),
            })
        }
        "route_changes" => {
            let known = serde_json::from_value(data["known_ids"].clone())?;
            let mut control = RouteControl::new(known, parse_route(&data["initial"])?)?;
            let mut records = Vec::new();
            let mut published = data["initial"].clone();
            for request in data["requests"].as_array().ok_or("requests")? {
                let result = parse_route(&request["route"]).and_then(|route| {
                    control.apply(
                        route,
                        request["requested_sample"]
                            .as_u64()
                            .ok_or("requested_sample")?,
                        request["next_block_start"]
                            .as_u64()
                            .ok_or("next_block_start")?,
                    )
                });
                let mut record = match result {
                    Ok(sample) => {
                        published = request["route"].clone();
                        json!({"request_id":request["id"],"status":"applied","sample":sample,"revision":control.current().revision})
                    }
                    Err(reason) => {
                        json!({"request_id":request["id"],"status":"rejected","reason":reason})
                    }
                };
                record["published_route"] = published.clone();
                records.push(record);
            }
            Ok(json!(records))
        }
        "taps" => {
            let stage = DeviceStage {
                mute: data["mute"].as_bool().ok_or("mute")?,
                gain: data["gain"].as_f64().ok_or("gain")?,
                quantization_step: data["quantization_step"].as_f64().ok_or("step")?,
                mapping: serde_json::from_value(data["mapping"].clone())?,
                dither: data["dither"].as_str().ok_or("dither")?.into(),
            };
            let mixed: Vec<Vec<f64>> = serde_json::from_value(data["mixed"].clone())?;
            stage.validate(mixed.first().ok_or("empty")?.len())?;
            let submitted: Vec<Vec<_>> = mixed
                .iter()
                .map(|row| {
                    stage
                        .mapping
                        .iter()
                        .map(|i| stage.sample(row[*i]))
                        .collect()
                })
                .collect();
            Ok(
                json!({"output.mixed":mixed,"output.device_buffer":submitted,"physical_output":{"value":null,"reason":"not_measured"},
                "virtual_loopback":{"source_tap":"output.mixed","delay_frames":data["loopback_delay_frames"],
                    "initial_validity":{"interval":[0,data["loopback_delay_frames"]],"reason":"warmup"}}}),
            )
        }
        "blocks" => {
            let blocks: Vec<BlockHeader> = serde_json::from_value(data["blocks"].clone())?;
            let mut validator = BlockValidator::default();
            Ok(json!(blocks.iter().map(|block| match validator.accept(block) {
                Ok(missing) => json!({"status":"accepted","generation":block.generation,"interval":[block.start,block.start+block.frames as i64],"missing":missing}),
                Err(reason) => json!({"status":"rejected","reason":reason}),
            }).collect::<Vec<_>>()))
        }
        _ => Err("unsupported operation".into()),
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct QueueRequest {
    schema_version: u64,
    channel_ids: Vec<String>,
    dtype: String,
    frames: usize,
    chunk_frames: usize,
    capacity: usize,
    generation: u64,
    rate: u64,
}
fn transfer<T: Sample>(
    request: &QueueRequest,
    values: &[T],
    tx: &mut Producer<T>,
    rx: &mut Consumer<T>,
    encode: impl Fn(T, &mut fs::File) -> std::io::Result<()>,
    file: &mut fs::File,
) -> Result<Vec<u64>, Box<dyn Error>> {
    let mut samples = Vec::new();
    for chunk in values.chunks(request.chunk_frames * request.channel_ids.len()) {
        tx.write(chunk, None, 0)?;
        while let Some(item) = rx.take() {
            match item {
                Delivery::Frame { sample, values, .. } => {
                    samples.push(sample);
                    for value in values {
                        encode(value, file)?
                    }
                }
                Delivery::Gap { .. } => return Err("unexpected queue overflow".into()),
            }
        }
    }
    Ok(samples)
}
fn queue_run(args: &[String]) -> Result<(), Box<dyn Error>> {
    if args.len() != 5 {
        return Err("usage: audio-core --queue REQUEST.json INPUT.bin OUTPUT_DIRECTORY".into());
    }
    let request: QueueRequest = serde_json::from_slice(&fs::read(&args[2])?)?;
    if request.schema_version != 1
        || request.frames == 0
        || request.frames > MAX_QUEUE_FRAMES
        || request.chunk_frames == 0
        || request.chunk_frames > MAX_CALLBACK_FRAMES
        || request.capacity < request.chunk_frames
        || request.capacity > MAX_QUEUE_FRAMES
        || !["<f4", "<f8"].contains(&request.dtype.as_str())
    {
        return Err("queue request".into());
    }
    let format = IoFormat {
        stream_id: "fixture.audio".into(),
        generation: request.generation,
        timebase_id: "fixture.timebase".into(),
        clock_domain: "fixture.virtual".into(),
        rate: [request.rate, 1],
        input_ids: request.channel_ids.clone(),
        input_ports: (0..request.channel_ids.len()).collect(),
        output_ids: vec![],
        output_ports: vec![],
    };
    format.validate(request.channel_ids.len(), 0)?;
    let bytes = fs::read(&args[3])?;
    let width = if request.dtype == "<f4" { 4 } else { 8 };
    if bytes.len() != request.frames * request.channel_ids.len() * width {
        return Err("frame_shape".into());
    }
    let output = Path::new(&args[4]);
    if output.exists() {
        return Err("output exists".into());
    }
    fs::create_dir(output)?;
    let mut file = fs::File::create(output.join("output.bin"))?;
    let samples = if width == 4 {
        let values: Vec<_> = bytes
            .as_chunks::<4>()
            .0
            .iter()
            .map(|v| f32::from_le_bytes(*v))
            .collect();
        let (mut tx, mut rx) = frame_queue(
            request.capacity,
            request.channel_ids.len(),
            request.rate as f64,
        )?;
        transfer(
            &request,
            &values,
            &mut tx,
            &mut rx,
            |v, f| f.write_all(&v.to_le_bytes()),
            &mut file,
        )?
    } else {
        let values: Vec<_> = bytes
            .as_chunks::<8>()
            .0
            .iter()
            .map(|v| f64::from_le_bytes(*v))
            .collect();
        let (mut tx, mut rx) = frame_queue_f64(
            request.capacity,
            request.channel_ids.len(),
            request.rate as f64,
        )?;
        transfer(
            &request,
            &values,
            &mut tx,
            &mut rx,
            |v, f| f.write_all(&v.to_le_bytes()),
            &mut file,
        )?
    };
    fs::write(
        output.join("manifest.json"),
        serde_json::to_vec(
            &json!({"schema_version":1,"format":format,"dtype":request.dtype,"frames":request.frames,"samples":samples,"gaps":[]}),
        )?,
    )?;
    Ok(())
}
fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.get(1).is_some_and(|arg| arg == "--queue") {
        return queue_run(&args);
    }
    if args.len() != 2 {
        return Err("usage: audio-core REQUEST.json".into());
    }
    let cases: Vec<Value> = serde_json::from_slice(&fs::read(&args[1])?)?;
    let records: Result<Vec<_>, _> = cases
        .iter()
        .map(|case| evaluate(case).map(|value| json!({"id":case["id"],"observed":value})))
        .collect();
    println!("{}", serde_json::to_string(&records?)?);
    Ok(())
}
