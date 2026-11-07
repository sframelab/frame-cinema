shader_type spatial;
render_mode specular_disabled, ambient_light_disabled;
#include "desert_atmosphere.gdshaderinc"
uniform sampler2D radiance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D reflectance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform float baked_strength=1.0;
varying vec3 room_position;
varying vec3 room_normal;
void vertex() { room_position=VERTEX;room_normal=NORMAL; }
void fragment() {
    vec3 rock=texture(reflectance,UV).rgb;
    // Irradiance comes from the surrounding ground, not the stone's own baked
    // contact shadow directly underneath it. Preserve broader cliff shelter.
    vec3 ground=textureLod(radiance,room_position.xz/24.0+vec2(.5),6.0).rgb;
    // 0.5.4: keep the scan's colour and grain (per channel, around the boulder
    // scan's mean), so fragments read as stone rather than flat dark blobs.
    vec3 tone=clamp(rock/vec3(.17,.14,.12),vec3(.55),vec3(1.6));
    vec3 normal=normalize(room_normal);
    vec3 sun=DESERT_SUN_DIRECTION;
    // Restore face separation while keeping fragments close to their parent rock.
    float facing=.70+.62*max(0.0,dot(normal,sun));
    NORMAL=normalize((VIEW_MATRIX*MODEL_MATRIX*vec4(normal,0.0)).xyz);
    ALBEDO=rock;
    EMISSION=ground*vec3(.92,.84,.74)*tone*facing*baked_strength;
    ROUGHNESS=1.0;
}
