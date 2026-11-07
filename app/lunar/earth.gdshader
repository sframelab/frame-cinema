shader_type spatial;
render_mode unshaded, fog_disabled, blend_mix, depth_draw_never, cull_disabled, shadows_disabled;
// Earth seen from the Moon: NASA Blue Marble surface, cloud cover and Black
// Marble city lights (public domain), lit from the sun direction recovered
// from the original bake so the crescent keeps its orientation.
//
// 0.5.1: an analytic sphere on a camera-facing card instead of the baked mesh.
// Each pixel intersects the exact sphere, so the silhouette is a true circle
// with per-pixel coverage (no polygon edge, no MSAA dependence); texture
// lookups use seam-safe gradients; ocean glints widen with the pixel
// footprint instead of sparkling; a thin atmosphere glows past the limb.
uniform sampler2D surface : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D masks : filter_linear_mipmap_anisotropic, repeat_enable; // R cloud, G lights, B water
uniform vec3 center = vec3(0.0);   // object space
uniform float radius = 1.0;        // object space
uniform vec3 sun = vec3(0.399, 0.193, -0.896);
uniform float longitude = 0.0;
uniform float baked_strength = 1.0;
const float HALO = 0.07;           // atmosphere glow width, in radii
varying vec3 view_position;
varying vec3 view_center;
varying float view_radius;

void vertex() {
	view_center = (MODELVIEW_MATRIX * vec4(center, 1.0)).xyz;
	view_radius = radius * length(MODELVIEW_MATRIX[0].xyz);
	// QuadMesh corners are +-1: a square facing the eye, large enough for the
	// perspective silhouette and the atmosphere halo.
	view_position = view_center + vec3(VERTEX.xy * view_radius * (1.0 + HALO * 4.0), 0.0);
	POSITION = PROJECTION_MATRIX * vec4(view_position, 1.0);
}

vec3 sample_seamless(sampler2D tex, vec2 uv) {
	vec2 dx = dFdx(uv);
	vec2 dy = dFdy(uv);
	dx.x -= round(dx.x);
	dy.x -= round(dy.x);
	return textureGrad(tex, uv, dx, dy).rgb;
}

void fragment() {
	vec3 ray = normalize(view_position);
	float along = dot(view_center, ray);
	float miss = length(view_center - ray * along);
	// Signed distance to the silhouette in radii; one pixel of it is coverage.
	float edge = miss / view_radius - 1.0;
	float pixel = max(fwidth(edge), 1e-5);
	float coverage = 1.0 - smoothstep(-pixel, pixel, edge);

	mat3 model = mat3(MODEL_MATRIX);
	vec3 light = normalize(model * sun);
	vec3 color = vec3(0.0);
	// Surface (computed slightly past the edge so coverage blends real colour).
	float inside = min(miss, view_radius * 0.9999);
	float depth = sqrt(view_radius * view_radius - inside * inside);
	vec3 hit = ray * (along - depth);
	vec3 view_normal = normalize(hit - view_center);
	vec3 world_normal = normalize((INV_VIEW_MATRIX * vec4(view_normal, 0.0)).xyz);
	vec3 n = normalize(inverse(model) * world_normal);
	vec2 uv = vec2(fract(atan(n.x, -n.z) / TAU + 0.5 + longitude), acos(clamp(n.y, -1.0, 1.0)) / PI);
	vec3 ground = sample_seamless(surface, uv);
	vec3 mask = sample_seamless(masks, uv);
	float cloud = smoothstep(0.08, 0.85, mask.r);
	vec3 to_eye = normalize((INV_VIEW_MATRIX * vec4(-ray, 0.0)).xyz);
	float ndl = dot(world_normal, light);
	// A soft terminator: sunlight scattering a few degrees past the geometric edge.
	float day = smoothstep(-0.06, 0.22, ndl);
	vec3 albedo = mix(ground * 0.9, vec3(0.92, 0.94, 0.97), cloud);
	color = albedo * day * max(ndl + 0.08, 0.0) * 3.6;
	// Sun glint on open ocean, widened by the pixel's normal spread so it never sparkles.
	float spread = length(fwidth(world_normal));
	float power = 1.0 / (1.0 / 60.0 + spread * spread * 6.0);
	float glint = pow(max(dot(reflect(-light, world_normal), to_eye), 0.0), power) * (power / 60.0);
	color += vec3(1.0, 0.96, 0.88) * glint * mask.b * (1.0 - cloud) * day * 1.6;
	// City lights on the night side, dimmed under cloud.
	float night = 1.0 - smoothstep(-0.18, 0.04, ndl);
	color += vec3(1.0, 0.72, 0.38) * mask.g * night * (1.0 - cloud * 0.7) * 0.6;
	// Atmosphere: thin blue limb, strongest on the lit side.
	float facing = clamp(dot(world_normal, to_eye), 0.0, 1.0);
	float limb_light = 0.12 + 0.9 * smoothstep(-0.25, 0.45, ndl);
	color += vec3(0.28, 0.52, 1.0) * pow(1.0 - facing, 3.0) * limb_light * 0.9;
	color = mix(color, color * vec3(0.82, 0.9, 1.08), day * 0.25);

	// Halo past the limb, lit by the sun on that side of the planet.
	vec3 rim_world = normalize((INV_VIEW_MATRIX * vec4(normalize(ray * along - view_center), 0.0)).xyz);
	float rim_lit = 0.15 + 0.85 * smoothstep(-0.3, 0.5, dot(rim_world, light));
	float halo = exp(-max(edge, 0.0) / HALO) * (1.0 - coverage) * rim_lit;
	vec3 glow = vec3(0.30, 0.55, 1.0) * 0.55;

	float alpha = clamp(coverage + halo * 0.6, 0.0, 1.0);
	vec3 premultiplied = color * coverage + glow * halo * 0.6;
	ALBEDO = premultiplied / max(alpha, 1e-4) * baked_strength;
	ALPHA = alpha;
}
