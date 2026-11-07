shader_type spatial;
render_mode cull_disabled;
uniform float room_light = 0.55;
uniform vec3 deep_color : source_color = vec3(0.018, 0.043, 0.058);
uniform vec3 horizon_color : source_color = vec3(0.15, 0.21, 0.28);
uniform sampler2D ripple_map : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
void fragment() {
    vec2 p = UV * 240.0;
    vec3 first = texture(ripple_map, p + vec2(TIME * 0.003, 0.0)).rgb * 2.0 - 1.0;
    vec3 second = texture(ripple_map, p * 0.47 + vec2(0.0, TIME * 0.002)).rgb * 2.0 - 1.0;
    vec2 ripple = (first.xy + second.xy) * 0.21;
    NORMAL = normalize(TANGENT * ripple.x + BINORMAL * ripple.y + NORMAL);
    float fresnel = pow(1.0 - max(dot(NORMAL, VIEW), 0.0), 4.0);
    ALBEDO = deep_color;
    EMISSION = mix(deep_color * 0.20, horizon_color * 0.55, fresnel) * room_light / 0.55;
    METALLIC = 0.0;
    ROUGHNESS = 0.38;
    SPECULAR = 0.3;
}
