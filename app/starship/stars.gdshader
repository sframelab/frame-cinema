shader_type spatial;
// Observation Deck stars: small additive triangles fixed on the sky (prepare_stars.py), real positions. The clip position is the projection of a direction (w = 0),
// so each eye's view offset vanishes and a star sits at true infinity whatever the camera far is. The kernel is fixed in angle: a star's triangle is baked as
// directions, so its brightness and existence do not depend on where it sits in the view. Frames occlude stars through the depth test. No TIME.
// The limb test is baked too: stars behind the Earth's disc are not in the file. So this shader holds no planet constants.
render_mode unshaded, blend_add, depth_draw_never, cull_disabled, shadows_disabled, ambient_light_disabled, fog_disabled, skip_vertex_transform;

uniform float star_gain = 1.0;
// Focus: the stars follow the square root of the Earth's slow ramp, so the brilliant ones stay brilliant and the canopy still goes down. A global, as in the sky: writing it touches no material.
global uniform float earth_gain;

// Amplitude code of CUSTOM0.a (prepare_stars.py AMP_MIN, AMP_MAX): log scale, about 2.9% per code. ln(1.4 / .001) = 7.244.
const float AMP_MIN = 0.001;
const float AMP_LOG_RANGE = 7.2442;
// Stars from here up carry a faint wide skirt (prepare_stars.py SKIRT_FROM, SKIRT_R): their one triangle spans the skirt, and the core is HERO_CORE times tighter inside it.
const float SKIRT_FROM = 0.4;
const float SKIRT_GAIN = 0.03;
const float STAR_CAP = 1.4;
const float HERO_CORE = 3.39;
// A star's triangle stops where its kernel rounds to nothing (prepare_stars.py TRIM), so quad runs to the star's own trim.
const vec4 TRIM = vec4(0.27, 0.873, 0.485, 0.339);
// Depth of a star in clip space, as a fraction of w (reversed Z, 0 at the far plane): behind all room geometry and never exactly the cleared depth.
const float STAR_DEPTH = 1e-6;
// Eye-dependent depth by tier, radians per eye, 0 by default. Positive sits past parallel, behind the Earth's zero disparity: the left eye's image moves left, the right eye's right.
// Total disparity is twice this. It must never be negative, or a star floats in front of the Earth. 1 arcmin = 2.909e-4.
const float DEPTH_HERO = 0.0;
const float DEPTH_MID = 0.0;
const float DEPTH_DUST = 0.0;
// Amplitude codes of the tier edges: ln(.0065 / .001) / 7.244 and ln(.1 / .001) / 7.244.
const float DUST_TOP_CODE = 0.2584;
const float HERO_FROM_CODE = 0.6357;

varying vec2 quad;
varying vec3 star;
varying float glare;

void vertex() {
	vec3 corner_dir = VERTEX;
	float code = CUSTOM0.a;
	float amp = AMP_MIN * exp(code * AMP_LOG_RANGE);
	int corner = VERTEX_ID % 3;
	quad = corner == 2 ? vec2(0.0, 2.0) : vec2(corner == 0 ? -1.7320508 : 1.7320508, -1.0);
	glare = 0.0;
	if (amp >= SKIRT_FROM) {
		glare = SKIRT_GAIN * smoothstep(SKIRT_FROM, STAR_CAP, amp) + 1e-5;
	} else {
		quad *= min(TRIM.x + TRIM.y * code, TRIM.z + TRIM.w * code);
	}
	star = CUSTOM0.rgb * amp * star_gain * sqrt(earth_gain);
	vec4 clip = PROJECTION_MATRIX * vec4(mat3(MODELVIEW_MATRIX) * corner_dir, 0.0);
	float depth = code < DUST_TOP_CODE ? DEPTH_DUST : (code < HERO_FROM_CODE ? DEPTH_MID : DEPTH_HERO);
	clip.x += PROJECTION_MATRIX[0][0] * depth * (VIEW_INDEX == VIEW_MONO_LEFT ? -1.0 : 1.0);
	POSITION = vec4(clip.xy, clip.w * STAR_DEPTH, clip.w);
}

void fragment() {
	float r2 = dot(quad, quad);
	float w = max(1.0 - r2, 0.0);
	float w2 = w * w;
	// (1 - r^2)^7: the same half maximum as the old exp(-4.99 r^2) (1 - r^2)^2 within 2%, compact, and no exp per fragment.
	float k = w2 * w2 * w2 * w;
	if (glare > 0.0) {
		float c = max(1.0 - r2 * HERO_CORE * HERO_CORE, 0.0);
		float c2 = c * c;
		k = c2 * c2 * c2 * c + glare * k;
	}
	ALBEDO = star * k;
}
