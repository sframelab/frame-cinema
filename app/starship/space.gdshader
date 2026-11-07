shader_type sky;
// Observation Deck sky (0.5.12). Godot room space: x right, y up, -z forward; starship_room.gd inverts
// the room transform through world_to_room. No TIME: a TIME or material uniform would re-render the
// radiance map every frame, so the only things that move are the global uniforms earth_spin and
// earth_gain, which starship_room.gd writes.
// - Night-side Earth: an analytic sphere sampled from a wrapped latitude belt (prepare_earth.py
//   --belt; geography at 3x the true scale, for an orbital-photo look), turning under the
//   ship. Moonlit cloud decks over grey-navy land and deep navy ocean, and a low amber glow where
//   there are cities. The lights themselves are points on the ground, cities.gdshader, from NASA Black Marble at 500 m.
//   Air from the ray's angle to the ground: extinction reddens and fades what lies toward the limb,
//   and a little blue in-scatter lowers its contrast. A blue twilight band that fades out 5-9 deg
//   inside the limb, a razor limb and halo, all three tied to the hidden sun and falling away round
//   the limb, and a faint green airglow line above the limb that closes the circle on the night side.
//   One rigid sphere: the Earth uses the room ray as it is, so the limb is a true circle from every direction.
// - Milky Way: two maps from NASA's real one, in a fixed galactic basis, a true great circle. galaxy is the smooth glow of
//   unresolved stars, with the printed stars out. dust is what stands in front of it. Behind both is true black, and off the band a faint field of tiny stars.
// - Stars are not here: they are one additive mesh, stars.gdshader, fixed on the same basis.
uniform sampler2D surface : source_color, hint_default_black, filter_linear_mipmap, repeat_enable;
uniform sampler2D masks : hint_default_black, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D clouds : hint_default_black, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D detail : hint_default_black, filter_linear_mipmap_anisotropic, repeat_enable;
// x ground, y clouds: longitude offset in turns, wrapped to 0-1 by starship_room.gd. A global uniform, so
// moving it writes one shared buffer and leaves the sky material and its radiance map alone.
global uniform vec2 earth_spin;
uniform sampler2D galaxy : hint_default_black, filter_linear_mipmap, repeat_enable;
// R: dust optical depth, .2 per unit, zero at .5, clumps below that. G: the fine grain of faint stars, zero at .5. 8192x1024 BC5, rows |sin b| < .3 (prepare_dust.py).
uniform sampler2D dust : hint_default_black, filter_linear_mipmap, repeat_enable;
// 1 keeps the half-step panel noise over the whole sky, as in 0.5.13. 0 leaves it only on the Earth and in its glare. For the head test.
uniform float sky_panel_noise = 0.0;
uniform mat3 world_to_room = mat3(1.0);
// A global too, set by starship_room.gd's slow Focus ramp, for the same reason. The room's lamps do not reach the sky, but this ramp does: the Milky Way follows it as the
// Earth does, so a dark film scene keeps the canopy down, and the stars and objects follow its square root.
global uniform float earth_gain;
uniform vec3 planet_direction = vec3(-0.3954, -0.8290, -0.3954);
uniform float planet_distance = 1.031;
// At the planet's azimuth and 74 deg from planet_direction: 1.9 deg inside the disk edge, behind the front-left limb.
uniform vec3 sun = vec3(-0.6725, 0.3090, -0.6725);
uniform float earth_exposure = 1.25;
uniform float twilight_gain = 4.0;
// How fast the twilight band and the limb fall away from the hidden sun: exp(limb_fall * (dot(normal, sun) - LIMB_NEAREST)).
// Round the limb the dot drops .03 at 30 deg from the sun's bearing, .12 at 60, .23 at 90 and .47 opposite it. See LIMB_FLOOR.
uniform float limb_fall = 8.0;
// The strip is stored 8x up (prepare_galaxy SCALE), so its faint levels stay normal halves through the BC6H pack.
// .125 would undo that exactly; .1875 shows the band at 1.5x (prepare_galaxy SHOWN_GAIN), picked on 2026-11-03.
uniform float galaxy_exposure = 0.1875;
// Orientation (2026-11-04, real sky), the 2026-11-02 basis turned by -24 deg about the up view's axis, because the band ran parallel to the frame beside a mullion through three rows of panes,
// then slid -55 deg along the band about the galactic pole, because in a dark film scene the bright stretch by the galactic centre stood in the pane right of the film. A true great circle, leaning 24 deg in the up view, off the film's
// centre line and to its right. The galactic centre is overhead and the fainter stretch toward Cygnus is beside the film. stars.dat and objects.dat are baked on this basis: change it here, then rerun prepare_stars.py and prepare_objects.py.
uniform vec3 galaxy_x = vec3(0.13902, 0.98620, -0.08954);
uniform vec3 galaxy_pole = vec3(-0.89189, 0.08545, -0.44401);
uniform vec3 galaxy_z = vec3(0.43025, -0.14162, -0.89159);
// Moonlit night side: clouds, land and ocean (see NIGHT_* below).
uniform float night_gain = 1.0;
uniform float city_gain = 1.0;
// The lights themselves are points (cities.gdshader). The map keeps a metro's broad glow around them: a coarse mip of its city channel, at this share of the full light.
uniform float city_glow = 0.14;
uniform float city_glow_lod = 3.0;

