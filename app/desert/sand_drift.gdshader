shader_type spatial;
render_mode unshaded, cull_disabled, depth_draw_never, shadows_disabled;
uniform float animation_time=0.0;
uniform float brightness=1.0;
varying float opacity;
float floor_height(vec2 p) {
    float r=length(p);
    float near=.07*sin(p.x*.25-p.y*.12)+.10*sin(-p.y*.18-.6);
    float ripple=.003*sin((-p.y+.14*sin(p.x*.8))*32.0)*(1.0-exp(-max(0.0,r-1.0)/4.0));
    return near+ripple+(1.0-exp(-max(0.0,r-9.0)/24.0))*(1.6+1.7*sin(-p.y*.028+p.x*.015)+1.15*sin(p.x*.036+p.y*.011));
}
void vertex() {
    float seed=INSTANCE_CUSTOM.x;
    float lifetime=.42+fract(seed*17.31)*.46;
    float phase=fract(INSTANCE_CUSTOM.x+animation_time/lifetime);
    // Saltation is a train of shallow ballistic hops. The shared slow envelope
    // makes patches come alive together, with quiet intervals between gusts.
    float gust=smoothstep(.12,.82,.5+.36*sin(animation_time*.31)+.14*sin(animation_time*.79+1.4));
    float path=(phase-.5)*(.65+fract(seed*29.7)*.75);
    VERTEX.x += path*.93;
    VERTEX.z += path*.367;
    vec2 origin=vec2(INSTANCE_CUSTOM.y*8.0-4.0,INSTANCE_CUSTOM.z*8.0-12.0);
    float ground_delta=floor_height(origin+vec2(path*.93,path*.367))-floor_height(origin);
    VERTEX.y += ground_delta+.012+4.0*(.018+fract(seed*13.87)*.065)*phase*(1.0-phase);
    opacity=smoothstep(0.0,.12,phase)*(1.0-smoothstep(.82,1.0,phase))*gust;
}
void fragment() {
    vec2 p=UV*2.0-1.0;
    float shape=exp(-dot(p*vec2(1.0,2.0),p*vec2(1.0,2.0))*4.0);
    ALBEDO=vec3(.39,.30,.19)*brightness;
    ALPHA=shape*opacity*.20;
}
