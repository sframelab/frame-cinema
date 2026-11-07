shader_type spatial;
// The room's diffuse lighting is baked. Godot Mobile otherwise derives
// specular occlusion from its deliberately zero ambient light and kills sky
// reflections outside the local probe (4.7.2 scene_forward_mobile.glsl).
render_mode specular_occlusion_disabled;

uniform sampler2DArray long_displacement : filter_linear_mipmap, repeat_enable;
// These fields are already variance-filtered and footprint-faded. Long
// anisotropic footprints at grazing angles waste bandwidth without retaining
// useful resolved waves; the mip energy becomes reflection roughness instead.
uniform sampler2DArray long_normal : filter_linear_mipmap, repeat_enable;
uniform sampler2DArray short_normal : filter_linear_mipmap, repeat_enable;
uniform sampler2DArray contact_foam : filter_linear_mipmap, repeat_disable;
uniform bool foam_enabled = false;
uniform sampler2D panorama : filter_linear_mipmap, repeat_disable;
uniform vec3 north_pole;
uniform vec3 south_pole;
uniform sampler2D shore : filter_linear_mipmap, repeat_disable;
uniform mat3 world_to_room = mat3(1.0);
uniform float frame_count = 256.0;
uniform float loop_duration = 32.0;
uniform float animation_time = 0.0;
uniform float brightness = 1.0;
uniform float height_scale = 1.0;
uniform float normal_strength = 1.0;
uniform float reflection_distortion = 1.0;
uniform int debug_view = 0;
uniform sampler2D planar_texture0 : filter_linear, repeat_disable;
uniform sampler2D planar_texture1 : filter_linear, repeat_disable;
uniform mat4 reflection_projection0;
uniform mat4 reflection_projection1;
uniform mat4 reflection_view0;
uniform mat4 reflection_view1;
uniform int preview_eye = -1;
uniform bool use_planar = false;
varying vec2 local_position;
varying vec2 displaced_position;
varying vec3 world_position;

vec2 pano_uv(vec3 direction) {
	return vec2(atan(direction.x, -direction.z) / (2.0 * PI) + 0.5, acos(clamp(direction.y, -1.0, 1.0)) / PI);
}

vec3 sky_color(vec3 direction, float lod) {
	float radius = length(direction.xz);
	vec3 pole_color = direction.y > 0.0 ? north_pole : south_pole;
	if (radius < 0.0008726645) { return pole_color; }
	vec2 uv = pano_uv(direction);
	float edge = max(2.5, 0.5 * exp2(lod)) / float(textureSize(panorama, 0).y);
	uv.y = clamp(uv.y, edge, 1.0 - edge);
	return mix(pole_color, textureLod(panorama, uv, lod).rgb,
		smoothstep(0.0008726645, 0.0087265355, radius));
}

vec4 sequence(sampler2DArray field, vec2 uv, float frame) {
	return mix(texture(field, vec3(uv, mod(floor(frame), frame_count))),
		texture(field, vec3(uv, mod(floor(frame) + 1.0, frame_count))), fract(frame));
}

float shoreline(vec2 uv, float frame) {
	return mix(texture(contact_foam, vec3(uv, mod(floor(frame), frame_count))).r,
		texture(contact_foam, vec3(uv, mod(floor(frame) + 1.0, frame_count))).r, fract(frame));
}

vec4 filtered_reflection(sampler2D field, vec2 uv, float variance, float horizon, float contact) {
	vec2 texel = 1.0 / vec2(textureSize(field, 0));
	// Bilinear filtering already covers a texel. Additional minimum blur
	// smeared the reflected cliff silhouette into a pale shoreline ribbon.
	vec2 blur = texel * clamp(0.15 + sqrt(variance) * 24.0 + horizon * 3.0, 0.15, 5.0) * (1.0 - contact * 0.85);
	// Filter premultiplied radiance and coverage together. Dividing before
	// filtering would leak bright RGB into zero-coverage shoreline samples.
	vec4 color = texture(field, clamp(uv, vec2(0.001), vec2(0.999))) * 0.40;
	color += texture(field, clamp(uv + vec2(blur.x, 0.0), vec2(0.001), vec2(0.999))) * 0.15;
	color += texture(field, clamp(uv - vec2(blur.x, 0.0), vec2(0.001), vec2(0.999))) * 0.15;
	color += texture(field, clamp(uv + vec2(0.0, blur.y), vec2(0.001), vec2(0.999))) * 0.15;
	color += texture(field, clamp(uv - vec2(0.0, blur.y), vec2(0.001), vec2(0.999))) * 0.15;
	return color;
}

