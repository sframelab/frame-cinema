shader_type spatial;
render_mode specular_disabled, ambient_light_disabled;

uniform sampler2D radiance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D reflectance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D surface_normal : filter_linear_mipmap_anisotropic, repeat_disable;
uniform bool contact_enabled = false;
uniform sampler2D contact_albedo : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D contact_normal : filter_linear_mipmap_anisotropic, repeat_disable;
uniform float baked_strength = 1.0;
uniform mat3 source_normal_basis;
uniform bool debug_normal = false;
uniform bool debug_albedo = false;
// Near-field grain for the photogrammetry: the 4K bake smears at arm's length.
uniform sampler2D rock_detail : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform float rock_detail_mean = 0.348;
// 0.5.4: pebble detail for smeared scan areas (rocks_ground_06, CC0).
// Sampled raw (no source_color): the mean is the sRGB-encoded luminance mean.
uniform sampler2D ground_detail : filter_linear_mipmap_anisotropic, repeat_enable;
uniform float ground_detail_mean = 0.521;
// 0.5.1 detail transfer: rock-texture resolution / this part's lighting-bake
// resolution (2 for a 2K bake under a 4K texture). The bake is multiplied by the
// texture's sharp/blurred ratio, restoring the detail a lower-resolution bake
// lost, so neighbouring parts match and their joins stop reading as seams.
uniform float detail_ratio = 1.0;
varying vec3 rock_position;
varying vec3 rock_normal;

void vertex() {
	rock_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	rock_normal = (MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz;
}

void fragment() {
	vec3 n = texture(surface_normal, UV).rgb * 2.0 - vec3(1.0);
	ALBEDO = texture(reflectance, UV).rgb;
	if (contact_enabled) {
		vec2 dx = dFdx(UV);
		vec2 dy = dFdy(UV);
		if (UV2.x > 0.0001) {
			float weight = smoothstep(0.0, 0.04, UV2.x);
			n = normalize(mix(n, textureGrad(contact_normal, UV, dx, dy).rgb * 2.0 - vec3(1.0), weight));
			ALBEDO = mix(ALBEDO, textureGrad(contact_albedo, UV, dx, dy).rgb, weight);
		}
	}
	NORMAL = normalize((VIEW_MATRIX * MODEL_MATRIX * vec4(source_normal_basis * n, 0.0)).xyz);
	EMISSION = texture(radiance, UV).rgb * baked_strength;
	// 0.5.4: the soft sample sits at least log2(ratio) mips down. Up close
	// (magnified, the floor under the seat) a footprint-scaled gradient still
	// landed on mip 0, so 0.5.1-0.5.3 restored nothing exactly where it mattered.
	if (detail_ratio > 1.01) {
		vec2 scan_size = vec2(textureSize(reflectance, 0));
		float lod = max(0.0, 0.5 * log2(max(dot(dFdx(UV) * scan_size, dFdx(UV) * scan_size), dot(dFdy(UV) * scan_size, dFdy(UV) * scan_size))));
		vec3 sharp = texture(reflectance, UV).rgb;
		vec3 soft = textureLod(reflectance, UV, lod + log2(detail_ratio)).rgb;
		EMISSION *= clamp((sharp + 0.03) / (soft + 0.03), vec3(0.55), vec3(1.7));
	}
	// 0.5.6: one gentle, uniform grain on all rock within ~8 m, fading with
	// distance. 0.5.1-0.5.5 switched grain on per pixel where the scan looked
	// smeared or stretched; on the headset the boundaries between treated and
	// untreated patches read as a texture mashup. No per-area switching now.
	vec3 luma3 = vec3(0.2126, 0.7152, 0.0722);
	float grain_w = 0.35 * (1.0 - smoothstep(3.0, 8.0, length(VERTEX)));
	if (grain_w > 0.0) {
		vec3 blend = pow(abs(normalize(rock_normal)), vec3(4.0));
		blend /= dot(blend, vec3(1.0));
		// Pebble ground (rocks_ground_06, ~2 m tile), cracks two mips soft and
		// contrast compressed: surface grain, never outlines.
		vec3 p = rock_position * 0.5;
		float a = 0.0;
		if (blend.x > 0.02) a += dot(texture(ground_detail, p.zy, 2.0).rgb, luma3) * blend.x;
		if (blend.y > 0.02) a += dot(texture(ground_detail, p.xz, 2.0).rgb, luma3) * blend.y;
		if (blend.z > 0.02) a += dot(texture(ground_detail, p.xy, 2.0).rgb, luma3) * blend.z;
		EMISSION *= mix(1.0, pow(clamp(a / ground_detail_mean, 0.5, 1.6), 0.5), grain_w);
	}
	ROUGHNESS = 1.0;
	if (debug_normal) {
		vec3 world_normal = normalize((INV_VIEW_MATRIX * vec4(NORMAL, 0.0)).xyz);
		EMISSION = vec3(world_normal.x, -world_normal.z, world_normal.y) * 0.5 + vec3(0.5);
		ALBEDO = vec3(0.0);
	} else if (debug_albedo) {
		EMISSION = ALBEDO;
		ALBEDO = vec3(0.0);
	}
}
