shader_type canvas_item;

// 0.4.34 service tile: a lit, glassy poster card in the service's own hue.
// No provider artwork or logos are drawn; identity comes from colour and type.
uniform vec2 card_size = vec2(480.0, 260.0);
uniform float corner_radius = 40.0;
uniform vec3 hue = vec3(0.84, 0.13, 0.21);
uniform float hover = 0.0;
uniform float pressed = 0.0;

float rounded_box(vec2 p, vec2 half_size, float r) {
	vec2 q = abs(p) - half_size + r;
	return length(max(q, vec2(0.0))) + min(max(q.x, q.y), 0.0) - r;
}

float hash(vec2 p) {
	return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

void fragment() {
	vec2 pixel = UV * card_size;
	vec2 local = pixel - card_size * 0.5;
	float d = rounded_box(local, card_size * 0.5 - vec2(1.0), corner_radius);
	float mask = 1.0 - smoothstep(-0.75, 0.75, d);
	vec2 uv = UV;
	// Deep, saturated base that falls to near-black at the lower right.
	vec3 deep = hue * 0.16 + vec3(0.012, 0.013, 0.018);
	vec3 bright = mix(hue, vec3(1.0), 0.08) * 0.95;
	float diagonal = clamp(uv.x * 0.45 + uv.y * 0.75, 0.0, 1.0);
	vec3 color = mix(bright, deep, smoothstep(0.0, 1.0, diagonal));
	// Studio light from the top left, plus a faint cool counter-light.
	float key = exp(-2.6 * length((uv - vec2(0.12, -0.08)) * vec2(0.9, 1.4)));
	color += mix(hue, vec3(1.0), 0.55) * key * (0.20 + 0.10 * hover);
	float counter = exp(-3.5 * length((uv - vec2(1.05, 1.1)) * vec2(1.0, 1.2)));
	color += vec3(0.20, 0.24, 0.32) * counter * 0.10;
	// Bottom scrim keeps the title legible.
	color *= mix(1.0, 0.62, smoothstep(0.45, 1.0, uv.y));
	color *= 1.0 + 0.10 * hover - 0.10 * pressed;
	// Glass edge: bright top rim, faint everywhere else.
	vec2 g = vec2(rounded_box(local + vec2(1.0, 0.0), card_size * 0.5 - vec2(1.0), corner_radius) - rounded_box(local - vec2(1.0, 0.0), card_size * 0.5 - vec2(1.0), corner_radius),
		rounded_box(local + vec2(0.0, 1.0), card_size * 0.5 - vec2(1.0), corner_radius) - rounded_box(local - vec2(0.0, 1.0), card_size * 0.5 - vec2(1.0), corner_radius));
	vec2 n = length(g) > 0.0001 ? normalize(g) : vec2(0.0, -1.0);
	float rim = exp(-max(-d, 0.0) / 1.2) * mask;
	float top = clamp(dot(n, normalize(vec2(-0.3, -1.0))), 0.0, 1.0);
	color = mix(color, vec3(1.0), rim * (0.12 + 0.50 * top * top + 0.25 * hover));
	color += (hash(floor(pixel)) - 0.5) * 0.014;
	COLOR = vec4(color, mask);
}