void vertex() {
	local_position = VERTEX.xz;
	float frame = mod(animation_time, loop_duration) / loop_duration * frame_count;
	float fade = 1.0 - smoothstep(155.0, 190.0, max(abs(VERTEX.x), abs(VERTEX.z)));
	vec3 displacement = sequence(long_displacement, VERTEX.xz / 224.0, frame).xyz;
	VERTEX += displacement * fade * height_scale;
	displaced_position = VERTEX.xz;
	world_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	float frame = mod(animation_time, loop_duration) / loop_duration * frame_count;
	vec4 coarse = sequence(long_normal, local_position / 224.0, frame);
	vec4 fine = sequence(short_normal, local_position / 29.0, frame);
	float footprint = max(length(dFdx(local_position)), length(dFdy(local_position)));
	float fine_resolved = 1.0 - smoothstep(0.45, 2.5, footprint);
	float coarse_resolved = 1.0 - smoothstep(4.0, 20.0, footprint);
	// Normal filtering loses resolved slope energy; turn that into roughness.
	float variance = max(0.0, 2.0 - dot(coarse.xyz, coarse.xyz) - dot(fine.xyz, fine.xyz));
	vec2 slopes = (coarse.xz / max(coarse.y, 0.1) * coarse_resolved + fine.xz / max(fine.y, 0.1) * fine_resolved) * normal_strength;
	variance += dot(fine.xz, fine.xz) * (1.0 - fine_resolved * fine_resolved) + dot(coarse.xz, coarse.xz) * (1.0 - coarse_resolved * coarse_resolved);
	// A weak fine band breaks up metre-scale, waxy reflection patches. Reuse
	// the short-wave cache at lambda/4 with period/2 (deep-water similarity).
	// Its footprint gate transfers unresolved slope energy into roughness.
	// Cross this reused band by 35 degrees; rotate its slope back into the
	// room basis as well. Wavelength / 4 and period / 2 remain coherent.
	mat2 ripple_rotation = mat2(vec2(0.819152, 0.573576), vec2(-0.573576, 0.819152));
	vec4 ripple = sequence(short_normal, ripple_rotation * local_position / 7.25 + vec2(0.371, 0.123), frame * 2.0);
	ripple.xz = transpose(ripple_rotation) * ripple.xz;
	float ripple_resolved = 1.0 - smoothstep(0.1125, 0.625, footprint);
	float ripple_gain = 0.35 * normal_strength;
	slopes += ripple.xz / max(ripple.y, 0.1) * ripple_resolved * ripple_gain;
	variance += (max(0.0, 1.0 - dot(ripple.xyz, ripple.xyz)) + dot(ripple.xz, ripple.xz) * (1.0 - ripple_resolved * ripple_resolved)) * ripple_gain * ripple_gain;
	// A normal deflection doubles the reflected-ray angle. Map unresolved
	// slope variance to a panorama footprint instead of reflecting a fixed
	// planar sky with an arbitrary, very small UV distortion. The 0.0009
	// floor represents unresolved fine surface roughness in this sea state.
	float sky_lod = clamp(log2(max(1.0, float(textureSize(panorama, 0).y) * 2.0 * sqrt(variance + 0.0009) / PI)), 2.0, 8.0);
	float foam = 0.0;
	vec2 shore_uv = (displaced_position - vec2(-128.0, -180.0)) / 256.0;
	if (foam_enabled && all(greaterThanEqual(shore_uv, vec2(0.0))) && all(lessThanEqual(shore_uv, vec2(1.0)))) {
		foam = shoreline(shore_uv, frame);
	}
	vec2 contact_uv = (displaced_position + vec2(180.0, 220.0)) / 360.0;
	float contact = 0.0;
	if (all(greaterThanEqual(contact_uv, vec2(0.0))) && all(lessThanEqual(contact_uv, vec2(1.0)))) {
		contact = smoothstep(0.3, 0.85, texture(shore, contact_uv).r);
	}
	vec3 n = normalize((MODEL_MATRIX * vec4(normalize(vec3(slopes.x, 1.0, slopes.y)), 0.0)).xyz);
	NORMAL = normalize((VIEW_MATRIX * vec4(n, 0.0)).xyz);
	// VIEW is per eye in multiview; CAMERA_POSITION_WORLD is eye midpoint.
	vec3 eye = normalize((INV_VIEW_MATRIX * vec4(VIEW, 0.0)).xyz);
	// Continuous sea haze avoids a bright shelf where rough reflected sky
	// meets the viewed horizon. Keep the nearby headland contact clear. The
	// final 0.5% contribution reaches zero so distant sampling can stop.
	float horizon = min(1.0, (1.0 - exp(-max(0.0, length(CAMERA_POSITION_WORLD - world_position) - 85.0) / 220.0)) / 0.995);
	// The probe is local to the cliffs. Blend back to the actual sky outside it.
	float outside_probe = smoothstep(95.0, 155.0, length(local_position - vec2(-15.0, -45.0)));
	vec3 reflected_sky = vec3(0.0);
	if (!use_planar || debug_view == 3) {
		reflected_sky = sky_color(world_to_room * reflect(-eye, n), sky_lod) * brightness;
	}
	RADIANCE = vec4(reflected_sky * (1.0 - horizon), outside_probe);
	float f = 0.0204 + 0.9796 * pow(1.0 - clamp(dot(n, eye), 0.0, 1.0), 5.0);
	ALBEDO = vec3(0.004, 0.011, 0.014);
	EMISSION = vec3(0.006, 0.014, 0.018) * (1.0 - f) * brightness;
	if (horizon > 0.0) {
		EMISSION = mix(vec3(0.006, 0.014, 0.018) * (1.0 - f), sky_color(world_to_room * -eye, 2.0), horizon) * brightness;
	}
	METALLIC = 0.0;
	SPECULAR = 0.255;
	ROUGHNESS = clamp(sqrt(0.012 + variance * 0.4), 0.08, 0.5);
	if (use_planar) {
		bool right_eye = (preview_eye >= 0 ? preview_eye : int(VIEW_INDEX)) == 1;
		mat4 reflection_projection = right_eye ? reflection_projection1 : reflection_projection0;
		mat4 reflection_view = right_eye ? reflection_view1 : reflection_view0;
		// Project the world-space water point into a mirrored camera. Deflect
		// the lookup using the resolved wave slope, fading toward the horizon.
		vec4 reflected_clip = reflection_projection * reflection_view * vec4(world_position, 1.0);
		vec2 reflected_uv = vec2(reflected_clip.x, -reflected_clip.y) / reflected_clip.w * 0.5 + 0.5;
		vec3 plane_normal = normalize((MODEL_MATRIX * vec4(0.0, 1.0, 0.0, 0.0)).xyz);
		vec3 view_slope = (reflection_view * vec4(n - plane_normal, 0.0)).xyz;
		// Planar distortion cannot reconstruct occluded geometry. Keep the
		// actual cliff contact aligned instead of pulling sky underneath it.
		reflected_uv += view_slope.xy * vec2(0.075, -0.050) * (1.0 - horizon) * (1.0 - contact * 0.94) * reflection_distortion;
		// Current reflected rock geometry fits within 114.255 m of this
		// center. Leave a broad distortion margin, then skip empty captures.
		float rock_coverage = 1.0 - smoothstep(145.0, 205.0, length(local_position - vec2(-15.0, -45.0)));
		float border = rock_coverage * smoothstep(0.0, 0.05, min(min(reflected_uv.x, reflected_uv.y), min(1.0 - reflected_uv.x, 1.0 - reflected_uv.y)));
		// Resolved slope variance broadens the reflection too, not just PBR
		// ROUGHNESS (which the explicit planar path intentionally bypasses).
		if (horizon < 1.0 && debug_view != 3) {
			reflected_sky = sky_color(world_to_room * reflect(-eye, n), sky_lod) * brightness;
		}
		vec4 planar = vec4(0.0);
		if (border > 0.0 && horizon < 1.0) {
			planar = right_eye ? filtered_reflection(planar_texture1, reflected_uv, variance, horizon, contact) : filtered_reflection(planar_texture0, reflected_uv, variance, horizon, contact);
		}
		RADIANCE = vec4(0.0, 0.0, 0.0, 1.0);
		EMISSION += (reflected_sky * (1.0 - planar.a * border) + planar.rgb * border) * f * (1.0 - horizon);
	}
	// Foam density is advected and decays in the shore solve. Its brightness
	// comes from the dusk sky; no permanent distance-based white outline.
	if (foam > 0.0) {
		foam = pow(foam, 1.4) * 0.7;
		vec3 foam_color = north_pole * brightness * 0.6;
		EMISSION = mix(EMISSION, foam_color, clamp(foam * 0.8, 0.0, 0.8));
		RADIANCE.rgb *= 1.0 - foam * 0.8;
	}
	if (debug_view > 0) {
		RADIANCE = vec4(0.0, 0.0, 0.0, 1.0);
		ALBEDO = vec3(0.0);
		EMISSION = debug_view == 1 ? coarse.xyz * 0.5 + 0.5 : vec3(horizon, outside_probe, 0.0);
		if (debug_view == 3) { EMISSION = reflected_sky; }
		if (debug_view == 4) { EMISSION = n * 0.5 + 0.5; }
	}
}
