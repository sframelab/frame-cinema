shader_type spatial;
// Observation Deck city lights: one mesh of small additive quads on the ground (prepare_cities.py), from real night light.
// A map smears a light along the limb; this keeps it round and fixed in angle wherever it is on the disc. The vertex stage
// runs the sky shader's geography backwards with the global earth_spin, so a light sits where the map holds it at any
// spin. The clip position is the projection of a direction (w = 0), at true infinity like the stars. Frames occlude
// through the depth test. A light past the limb, off the night side or under thick cloud is clipped whole. The only clock is the global earth_spin.
render_mode unshaded, blend_add, depth_draw_never, cull_disabled, shadows_disabled, ambient_light_disabled, fog_disabled, skip_vertex_transform;

global uniform vec2 earth_spin;
global uniform float earth_gain;
// The sky's own map, no new texture. x ground, y clouds as in space.gdshader.
uniform sampler2D clouds : hint_default_black, filter_linear_mipmap, repeat_enable;
// Same defaults as space.gdshader.
uniform vec3 planet_direction = vec3(-0.3954, -0.8290, -0.3954);
uniform float planet_distance = 1.031;
uniform vec3 sun = vec3(-0.6725, 0.3090, -0.6725);
uniform float limb_fall = 8.0;
uniform float city_gain = 1.0;
// Cloud that lets a light through, and cloud that stops it, in the map's thickness. What is left under thick cloud.
uniform float cloud_lets = 0.40;
uniform float cloud_stops = 0.90;
uniform float cloud_keeps = 0.05;
uniform float cloud_lod = 1.0;
// Radians. Half-width of the faintest and of the brightest bead's quad; the kernel's FWHM is half-width / 1.6.
uniform float half_faint = 0.0027;
uniform float half_bead = 0.0030;
// How far from the limb, in the sky's depth (1 at nadir, 0 at the limb), a light of the faintest and of the top amplitude has faded out.
uniform float limb_faint = 0.30;
uniform float limb_top = 0.07;

// Copied from space.gdshader: its geography and air.
const vec3 CAP_N0 = vec3(0.395415, 0.829032, 0.395415);
const vec3 CAP_EAST = vec3(0.707107, 0.000000, -0.707107);
const vec3 CAP_NORTH = vec3(-0.586214, 0.559201, -0.586214);
const mat3 GEO_BASIS = mat3(vec3(-0.263818, 0.540908, 0.798636), vec3(-0.898794, -0.438371, 0.000000), vec3(0.350099, -0.717809, 0.601815));
const float BELT_TOP = 0.984808;
const float BELT_SCALE = 0.917990;
const float RING_LO = 0.005642;
const float RING_HI = 0.014369;
// The cloud deck's shell in Earth radii, as in space.gdshader.
const float CLOUD_H = 0.003;
const float AIR_SOFT = 0.05;
const float AIR_TAU = 0.10;
const float LIMB_NEAREST = -0.0330;
// Amplitude code of CUSTOM0.a (prepare_cities.py AMP_MIN, AMP_MAX): log scale. ln(2 / .004) = 6.2146.
const float AMP_MIN = 0.004;
const float AMP_LOG_RANGE = 6.2146;
// Kernel: exp(-CORE_K * r^2) * (1 - r^2)^2 with r in quad half-widths has its half maximum at r = 1/3.2 (stars.gdshader).
const float CORE_K = 4.99;
// The room's 1.6 linear limit, on the core and skirt together and with the ground under them: past it the 10-bit buffer clips and the core loses its colour.
const float CITY_CAP = 1.5;
// Hub cores: a wider amber skirt under the hot point.
const float SKIRT_FROM = 0.7;
const float SKIRT_GAIN = 0.10;
const float SKIRT_WIDTH = 3.0;
const vec3 SKIRT_COLOR = vec3(1.0, 0.45, 0.13);
// Below half a step of the 10-bit buffer a light shows nothing, so it costs nothing either: it is clipped.
const float LEAST = 0.001;
// Depth of a light in clip space as a fraction of w (reversed Z): behind all room geometry, as the stars.
const float CITY_DEPTH = 1e-6;

varying vec2 quad;
varying vec3 core;
varying vec3 skirt;
varying float extent;

