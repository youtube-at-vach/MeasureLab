//! Offline driver for the actual control/callback mailbox. Expectations stay in Python.
#![forbid(unsafe_code)]
use audio_core::dynamic_route::{RouteStatus, route_mailbox};
use audio_core::{MAX_CALLBACK_FRAMES, MAX_QUEUE_FRAMES, Route};
use serde::Deserialize;
use serde_json::json;
use std::{error::Error, fs, path::Path};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Update {
    route: Route,
    generation: u64,
    requested_sample: u64,
    send_after_sample: u64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: u64,
    source_ids: Vec<String>,
    generation: u64,
    frames: usize,
    block_frames: Vec<usize>,
    ack_every_blocks: usize,
    mute_interval: [u64; 2],
    initial: Route,
    updates: Vec<Update>,
}
fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 3 {
        return Err("usage: route-candidate REQUEST INPUT.f32 OUTPUT_DIRECTORY".into());
    }
    let output = Path::new(&args[2]);
    if output.exists() {
        return Err("output exists".into());
    }
    let bytes = fs::read(&args[0])?;
    let request: Request = serde_json::from_slice(&bytes)?;
    if request.schema_version != 1
        || !(1..=MAX_QUEUE_FRAMES).contains(&request.frames)
        || request.block_frames.is_empty()
        || request.block_frames.len() > 32
        || request
            .block_frames
            .iter()
            .any(|n| !(1..=MAX_CALLBACK_FRAMES).contains(n))
        || !(1..=64).contains(&request.ack_every_blocks)
        || request.updates.len() > 64
        || request.mute_interval[0] > request.mute_interval[1]
        || request.mute_interval[1] > request.frames as u64
    {
        return Err("route request".into());
    }
    let (mut ctl, mut cb) = route_mailbox(
        request.source_ids.clone(),
        request.initial.clone(),
        request.generation,
    )?;
    let source_bytes = fs::read(&args[1])?;
    if source_bytes.len() != request.frames * request.source_ids.len() * 4 {
        return Err("input shape".into());
    }
    let source: Vec<_> = source_bytes
        .as_chunks::<4>()
        .0
        .iter()
        .map(|b| f32::from_le_bytes(*b))
        .collect();
    if source.iter().any(|v| !v.is_finite()) {
        return Err("nonfinite input".into());
    }
    // Validate the entire schedule before rendering anything or creating output files.
    let mut last_requested = 0;
    let mut last_send = 0;
    let mut last_revision = &request.initial.revision;
    for update in &request.updates {
        update.route.compile(&request.source_ids)?;
        if update.generation != request.generation
            || update.route.outputs != request.initial.outputs
            || update.route.revision == *last_revision
            || update.requested_sample < last_requested
            || update.send_after_sample < last_send
            || update.send_after_sample >= request.frames as u64
            || update.requested_sample >= request.frames as u64
        {
            return Err("route schedule".into());
        }
        last_requested = update.requested_sample;
        last_send = update.send_after_sample;
        last_revision = &update.route.revision;
    }
    let channels = request.source_ids.len();
    let outputs = request.initial.outputs.len();
    let mut mixed = vec![0f32; request.frames * outputs];
    let mut blocks = Vec::new();
    let mut events = Vec::new();
    let mut next = 0;
    let mut start = 0;
    while start < request.frames {
        if blocks.len() % request.ack_every_blocks == 0
            && let Some(event) = ctl.take_event()
        {
            events.push(event);
        }
        if events.len() == next
            && let Some(update) = request.updates.get(next)
            && start as u64 >= update.send_after_sample
        {
            ctl.publish(&update.route, update.generation, update.requested_sample)?;
            next += 1;
        }
        let count = request.block_frames[blocks.len() % request.block_frames.len()]
            .min(request.frames - start);
        blocks.push(cb.process_block(
            start as u64,
            &source[start * channels..(start + count) * channels],
            &mut mixed[start * outputs..(start + count) * outputs],
        )?);
        start += count;
    }
    ctl.close();
    drop(cb);
    while let Some(event) = ctl.take_event() {
        events.push(event);
    }
    if next != request.updates.len()
        || events.len() != next
        || events.iter().any(|e| e.status != RouteStatus::Applied)
    {
        return Err("schedule did not complete".into());
    }
    let mut device = mixed.clone();
    for frame in request.mute_interval[0] as usize..request.mute_interval[1] as usize {
        device[frame * outputs..(frame + 1) * outputs].fill(0.);
    }
    fs::create_dir(output)?;
    for (name, values) in [("mixed.bin", mixed), ("device.bin", device)] {
        let encoded: Vec<_> = values.iter().flat_map(|v| v.to_le_bytes()).collect();
        fs::write(output.join(name), encoded)?;
    }
    let report = json!({"schema_version":1,"request":serde_json::from_slice::<serde_json::Value>(&bytes)?,
        "blocks":blocks,"events":events,"rendered_through":ctl.rendered_through(),"dtype":"<f4",
        "taps":["output.mixed","output.device_buffer"],"physical_output":null});
    fs::write(output.join("manifest.json"), serde_json::to_vec(&report)?)?;
    Ok(())
}
