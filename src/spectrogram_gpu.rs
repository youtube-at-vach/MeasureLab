//! Desktop adapter for the GUI-independent, bounded spectrogram history.
use crate::{
    spectrogram::{History, Placement, ROWS, TEXTURE_WIDTH},
    spectrum::{FrequencyScale, View},
};
use eframe::{
    egui,
    egui_wgpu::{self, wgpu},
};
use std::sync::{Arc, Mutex};
use wgpu::util::DeviceExt;

pub struct Renderer {
    pipeline: wgpu::RenderPipeline,
    layout: wgpu::BindGroupLayout,
    uniform: wgpu::Buffer,
    texture: wgpu::Texture,
    binding: wgpu::BindGroup,
    instances: wgpu::Buffer,
    scanlines: usize,
    versions: [u64; ROWS],
    revision: u64,
    seconds: f64,
    count: u32,
    placements: Vec<Placement>,
    vertices: Vec<[f32; 4]>,
    parameters: [f32; 8],
    pub uploaded_rows: u64,
}

impl Renderer {
    pub fn new(device: &wgpu::Device, format: wgpu::TextureFormat) -> Self {
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("MeasureLab spectrogram shader"),
            source: wgpu::ShaderSource::Wgsl(include_str!("spectrogram.wgsl").into()),
        });
        let layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("MeasureLab spectrogram resources"),
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: std::num::NonZeroU64::new(32),
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: false },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
            ],
        });
        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("MeasureLab spectrogram layout"),
            bind_group_layouts: &[Some(&layout)],
            immediate_size: 0,
        });
        let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("MeasureLab spectrogram rows"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs_main"),
                buffers: &[Some(wgpu::VertexBufferLayout {
                    array_stride: 16,
                    step_mode: wgpu::VertexStepMode::Instance,
                    attributes: &wgpu::vertex_attr_array![0 => Float32x4],
                })],
                compilation_options: Default::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs_main"),
                targets: &[Some(wgpu::ColorTargetState {
                    format,
                    blend: None,
                    write_mask: wgpu::ColorWrites::ALL,
                })],
                compilation_options: Default::default(),
            }),
            primitive: Default::default(),
            depth_stencil: None,
            multisample: Default::default(),
            multiview_mask: None,
            cache: None,
        });
        let uniform = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("MeasureLab spectrogram parameters"),
            contents: bytemuck::cast_slice(&[0_f32; 8]),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });
        let texture = texture(device, 1);
        let binding = binding(device, &layout, &uniform, &texture);
        let instances = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("MeasureLab spectrogram time intervals"),
            size: (ROWS * 2 * 16) as u64,
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        Self {
            pipeline,
            layout,
            uniform,
            texture,
            binding,
            instances,
            scanlines: 1,
            versions: [0; ROWS],
            revision: u64::MAX,
            seconds: 0.0,
            count: 0,
            placements: Vec::with_capacity(ROWS * 2),
            vertices: Vec::with_capacity(ROWS * 2),
            parameters: [0.0; 8],
            uploaded_rows: 0,
        }
    }

    pub fn prepare(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        history: &History,
        view: View,
        seconds: f64,
        width: f32,
    ) {
        let Some(config) = history.config() else {
            self.count = 0;
            return;
        };
        let scanlines = history.stride() / TEXTURE_WIDTH;
        if self.scanlines != scanlines {
            self.texture = texture(device, scanlines);
            self.binding = binding(device, &self.layout, &self.uniform, &self.texture);
            self.scanlines = scanlines;
            self.versions.fill(0);
        }
        for slot in 0..ROWS {
            if self.versions[slot] == history.version(slot) {
                continue;
            }
            if let Some((_, db)) = history.row(slot) {
                queue.write_texture(
                    wgpu::TexelCopyTextureInfo {
                        texture: &self.texture,
                        mip_level: 0,
                        origin: wgpu::Origin3d {
                            x: 0,
                            y: (slot * scanlines) as u32,
                            z: 0,
                        },
                        aspect: wgpu::TextureAspect::All,
                    },
                    bytemuck::cast_slice(db),
                    wgpu::TexelCopyBufferLayout {
                        offset: 0,
                        bytes_per_row: Some((TEXTURE_WIDTH * 4) as u32),
                        rows_per_image: Some(scanlines as u32),
                    },
                    wgpu::Extent3d {
                        width: TEXTURE_WIDTH as u32,
                        height: scanlines as u32,
                        depth_or_array_layers: 1,
                    },
                );
                self.uploaded_rows += 1;
            }
            self.versions[slot] = history.version(slot);
        }
        if self.revision != history.revision() || self.seconds != seconds {
            history.placements(seconds, &mut self.placements);
            self.vertices.clear();
            self.vertices.extend(self.placements.iter().map(|p| {
                [
                    p.slot.map_or(-1.0, |slot| slot as f32),
                    p.top,
                    p.bottom,
                    0.0,
                ]
            }));
            if !self.vertices.is_empty() {
                queue.write_buffer(&self.instances, 0, bytemuck::cast_slice(&self.vertices));
            }
            self.count = self.vertices.len() as u32;
            self.revision = history.revision();
            self.seconds = seconds;
        }
        let parameters = [
            view.min_hz,
            view.max_hz,
            config.sample_rate as f32 / config.size as f32,
            view.floor_db,
            view.ceiling_db,
            if view.scale == FrequencyScale::Log {
                1.0
            } else {
                0.0
            },
            width,
            scanlines as f32,
        ];
        if self.parameters != parameters {
            queue.write_buffer(&self.uniform, 0, bytemuck::cast_slice(&parameters));
            self.parameters = parameters;
        }
    }
    pub fn paint(&self, pass: &mut wgpu::RenderPass<'_>) {
        if self.count == 0 {
            return;
        }
        pass.set_pipeline(&self.pipeline);
        pass.set_bind_group(0, &self.binding, &[]);
        pass.set_vertex_buffer(0, self.instances.slice(..));
        pass.draw(0..6, 0..self.count);
    }
}
fn texture(device: &wgpu::Device, scanlines: usize) -> wgpu::Texture {
    device.create_texture(&wgpu::TextureDescriptor {
        label: Some("MeasureLab bounded circular STFT texture"),
        size: wgpu::Extent3d {
            width: TEXTURE_WIDTH as u32,
            height: (ROWS * scanlines) as u32,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: wgpu::TextureFormat::R32Float,
        usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
        view_formats: &[],
    })
}
fn binding(
    device: &wgpu::Device,
    layout: &wgpu::BindGroupLayout,
    uniform: &wgpu::Buffer,
    texture: &wgpu::Texture,
) -> wgpu::BindGroup {
    device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("MeasureLab spectrogram binding"),
        layout,
        entries: &[
            wgpu::BindGroupEntry {
                binding: 0,
                resource: uniform.as_entire_binding(),
            },
            wgpu::BindGroupEntry {
                binding: 1,
                resource: wgpu::BindingResource::TextureView(
                    &texture.create_view(&Default::default()),
                ),
            },
        ],
    })
}

pub struct Callback {
    // Only UI and renderer access this lock. Acquisition and DSP never lock it.
    pub history: Arc<Mutex<History>>,
    pub view: View,
    pub seconds: f64,
    pub width: f32,
}
impl egui_wgpu::CallbackTrait for Callback {
    fn prepare(
        &self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        _: &egui_wgpu::ScreenDescriptor,
        _: &mut wgpu::CommandEncoder,
        resources: &mut egui_wgpu::CallbackResources,
    ) -> Vec<wgpu::CommandBuffer> {
        if let Some(renderer) = resources.get_mut::<Renderer>() {
            renderer.prepare(
                device,
                queue,
                &self.history.lock().unwrap(),
                self.view,
                self.seconds,
                self.width,
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
        if let Some(renderer) = resources.get::<Renderer>() {
            renderer.paint(pass);
        }
    }
}
