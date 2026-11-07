// Observation Deck floor: baked lighting plus a parallax-corrected mirror lookup.
// Included by deck.gdshader and, with FIELD defined, by deck_field.gdshader (the
// variant used only while Cinema's ambient glow is on: it adds the movie field and light).
// Model space is room space (Godot metres: x right, y up, -z forward). Unshaded: the Mobile
// renderer writes ALBEDO straight out, ignores EMISSION and compiles out the light loop.
render_mode unshaded;

uniform sampler2D radiance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D reflectance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform float baked_strength = 1.0;
uniform float screen_z = -4.5;
// deck-mirror: equirect seen from the mirror eye (0, -0.69, 0), latitude -6..90,
// 2048 px of longitude plus 32 px of wrap on each side (build_runtime.py).
uniform sampler2D mirror : hint_default_black, filter_linear_mipmap, repeat_disable;
uniform sampler2D wear : hint_default_white, filter_linear_mipmap, repeat_enable;
uniform float mirror_strength = 1.6;
uniform float mirror_u_sign = 1.0;
// Satin metal: a metallic F0 for steep views blending to f90 at grazing (f90 < f0 keeps the
// far plates satin rather than mirror-bright).
uniform float mirror_f0 = 0.04;
uniform float mirror_f90 = 1.0;
// 5 is Schlick; lower values move the f0 -> f90 blend toward steeper views (art control:
// a looking-down view of the satin plate reads brighter than its grazing far plates).
uniform float mirror_fresnel_pow = 5.0;
// A faint cool satin sheen on the glossy tops (the canopy's earthshine), scuffed by the wear map.
uniform vec3 sheen = vec3(0.0);
// The sheen follows the baked albedo (per-plate tone, grain, seam AO) relative to this value.
uniform float sheen_albedo_ref = 0.035;
// Reflection strength across the wear map (scuffed .. polished).
uniform vec2 wear_range = vec2(0.55, 1.2);
uniform vec2 screen_center = vec2(0.0, 2.1);
uniform vec2 screen_half = vec2(2.1, 1.18125);
uniform vec2 housing_min = vec2(-2.8, 0.45);
uniform vec2 housing_max = vec2(2.8, 3.62);
// Final look pass: where the mirrored ray meets the picture itself the deck shows a dim cool gloss
// (linear, before mirror_strength) instead of the black housing; the field variant adds the movie.
uniform vec3 screen_sheen = vec3(0.012, 0.014, 0.020);
// Weight of the mirror on the grooved beds (.472) under the slats: a second, dimmer gloss tier.
uniform float bed_gloss = 0.4;
#ifdef FIELD
uniform sampler2D field : hint_default_black, filter_linear, repeat_disable;
uniform vec2 field_size = vec2(8.57, 6.73);
// The picture as Fit shows it, which can be shorter than the aperture.
uniform vec2 picture_half = vec2(2.1, 1.18125);
uniform float field_gain = 0.0;
uniform float screen_gain = 0.8;
// Whole-edge averages of the picture and their mean: what the field cannot hold inside the picture,
// and the pool's colour, with no per-fragment fetch.
uniform vec3 edge_top = vec3(0.0);
uniform vec3 edge_right = vec3(0.0);
uniform vec3 edge_bottom = vec3(0.0);
uniform vec3 edge_left = vec3(0.0);
uniform vec3 edge_mean = vec3(0.0);
// The movie light, as on the hull (hull.gdshader).
uniform bool movie_on = false;
uniform float spill_gain = 0.6;
uniform vec3 movie_source = vec3(0.0, 1.65, -3.25);
uniform vec3 movie_left = vec3(0.0);
uniform vec3 movie_right = vec3(0.0);
uniform float movie_side = 0.2;
// A satin plate answers a broad light well above its dark diffuse.
uniform float movie_satin = 0.03;
#endif

