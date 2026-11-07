shader_type spatial;
render_mode unshaded, fog_disabled;
uniform sampler2D radiance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform float baked_strength = 1.0;
// Earth only: a faint lift of the unlit hemisphere and a thin atmosphere rim,
// so the planet reads as a sphere against the black sky, not a floating arc.
uniform float night_fill = 0.0;
void fragment() {
    vec3 day = max(texture(radiance, UV).rgb, vec3(0.0)) * baked_strength;
    float facing = clamp(dot(normalize(NORMAL), normalize(VIEW)), 0.0, 1.0);
    vec3 night = vec3(0.020, 0.028, 0.045) * (0.35 + 0.65 * facing);
    vec3 rim = vec3(0.10, 0.17, 0.32) * pow(1.0 - facing, 3.0);
    ALBEDO = max(day, night * night_fill) + rim * night_fill;
}