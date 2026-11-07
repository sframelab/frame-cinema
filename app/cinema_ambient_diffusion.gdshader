shader_type canvas_item;
render_mode unshaded, blend_disabled;

uniform sampler2D edge_colors : filter_nearest, repeat_disable;
uniform vec2 screen_size = vec2(4.2, 2.3625);
uniform float margin = 2.688;
uniform float sigma_max = 1.80656;

void fragment() {
	int row = min(63, int(UV.y * 64.0));
	int side = row / 16;
	float level = float(row - side * 16) / 15.0;
	float sigma = 0.14 * pow(sigma_max / 0.14, level);
	float length = (side == 0 || side == 2) ? screen_size.x : screen_size.y;
	float point = (UV.x - 0.5) * (length + 2.0 * margin);
	float inverse_variance = 0.5 / (sigma * sigma);
	vec3 energy = vec3(0.0);
	float mass = 0.0;
	for (int region = 0; region < 64; region++) {
		float t = (float(region) + 0.5) / 64.0;
		float delta = point - (t - 0.5) * length;
		float weight = exp(-delta * delta * inverse_variance) * length / 64.0;
		vec3 color = textureLod(edge_colors, vec2(t, (float(side) + 0.5) / 4.0), 0.0).rgb;
		energy += color * weight;
		mass += weight;
	}
	// Premultiplied energy and Gaussian mass; the field normalizes only after
	// combining all four sides. HDR storage preserves values above one.
	COLOR = vec4(energy, mass);
}
