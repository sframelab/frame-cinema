// Reuse the room's sky texture: no additional image allocation or render pass.
uniform sampler2D atmosphere_sky : filter_linear_mipmap, repeat_disable;
// build_scene.py afterglow at Blender (-80,160,42), aimed at (0,0,1),
// converted to this room's Godot coordinates (x,z,-y).
const vec3 DESERT_SUN_DIRECTION=vec3(-.43591,.22340,-.87182);
// Distant dust changes terrain radiance, so room dimming also dims the haze.
vec3 desert_atmosphere(vec3 radiance, vec3 position) {
    float distance=max(0.0,length(position.xz)-20.0);
    if (distance<=0.0) { return radiance; }
    float amount=1.0-exp(-distance*.0032);
    // The finite terrain fades completely into its actual panorama at the rim.
    amount=mix(amount,1.0,smoothstep(360.0,590.0,length(position.xz)));
    vec3 direction=normalize(position-vec3(0.0,1.65,0.0));
    vec2 uv=vec2(atan(direction.x,-direction.z)/(2.0*PI)+.5,acos(clamp(direction.y,-1.0,1.0))/PI);
    vec3 sky=textureLod(atmosphere_sky,uv,4.0).rgb;
    return mix(radiance,sky,amount);
}