const vec3 TINT_DUST = vec3(0.8, 1.0, 1.22);
const float GRAIN_DEPTH = 3.0;
const float DUST_DEPTH = 0.8;
const float GLOW_BLACK = 0.008798;
// Slow waves in the black point, half a wave about 7 deg, so the band's outline has no long straight run. Fixed on the galactic basis.
const float GLOW_WANDER = 1.6;
// The band's tone, after the dust: mids down, the top kept, less red. A pale wash becomes a deep blue with bright clouds in it. prepare_dust.py holds the same three, for shown_glow.npy.
const float TONE_TOP = 1.17;
const float TONE_KNEE = 0.017;
const vec3 BAND_TINT = vec3(0.6, 0.86, 1.08);
// The faint field: at most one tiny star in each cell of a cube grid on the galactic basis, FIELD_CELLS across half a face, at a place fixed by its cell, clumped by slow waves. No map and no triangle. Positions are invented, unlike the mesh's.
// Its top stays under the real-sky check's bg+8 row, so it fills only the rows the check leaves free. Kernel: FWHM .138 deg, so it holds still under head motion (a tighter one fired the under-sampled control).
const float FIELD_CELLS = 80.0;
const float FIELD_LOW = 0.0026;
const float FIELD_TOP = 0.0049;
// Square degrees from the star where the kernel has rounded to nothing, and the band's green above which the field stands aside.
const float FIELD_REACH = 0.016;
const float FIELD_BAND = 0.004;
const vec3 MOON = vec3(-0.3478, 0.7950, 0.4969); // normalize(-0.35, 0.80, 0.50)
const vec3 MOON_COLOR = vec3(0.022, 0.035, 0.075);
const float HALO_SOFT = 0.12;
// Final look pass: a saturated blue band (the grey-steel (0.24, 0.38, 0.74) went grey through AgX 1.2).
const vec3 TWILIGHT = vec3(0.13, 0.31, 0.92);
// Night side, before earth_exposure: moonlit cloud tops read blue-grey (luma 40-90 through
// AgX 1.2), land a dark grey-navy and open ocean a deep navy floor, as planned for the front and left views.
const vec3 NIGHT_OCEAN = vec3(0.0036, 0.0085, 0.0255);
// City glow: amber.
// CITY_PEAK is the linear radiance of a full-scale texel in red, at any room level (no bloom, gate 1.6).
const vec3 CITY_COLOR = vec3(1.0, 0.47, 0.14);
const float CITY_PEAK = 1.6;
// Written by prepare_earth.geo_basis_constants: the room tangent frame at n0 = -planet_direction, and that frame onto the
// geography of the first view (the sub-viewer point and the bearing of room north). As constants the Earth branch needs no normalize and cross.
const vec3 CAP_N0 = vec3(0.395415, 0.829032, 0.395415);
const vec3 CAP_EAST = vec3(0.707107, 0.000000, -0.707107);
const vec3 CAP_NORTH = vec3(-0.586214, 0.559201, -0.586214);
const mat3 GEO_BASIS = mat3(vec3(-0.263818, 0.540908, 0.798636), vec3(-0.898794, -0.438371, 0.000000), vec3(0.350099, -0.717809, 0.601815));
// v = (BELT_TOP - sin(lat)) * BELT_SCALE: rows linear in sin(lat), latitude -6 to 80.
const float BELT_TOP = 0.984808;
const float BELT_SCALE = 0.917990;
// The second cloud sample comes in over sin^2 of the surface angle from n0: 4.3-6.9 deg, off nadir and across every window.
const float RING_LO = 0.005642;
const float RING_HI = 0.014369;
// Air. Plane-parallel air mass 1 / (dot(-ray, nrm) + AIR_SOFT), and dot(-ray, nrm) is the chord half-length "depth" on a unit sphere.
// AIR_SOFT caps it at 20 at the limb, where the real curve bends over too. AIR_TAU is the green optical depth for one air mass; it is
// about twice the clear-air figure (.05-.1) because the geography is drawn at 3x the true scale, so a ray crosses 3x the ground.
// Red gets half of it and blue twice (sqrt and square of the one exp), so lights redden on their way to the limb. AIR_MOON: moonlit air seen at full in-scatter.
const float AIR_SOFT = 0.05;
const float AIR_TAU = 0.10;
const vec3 AIR_MOON = vec3(0.007, 0.016, 0.040);
// dot(normal, sun) on the limb at the sun's bearing (the sun is 74 deg from the centre, the limb's normal 14.09 from n0), its largest on the disk.
const float LIMB_NEAREST = -0.0330;
// What the razor line and halo keep on the night side, so the edge still reads against the sky.
const float LIMB_FLOOR = 0.035;
// A thin warm layer on the razor line, right at the sun's bearing: gone by about 60 deg round the limb.
const vec3 LIMB_WARM = vec3(1.0, 0.42, 0.16);
const float LIMB_WARM_FALL = 26.0;
// Airglow: the 95-100 km oxygen layer seen edge-on, drawn at 115 km (edge = h / 6371, 4.9 deg above the limb from this orbit), width about 10 km.
// A hard top and a long tail toward the ground, since rays below the layer still cross it. Radiance sits 2-4 buffer steps above black, so stars show through it.
const float AIRGLOW_HEIGHT = 0.0180;
const float AIRGLOW_WIDTH = 0.0016;
const vec3 AIRGLOW = vec3(0.0020, 0.0078, 0.0030);

