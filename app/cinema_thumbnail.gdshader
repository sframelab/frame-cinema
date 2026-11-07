shader_type canvas_item;
// 0.4.34 environment photo: rounded clip, lifted midtones and a lower scrim
// for the caption. Dark Room draws a procedural theatre glow instead.
uniform vec2 card_size = vec2(488.0, 160.0);
uniform float corner_radius = 28.0;
uniform float scrim = 1.0;
uniform bool dark_room = false;
varying vec2 local_position;
void vertex() {
	local_position = VERTEX;
}
void fragment() {
	// KEEP_ASPECT_COVERED crops texture UVs. Clip in card coordinates so the
	// rounded corners stay at the control edges, not at the cropped photo edges.
	vec2 card_uv = local_position / card_size;
	vec2 q = abs(local_position - card_size * 0.5) - card_size * 0.5 + corner_radius;
	float d = length(max(q, vec2(0.0))) + min(max(q.x, q.y), 0.0) - corner_radius;
	vec3 color;
	if (dark_room) {
		// A dim screen glowing above a black floor.
		vec2 s = (card_uv - vec2(0.5, 0.36)) * vec2(1.0, 1.9);
		float screen = 1.0 - smoothstep(0.20, 0.23, max(abs(s.x), abs(s.y) * 0.62));
		float halo = exp(-5.0 * length(s * vec2(0.8, 1.0)));
		color = vec3(0.012, 0.014, 0.02) + vec3(0.30, 0.36, 0.50) * halo * 0.35 + vec3(0.42, 0.48, 0.60) * screen * 0.55;
		float floor_glow = exp(-6.0 * length((card_uv - vec2(0.5, 0.82)) * vec2(0.7, 2.2)));
		color += vec3(0.18, 0.22, 0.30) * floor_glow * 0.25;
	} else {
		vec4 photo = texture(TEXTURE, UV);
		// Thumbnails are captured dark; lift mid-tones without clipping skies.
		color = pow(max(photo.rgb, vec3(0.0)), vec3(0.86)) * 1.06;
	}
	color *= mix(1.0, 0.42, scrim * smoothstep(0.38, 1.0, card_uv.y));
	COLOR = vec4(color, 1.0 - smoothstep(-0.8, 0.8, d));
}
