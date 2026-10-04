struct Parameters { viewport: vec2<f32>, width: f32, padding: f32 };
@group(0) @binding(0) var<uniform> parameters: Parameters;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) color: vec4<f32>,
    @location(1) side: f32,
};

@vertex
fn vs_main(
    @builtin(vertex_index) vertex: u32,
    @location(0) a: vec2<f32>,
    @location(1) b: vec2<f32>,
    @location(2) color: vec4<f32>,
) -> VertexOutput {
    let corners = array<vec2<f32>, 6>(
        vec2(0.0, -1.0), vec2(1.0, -1.0), vec2(1.0, 1.0),
        vec2(0.0, -1.0), vec2(1.0, 1.0), vec2(0.0, 1.0),
    );
    let corner = corners[vertex];
    let delta = (b - a) * parameters.viewport;
    let length = max(length(delta), 0.0001);
    let direction = select(vec2(1.0, 0.0), delta / length, length > 0.0002);
    let normal = vec2(-direction.y, direction.x);
    let half_width = parameters.width * 0.5 + 1.0;
    let pixel = mix(a, b, corner.x) * parameters.viewport
        + normal * corner.y * half_width
        + direction * (corner.x * 2.0 - 1.0) * 0.5;
    var out: VertexOutput;
    out.position = vec4(pixel.x / parameters.viewport.x * 2.0 - 1.0,
        1.0 - pixel.y / parameters.viewport.y * 2.0, 0.0, 1.0);
    out.color = color;
    out.side = corner.y * half_width;
    return out;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    let alpha = 1.0 - smoothstep(parameters.width * 0.5,
        parameters.width * 0.5 + 1.0, abs(in.side));
    return vec4(in.color.rgb, in.color.a * alpha);
}
