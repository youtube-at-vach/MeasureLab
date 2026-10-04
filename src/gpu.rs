use bytemuck::{Pod, Zeroable};
use eframe::{
    egui,
    egui_wgpu::{self, wgpu},
};
use std::sync::Arc;
use wgpu::util::DeviceExt;

pub const COLORS: [[f32; 4]; 2] = [[0.22, 0.95, 0.68, 1.0], [0.34, 0.65, 1.0, 1.0]];

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct Segment {
    pub a: [f32; 2],
    pub b: [f32; 2],
    pub color: [f32; 4],
}

#[derive(Clone, Copy)]
pub enum PlotId {
    Scope = 0,
    Spectrum = 1,
}

pub struct TraceRenderer {
    pipeline: wgpu::RenderPipeline,
    plots: [TraceBuffers; 2],
}

struct TraceBuffers {
    uniform: wgpu::Buffer,
    binding: wgpu::BindGroup,
    instances: wgpu::Buffer,
    capacity: usize,
    count: u32,
    revision: u64,
}

impl TraceRenderer {
    pub fn new(device: &wgpu::Device, format: wgpu::TextureFormat) -> Self {
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("RAS trace shader"),
            source: wgpu::ShaderSource::Wgsl(include_str!("trace.wgsl").into()),
        });
        let layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("RAS parameters"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: std::num::NonZeroU64::new(16),
                },
                count: None,
            }],
        });
        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("RAS trace layout"),
            bind_group_layouts: &[Some(&layout)],
            immediate_size: 0,
        });
        let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("RAS instanced anti-aliased traces"), layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader, entry_point: Some("vs_main"),
                buffers: &[Some(wgpu::VertexBufferLayout {
                    array_stride: std::mem::size_of::<Segment>() as u64,
                    step_mode: wgpu::VertexStepMode::Instance,
                    attributes: &wgpu::vertex_attr_array![0 => Float32x2, 1 => Float32x2, 2 => Float32x4],
                })],
                compilation_options: Default::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader, entry_point: Some("fs_main"),
                targets: &[Some(wgpu::ColorTargetState { format,
                    blend: Some(wgpu::BlendState::ALPHA_BLENDING), write_mask: wgpu::ColorWrites::ALL })],
                compilation_options: Default::default(),
            }),
            primitive: Default::default(), depth_stencil: None,
            multisample: Default::default(), multiview_mask: None, cache: None,
        });
        Self {
            pipeline,
            plots: std::array::from_fn(|_| TraceBuffers::new(device, &layout)),
        }
    }

    pub fn paint(&self, plot: PlotId, pass: &mut wgpu::RenderPass<'_>) {
        let buffers = &self.plots[plot as usize];
        if buffers.count == 0 {
            return;
        }
        pass.set_pipeline(&self.pipeline);
        pass.set_bind_group(0, &buffers.binding, &[]);
        pass.set_vertex_buffer(0, buffers.instances.slice(..));
        pass.draw(0..6, 0..buffers.count);
    }
}

impl TraceBuffers {
    fn new(device: &wgpu::Device, layout: &wgpu::BindGroupLayout) -> Self {
        let uniform = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("RAS per-plot viewport parameters"),
            contents: bytemuck::cast_slice(&[1.0_f32, 1.0, 1.5, 0.0]),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });
        let binding = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("RAS per-plot parameters"),
            layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: uniform.as_entire_binding(),
            }],
        });
        let capacity = 8192;
        Self {
            uniform,
            binding,
            instances: instance_buffer(device, capacity),
            capacity,
            count: 0,
            revision: u64::MAX,
        }
    }

    pub fn prepare(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        segments: &[Segment],
        dimensions: [f32; 2],
        width: f32,
        revision: u64,
    ) {
        queue.write_buffer(
            &self.uniform,
            0,
            bytemuck::cast_slice(&[dimensions[0].max(1.0), dimensions[1].max(1.0), width, 0.0]),
        );
        if self.revision == revision {
            return;
        }
        if segments.len() > self.capacity {
            self.capacity = segments.len().next_power_of_two();
            self.instances = instance_buffer(device, self.capacity);
        }
        if !segments.is_empty() {
            queue.write_buffer(&self.instances, 0, bytemuck::cast_slice(segments));
        }
        self.count = segments.len() as u32;
        self.revision = revision;
    }
}

fn instance_buffer(device: &wgpu::Device, capacity: usize) -> wgpu::Buffer {
    device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("RAS reusable trace instances"),
        size: (capacity * std::mem::size_of::<Segment>()) as u64,
        usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    })
}