void vertex() {
	int corner = VERTEX_ID & 3;
	quad = vec2(corner == 1 || corner == 2 ? 1.0 : -1.0, corner >= 2 ? 1.0 : -1.0);
	core = vec3(0.0);
	skirt = vec3(0.0);
	extent = 1.0;
	POSITION = vec4(2.0, 2.0, 2.0, 1.0);
	// The belt's u and v back to geography at the first view's frame, past the ground's turn. GEO_BASIS is a rotation, so g * GEO_BASIS inverts it.
	float lon = TAU * (VERTEX.x - earth_spin.x - 0.5);
	float z = BELT_TOP - VERTEX.y / BELT_SCALE;
	float across = sqrt(max(1.0 - z * z, 0.0));
	vec3 t = vec3(across * cos(lon), across * sin(lon), z) * GEO_BASIS;
	// Geography is 3x the surface angle from n0, so t.z is cos(3a). Past 3 x the limb's angle (.740) the light is on the far side, and most of the mesh stops here.
	float limb_c0 = 1.0 / planet_distance;
	if (t.z > limb_c0 * (4.0 * limb_c0 * limb_c0 - 3.0)) {
		float bearing = length(t.xy);
		float a = atan(bearing, t.z) / 3.0;
		float c0 = cos(a);
		vec3 nrm = CAP_N0 * c0 + (CAP_EAST * t.x + CAP_NORTH * t.y) * sin(a) / max(bearing, 1e-6);
		vec3 dir = normalize(normalize(planet_direction) * planet_distance + nrm);
		// As the sky: depth is the half chord, dot(-ray, nrm).
		float depth = -dot(dir, nrm);
		float amp = AMP_MIN * exp(CUSTOM0.a * AMP_LOG_RANGE);
		float top = smoothstep(0.02, 1.2, amp);
		// A light's size belongs to the light. Read from what fades, a hub would change shape in one frame as it passed SKIRT_FROM.
		extent = amp > SKIRT_FROM ? SKIRT_WIDTH : 1.0;
		// A faint light goes first on its way to the limb, before foreshortening piles the lights up.
		float limb = smoothstep(0.02, limb_top + (limb_faint - limb_top) * (1.0 - sqrt(top)), depth);
		float ndl = dot(nrm, normalize(sun));
		float d2 = depth * depth;
		float inside_deg = d2 * (108.17 + d2 * (-215.83 + d2 * 338.51));
		float tw = exp(-inside_deg / 2.2) * (1.0 - smoothstep(5.0, 9.0, inside_deg)) * exp(limb_fall * (ndl - LIMB_NEAREST));
		float night = (1.0 - smoothstep(-0.20, -0.02, ndl)) * clamp(1.0 - 1.5 * tw, 0.0, 1.0);
		amp *= limb * night * city_gain;
		float dim = min(earth_gain, 1.0);
		if (amp * dim > LEAST) {
			// Clouds cross the lights: the deck where this ray meets its shell, as the sky draws it, and the sky's second sample ring.
			float shell = 1.0 + CLOUD_H;
			vec3 center = normalize(planet_direction) * planet_distance;
			vec3 nc = (dir * (dot(center, dir) - sqrt(shell * shell - 1.0 + depth * depth)) - center) / shell;
			float cc = dot(nc, CAP_N0);
			float s2c = 1.0 - cc * cc;
			vec3 gc = GEO_BASIS * vec3(vec2(dot(nc, CAP_EAST), dot(nc, CAP_NORTH)) * (3.0 - 4.0 * s2c), cc * (4.0 * cc * cc - 3.0));
			vec2 layers = textureLod(clouds, vec2(atan(gc.y, gc.x) / TAU + 0.5 + earth_spin.y, (BELT_TOP - gc.z) * BELT_SCALE), cloud_lod).rg;
			float thick = 1.0 - (1.0 - layers.r) * (1.0 - layers.g * smoothstep(RING_LO, RING_HI, s2c));
			amp *= mix(1.0, cloud_keeps, smoothstep(cloud_lets, cloud_stops, thick));
			float clear = exp(-AIR_TAU / (depth + AIR_SOFT));
			vec3 through = vec3(sqrt(clear), clear, clear * clear);
			// Before the room's dimmer, so a metro keeps its glow in Focus.
			float wide = smoothstep(SKIRT_FROM, 1.4, amp);
			float shown = min(amp * dim, CITY_CAP / (1.0 + SKIRT_GAIN * wide));
			core = CUSTOM0.rgb * through * shown;
			skirt = SKIRT_COLOR * through * shown * SKIRT_GAIN * wide;
			float half_width = mix(half_faint, half_bead, top) * extent;
			vec3 side = normalize(cross(dir, abs(dir.y) < 0.9 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0)));
			vec3 corner_dir = dir + (side * quad.x + cross(dir, side) * quad.y) * half_width;
			vec4 clip = PROJECTION_MATRIX * vec4(mat3(MODELVIEW_MATRIX) * corner_dir, 0.0);
			if (amp * dim > LEAST) {
				POSITION = vec4(clip.xy, clip.w * CITY_DEPTH, clip.w);
			}
		}
	}
}

void fragment() {
	float r2 = dot(quad, quad);
	float window = max(1.0 - r2, 0.0);
	float scaled = r2 * extent * extent;
	ALBEDO = (core * exp(-CORE_K * scaled) * min(window * extent, 1.0) + skirt * exp(-CORE_K * scaled / (SKIRT_WIDTH * SKIRT_WIDTH))) * window;
}
