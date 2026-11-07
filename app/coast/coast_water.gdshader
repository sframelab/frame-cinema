shader_type spatial;
render_mode specular_disabled, ambient_light_disabled;

uniform sampler2D panorama : filter_linear_mipmap, repeat_enable;
uniform sampler2D waves : filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D shore : filter_linear_mipmap, repeat_disable;
uniform float brightness = 1.0;
uniform float animation_time = 0.0;
uniform mat3 world_to_room = mat3(1.0);
varying vec3 world_position;
varying vec2 local_position;
varying vec3 swell_normal;

// Metres, seconds, deep-water dispersion. Different directions/periods avoid
// a sliding tiled appearance; low steepness keeps the crests from folding.
vec3 swell(vec2 p, vec2 direction, float length_m, float amplitude, float phase, inout vec2 gradient) {
	float k = 2.0 * PI / length_m;
	float angle = k * dot(direction, p) - sqrt(9.81 * k) * animation_time + phase;
	gradient += direction * (amplitude * k * cos(angle));
	return vec3(direction.x * amplitude * 0.6 * cos(angle), amplitude * sin(angle), direction.y * amplitude * 0.6 * cos(angle));
}

vec2 pano_uv(vec3 direction) {
	return vec2(atan(direction.x, -direction.z) / (2.0 * PI) + 0.5, acos(clamp(direction.y, -1.0, 1.0)) / PI);
}

void vertex() {
	vec2 p = VERTEX.xz;
	vec2 gradient = vec2(0.0);
	vec3 displacement = swell(p, normalize(vec2(0.35, 1.0)), 24.0, 0.24, 0.4, gradient);
	displacement += swell(p, normalize(vec2(-0.15, 1.0)), 41.0, 0.11, 2.3, gradient);
	displacement += swell(p, normalize(vec2(0.65, 0.85)), 13.0, 0.07, 1.7, gradient);
	displacement += swell(p, normalize(vec2(-0.6, 0.8)), 9.5, 0.04, 4.5, gradient);
	float fade = 1.0 - smoothstep(155.0, 190.0, max(abs(p.x), abs(p.y)));
	vec2 shore_uv = (p + vec2(180.0, 220.0)) / 360.0;
	if (all(greaterThanEqual(shore_uv, vec2(0.0))) && all(lessThanEqual(shore_uv, vec2(1.0)))) {
		fade *= 1.0 - smoothstep(0.65, 0.98, textureLod(shore, shore_uv, 0.0).r);
	}
	VERTEX += displacement * fade;
	swell_normal = vec3(-gradient.x * fade, 1.0, -gradient.y * fade);
	world_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	local_position = p;
}

void fragment() {
	vec2 p = local_position;
	vec2 slope = texture(waves, p * 0.08 + animation_time * vec2(0.009, 0.015)).rg * 2.0 - 1.0;
	slope += (texture(waves, p.yx * 0.2 + animation_time * vec2(-0.018, 0.011)).gr * 2.0 - 1.0) * 0.3;
	vec3 to_eye = normalize(CAMERA_POSITION_WORLD - world_position);
	// Reduce unresolved grazing-angle ripple detail instead of reflecting the
	// underside of the panorama through facets that have no geometric occlusion.
	vec3 room_up = normalize((MODEL_MATRIX * vec4(0.0, 1.0, 0.0, 0.0)).xyz);
	float resolved = mix(0.3, 1.0, smoothstep(0.0, 0.35, dot(to_eye, room_up)));
	vec3 surface_normal = swell_normal + vec3(slope.x, 0.0, slope.y) * 0.13 * resolved;
	vec3 n = normalize((MODEL_MATRIX * vec4(surface_normal, 0.0)).xyz);
	vec3 reflected = reflect(-to_eye, n);
	float fresnel = 0.02 + 0.85 * pow(1.0 - max(dot(to_eye, n), 0.0), 5.0);
	vec3 sky_color = textureLod(panorama, pano_uv(world_to_room * reflected), 2.5).rgb;
	vec2 shore_uv = (p + vec2(180.0, 220.0)) / 360.0;
	float contact = 0.0;
	if (all(greaterThanEqual(shore_uv, vec2(0.0))) && all(lessThanEqual(shore_uv, vec2(1.0)))) {
		contact = texture(shore, shore_uv).r;
	}
	// Baked shoreline proximity supplies the dark contact missing from a
	// sky-only reflection. It is a bounded approximation, not cliff reflection.
	vec3 water_color = (sky_color * fresnel + vec3(0.004, 0.009, 0.012) * (1.0 - fresnel)) * (1.0 - 0.94 * contact);
	// Meet the visible sky before the 1800 m camera clip. The reflected sky
	// remains darker at grazing angles and otherwise exposes a straight seam.
	float haze = smoothstep(650.0, 1450.0, length(CAMERA_POSITION_WORLD - world_position));
	vec3 horizon_color = texture(panorama, pano_uv(world_to_room * -to_eye)).rgb;
	EMISSION = mix(water_color, horizon_color, haze) * brightness;
	ALBEDO = vec3(0.014, 0.036, 0.046) * (1.0 - haze);
	NORMAL = normalize((VIEW_MATRIX * vec4(n, 0.0)).xyz);
	ROUGHNESS = 0.14;
}