pub struct TraceCallback {
    pub plot: PlotId,
    pub segments: Arc<Vec<Segment>>,
    pub dimensions: [f32; 2],
    pub width: f32,
    pub revision: u64,
}

impl egui_wgpu::CallbackTrait for TraceCallback {
    fn prepare(
        &self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        _: &egui_wgpu::ScreenDescriptor,
        _: &mut wgpu::CommandEncoder,
        resources: &mut egui_wgpu::CallbackResources,
    ) -> Vec<wgpu::CommandBuffer> {
        if let Some(renderer) = resources.get_mut::<TraceRenderer>() {
            renderer.plots[self.plot as usize].prepare(
                device,
                queue,
                &self.segments,
                self.dimensions,
                self.width,
                self.revision,
            );
        }
        Vec::new()
    }

    fn paint(
        &self,
        _: egui::PaintCallbackInfo,
        pass: &mut wgpu::RenderPass<'static>,
        resources: &egui_wgpu::CallbackResources,
    ) {
        if let Some(renderer) = resources.get::<TraceRenderer>() {
            renderer.paint(self.plot, pass);
        }
    }
}

/// Validates the actual shader, instance layout and draw by reading pixels back.
pub fn smoke_test() -> Result<(), Box<dyn std::error::Error>> {
    pollster::block_on(async {
        let instance = wgpu::Instance::default();
        let adapter = instance
            .request_adapter(&wgpu::RequestAdapterOptions::default())
            .await?;
        let (device, queue) = adapter
            .request_device(&wgpu::DeviceDescriptor::default())
            .await?;
        let format = wgpu::TextureFormat::Rgba8Unorm;
        let mut renderer = TraceRenderer::new(&device, format);
        let segments = [
            Segment {
                a: [0.1, 0.25],
                b: [0.9, 0.25],
                color: COLORS[0],
            },
            Segment {
                a: [0.1, 0.75],
                b: [0.9, 0.75],
                color: COLORS[1],
            },
        ];
        // Both callbacks are prepared before either is painted, with the same
        // revision. Shared state would overwrite the first plot here.
        renderer.plots[PlotId::Scope as usize].prepare(
            &device,
            &queue,
            &segments[..1],
            [256.0, 64.0],
            2.0,
            1,
        );
        renderer.plots[PlotId::Spectrum as usize].prepare(
            &device,
            &queue,
            &segments[1..],
            [256.0, 64.0],
            2.0,
            1,
        );
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("RAS smoke output"),
            size: wgpu::Extent3d {
                width: 256,
                height: 128,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let view = texture.create_view(&Default::default());
        let readback = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("RAS smoke readback"),
            size: 256 * 128 * 4,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let mut encoder = device.create_command_encoder(&Default::default());
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("RAS smoke draw"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    depth_slice: None,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                ..Default::default()
            });
            pass.set_viewport(0.0, 0.0, 256.0, 64.0, 0.0, 1.0);
            renderer.paint(PlotId::Scope, &mut pass);
            pass.set_viewport(0.0, 64.0, 256.0, 64.0, 0.0, 1.0);
            renderer.paint(PlotId::Spectrum, &mut pass);
        }
        encoder.copy_texture_to_buffer(
            texture.as_image_copy(),
            wgpu::TexelCopyBufferInfo {
                buffer: &readback,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(1024),
                    rows_per_image: Some(128),
                },
            },
            texture.size(),
        );
        queue.submit([encoder.finish()]);
        let (sender, receiver) = std::sync::mpsc::channel();
        readback
            .slice(..)
            .map_async(wgpu::MapMode::Read, move |result| {
                let _ = sender.send(result);
            });
        device.poll(wgpu::PollType::wait_indefinitely())?;
        receiver.recv()??;
        let pixels = readback.slice(..).get_mapped_range()?;
        let green = pixels[..256 * 64 * 4]
            .as_chunks::<4>()
            .0
            .iter()
            .filter(|p| p[1] > 200 && p[0] < 100)
            .count();
        let blue = pixels[256 * 64 * 4..]
            .as_chunks::<4>()
            .0
            .iter()
            .filter(|p| p[2] > 200 && p[0] < 130)
            .count();
        if green < 200 || blue < 200 {
            return Err("GPU readback did not contain both traces".into());
        }
        println!(
            "GPU OK: {:?}, {} / {} green / {} blue pixels",
            adapter.get_info().backend,
            adapter.get_info().name,
            green,
            blue
        );
        drop(pixels);
        readback.unmap();
        Ok(())
    })
}
