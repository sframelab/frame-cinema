shader_type spatial;
render_mode specular_disabled, ambient_light_disabled;
#include "desert_atmosphere.gdshaderinc"

uniform sampler2D radiance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D reflectance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D surface_normal : filter_linear_mipmap_anisotropic, repeat_disable;
uniform float baked_strength = 1.0;
// Rock albedo texels per lighting-bake texel (east-shoulder 2: a 2K bake on the
// same 4K cliff scan as the west wall it meets beside the seat).
uniform float detail_ratio = 1.0;
uniform vec3 radiance_tint = vec3(1.0);
uniform mat3 source_normal_basis;
uniform bool debug_normal = false;
uniform bool debug_albedo = false;

varying vec3 room_position;
void vertex() { room_position=VERTEX; }

void fragment() {
	vec3 n = texture(surface_normal, UV).rgb * 2.0 - vec3(1.0);
	NORMAL = normalize((VIEW_MATRIX * MODEL_MATRIX * vec4(source_normal_basis * n, 0.0)).xyz);
	ALBEDO = texture(reflectance, UV).rgb;
	vec3 baked=texture(radiance, UV).rgb;
	vec3 local_mean=textureLod(radiance, UV, 3.0).rgb;
	float detail=clamp(dot(baked,vec3(.2126,.7152,.0722))/max(.002,dot(local_mean,vec3(.2126,.7152,.0722))),.65,1.5);
	// A restrained local contrast restores scan fissures without lifting occlusion.
	baked *= pow(detail,.20)*vec3(1.08,1.025,.97);
	// 0.5.4 detail transfer: restore what a lower-resolution bake lost from the
	// full-resolution scan (sharp / bake-footprint-blurred albedo), so parts
	// with 2K/1K bakes match the 4K ones at their seams.
	// The soft sample sits at least log2(ratio) mips down: up close (magnified)
	// a footprint-scaled gradient still lands on mip 0 and restores nothing.
	if (detail_ratio > 1.01) {
		vec2 scan_size = vec2(textureSize(reflectance, 0));
		float lod = max(0.0, 0.5 * log2(max(dot(dFdx(UV) * scan_size, dFdx(UV) * scan_size), dot(dFdy(UV) * scan_size, dFdy(UV) * scan_size))));
		vec3 sharp = texture(reflectance, UV).rgb;
		vec3 soft = textureLod(reflectance, UV, lod + log2(detail_ratio)).rgb;
		baked *= clamp((sharp + 0.03) / (soft + 0.03), vec3(0.55), vec3(1.7));
	}
	EMISSION = desert_atmosphere(baked*radiance_tint,room_position) * baked_strength;
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
