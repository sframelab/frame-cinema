shader_type spatial;
render_mode specular_disabled;
uniform sampler2D surface_map : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform vec4 stone_color : source_color = vec4(0.53, 0.50, 0.45, 1.0);
uniform bool floor_tiles = false;
varying vec3 world_position;
varying vec3 world_normal;
varying vec2 surface_uv;
void vertex() {
    // Object metres keep seams/materials attached during a room recenter.
    world_position = VERTEX;
    world_normal = NORMAL;
    vec3 n = abs(NORMAL);
    surface_uv = (n.x > n.y && n.x > n.z ? VERTEX.yz : (n.y > n.z ? VERTEX.xz : VERTEX.xy)) / 2.5;
}
void fragment() {
    vec3 detail = texture(surface_map, surface_uv).rgb;
    ALBEDO = stone_color.rgb * (0.94 + detail * 0.16);
    if (floor_tiles) {
        vec2 cell = abs(fract(world_position.xz / 2.4) - 0.5);
        vec2 aa = max(fwidth(world_position.xz / 2.4), vec2(0.0002));
        float seam = max(smoothstep(0.497-aa.x, 0.498+aa.x, cell.x), smoothstep(0.497-aa.y, 0.498+aa.y, cell.y));
        ALBEDO *= 1.0 - 0.27 * seam;
    }
    ROUGHNESS = 0.84;
    SPECULAR = 0.25;
}
