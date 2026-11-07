shader_type spatial;
render_mode unshaded;

// Baked ship surfaces. Static, occluded lighting lives in `radiance`; the movie's light is one
// analytic source below (Cinema's two screen OmniLights stay hidden in this room). Unshaded: the
// Mobile renderer writes ALBEDO straight out, ignores EMISSION and compiles out the light loop.
// Model space is room space: every part is a direct child of the ship at identity.
uniform sampler2D radiance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D reflectance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform float baked_strength = 1.0;
uniform float spill_gain = 0.5;
uniform float screen_z = -4.5;
uniform float rim_gain = 0.0;
// Set by starship_room.gd from Cinema's edge averages; off for black frames and Ambient Off.
uniform bool movie_on = false;
uniform vec3 movie_source = vec3(0.0, 1.65, -3.25);
uniform vec3 movie_left = vec3(0.0);
uniform vec3 movie_right = vec3(0.0);
uniform vec3 movie_top = vec3(0.0);
// 1 / metres over which the colour crosses from the left edge's to the right edge's.
uniform float movie_side = 0.2;

varying vec3 room_pos;
varying vec3 room_normal;

void vertex() {
	room_pos = VERTEX;
	room_normal = NORMAL;
}

void fragment() {
	vec3 color = texture(radiance, UV).rgb;
	// A faint cool glint on canopy members seen at a grazing angle (the glass edge).
	// Silhouette slivers (NdV under .08) never light. Only the canopy (y above 3.9) reaches it.
	if (rim_gain > 0.0 && room_pos.y > 3.9) {
		float ndv = clamp(dot(NORMAL, VIEW), 0.0, 1.0);
		float grazing = (1.0 - ndv) * (1.0 - ndv);
		float rim = grazing * grazing * smoothstep(0.08, 0.30, ndv)
			* step(0.4, abs(normalize(room_normal).y)) * smoothstep(3.9, 4.2, room_pos.y);
		color += vec3(0.010, 0.022, 0.050) * rim * rim_gain;
	}
	color *= baked_strength;
	if (movie_on) {
		// Wrapped Lambert from a soft source in front of the picture, a reach like Cinema's
		// lights and a small fill for the closed cabin's bounce, which also lights faces turned
		// away. Nothing behind the screen plane receives movie light. It follows neither the
		// room light nor Focus.
		mediump vec3 to_source = movie_source - room_pos;
		mediump float d2 = dot(to_source, to_source);
		mediump float wrapped = clamp(dot(room_normal, to_source) * inversesqrt(d2) * 0.74 + 0.26, 0.0, 1.0);
		mediump float reach = d2 * d2 * 0.000316;
		reach = max(1.0 - reach, 0.0);
		mediump float light = (wrapped / (0.8 + 0.25 * d2) + 0.018) * reach * reach
			* clamp((room_pos.z - screen_z + 0.25) * 1.667, 0.0, 1.0) * spill_gain;
		mediump vec3 side = mix(movie_left, movie_right, clamp(room_pos.x * movie_side + 0.5, 0.0, 1.0));
		color += texture(reflectance, UV).rgb * mix(side, movie_top, clamp(room_pos.y * 0.5 - 1.2, 0.0, 1.0)) * light;
	}
	ALBEDO = color;
}
