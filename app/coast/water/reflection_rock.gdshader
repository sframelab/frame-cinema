shader_type spatial;
render_mode specular_disabled, ambient_light_disabled;

uniform sampler2D radiance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D reflectance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D surface_normal : filter_linear_mipmap_anisotropic, repeat_disable;
uniform float baked_strength = 1.0;
uniform mat3 source_normal_basis;
uniform bool debug_normal = false;
uniform bool debug_albedo = false;
uniform vec4 reflection_clip_plane = vec4(0.0, 1.0, 0.0, 10000.0);
varying vec3 world_position;

void vertex() {
	world_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	// Only reflected cameras lie below this world-space water plane. Clip
	// submerged source geometry there; keep the original main view untouched.
	// Cover the cached trough envelope (-0.676 m) plus raster/filter margin.
	// Exact mean-plane clipping exposed sky under the cliff as waves fell.
	// This guard only affects the reflection; main geometry stays unchanged.
	if (dot(reflection_clip_plane, vec4(CAMERA_POSITION_WORLD, 1.0)) < 0.0 && dot(reflection_clip_plane, vec4(world_position, 1.0)) < -0.75) { discard; }
	vec3 n = texture(surface_normal, UV).rgb * 2.0 - vec3(1.0);
	NORMAL = normalize((VIEW_MATRIX * MODEL_MATRIX * vec4(source_normal_basis * n, 0.0)).xyz);
	ALBEDO = texture(reflectance, UV).rgb;
	EMISSION = texture(radiance, UV).rgb * baked_strength;
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
