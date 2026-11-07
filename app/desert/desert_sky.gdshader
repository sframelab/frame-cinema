shader_type sky;
// Longitude stays in [0,1]. Clamp latitude at every mip so the zenith cannot
// wrap into the dark opposite pole through a coarse footprint.
uniform sampler2D panorama : filter_linear_mipmap, repeat_disable;
uniform float brightness = 1.0;
uniform mat3 world_to_room = mat3(1.0);
uniform vec3 north_pole;
uniform vec3 south_pole;

vec2 pano_uv(vec3 direction) {
	return vec2(atan(direction.x, -direction.z) / (2.0 * PI) + 0.5, acos(clamp(direction.y, -1.0, 1.0)) / PI);
}

void sky() {
	vec3 direction = normalize(world_to_room * EYEDIR);
	float radius = length(direction.xz);
	vec3 pole_color = direction.y > 0.0 ? north_pole : south_pole;
	// The inner 0.05 degrees never evaluate the singular atan derivative.
	// Join the unique pole radiance to the panorama over the final 0.5 degrees.
	if (radius < 0.0008726645) {
		COLOR = pole_color * brightness;
	} else {
	vec2 uv = pano_uv(direction);
	// atan's rear-meridian wrap is a UV discontinuity, not a huge texture
	// footprint. Unwrap its derivatives before choosing the mip level.
	vec2 dx = dFdx(uv);
	vec2 dy = dFdy(uv);
	dx.x -= round(dx.x);
	dy.x -= round(dy.x);
	float pole = 2.5 / float(textureSize(panorama, 0).y);
	uv.y = clamp(uv.y, pole, 1.0 - pole);
	vec3 sampled = textureGrad(panorama, uv, dx, dy).rgb;
	COLOR = mix(pole_color, sampled, smoothstep(0.0008726645, 0.0087265355, radius)) * brightness;
	}
}
