shader_type canvas_item;
render_mode unshaded, blend_disabled;

uniform sampler2D edge_diffusion : filter_linear, repeat_disable;
uniform vec2 screen_size = vec2(4.2, 2.3625);
uniform vec2 field_size = vec2(9.0, 7.1625);
uniform float margin = 2.688;
uniform float sigma_max = 1.80656;

vec4 edge(int side, float point, float level) {
	float length = (side == 0 || side == 2) ? screen_size.x : screen_size.y;
	vec2 uv = vec2(point / (length + 2.0 * margin) + 0.5,
		(float(side * 16) + clamp(level, 0.0, 15.0) + 0.5) / 64.0);
	return textureLod(edge_diffusion, uv, 0.0);
}

void fragment() {
	vec2 point = (UV - 0.5) * field_size;
	vec2 outside = max(abs(point) - screen_size * 0.5, vec2(0.0));
	float distance = length(outside);
	// Every perimeter sample contributes a radial Gaussian. The minimum
	// width joins neighbouring regions; increasing width lets colours overlap
	// naturally farther from the picture without choosing a nearest side.
	float sigma = 0.14 + 0.62 * distance;
	float inverse_variance = 0.5 / (sigma * sigma);
	float level = log(sigma / 0.14) / log(sigma_max / 0.14) * 15.0;
	vec2 top_right = point + vec2(0.0, screen_size.y * 0.5);
	vec4 total = edge(0, point.x, level) * exp(-top_right.y * top_right.y * inverse_variance);
	float separation = point.x - screen_size.x * 0.5;
	total += edge(1, point.y, level) * exp(-separation * separation * inverse_variance);
	separation = point.y - screen_size.y * 0.5;
	total += edge(2, -point.x, level) * exp(-separation * separation * inverse_variance);
	separation = point.x + screen_size.x * 0.5;
	total += edge(3, -point.y, level) * exp(-separation * separation * inverse_variance);
	// Constant input must stay constant through corners. Spatial falloff and
	// optical dark-colour compensation are applied once in the world shader.
	COLOR = vec4(total.rgb / max(total.a, 0.0000001), 1.0);
}