// Deck height in Earth radii, 19 km: above the real tops, so it foreshortens less toward the limb. Only the clouds use it; the limb stays the unit sphere's.
const float CLOUD_H = 0.003;
const vec3 CLOUD_THIN = vec3(0.006, 0.014, 0.05);
const vec3 CLOUD_TOP = vec3(0.045, 0.072, 0.2);
const vec3 CLOUD_LOW = vec3(0.008, 0.018, 0.058);
const vec3 TWILIGHT_CLOUD = vec3(0.32, 0.38, 0.68);
// detail repeats 8 times round the belt and 4 times down it. Longitude runs across the limb in the forward panes, so its cells are long there and survive foreshortening.
const vec2 DETAIL_SCALE = vec2(8.0, 4.0);
// How hard detail bites into thin cloud. The belt has real detail of its own from its 1 km source; the old 8192x2048 map wanted .42.
const float CLOUD_BITE = 0.33;
// Belt uv change per unit of room length along a tangent t, at a point with cap terms s, c, s2 and geography g: the chain rule of the mapping in sky().
vec2 belt_step(vec3 t, vec2 s, float c, float s2, vec3 g) {
	vec2 ts = vec2(dot(t, CAP_EAST), dot(t, CAP_NORTH));
	float sd = dot(s, ts);
	vec3 dg = GEO_BASIS * vec3(ts * (3.0 - 4.0 * s2) - s * 8.0 * sd, -sd / c * (12.0 * c * c - 3.0));
	return vec2((g.x * dg.y - g.y * dg.x) / ((g.x * g.x + g.y * g.y) * TAU), -dg.z * BELT_SCALE);
}

