shader_type canvas_item;

// Fit the untouched TV icon without stretching or cropping its wordmark.
// Clamping extends the artwork's background to the taller cinema tile.
uniform sampler2D artwork : source_color, filter_linear_mipmap, repeat_disable;
uniform vec2 artwork_size = vec2(1280.0, 768.0);
uniform vec2 card_size = vec2(275.2, 252.0);
uniform float corner_radius = 40.0;
uniform float hover = 0.0;
uniform bool light_artwork = false;

float rounded_box(vec2 p, vec2 half_size, float r) {
	vec2 q = abs(p) - half_size + r;
	return length(max(q, vec2(0.0))) + min(max(q.x, q.y), 0.0) - r;
}

void fragment() {
	vec2 pixel = UV * card_size;
	float d = rounded_box(pixel - card_size * 0.5, card_size * 0.5 - vec2(1.0), corner_radius);
	float mask = 1.0 - smoothstep(-0.75, 0.75, d);
	float scale = min(card_size.x * 0.90 / artwork_size.x, (card_size.y - 70.0) / artwork_size.y);
	vec2 fitted_size = artwork_size * scale;
	vec2 center = card_size * 0.5 - vec2(0.0, 8.0);
	vec2 artwork_uv = clamp((pixel - center) / fitted_size + vec2(0.5), vec2(0.0), vec2(1.0));
	vec3 color = texture(artwork, artwork_uv).rgb;
	float rim = smoothstep(-3.2, -1.2, d) * (0.12 + 0.58 * hover);
	color = mix(color, light_artwork ? vec3(0.1) : vec3(1.0), rim);
	COLOR = vec4(color, mask);
}
