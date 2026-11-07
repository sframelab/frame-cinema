shader_type spatial;
render_mode unshaded;

// Near-black screen housing, unshaded like the rest of the cabin. The movie bleeds onto it from
// Cinema's cached field; a cool earthlight gradient keeps the dark faces readable; chamfer faces
// (COLOR.r) pick up a grazing rim, COLOR.g carries the precomputed warm spill around the amber
// slits and COLOR.b marks the lit picture-side lip. Model space is housing space (room axes).
uniform float strength = 1.0;
uniform float strength_e = 1.0;
// Cinema's cached ambient field (colour only, metres about the screen centre).
uniform sampler2D field : hint_default_black, filter_linear, repeat_disable;
uniform vec2 field_size = vec2(8.57, 6.73);
uniform vec2 picture_half = vec2(2.1, 1.18125);
uniform float field_gain = 0.0;
// The picture-side lip (COLOR.b) also catches a little of the picture's own light, so it
// reads as a thin line even when it faces the viewer.
const float CHAMFER_BOUNCE = 0.35;
// Warm spill on the post face around each slit (was .35: the 1 cm ring read 174/127/77).
const float SLIT_SPILL = 0.22;

varying vec3 room_normal;
varying vec2 housing_xy;

void vertex() {
	room_normal = NORMAL;
	housing_xy = VERTEX.xy;
}

void fragment() {
	vec3 n = normalize(room_normal);
	// Final look pass: a neutral graphite gradient (the blue-heavy weights read navy, B/R about 5,
	// where the design has a neutral black housing base).
	vec3 grad = mix(vec3(0.35, 0.38, 0.42), vec3(0.9, 1.0, 1.15), n.y * 0.5 + 0.5)
		+ max(dot(n, normalize(vec3(-0.6, 0.05, -0.8))), 0.0) * vec3(0.5, 0.6, 0.8);
	grad = mix(grad, min(grad, vec3(1.0)), step(0.5, n.z));
	float facing = abs(dot(NORMAL, VIEW));
	vec3 color = (vec3(0.0050, 0.0054, 0.0062) * grad
		+ vec3(0.035, 0.055, 0.09) * (COLOR.r * pow(1.0 - facing, 2.0) + COLOR.b * CHAMFER_BOUNCE)
		+ vec3(1.0, 0.5, 0.16) * SLIT_SPILL * COLOR.g * strength_e) * strength;
	if (field_gain > 0.0) {
		// The picture bleeds onto its frame: strongest beside it, fading outward, its colour from
		// the field at this point. Faces turned toward the viewer take it, the lit lip most.
		vec2 outside = max(abs(housing_xy) - picture_half, vec2(0.0));
		mediump float bleed = 0.45 * exp(-length(outside) * 6.0) * max(n.z, 0.0) + COLOR.b * 0.4;
		color += textureLod(field, vec2(housing_xy.x, -housing_xy.y) / field_size + 0.5, 0.0).rgb * bleed * field_gain;
	}
	ALBEDO = color;
}
