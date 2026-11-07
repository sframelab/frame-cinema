shader_type spatial;
render_mode specular_disabled, ambient_light_disabled;

uniform sampler2D radiance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D reflectance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D surface_normal : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D parent_radiance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D parent_reflectance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D parent_normal : filter_linear_mipmap_anisotropic, repeat_disable;
uniform float extent = 8.0;
uniform float parent_extent = 32.0;
uniform float size = 8.0;
uniform float dynamic_response = 1.0;
uniform float parent_dynamic_response = 1.0;
uniform bool has_parent = true;
uniform float baked_strength = 1.0;
varying vec2 ground_xy;
varying mat3 local_normal_to_view;

vec3 decode_normal(vec2 encoded) {
    vec2 xy = encoded * 2.0 - vec2(1.0);
    return normalize(vec3(xy, sqrt(max(0.0, 1.0-dot(xy,xy)))));
}

void vertex() {
    ground_xy = vec2(VERTEX.x, -VERTEX.z);
    local_normal_to_view = MODELVIEW_NORMAL_MATRIX;
}

void fragment() {
    vec2 uv = ground_xy / extent + vec2(0.5);
    uv.y = 1.0 - uv.y;
    vec2 parent_uv = ground_xy / parent_extent + vec2(0.5);
    parent_uv.y = 1.0 - parent_uv.y;
    float distance = max(abs(ground_xy.x), abs(ground_xy.y));
    // At the shared edge both meshes sample exactly the same parent field.
    float blend = has_parent ? smoothstep(size*0.4, size*0.5, distance) : 0.0;
    vec3 light = mix(texture(radiance,uv).rgb, texture(parent_radiance,parent_uv).rgb, blend);
    vec3 color = mix(texture(reflectance,uv).rgb*dynamic_response,
                     texture(parent_reflectance,parent_uv).rgb*parent_dynamic_response, blend);
    vec3 n = decode_normal(texture(surface_normal,uv).xy);
    vec3 pn = decode_normal(texture(parent_normal,parent_uv).xy);
    n = normalize(mix(n,pn,blend));
    NORMAL = normalize(local_normal_to_view * vec3(n.x,n.z,-n.y));
    ALBEDO = color;
    EMISSION = max(light, vec3(0.0))*baked_strength;
    ROUGHNESS = 1.0;
}
