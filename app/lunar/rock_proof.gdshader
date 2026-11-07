shader_type spatial;
render_mode specular_disabled, ambient_light_disabled;

uniform sampler2D radiance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D reflectance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D surface_normal : filter_linear_mipmap_anisotropic, repeat_disable;
uniform float baked_strength = 1.0;
uniform float normal_y = 1.0;
uniform bool debug_normal = false;
uniform bool constant_normal = false;
uniform float constant_normal_z = 1.0;

void fragment() {
	// Preserve signed Z as well as XY: a coarse receiver may differ by more
	// than 90 degrees from an individual source texel. No source_color on data.
	vec3 n = texture(surface_normal, UV).xyz * 2.0 - vec3(1.0);
	if (constant_normal) { n = vec3(0.4, 0.3, sqrt(0.75) * constant_normal_z); }
	n.y *= normal_y;
	NORMAL = normalize(TANGENT * n.x + BINORMAL * n.y + NORMAL * n.z);
	ALBEDO = texture(reflectance, UV).rgb;
	EMISSION = texture(radiance, UV).rgb * baked_strength;
	ROUGHNESS = 1.0;
	if (debug_normal) {
		vec3 world_normal = normalize((INV_VIEW_MATRIX * vec4(NORMAL, 0.0)).xyz);
		vec3 blender_normal = vec3(world_normal.x, -world_normal.z, world_normal.y);
		ALBEDO = vec3(0.0);
		EMISSION = blender_normal * 0.5 + vec3(0.5);
	}
}
