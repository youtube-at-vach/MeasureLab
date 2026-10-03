//! MIG-007-C: isolated GPU raster and binary RGBA transport; no product widgets.
use bytemuck::{Pod, Zeroable};
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::io::{self, BufRead, Write};
use std::time::{Duration, Instant};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    kind: String,
    points: u32,
    width: u32,
    height: u32,
}
impl Config {
    fn validate(&self) -> Result<(), String> {
        if !matches!(self.kind.as_str(), "spectrum" | "spectrogram")
            || !(2..=1_000_000).contains(&self.points)
            || !(2..=2048).contains(&self.width)
            || !(2..=1024).contains(&self.height)
            || (self.kind == "spectrogram" && self.points > 4096)
        {
            return Err("invalid spike dimensions/kind".into());
        }
        Ok(())
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    frame: u32,
    low: f32,
    high: f32,
    cursor: f32,
}
impl Request {
    fn validate(&self) -> Result<(), String> {
        if self.frame > 100_000
            || !self.low.is_finite()
            || !self.high.is_finite()
            || !self.cursor.is_finite()
            || self.low < 0.0
            || self.high > 1.0
            || self.low >= self.high
            || !(0.0..=1.0).contains(&self.cursor)
        {
            return Err("invalid frame/view/cursor".into());
        }
        Ok(())
    }
}
#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct Params {
    low: f32,
    high: f32,
    points: u32,
    width: u32,
    height: u32,
    head: u32,
    retained: u32,
    heatmap: u32,
}
fn values(points: u32, frame: u32) -> Vec<f32> {
    let peak = (points / 3 + frame * 13) % points;
    (0..points)
        .map(|k| {
            if k == peak {
                0.8
            } else {
                0.001 + ((k * 37 + frame * 101) % 4096) as f32 / 4096.0 * 0.09
            }
        })
        .collect()
}
fn cursor(points: u32, low: f32, high: f32, fraction: f32) -> u32 {
    (((low as f64 + (high - low) as f64 * fraction as f64) * (points - 1) as f64).round() as u32)
        .min(points - 1)
}
struct Renderer {
    device: wgpu::Device,
    queue: wgpu::Queue,
    input: wgpu::Buffer,
    image: wgpu::Buffer,
    uniform: wgpu::Buffer,
    staging: wgpu::Buffer,
    bind: wgpu::BindGroup,
    reduce: wgpu::ComputePipeline,
    raster: wgpu::ComputePipeline,
    queries: Option<(wgpu::QuerySet, wgpu::Buffer)>,
    config: Config,
    head: u32,
    retained: u32,
}
impl Renderer {
    fn new(config: Config) -> Result<(Self, Value), String> {
        config.validate()?;
        let instance = wgpu::Instance::new(wgpu::InstanceDescriptor::new_without_display_handle());
        let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::LowPower,
            ..Default::default()
        }))
        .map_err(|e| e.to_string())?;
        let info = adapter.get_info();
        let features = adapter.features() & wgpu::Features::TIMESTAMP_QUERY;
        let (device, queue) = pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor {
            required_features: features,
            ..Default::default()
        }))
        .map_err(|e| e.to_string())?;
        let buffer = |size, usage| {
            device.create_buffer(&wgpu::BufferDescriptor {
                label: None,
                size,
                usage,
                mapped_at_creation: false,
            })
        };
        let rows = if config.kind == "spectrogram" { 32 } else { 1 };
        let input = buffer(
            config.points as u64 * 4 * rows,
            wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
        );
        let columns = buffer(config.width as u64 * 4, wgpu::BufferUsages::STORAGE);
        let bytes = config.width as u64 * config.height as u64 * 4;
        let image = buffer(
            bytes,
            wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
        );
        let uniform = buffer(
            32,
            wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        );
        let staging = buffer(
            bytes + 32,
            wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
        );
        let layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: None,
            entries: &[0, 1, 2, 3].map(|binding| wgpu::BindGroupLayoutEntry {
                binding,
                visibility: wgpu::ShaderStages::COMPUTE,
                ty: wgpu::BindingType::Buffer {
                    ty: match binding {
                        0 => wgpu::BufferBindingType::Storage { read_only: true },
                        3 => wgpu::BufferBindingType::Uniform,
                        _ => wgpu::BufferBindingType::Storage { read_only: false },
                    },
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            }),
        });
        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None,
            bind_group_layouts: &[Some(&layout)],
            immediate_size: 0,
        });
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("spike raster"),
            source: wgpu::ShaderSource::Wgsl(include_str!("plot.wgsl").into()),
        });
        let pipeline = |entry| {
            device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
                label: Some(entry),
                layout: Some(&pipeline_layout),
                module: &shader,
                entry_point: Some(entry),
                compilation_options: Default::default(),
                cache: None,
            })
        };
        let reduce = pipeline("reduce");
        let raster = pipeline("raster");
        let resources = [&input, &columns, &image, &uniform]
            .into_iter()
            .enumerate()
            .map(|(i, b)| wgpu::BindGroupEntry {
                binding: i as u32,
                resource: b.as_entire_binding(),
            })
            .collect::<Vec<_>>();
        let bind = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None,
            layout: &layout,
            entries: &resources,
        });
        let queries = (!features.is_empty()).then(|| {
            (
                device.create_query_set(&wgpu::QuerySetDescriptor {
                    label: None,
                    ty: wgpu::QueryType::Timestamp,
                    count: 4,
                }),
                buffer(
                    32,
                    wgpu::BufferUsages::QUERY_RESOLVE | wgpu::BufferUsages::COPY_SRC,
                ),
            )
        });
        let metadata = json!({"adapter": info.name, "backend": format!("{:?}", info.backend), "device_type": format!("{:?}", info.device_type), "timestamps": queries.is_some(), "width": config.width, "height": config.height});
        Ok((
            Self {
                device,
                queue,
                input,
                image,
                uniform,
                staging,
                bind,
                reduce,
                raster,
                queries,
                config,
                head: 31,
                retained: 0,
            },
            metadata,
        ))
    }
    fn render(&mut self, request: Request) -> Result<(Value, Vec<u8>), String> {
        request.validate()?;
        let started = Instant::now();
        let data = values(self.config.points, request.frame);
        let data_bytes = bytemuck::cast_slice(&data);
        let hash = format!("{:x}", Sha256::digest(data_bytes));
        let heatmap = self.config.kind == "spectrogram";
        self.head = (self.head + 1) % 32;
        self.retained = (self.retained + 1).min(32);
        let offset = if heatmap {
            self.head as u64 * data_bytes.len() as u64
        } else {
            0
        };
        self.queue.write_buffer(&self.input, offset, data_bytes);
        let p = Params {
            low: request.low,
            high: request.high,
            points: self.config.points,
            width: self.config.width,
            height: self.config.height,
            head: self.head,
            retained: self.retained,
            heatmap: u32::from(heatmap),
        };
        self.queue
            .write_buffer(&self.uniform, 0, bytemuck::bytes_of(&p));
        let mut encoder = self.device.create_command_encoder(&Default::default());
        for (index, pipeline) in [&self.reduce, &self.raster].into_iter().enumerate() {
            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: None,
                timestamp_writes: self.queries.as_ref().map(|(queries, _)| {
                    wgpu::ComputePassTimestampWrites {
                        query_set: queries,
                        beginning_of_pass_write_index: Some(index as u32 * 2),
                        end_of_pass_write_index: Some(index as u32 * 2 + 1),
                    }
                }),
            });
            pass.set_pipeline(pipeline);
            pass.set_bind_group(0, &self.bind, &[]);
            if index == 0 {
                if !heatmap {
                    pass.dispatch_workgroups(self.config.width.div_ceil(64), 1, 1);
                }
            } else {
                pass.dispatch_workgroups(
                    self.config.width.div_ceil(8),
                    self.config.height.div_ceil(8),
                    1,
                );
            }
        }
        let bytes = self.config.width as u64 * self.config.height as u64 * 4;
        encoder.copy_buffer_to_buffer(&self.image, 0, &self.staging, 0, bytes);
        if let Some((queries, resolved)) = &self.queries {
            encoder.resolve_query_set(queries, 0..4, resolved, 0);
            encoder.copy_buffer_to_buffer(resolved, 0, &self.staging, bytes, 32);
        }
        let submission = self.queue.submit([encoder.finish()]);
        let slice = self.staging.slice(..);
        let (tx, rx) = std::sync::mpsc::channel();
        slice.map_async(wgpu::MapMode::Read, move |result| {
            let _ = tx.send(result);
        });
        self.device
            .poll(wgpu::PollType::Wait {
                submission_index: Some(submission),
                timeout: Some(Duration::from_secs(10)),
            })
            .map_err(|e| e.to_string())?;
        rx.recv_timeout(Duration::from_secs(1))
            .map_err(|e| e.to_string())?
            .map_err(|e| e.to_string())?;
        let mapped = slice.get_mapped_range().map_err(|e| e.to_string())?;
        let image = mapped[..bytes as usize].to_vec();
        let gpu_ms = self.queries.as_ref().map(|_| {
            let first = u64::from_le_bytes(
                mapped[bytes as usize..bytes as usize + 8]
                    .try_into()
                    .unwrap(),
            );
            let last = u64::from_le_bytes(
                mapped[bytes as usize + 24..bytes as usize + 32]
                    .try_into()
                    .unwrap(),
            );
            last.saturating_sub(first) as f64 * self.queue.get_timestamp_period() as f64 / 1e6
        });
        drop(mapped);
        self.staging.unmap();
        let bin = cursor(
            self.config.points,
            request.low,
            request.high,
            request.cursor,
        );
        Ok((
            json!({"frame": request.frame, "rgba_bytes": bytes, "input_sha256": hash, "cursor_bin": bin, "cursor_hz": bin as f64 * 24000.0 / (self.config.points - 1) as f64, "cursor_value": data[bin as usize], "gpu_ms": gpu_ms, "render_readback_ms": started.elapsed().as_secs_f64() * 1000.0, "input_upload_bytes": data_bytes.len(), "uniform_upload_bytes": 32, "retained": self.retained, "head": self.head}),
            image,
        ))
    }
}
fn run() -> Result<(), String> {
    let mut lines = io::stdin().lock().lines();
    let config = lines
        .next()
        .ok_or("missing config")?
        .map_err(|e| e.to_string())?;
    let (mut renderer, metadata) =
        Renderer::new(serde_json::from_str(&config).map_err(|e| e.to_string())?)?;
    let mut out = io::stdout().lock();
    writeln!(out, "{metadata}").map_err(|e| e.to_string())?;
    out.flush().map_err(|e| e.to_string())?;
    for line in lines {
        let line = line.map_err(|e| e.to_string())?;
        if line == "{\"stop\":true}" {
            break;
        }
        let request = serde_json::from_str(&line).map_err(|e| e.to_string())?;
        let (metadata, bytes) = renderer.render(request)?;
        writeln!(out, "{metadata}").map_err(|e| e.to_string())?;
        out.write_all(&bytes).map_err(|e| e.to_string())?;
        out.flush().map_err(|e| e.to_string())?;
    }
    renderer.device.destroy();
    drop(renderer);
    writeln!(
        out,
        "{}",
        json!({"stopped": true, "gpu_owner_dropped": true})
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("RENDERER_FAIL {error}");
        std::process::exit(1);
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_unbounded_allocations_and_invalid_views() {
        for (kind, points, width) in [
            ("bad", 2, 2),
            ("spectrum", 1_000_001, 2),
            ("spectrogram", 4097, 2),
            ("spectrum", 100_000, 0),
        ] {
            assert!(
                Config {
                    kind: kind.into(),
                    points,
                    width,
                    height: 256
                }
                .validate()
                .is_err()
            );
        }
        for (low, high, cursor) in [(0.5, 0.5, 0.0), (0.0, 1.1, 0.0), (0.0, 1.0, f32::NAN)] {
            assert!(
                Request {
                    frame: 0,
                    low,
                    high,
                    cursor
                }
                .validate()
                .is_err()
            );
        }
    }
    #[test]
    fn cursor_uses_original_data_after_zoom_and_pan() {
        assert_eq!(cursor(100_001, 0.0, 1.0, 0.5), 50_000);
        assert_eq!(cursor(100_001, 0.25, 0.75, 0.5), 50_000);
        assert_eq!(cursor(100_001, 0.5, 1.0, 0.5), 75_000);
        assert_eq!(cursor(100_001, 0.5, 1.0, 1.0), 100_000);
        assert_eq!(values(100_000, 0)[100_000 / 3], 0.8);
    }
}
