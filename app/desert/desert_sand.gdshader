shader_type spatial;
render_mode specular_disabled, ambient_light_disabled;
#include "desert_atmosphere.gdshaderinc"
uniform sampler2D radiance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D reflectance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D surface_normal : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D near_radiance : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D grain_reflectance : filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D fine_grain : filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D contact_map : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D ripple_detail : filter_linear_mipmap_anisotropic, repeat_enable;
uniform bool near_surface = false;
uniform bool detail_enabled = false;
uniform bool mineral_grain = false;
uniform float baked_strength = 1.0;
uniform mat3 source_normal_basis;
varying vec3 room_position;
varying vec3 mesh_normal;
void vertex() { room_position=VERTEX; mesh_normal=NORMAL; }
void fragment() {
    vec3 n;
    if (near_surface || detail_enabled) { n=normalize(mesh_normal); }
    else { n=normalize(source_normal_basis*(texture(surface_normal,UV).rgb*2.0-vec3(1.0))); }
    ALBEDO=texture(reflectance,UV).rgb;
    vec2 nearby_uv=room_position.xz/24.0+vec2(.5);
    // The coarse far atlas has an unused central hole. A continuous handover
    // from the dense seated atlas avoids its mip footprint making a dark rim.
    float extent=max(abs(room_position.x),abs(room_position.z));
    float handover=near_surface ? 0.0 : smoothstep(12.0,28.0,extent);
    vec3 base;
    if (near_surface) { base=detail_enabled ? textureLod(radiance,UV,3.5).rgb : texture(radiance,UV).rgb; }
    else {
        float edge_lod=log2(max(1.0,(extent-12.0)*72.0));
        base=mix(textureLod(near_radiance,clamp(nearby_uv,vec2(.001),vec2(.999)),edge_lod).rgb,
                 texture(radiance,UV).rgb,handover);
    }
    if (detail_enabled && !near_surface) {
        // Far lighting retains the captured dusk color, while the new dune
        // slopes receive directional afterglow. Keep the 12–28 m handover.
        float front=clamp((-room_position.z-12.0)/24.0,0.0,1.0);
        front=front*front*(3.0-2.0*front);
        float side=1.0-smoothstep(500.0,600.0,abs(room_position.x));
        float dune_light=.36+2.85*max(0.0,dot(n,DESERT_SUN_DIRECTION));
        vec3 distant_sand=textureLod(near_radiance,vec2(.5,.20),6.0).rgb;
        base=mix(base,distant_sand*dune_light,front*side*handover);
    }
    // Keep the same stationary grain scale across the geometry boundary.
    // Ordinary mip filtering removes subpixel grains toward the horizon.
    float modulation=1.0;
    if (!near_surface) {
        vec3 grain=texture(grain_reflectance,nearby_uv).rgb;
        float micro=clamp(dot(grain,vec3(.2126,.7152,.0722))/.37,.75,1.25);
        modulation=mix(1.0,micro,.55*handover);
    }
    if (detail_enabled) {
        vec2 p=room_position.xz;
        vec3 contact=vec3(0.0);
        if (near_surface) {
            contact=texture(contact_map,clamp(nearby_uv,vec2(.001),vec2(.999))).rgb;
            contact *= 1.0-smoothstep(10.5,12.0,extent);
        }
        // Captured irregular ripple junctions replace procedural parallel rows.
        // Keep their physical 30 m field scale, independent of millimetre grains.
        vec2 ripple_uv=vec2(p.x*.94-p.y*.342,p.x*.342+p.y*.94)/30.0;
        vec4 ripple=texture(ripple_detail,ripple_uv);
        vec2 macro_normal=textureLod(ripple_detail,ripple_uv,8.0).rg;
        float exposed=.48+.52*smoothstep(2.2,8.0,length(p));
        vec2 slopes=(ripple.rg-macro_normal)*2.0*.64*(1.0-contact.r*.8)*exposed;
        // Overlapping 7.5 / 15 / 30 m fields avoid a fourfold size jump.
        // One world-space blend crosses both ground meshes; the fine field
        // no longer ends at the seated mesh edge. Never rescale UVs with head
        // distance: fixed coordinates keep each ripple stationary during a lean.
        float distance_from_seat=length(p);
        float fine_weight=1.0-smoothstep(6.0,28.0,distance_from_seat);
        float coarse_blend=smoothstep(18.0,70.0,distance_from_seat);
        float middle_weight=(1.0-fine_weight)*(1.0-coarse_blend);
        float coarse_weight=(1.0-fine_weight)*coarse_blend;
        float nearby=fine_weight*(1.0-contact.r*.75);
        slopes *= .12+.88*coarse_weight;
        // Explicit gradients remain defined across the zero-weight branches.
        // Distant pixels skip the extra octave reads once their weights vanish.
        vec2 ripple_dx=dFdx(ripple_uv),ripple_dy=dFdy(ripple_uv);
        if (fine_weight>0.0) {
            vec2 small_uv=ripple_uv*4.0+vec2(.317,.683);
            vec2 small_normal=textureGrad(ripple_detail,small_uv,ripple_dx*4.0,ripple_dy*4.0).rg;
            vec2 small_mean=textureLod(ripple_detail,small_uv,8.0).rg;
            slopes += (small_normal-small_mean)*2.0*.70*nearby;
        }
        if (middle_weight>0.0) {
            vec2 middle_uv=ripple_uv*2.0+vec2(.173,.419);
            vec2 middle_normal=textureGrad(ripple_detail,middle_uv,ripple_dx*2.0,ripple_dy*2.0).rg;
            vec2 middle_mean=textureLod(ripple_detail,middle_uv,8.0).rg;
            slopes += (middle_normal-middle_mean)*2.0*.70*middle_weight*(1.0-contact.r*.75);
        }
        vec3 detailed=normalize(n+vec3(slopes.x*.94+slopes.y*.342,0.0,-slopes.x*.342+slopes.y*.94));
        vec4 grain_sample=texture(fine_grain,p/2.14);
        float grain=(mineral_grain ? grain_sample.a : grain_sample.r)-.5;
        // Millimetre relief follows the projected pixel footprint, so it gains
        // diffuse shading close to the seat and filters out before it sparkles.
        float footprint=max(length(dFdx(p)),length(dFdy(p)));
        float grain_height=grain*.0022*(1.0-smoothstep(.002,.012,footprint));
        vec3 dpdx=dFdx(room_position),dpdy=dFdy(room_position);
        vec3 du=cross(dpdy,detailed),dv=cross(detailed,dpdx);
        float determinant=dot(dpdx,du);
        if (abs(determinant)>.00000001) {
            vec3 gradient=(du*dFdx(grain_height)+dv*dFdy(grain_height))/determinant;
            detailed=normalize(detailed-gradient);
        }
        vec3 light_direction=DESERT_SUN_DIRECTION;
        float diffuse_weight=.52+.05*nearby;
        float old_light=1.0-diffuse_weight+diffuse_weight*max(0.0,dot(n,light_direction));
        float new_light=1.0-diffuse_weight+diffuse_weight*max(0.0,dot(detailed,light_direction));
        modulation *= new_light/old_light;
        modulation *= 1.0+grain*(.24+.12*nearby);
        if (mineral_grain) {
            // Actual scanned mineral color, with broad lighting removed offline.
            // The same mip-filtered sample feeds both baked and screen lighting.
            vec3 mineral=mix(vec3(1.0),clamp(grain_sample.rgb*2.0,vec3(.5),vec3(1.7)),nearby*.60);
            base *= mineral;
            ALBEDO *= mineral;
        }
        modulation *= mix(1.0,clamp(ripple.a/.57,.82,1.18),(.28-.12*nearby)*(1.0-contact.r*.55));
        modulation *= 1.0-contact.g*.20;
        // Weathered mineral fines accumulate next to the parent rocks.
        base *= mix(vec3(1.0),vec3(.87,.81,.75),contact.b*.28);
        ALBEDO *= mix(vec3(1.0),vec3(.87,.81,.75),contact.b*.28);
        n=detailed;
    }
    NORMAL=normalize((VIEW_MATRIX*MODEL_MATRIX*vec4(n,0.0)).xyz);
    // Preserve the baked occlusion while giving quartz sand its warm reflectance.
    // Keep this in linear light, before the common exposure and tone mapper.
    vec3 sand_tint=vec3(1.28,1.08,.82);
    ALBEDO *= sand_tint;
    EMISSION=desert_atmosphere(base*modulation*sand_tint,room_position)*baked_strength;
    ROUGHNESS=1.0;
}
