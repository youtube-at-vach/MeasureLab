struct Params {
    low: f32, high: f32, points: u32, width: u32,
    height: u32, head: u32, retained: u32, heatmap: u32,
};
@group(0) @binding(0) var<storage, read> input: array<f32>;
@group(0) @binding(1) var<storage, read_write> columns: array<f32>;
@group(0) @binding(2) var<storage, read_write> image: array<u32>;
@group(0) @binding(3) var<uniform> p: Params;
@compute @workgroup_size(64)
fn reduce(@builtin(global_invocation_id) id: vec3<u32>) {
    let x = id.x;
    if x >= p.width { return; }
    let last = f32(p.points - 1u);
    let a = u32(floor((p.low + (p.high - p.low) * f32(x) / f32(p.width)) * last));
    let b = min(p.points - 1u, u32(ceil((p.low + (p.high - p.low) * f32(x + 1u) / f32(p.width)) * last)));
    var peak = 0.0;
    for (var k = a; k <= b; k += 1u) { peak = max(peak, input[k]); }
    columns[x] = clamp(-20.0 * log2(max(peak, 1e-6)) / log2(10.0) / 120.0, 0.0, 1.0);
}
@compute @workgroup_size(8, 8)
fn raster(@builtin(global_invocation_id) id: vec3<u32>) {
    let x = id.x;
    let y = id.y;
    if x >= p.width || y >= p.height { return; }
    var rgb = vec3<f32>(16.0, 27.0, 43.0);
    if p.heatmap == 1u {
        let age = min(31u, y * 32u / p.height);
        if age < p.retained {
            let row = (p.head + 32u - age) % 32u;
            let k = min(p.points - 1u, u32((p.low + (p.high - p.low) * f32(x) / f32(p.width - 1u)) * f32(p.points - 1u)));
            let peak = input[row * p.points + k];
            let level = clamp((20.0 * log2(max(peak, 1e-6)) / log2(10.0) + 100.0) / 100.0, 0.0, 1.0);
            rgb = vec3<f32>(220.0 * level, 170.0 * level, 210.0 * (1.0 - level));
        }
    } else {
        let a = columns[x] * f32(p.height - 1u);
        let b = columns[select(x - 1u, 0u, x == 0u)] * f32(p.height - 1u);
        if f32(y) >= min(a, b) - 1.0 && f32(y) <= max(a, b) + 1.0 {
            rgb = vec3<f32>(98.0, 216.0, 233.0);
        }
    }
    let c = vec3<u32>(rgb);
    image[y * p.width + x] = c.r | (c.g << 8u) | (c.b << 16u) | 0xff000000u;
}