const vec3 BOX_LO = vec3(-3.45, 0.45, -4.50);
const vec3 BOX_HI = vec3(3.45, 4.50, 6.05);
const vec3 MIRROR_EYE = vec3(0.0, -0.69, 0.0);
const vec3 HOUSING_SPEC = vec3(0.004, 0.005, 0.007);
const float MAX_REFLECTION = 1.4;
// Past about 1.4 m from the seat (to_eye.y under .65) a slat's bevels and walls narrow toward a pixel and
// 2x coverage makes them crawl between the bright tops and beds. They take a little of the mirror there,
// up to FAR_GLOSS by about 2.7 m, so the grooves stay as dark lines with less step. Reflection only;
// the baked seams keep their value.
const float FAR_START = 0.65;
const float FAR_SLOPE = 1.2;
const float FAR_GLOSS = 0.3;
#ifdef FIELD
// The same faces in the movie's reflection: up to .6 of it by the same distance (FAR_GLOSS * FAR_SATIN).
// More flattens the far grooves under a bright film and calms almost nothing else.
const float FAR_SATIN = 2.0;
#endif

varying vec3 v_room;
varying vec3 v_n;
varying vec3 v_eye;

void vertex() {
	v_room = VERTEX;
	v_n = NORMAL;
	// Per eye: under multiview Godot shares one view matrix and passes each eye's
	// offset (view space) separately, so the eye is INV_VIEW_MATRIX * EYE_OFFSET.
	vec3 eye_world = (INV_VIEW_MATRIX * vec4(EYE_OFFSET, 1.0)).xyz;
	v_eye = transpose(mat3(MODEL_MATRIX)) * (eye_world - MODEL_MATRIX[3].xyz) - VERTEX;
}

