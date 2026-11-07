shader_type spatial;
render_mode unshaded, blend_add, depth_draw_never, cull_back, fog_disabled, shadows_disabled;

// Additive lamp halos: one small quad per lamp, math only (no texture, no depth read).
// UV is metres from the lamp centre, UV2 the core half-extents. Vertex colours are
// 8-bit, so COLOR.rgb holds tint*gain/2 and COLOR.a holds sigma*10 (metres).
uniform float brightness = 1.0;

const float MARGIN = 0.06;
const float COLOR_SCALE = 2.0;

float edge_feather(vec2 p, vec2 core) {
	vec2 room = core + MARGIN - abs(p);
	return smoothstep(0.0, 0.02, min(room.x, room.y));
}

void fragment() {
	vec2 q = max(abs(UV) - UV2, vec2(0.0));
	float sigma = max(COLOR.a * 0.1, 0.002);
	ALBEDO = COLOR.rgb * COLOR_SCALE * exp(-dot(q, q) / (sigma * sigma)) * brightness * edge_feather(UV, UV2);
}
