shader_type spatial;
render_mode unshaded, blend_add, depth_draw_never, cull_disabled, fog_disabled;
uniform sampler2D color_field : filter_linear, repeat_disable;
uniform vec2 field_size = vec2(9.0, 7.1625);
uniform vec2 screen_size = vec2(4.2, 2.3625);
uniform vec2 plane_size = vec2(7.6, 5.7625);
uniform float spread = 0.85;
uniform float brightness = 0.5;
uniform float diffusion = 0.0;
uniform sampler2D terrain_contact : filter_linear, repeat_disable;
uniform bool terrain_contact_enabled = false;
uniform vec3 screen_origin = vec3(0.0,2.1,-4.56);
uniform float recess = 0.0;
uniform vec2 ground_fade = vec2(-100.0, -99.0);
varying vec3 room_position;
void vertex() {
	float fraction = VERTEX.z;
	float margin = (plane_size.x-screen_size.x)*0.5;
	vec2 point = UV2*screen_size*0.5 + VERTEX.xy*margin*fraction;
	if (fraction == 0.0) point *= 0.99;
	VERTEX = vec3(point,-recess*fraction*fraction);
	UV = vec2(point.x,-point.y)/plane_size + vec2(0.5);
	room_position = VERTEX + screen_origin;
}
void fragment() {
	vec2 point = (UV - 0.5) * plane_size;
	vec2 half_size = screen_size * 0.5;
	vec2 outside = abs(point) - half_size;
	float distance = length(max(outside, vec2(0.0)));
	float edge_distance = max(outside.x, outside.y);
	float coverage = max(fwidth(edge_distance), 0.0001);
	float mask = smoothstep(-coverage, coverage, edge_distance);
    float falloff = exp(-2.0 * distance * distance / (spread * spread));
    falloff *= 1.0 - smoothstep(1.3, 1.6, distance / spread);
	vec3 color = textureLod(color_field, point / field_size + vec2(0.5), 0.0).rgb;
	// Use the sampled linear RGB field directly. Dark regions must stay dim;
	// only the user's brightness/mode and spatial falloff scale their light.
	// A restrained broad field supplies visible scattered color in an empty
	// room. No time-varying noise, screen-space history or camera-facing mesh.
	falloff = mix(falloff, exp(-1.35 * distance * distance / (spread * spread)) * (1.0 - smoothstep(1.2, 1.6, distance / spread)), diffusion);
	falloff *= smoothstep(ground_fade.x, ground_fade.y, room_position.y);
    if (terrain_contact_enabled) {
        // Offline static terrain height/coverage, in the shared seat space.
        // No scene-depth copy: mobile depth resolves were a measured GPU
        // regression. Missing maps fall back to ordinary geometry occlusion.
        vec2 sample_uv = (room_position.xz - vec2(-7.0,-6.3)) / vec2(14.0,2.1);
        vec2 contact = textureLod(terrain_contact, sample_uv, 0.0).rg;
        float height = contact.r / max(contact.g, 0.0001);
        float coverage = step(0.0,sample_uv.x)*step(sample_uv.x,1.0)*step(0.0,sample_uv.y)*step(sample_uv.y,1.0);
        falloff *= mix(1.0, smoothstep(0.01,0.15,room_position.y-height), clamp(contact.g,0.0,1.0)*coverage);
    }
    ALBEDO = color * brightness * 1.15;
	ALPHA = mask * falloff;
}