void fragment() {
	vec3 plate = texture(reflectance, UV).rgb;
	vec3 base = texture(radiance, UV).rgb;
	vec3 to_eye = normalize(v_eye);
	vec3 n = normalize(v_n);
	// Only flat, level tops at plate/slat/rail/bar height mirror (.480/.484): beds,
	// grilles, curbs, bevels and walls do not, apart from far_gloss below.
	float level = smoothstep(0.92, 0.985, n.y) * (1.0 - smoothstep(0.04, 0.25, length(fwidth(v_n))));
	float gloss = smoothstep(0.476, 0.479, v_room.y) * (1.0 - smoothstep(0.487, 0.490, v_room.y)) * level;
	// The groove beds (exactly .472; vent grilles and seam fills at .470 stay matte) reflect at bed_gloss.
	float above_grille = smoothstep(0.4705, 0.4712, v_room.y);
	gloss += bed_gloss * above_grille * (1.0 - smoothstep(0.4728, 0.4735, v_room.y)) * level;
	float far_gloss = clamp((FAR_START - to_eye.y) * FAR_SLOPE, 0.0, FAR_GLOSS) * above_grille;
	gloss = max(gloss, far_gloss);
	// Reflection about the flat floor normal, then a proxy-box parallax hit.
	vec3 r = vec3(-to_eye.x, to_eye.y, -to_eye.z);
	vec3 rs = mix(vec3(1e-5), r, step(vec3(1e-5), abs(r)));
	vec3 bound = mix(BOX_LO, BOX_HI, step(vec3(0.0), rs));
	vec3 tv = (bound - v_room) / rs;
	float t = max(min(tv.x, min(tv.y, tv.z)), 0.0);
	vec3 q = normalize(v_room + t * r - MIRROR_EYE);
	vec2 uv = vec2((32.0 + fract(0.5 + mirror_u_sign * atan(q.x, -q.z) / TAU) * 2048.0) / 2112.0,
		(radians(90.0) - asin(clamp(q.y, -1.0, 1.0))) / radians(96.0));
	float w = texture(wear, v_room.xz * 0.6).r;
	float lod = clamp(log2(max(length(dFdx(q)), length(dFdy(q))) * 2048.0 / TAU + 1e-6) + log2(1.0 + 2.0 * w), 0.0, 6.0);
	vec3 spec = textureLod(mirror, uv, lod).rgb;
	// The screen housing is built at runtime, so the map has none: where the mirrored
	// ray meets the housing plane inside its outline, it sees near-black housing.
	float th = (screen_z + 0.03 - v_room.z) / rs.z;
	vec2 hit = v_room.xy + r.xy * th;
	vec2 inside = min(hit - housing_min, housing_max - hit);
	// A soft edge (about 0.2 m at the housing plane): the satin plate blurs the housing outline,
	// so the plates either side of it do not show a crisp light-dark column.
	float in_front = step(0.0, th) * step(th, t);
	float housing = smoothstep(-0.10, 0.10, min(inside.x, inside.y)) * in_front;
	vec2 in_picture = screen_half - abs(hit - screen_center);
	float picture = smoothstep(-0.04, 0.04, min(in_picture.x, in_picture.y)) * in_front;
	spec = mix(spec, mix(HOUSING_SPEC, screen_sheen, picture), housing);
	float f = mix(mirror_f0, mirror_f90, pow(1.0 - clamp(to_eye.y, 0.0, 1.0), mirror_fresnel_pow));
	float tone = clamp(dot(plate, vec3(0.2126, 0.7152, 0.0722)) / sheen_albedo_ref, 0.0, 2.0);
	// Reflections stay under the emitter cap (1.6 linear with the baked pool under them).
	vec3 refl = min((spec * mirror_strength + sheen * tone) * f * mix(wear_range.x, wear_range.y, w) * gloss, vec3(MAX_REFLECTION));
	vec3 color = (base + refl) * baked_strength;
#ifdef FIELD
	// The movie's cached ambient field, mirrored at the screen plane. The field holds colour only and
	// clamps at its edge; it is black inside the picture and sharp just outside, so the picture
	// and a satin blur past its edge take the edge averages.
	vec2 field_hit = hit - screen_center;
	vec3 c = textureLod(field, vec2(field_hit.x, -field_hit.y) / field_size + 0.5, 0.0).rgb;
	vec2 in_film = picture_half - abs(field_hit);
	vec2 across = clamp(field_hit / picture_half, -1.0, 1.0) * 0.5 + 0.5;
	c = mix(c, 0.5 * (mix(edge_left, edge_right, across.x) + mix(edge_bottom, edge_top, across.y)), smoothstep(-0.5, 0.0, min(in_film.x, in_film.y)));
	// The satin plate smears the picture toward the viewer: a broad falloff around the mirrored
	// rectangle (wider vertically, the view's own axis), so colour runs along the plates and fades.
	// Below the picture it pools in the picture's mean in front of the housing.
	vec2 outside = max(-in_film, vec2(0.0));
	c = mix(c, edge_mean, smoothstep(0.0, 0.3, -picture_half.y - field_hit.y));
	mediump float spread = outside.x * outside.x * 0.45 + outside.y * outside.y * (field_hit.y > 0.0 ? 0.16 : 0.45);
	// The groove walls and bevels keep half of it, by the filtered albedo (vents and seams stay dark), so
	// the slats' edges do not crawl against a lit plate.
	float satin = max(max(gloss, 0.5 * min(tone, 1.0)), far_gloss * FAR_SATIN);
	color += c * max(f, 0.12) * satin * screen_gain * field_gain * step(0.0, th) * exp(-spread);
	// Movie light on the plates: wrapped Lambert from the soft source; nothing behind the screen plane.
	if (movie_on) {
		mediump vec3 to_source = movie_source - v_room;
		mediump float d2 = dot(to_source, to_source);
		mediump float wrapped = clamp(dot(n, to_source) * inversesqrt(d2) * 0.74 + 0.26, 0.0, 1.0);
		mediump float reach = d2 * d2 * 0.000316;
		reach = max(1.0 - reach, 0.0);
		mediump float light = (wrapped / (0.8 + 0.25 * d2) + 0.018) * reach * reach
			* clamp((v_room.z - screen_z + 0.25) * 1.667, 0.0, 1.0) * spill_gain;
		color += (plate + movie_satin * satin) * mix(movie_left, movie_right, clamp(v_room.x * movie_side + 0.5, 0.0, 1.0)) * light;
	}
#endif
	ALBEDO = color;
}
