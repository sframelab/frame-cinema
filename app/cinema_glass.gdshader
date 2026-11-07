shader_type canvas_item;

// 0.4.34 visionOS-style window glass. The UI is uploaded as a compositor
// overlay, so true backdrop blur is impossible here; depth comes from a
// luminous body, a directional specular rim, a soft contact shadow and fine
// grain that reads as frosted material and prevents gradient banding.
// The rect covers the whole UI viewport; the glass is inset by `inset`.
uniform vec2 panel_size = vec2(1600.0, 650.0);
uniform float inset = 16.0;
uniform float corner_radius = 52.0;
uniform float opacity = 0.84;
uniform float shadow = 1.0;
uniform vec3 top_tint = vec3(0.215, 0.222, 0.240);
uniform vec3 bottom_tint = vec3(0.118, 0.123, 0.138);

float rounded_box(vec2 p, vec2 half_size, float r) {
	vec2 q = abs(p) - half_size + r;
	return length(max(q, vec2(0.0))) + min(max(q.x, q.y), 0.0) - r;
}

float hash(vec2 p) {
	return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

void fragment() {
	vec2 pixel = UV * panel_size;
	vec2 body = panel_size - vec2(inset * 2.0);
	vec2 local = pixel - panel_size * 0.5;
	float d = rounded_box(local, body * 0.5, corner_radius);
	// Analytic edge normal for the rim light.
	float e = 1.0;
	vec2 grad = vec2(
		rounded_box(local + vec2(e, 0.0), body * 0.5, corner_radius) - rounded_box(local - vec2(e, 0.0), body * 0.5, corner_radius),
		rounded_box(local + vec2(0.0, e), body * 0.5, corner_radius) - rounded_box(local - vec2(0.0, e), body * 0.5, corner_radius));
	vec2 normal = length(grad) > 0.0001 ? normalize(grad) : vec2(0.0, -1.0);
	float mask = 1.0 - smoothstep(-0.75, 0.75, d);
	vec2 inner_uv = clamp((pixel - vec2(inset)) / body, vec2(0.0), vec2(1.0));

	vec3 surface = mix(top_tint, bottom_tint, smoothstep(0.0, 1.0, inner_uv.y));
	// Broad overhead sheen, offset to the upper left like a soft key light.
	float sheen = exp(-3.2 * length((inner_uv - vec2(0.22, -0.25)) * vec2(0.85, 1.35)));
	surface += vec3(1.0) * sheen * 0.055;
	// Directional specular rim: strong along the top, faint on the sides.
	float light = clamp(dot(normal, normalize(vec2(-0.25, -1.0))), 0.0, 1.0);
	float rim = exp(-max(-d, 0.0) / 1.15) * mask;
	surface = mix(surface, vec3(0.96, 0.97, 1.0), rim * (0.10 + 0.55 * light * light));
	// A gentle inner falloff near the lower edge adds thickness.
	float lower = exp(-max(-d, 0.0) / 10.0) * clamp(dot(normal, vec2(0.0, 1.0)), 0.0, 1.0);
	surface *= 1.0 - 0.18 * lower;
	// Frosted grain, below one 8-bit step at mid grey.
	surface += (hash(floor(pixel)) - 0.5) * 0.012;

	float alpha = mask * opacity;
	// Soft, slightly lowered contact shadow outside the glass.
	float ds = rounded_box(local - vec2(0.0, 5.0), body * 0.5, corner_radius);
	float halo = shadow * 0.30 * exp(-max(ds, 0.0) / 7.5) * (1.0 - mask) * smoothstep(-6.0, 0.5, ds);
	vec3 color = surface * alpha;
	float total = alpha + halo * (1.0 - alpha);
	COLOR = vec4(total > 0.0 ? color / total : vec3(0.0), total);
}