void sky() {
	// Cabin lighting is baked and Environment ambient/reflections are disabled.
	// Any engine-requested radiance update can therefore skip the detailed sky.
	if (AT_CUBEMAP_PASS) {
		COLOR = vec3(0.0);
	} else {
	vec3 ray = normalize(world_to_room * EYEDIR);
	// Milky Way, in the fixed galactic basis: a smooth glow seen through dust. Its fetches come after the Earth's coverage, below.
	vec3 g = vec3(dot(galaxy_x, ray), dot(galaxy_pole, ray), dot(galaxy_z, ray));
	vec2 guv = vec2(atan(g.z, g.x) / TAU + 0.5, g.y / 1.2 + 0.5);
	vec2 gdx = dFdx(guv);
	vec2 gdy = dFdy(guv);
	gdx.x -= round(gdx.x);
	gdy.x -= round(gdy.x);

	vec3 P = normalize(planet_direction);
	vec3 center = P * planet_distance;
	vec3 light = normalize(sun);
	float along = dot(center, ray);
	float miss = length(center - along * ray);
	float edge = miss - 1.0;
	float pixel = max(fwidth(edge), 0.000025);
	float coverage = (1.0 - smoothstep(-pixel, pixel, edge)) * step(0.0, along);

	vec3 milky = vec3(0.0);
	if (coverage < 1.0 && abs(g.y) < 0.6) {
		milky = textureGrad(galaxy, guv, gdx, gdy).rgb * galaxy_exposure;
		float seen = milky.g;
		if (abs(g.y) < 0.3) {
			// Mip bias -.5 on the dust; its rows are twice the strip's in v. Dust is one optical depth: blue is stopped a little more than red, so lanes redden at their rims.
			vec2 foot = vec2(0.7071, 1.4142);
			vec2 fog = textureGrad(dust, vec2(guv.x, g.y / 0.6 + 0.5), gdx * foot, gdy * foot).rg;
			float lane = (2.5 - fog.r * 5.0) * DUST_DEPTH;
			seen *= exp(lane);
			milky *= exp((lane + (fog.g - 0.5) * GRAIN_DEPTH) * TINT_DUST);
		}
		// True black between the clouds: a soft black point after the dust and before the grain, hue kept, so the band's edge breaks into clumps and does not fade, lanes keep their inner shape, and the grain does not turn faint glow to static.
		float wander = sin(dot(g, vec3(17.0, 9.0, -13.0))) * sin(dot(g, vec3(-11.0, 19.0, 7.0))) + 0.5 * sin(dot(g, vec3(31.0, -23.0, 19.0)) + 0.7);
		milky *= seen / (seen + GLOW_BLACK * exp(GLOW_WANDER * wander));
		milky *= BAND_TINT * TONE_TOP * milky.g / (milky.g + TONE_KNEE);
	}
	vec3 field = vec3(0.0);
	if (coverage < 1.0 && milky.g < FIELD_BAND) {
		vec3 fq = abs(g);
		vec2 fc;
		float ff;
		if (fq.x >= fq.y && fq.x >= fq.z) { fc = g.yz / fq.x; ff = g.x > 0.0 ? 1.0 : 2.0; }
		else if (fq.y >= fq.z) { fc = g.xz / fq.y; ff = g.y > 0.0 ? 3.0 : 4.0; }
		else { fc = g.xy / fq.z; ff = g.z > 0.0 ? 5.0 : 6.0; }
		// x (1 + .3478 (1 - |x|)) is atan(x) / (pi / 4) to within .5%: near equal cells, with no atan on every sky pixel.
		vec2 fp = fc * (1.0 + 0.3478 * (1.0 - abs(fc))) * FIELD_CELLS;
		vec2 fid = floor(fp);
		vec3 fh = fract(vec3(fid.x, fid.y, fid.x + ff * 37.0) * vec3(0.1031, 0.1030, 0.0973));
		fh += dot(fh, fh.yxz + 33.33);
		fh = fract((fh.xxy + fh.yzz) * fh.zyx);
		vec2 fd = (fp - fid - 0.2 - 0.6 * fh.xy) / (FIELD_CELLS * 1.27324);
		float fr2 = dot(fd, fd) * 3282.8;
		// Most sky pixels stop here.
		if (fr2 < FIELD_REACH) {
			vec3 fi = fract(fh * vec3(47.1, 53.7, 61.3) + fh.yzx);
			float fclump = sin(dot(g, vec3(9.1, 4.3, -7.7))) * sin(dot(g, vec3(-3.9, 11.3, 5.1))) + 0.6 * sin(dot(g, vec3(23.0, -17.0, 19.0)) + 1.3) * sin(dot(g, vec3(-13.0, 21.0, 27.0)));
			float fon = step(fi.x, smoothstep(-1.1, 1.0, fclump));
			field = mix(vec3(0.86, 1.0, 1.04), vec3(0.74, 0.96, 1.3), fi.y) * fon * mix(FIELD_LOW, FIELD_TOP, fh.z * fh.z * fh.z) * exp(-fr2 * 145.6);
			field *= (1.0 - smoothstep(0.0, FIELD_BAND, milky.g)) * max(step(along, 0.0), smoothstep(0.0, 0.04, edge)) * sqrt(earth_gain);
		}
	}
	vec3 color = (milky * earth_gain + field) * (1.0 - coverage);

	vec3 earth = vec3(0.0);
	if (along > 0.0 && edge < 0.06) {
		// The surface path stops a little past the limb, so limb quads keep whole derivatives; the rest of the 6 deg above it skips the fetches.
		if (edge < 0.004) {
			float inside = min(miss, 0.999999);
			float depth = sqrt(max(1.0 - inside * inside, 0.0));
			// A point on the unit sphere less its centre, so already unit length.
			vec3 nrm = ray * (along - depth) - center;
			// Geography at 3x the surface angle: sin(3a)/sin(a) = 3 - 4 sin^2(a), cos(3a) = c (4 c^2 - 3), so no trig but the atan.
			vec2 s = vec2(dot(nrm, CAP_EAST), dot(nrm, CAP_NORTH));
			float c0 = dot(nrm, CAP_N0);
			float s2 = 1.0 - c0 * c0;
			vec3 g = GEO_BASIS * vec3(s * (3.0 - 4.0 * s2), c0 * (4.0 * c0 * c0 - 3.0));
			vec2 uv = vec2(atan(g.y, g.x) / TAU + 0.5, (BELT_TOP - g.z) * BELT_SCALE);
			vec2 dx = dFdx(uv);
			vec2 dy = dFdy(uv);
			dx.x -= round(dx.x);
			dy.x -= round(dy.x);
			vec3 ground = textureGrad(surface, uv + vec2(earth_spin.x, 0.0), dx, dy).rgb;
			vec2 mask = textureGrad(masks, uv + vec2(earth_spin.x, 0.0), dx, dy).rg;
			// Fetches: two more taps of the cloud map, and detail within 9 deg of the limb.
			float ndl = dot(nrm, light);
			float d2 = depth * depth;
			float inside_deg = d2 * (108.17 + d2 * (-215.83 + d2 * 338.51));
			float sunward = exp(limb_fall * (ndl - LIMB_NEAREST));
			// The band fades out between 5 and 9 deg inside the limb (the design target: about 100-190 luma to 6 deg,
			// 26-47 beyond 8 deg), so the moonlit disk below it stays dark. The fade is shared with the bake's Earth proxy.
			float tw = exp(-inside_deg / 2.2) * (1.0 - smoothstep(5.0, 9.0, inside_deg)) * sunward;
			// The deck is a shell above the ground, so a ray meets it nearer the viewer than the ground it covers.
			float shell = 1.0 + CLOUD_H;
			vec3 nc = (ray * (along - sqrt(max(shell * shell - inside * inside, 0.0))) - center) / shell;
			vec2 sc = vec2(dot(nc, CAP_EAST), dot(nc, CAP_NORTH));
			float cc = dot(nc, CAP_N0);
			float s2c = 1.0 - cc * cc;
			vec3 gc = GEO_BASIS * vec3(sc * (3.0 - 4.0 * s2c), cc * (4.0 * cc * cc - 3.0));
			vec2 uvc = vec2(atan(gc.y, gc.x) / TAU + 0.5, (BELT_TOP - gc.z) * BELT_SCALE);
			vec2 dxc = dFdx(uvc);
			vec2 dyc = dFdy(uvc);
			dxc.x -= round(dxc.x);
			dyc.x -= round(dyc.x);
			uvc.x += earth_spin.y;
			float ring = smoothstep(RING_LO, RING_HI, s2c);
			// Half a mip up, more near the limb: the hard edge below must start from a wider footprint or it crawls.
			float foot = 1.41 + 0.5 * exp(-inside_deg / 2.5);
			vec2 layers = textureGrad(clouds, uvc, dxc * foot, dyc * foot).rg;
			float thick = 1.0 - (1.0 - layers.r) * (1.0 - layers.g * ring);
			// A step toward the moon on the map, at least 2 px long on screen.
			vec2 key_step = belt_step(MOON - nc * dot(nc, MOON), sc, cc, s2c, gc);
			vec2 map_size = vec2(textureSize(clouds, 0));
			vec2 jx = dxc * map_size;
			vec2 jy = dyc * map_size;
			vec2 kt = key_step * map_size;
			float px = length(vec2(jy.y * kt.x - jy.x * kt.y, jx.x * kt.y - jx.y * kt.x)) / max(abs(jx.x * jy.y - jx.y * jy.x), 1e-6);
			key_step *= max(0.0006, 2.0 / max(px, 1.0));
			// The thickness around this point, 3 mips up: big decks get a low threshold and bright tops, lone flakes a high one and dim tops.
			vec2 far_tap = textureGrad(clouds, uvc + key_step * 3.0, dxc * 8.0, dyc * 8.0).rg;
			float broad = 1.0 - (1.0 - far_tap.r) * (1.0 - far_tap.g * ring);
			// Near the limb the map has no along-limb detail left: band-limited noise bites into the edges of real cloud.
			if (inside_deg < 9.0) {
				vec2 detail_dx = dxc * DETAIL_SCALE * 1.41;
				vec2 detail_dy = dyc * DETAIL_SCALE * 1.41;
				float bite = textureGrad(detail, uvc * DETAIL_SCALE, detail_dx, detail_dy).r - 0.5;
				thick = clamp(thick + 4.0 * CLOUD_BITE * bite * thick * (1.0 - thick) * smoothstep(0.15, 0.6, broad) * (1.0 - smoothstep(3.0, 9.0, inside_deg)), 0.0, 1.0);
			}
			float cloud_mid = mix(0.6, 0.45, smoothstep(0.2, 0.7, broad));
			float cloud = smoothstep(cloud_mid - 0.2, cloud_mid + 0.2, thick);
			// Relief: thickness read as height against the taps toward the moon, so slopes facing it brighten and the far sides go dark.
			vec2 near_tap = textureGrad(clouds, uvc + key_step, dxc * foot, dyc * foot).rg;
			float near_thick = 1.0 - (1.0 - near_tap.r) * (1.0 - near_tap.g * ring);
			float shade = clamp(1.0 + 2.5 * (thick - near_thick) + 0.7 * (thick - broad), 0.35, 1.7);
			float height = thick * (0.45 + 0.55 * broad);
						// Air along this ray: one exp, then its square root and square for red and blue.
			float clear = exp(-AIR_TAU / (depth + AIR_SOFT));
			vec3 through = vec3(sqrt(clear), clear, clear * clear);
			float scatter = 1.0 - clear;
			float day = smoothstep(-0.16, 0.22, ndl);
			float grey = dot(ground, vec3(0.2126, 0.7152, 0.0722));
			vec3 albedo = mix(mix(ground, vec3(grey), 0.4) * vec3(0.66, 0.78, 1.0), vec3(0.60, 0.68, 0.80), cloud);
			// The true day side is only a sliver near the sun-side limb.
			vec3 planet = albedo * day * max(ndl + 0.13, 0.0) * 1.55;
			// Moonlit night side: grey-navy land, deep navy ocean, blue-grey cloud tops (thicker = brighter).
			float moonlit = 0.4 + 0.6 * max(dot(nrm, MOON), 0.0);
			vec3 ground_n = mix((0.12 + mix(vec3(grey), ground, 0.35)) * MOON_COLOR * 1.25, NIGHT_OCEAN, mask.g);
			// A soft low deck from the broad tap, under the hard tops.
			float low_deck = smoothstep(0.1, 0.65, broad);
			ground_n = mix(ground_n, CLOUD_LOW, low_deck);
			vec3 cloud_n = mix(CLOUD_THIN, CLOUD_TOP, 0.08 + 0.92 * height * height) * shade;
						planet += mix(ground_n, cloud_n, cloud) * moonlit * night_gain * (1.0 - day);
			planet *= through;
			planet += AIR_MOON * scatter * moonlit * night_gain;
			// Twilight band inside the limb, strongest toward the hidden sun. inside_deg is a fit in depth^2 (within .07 deg over the band), which costs no acos.
			// Air fills the gaps only in the last degree or so; clouds keep their edges up to it and turn near-neutral in the band.
			float air_fill = mix(scatter * scatter * scatter, scatter, exp(-inside_deg / 0.5)) + 0.1 * low_deck;
			vec3 band_cloud = mix(TWILIGHT, TWILIGHT_CLOUD, smoothstep(0.3, 2.0, inside_deg)) * (0.4 + 0.6 * shade);
			planet += ((0.08 + 0.92 * air_fill) * (1.0 - cloud) * TWILIGHT + cloud * band_cloud) * tw * twilight_gain;
						// A metro's glow under its point lights: no city sits on the lit twilight band or the day sliver, and the air reddens and fades it toward the limb.
			float glow = textureLod(masks, uv + vec2(earth_spin.x, 0.0), city_glow_lod).r;
			float city = glow * glow * city_glow * CITY_PEAK / (earth_exposure * max(earth_gain, 1.0));
			planet += CITY_COLOR * through * city * city_gain * (1.0 - smoothstep(-0.20, -0.02, ndl))
				* (1.0 - 0.85 * cloud) * clamp(1.0 - 1.5 * tw, 0.0, 1.0);
			earth = planet * earth_exposure * coverage;
		}
		// Razor limb line and soft atmosphere, brightest toward the hidden sun and nearly gone away from it; faded out by edge .06.
		float above = max(edge, 0.0);
		float rim_ndl = dot(along * ray - center, light) / miss;
		float rim = LIMB_FLOOR + exp(limb_fall * (rim_ndl - LIMB_NEAREST));
		// Razor line and soft halo in saturated blue (they read grey-teal / mint over the dark sky), warm right at the sun's bearing.
		vec3 razor = mix(vec3(0.38, 0.66, 1.0), LIMB_WARM, exp(LIMB_WARM_FALL * (rim_ndl - LIMB_NEAREST) - above / 0.0006));
		// The halo goes blue a little off the line; its luma stays.
		vec3 halo = 0.9 * exp(-above / 0.0010) * mix(razor, vec3(0.10, 0.71, 1.75), 1.0 - exp(-above / 0.0006)) + HALO_SOFT * exp(-above / 0.008) * vec3(0.05, 0.28, 1.0);
				earth += halo * rim * (1.0 - smoothstep(0.04, 0.06, above)) * (1.0 - coverage);
		// Airglow: it stands alone on the night side and gives way to the blue on the sun's side.
		float glow_at = (above - AIRGLOW_HEIGHT) / AIRGLOW_WIDTH;
		earth += AIRGLOW * exp(-glow_at * glow_at * (glow_at > 0.0 ? 1.0 : 0.07)) * clamp(1.0 - 1.2 * rim, 0.0, 1.0) * (1.0 - coverage);
	}
	// Veiling glare from the bright limb over the nearby glass: a lobe around the hidden sun (the 8th power of the cosine, about 30 deg to half), not a ring.
	float glare = max(dot(ray, light), 0.0);
	glare *= glare;
	glare *= glare;
	earth += vec3(0.0003, 0.0008, 0.0022) * glare * glare * (1.0 - coverage);
	COLOR = color + earth * earth_gain;
	// On true black one 10-bit step (.002 linear) is a hard contour, in the limb's glare and at the Earth's edge. Noise spanning half a step, pixel-fine (interleaved
	// gradient noise, fixed on the panel, no TIME), softens it; black stays black, since it rounds to zero. On the Milky Way the dust map's fine grain, fixed on the sky, does the same job.
	// Known item for the head test: sky_panel_noise sets whether this panel-fixed noise also covers the rest of the sky.
	COLOR = max(COLOR + (fract(52.9829189 * fract(dot(FRAGCOORD.xy, vec2(0.06711056, 0.00583715)))) - 0.5) * 0.00098 * max(sky_panel_noise, max(ceil(coverage), smoothstep(0.0001, 0.0004, earth.b * earth_gain))), vec3(0.0));
	}
}
