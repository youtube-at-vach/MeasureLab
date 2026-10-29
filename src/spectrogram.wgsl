struct Parameters {
    horizontal: vec4<f32>, // min, max, step (Hz or seconds), color floor
    display: vec4<f32>,   // color ceiling, logarithmic, physical width, scanlines/row
    palette: vec4<f32>,   // last color index, time offset, time scale, cepstral state marker
    colors: array<vec4<f32>, 256>, // Shared with the CPU color bar.
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
    let y = mix(row.y, row.z, corner.y) * p.palette.z + p.palette.y;
    var out: VertexOut;
    out.position = vec4(corner.x * 2. - 1., 1. - y * 2., 0., 1.);
    out.x = corner.x;
    out.slot = i32(row.x);
    return out;
}
fn coordinate(x: f32) -> f32 {
    if p.display.y > 0.5 {
        return p.horizontal.x * pow(p.horizontal.y / p.horizontal.x, x);
    }
    return mix(p.horizontal.x, p.horizontal.y, x);
}
fn color(t: f32) -> vec3<f32> {
    let position = clamp(t, 0., 1.) * p.palette.x;
    let index = min(u32(position), u32(p.palette.x) - 1u);
    return mix(p.colors[index].rgb, p.colors[index + 1u].rgb, position - f32(index));
}
@fragment
fn fs_main(in: VertexOut) -> @location(0) vec4<f32> {
    if in.slot < 0 {
        let stripe = u32(in.position.x + in.position.y) % 12u < 3u;
        return vec4(select(vec3(0.19, 0.075, 0.025), vec3(0.42, 0.19, 0.06), stripe), 1.);
    }
    let width = u32(textureDimensions(history).x);
    if p.display.w < 0. {
        let bin = min(u32(in.x * f32(width)), width - 1u);
        let value = textureLoad(history, vec2<i32>(i32(bin), in.slot), 0).r;
        let bits = bitcast<u32>(value);
        if p.palette.w > 0.5 && bits == 0x7f800000u { return vec4(0.10, 0.13, 0.15, 1.); }
        if (bits & 0x7f800000u) == 0x7f800000u && bits != 0xff800000u {
            let stripe = u32(in.position.x + in.position.y) % 12u < 3u;
            return vec4(select(vec3(0.19, 0.075, 0.025), vec3(0.42, 0.19, 0.06), stripe), 1.);
        }
        let t = clamp((value - p.horizontal.w) / (p.display.x - p.horizontal.w), 0., 1.);
        return vec4(color(t), 1.);
    }
    let half_pixel = 0.5 / max(p.display.z, 1.);
    let min_bin = u32(ceil(p.horizontal.x / p.horizontal.z));
    let max_bin = u32(floor(p.horizontal.y / p.horizontal.z));
    var first = max(min_bin, u32(ceil(coordinate(max(0., in.x - half_pixel)) / p.horizontal.z)));
    var last = min(max_bin, u32(floor(coordinate(min(1., in.x + half_pixel)) / p.horizontal.z)));
    if first > last {
        first = clamp(u32(round(coordinate(in.x) / p.horizontal.z)), min_bin, max_bin);
        last = first;
    }
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
        if p.palette.w > 0.5 && bits == 0x7f800000u { return vec4(0.10, 0.13, 0.15, 1.); }
        if (bits & 0x7f800000u) != 0x7f800000u || bits == 0xff800000u {
            valid = true;
            db = max(db, value);
        } else { invalid = true; }
    }
    if invalid || !valid {
        let stripe = u32(in.position.x + in.position.y) % 12u < 3u;
        return vec4(select(vec3(0.19, 0.075, 0.025), vec3(0.42, 0.19, 0.06), stripe), 1.);
    }
    let t = clamp((db - p.horizontal.w) / (p.display.x - p.horizontal.w), 0., 1.);
    return vec4(color(t), 1.);
}
