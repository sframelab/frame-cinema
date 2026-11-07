shader_type sky;
uniform float room_light = 0.55;
uniform vec3 zenith : source_color = vec3(0.021, 0.045, 0.09);
uniform vec3 horizon : source_color = vec3(0.18, 0.25, 0.32);
uniform vec3 moon_direction = vec3(-0.42, 0.36, -0.83);
uniform bool daylight = false;
float hash(vec3 p) { return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }
void sky() {
    vec3 d = normalize(EYEDIR);
    float height = clamp(d.y, 0.0, 1.0);
    vec3 color = mix(horizon, zenith, pow(height, 0.38));
    float moon = dot(d, normalize(moon_direction));
    color += vec3(0.35, 0.46, 0.63) * pow(max(moon, 0.0), 70.0) * 0.15;
    color = mix(color, vec3(0.83, 0.89, 1.0), smoothstep(0.99992, 0.99996, moon));
    vec3 grid = d * 420.0;
    float seed = hash(floor(grid));
    float point = 1.0 - smoothstep(0.08, 0.27, length(fract(grid) - 0.5));
    float stars = step(0.993, seed) * point * smoothstep(0.04, 0.3, height);
    color += vec3(0.65, 0.73, 0.86) * stars * (daylight ? 0.0 : 0.65);
    float dither = (hash(vec3(SCREEN_UV * 16384.0, 0.17)) - 0.5) / 512.0;
    COLOR = max(color * room_light / 0.55 + vec3(dither), vec3(0.0));
}
