shader_type spatial;
// Observation Deck deep-sky objects: clusters, nebulae, the Magellanic Clouds, each at its real place (prepare_objects.py).
// One mesh of two kinds of triangle. A star is one small triangle around a direction, with the same kernel family as
// stars.gdshader. A sprite is a quad on the tangent plane at the object, reading a baked picture from the atlas: light in RGB
// and, in alpha, how much of what lies behind it the object's dust hides. Clip w comes from a direction, so everything sits at
// true infinity, and frames cover it through the depth test. A quad costs fragments only where its object is on screen. No TIME.
render_mode unshaded, blend_premul_alpha, depth_draw_never, cull_disabled, shadows_disabled, ambient_light_disabled, fog_disabled, skip_vertex_transform;

uniform sampler2D atlas : hint_default_black, filter_linear_mipmap, repeat_disable;
uniform float object_gain = 1.0;
// Focus, as in stars.gdshader and space.gdshader: an object's light follows the Earth's slow ramp as the band does, its stars follow the square root, and its dust hides what it always hid.
global uniform float earth_gain;
// 1 keeps the emission nebulae's real colour, 0 turns their rose to the band's blue-white. At 1 it was the one hue in the sky you could name at a glance, so it stays at half.
uniform float rose = 0.5;
// Same defaults as space.gdshader and stars.gdshader: the Earth hides what is behind its disc.
uniform vec3 planet_direction = vec3(-0.3954, -0.8290, -0.3954);
uniform float planet_distance = 1.031;
// FWHM .138 deg, stars.gdshader's own. .00327 reads a little crisper and took tracked peak and flux to 1.3-1.6x 0.5.13's (stability_half.json), so it stays here.
uniform float star_half = 0.00385;

// Atlas codes hold sqrt(light / ATLAS_TOP), so a faint fade keeps many codes per 10-bit step of the buffer.
const float ATLAS_TOP = 0.5;
const float AMP_MIN = 0.001;
const float AMP_LOG_RANGE = 6.3969;
const float STAR_CAP = 0.6;
const float TIGHT_BELOW = 0.012;
const float TIGHT = 0.6;
const float CORE_K = 4.99;
const float SKIRT_FROM = 0.25;
const float SKIRT_GAIN = 0.05;
const float SKIRT_WIDTH = 3.0;
const float LIMB_FADE_DEG = 3.0;
const vec3 LIMB_RED = vec3(1.0, 0.42, 0.20);
const float STAR_DEPTH = 1e-6;

varying vec2 quad;
varying vec3 star;
varying float skirt;
varying float extent;
varying float sprite;

void vertex() {
	vec3 dir = VERTEX;
	float limb = degrees(asin(1.0 / planet_distance));
	float above = degrees(acos(clamp(dot(normalize(dir), normalize(planet_direction)), -1.0, 1.0))) - limb;
	float air = smoothstep(0.0, LIMB_FADE_DEG, above);
	vec3 corner_dir = dir;
	if (CUSTOM0.a > 0.001) {
		sprite = 0.0;
		int corner = VERTEX_ID % 3;
		quad = corner == 2 ? vec2(0.0, 2.0) : vec2(corner == 0 ? -1.7320508 : 1.7320508, -1.0);
		float amp = AMP_MIN * exp(CUSTOM0.a * AMP_LOG_RANGE) * object_gain;
		skirt = SKIRT_GAIN * smoothstep(SKIRT_FROM, STAR_CAP, amp);
		extent = skirt > 0.0 ? SKIRT_WIDTH : 1.0;
		amp *= air * air;
		star = CUSTOM0.rgb * mix(LIMB_RED, vec3(1.0), air) * min(amp, STAR_CAP / (1.0 + skirt)) * sqrt(earth_gain);
		vec3 side = normalize(cross(dir, abs(dir.y) < 0.9 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0)));
		float tight = amp < TIGHT_BELOW ? TIGHT : 1.0;
		corner_dir = dir + (side * quad.x + cross(dir, side) * quad.y) * star_half * extent * tight;
		quad *= tight;
	} else {
		quad = UV;
		star = vec3(0.0);
		skirt = 0.0;
		extent = 1.0;
		sprite = air * air * object_gain * CUSTOM0.r * 2.0;
	}
	vec4 clip = PROJECTION_MATRIX * vec4(mat3(MODELVIEW_MATRIX) * corner_dir, 0.0);
	POSITION = above > 0.0 ? vec4(clip.xy, clip.w * STAR_DEPTH, clip.w) : vec4(2.0, 2.0, 2.0, 1.0);
}

void fragment() {
	if (sprite > 0.0) {
		vec4 t = texture(atlas, quad);
		vec3 light = t.rgb * t.rgb * ATLAS_TOP * sprite * earth_gain;
		// Rose is red over green: without it, the excess of red goes to blue-white at the same luminance.
		float excess = max(light.r - light.g, 0.0) * (1.0 - rose);
		ALBEDO = light + excess * vec3(-0.75, 0.15, 0.45);
		ALPHA = min(t.a * sprite, 1.0);
	} else {
		float r2 = dot(quad, quad);
		float window = max(1.0 - r2, 0.0);
		float scaled = r2 * extent * extent;
		ALBEDO = star * (exp(-CORE_K * scaled) * min(window * extent, 1.0) + skirt * exp(-CORE_K * scaled / (SKIRT_WIDTH * SKIRT_WIDTH))) * window;
		ALPHA = 0.0;
	}
}
