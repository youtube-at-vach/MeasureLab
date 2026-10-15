struct Parameters {
    frequency: vec4<f32>, // min Hz, max Hz, bin Hz, floor dBFS
    display: vec4<f32>,   // ceiling dBFS, logarithmic, physical width, scanlines/row
    colors: array<vec4<f32>, 3>, // Shared with the CPU color bar.
}
@group(0) @binding(0) var<uniform> p: Parameters;
@group(0) @binding(1) var history: texture_2d<f32>;

struct VertexOut {
    @builtin(position) position: vec4<f32>,
    @location(0) x: f32,
    @location(1) @interpolate(flat) slot: i32,
}
@vertex
fn vs_main(@builtin(vertex_index) vertex: u32, @location(0) row: vec4<f32>) -> VertexOut {
    let corners = array<vec2<f32>, 6>(vec2(0., 0.), vec2(1., 0.), vec2(0., 1.),
                                     vec2(0., 1.), vec2(1., 0.), vec2(1., 1.));
    let corner = corners[vertex];
    let y = mix(row.y, row.z, corner.y);
    var out: VertexOut;
    out.position = vec4(corner.x * 2. - 1., 1. - y * 2., 0., 1.);
    out.x = corner.x;
    out.slot = i32(row.x);
    return out;
}
fn frequency(x: f32) -> f32 {
    if p.display.y > 0.5 {
        return p.frequency.x * pow(p.frequency.y / p.frequency.x, x);
    }
    return mix(p.frequency.x, p.frequency.y, x);
}
fn color(t: f32) -> vec3<f32> {
    if t < 0.5 { return mix(p.colors[0].rgb, p.colors[1].rgb, t * 2.); }
    return mix(p.colors[1].rgb, p.colors[2].rgb, (t - 0.5) * 2.);
}
@fragment
fn fs_main(in: VertexOut) -> @location(0) vec4<f32> {
    if in.slot < 0 {
        let stripe = u32(in.position.x + in.position.y) % 12u < 3u;
        return vec4(select(vec3(0.19, 0.075, 0.025), vec3(0.42, 0.19, 0.06), stripe), 1.);
    }
    let half_pixel = 0.5 / max(p.display.z, 1.);
    let min_bin = u32(ceil(p.frequency.x / p.frequency.z));
    let max_bin = u32(floor(p.frequency.y / p.frequency.z));
    var first = max(min_bin, u32(ceil(frequency(max(0., in.x - half_pixel)) / p.frequency.z)));
    var last = min(max_bin, u32(floor(frequency(min(1., in.x + half_pixel)) / p.frequency.z)));
    if first > last {
        first = clamp(u32(round(frequency(in.x) / p.frequency.z)), min_bin, max_bin);
        last = first;
    }
    let width = u32(textureDimensions(history).x);
    var db = -3.402823e38;
    var valid = false;
    var invalid = false;
    // Keep the strongest bin covered by this pixel, including on a log axis.
    for (var bin = first; bin <= last; bin += 1u) {
        let y = u32(in.slot) * u32(p.display.w) + bin / width;
        let value = textureLoad(history, vec2<i32>(i32(bin % width), i32(y)), 0).r;
        // Inspect bits: shader optimizations need not preserve NaN comparisons.
        // -infinity is valid silence; NaN and +infinity are invalid.
        let bits = bitcast<u32>(value);
        if (bits & 0x7f800000u) != 0x7f800000u || bits == 0xff800000u {
            valid = true;
            db = max(db, value);
        } else { invalid = true; }
    }
    if invalid || !valid {
        let stripe = u32(in.position.x + in.position.y) % 12u < 3u;
        return vec4(select(vec3(0.19, 0.075, 0.025), vec3(0.42, 0.19, 0.06), stripe), 1.);
    }
    let t = clamp((db - p.frequency.w) / (p.display.x - p.frequency.w), 0., 1.);
    return vec4(color(t), 1.);
}
