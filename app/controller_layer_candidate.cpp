// Absolute SBS quad controller experiment. Two shared-depth eye images;
// reads installed Valve geometry in place. Not enabled until device validation.
#include "openvr.h"
#include "scene_placement.h"
#include "controller_focus.h"
#include "controller_quad_projection.h"
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <GLES2/gl2ext.h>
#include <array>
#include <chrono>
#include <cstddef>
#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <thread>
#include <vector>
#include <unistd.h>
#include <csignal>
#include <sys/prctl.h>
#include <iomanip>
#include <algorithm>
using M=vr::HmdMatrix34_t;
static void require(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
static void glcheck(const char* stage){
    const GLenum error=glGetError();if(error!=GL_NO_ERROR){std::printf("{\"gl_stage\":\"%s\",\"gl_error\":%u}\n",stage,unsigned(error));throw std::runtime_error(stage);}
}
static GLuint shader(GLenum type,const char* source){
    GLuint id=glCreateShader(type);glShaderSource(id,1,&source,nullptr);glCompileShader(id);
    GLint ok=0;glGetShaderiv(id,GL_COMPILE_STATUS,&ok);require(ok,"shader_compile");return id;
}
static std::array<float,16> matrix(const M&m){
    std::array<float,16> r{};r[15]=1;for(int i=0;i<3;++i)for(int j=0;j<4;++j)r[j*4+i]=m.m[i][j];return r;
}
static volatile sig_atomic_t active=1;
static void stop(int){active=0;}
static double epoch(){return std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();}
static int64_t monotonic(){timespec t{};clock_gettime(CLOCK_MONOTONIC,&t);return int64_t(t.tv_sec)*1000000000+t.tv_nsec;}

// Synthetic, hidden-only material fixtures. World rotation of both head and
// hands preserves their eye-relative geometry while testing stage-fixed light.
struct HiddenProofPose {
    std::string name="default";
    M head=cinema_placement::identity();
    std::array<M,2> hands;
};
static M proof_axis_rotation(int axis,float degrees) {
    M r=cinema_placement::identity();
    const float radians=degrees*3.14159265358979323846f/180.f;
    const float c=std::cos(radians),s=std::sin(radians);
    const int a=(axis+1)%3,b=(axis+2)%3;
    r.m[a][a]=c;r.m[a][b]=-s;r.m[b][a]=s;r.m[b][b]=c;
    return r;
}
static HiddenProofPose hidden_proof_pose() {
    HiddenProofPose pose;
    if(const char* value=std::getenv("FRAME_CINEMA_CONTROLLER_PROOF_POSE"))pose.name=value;
    require(pose.name=="default"||pose.name=="yaw"||pose.name=="pitch"||
            pose.name=="roll"||pose.name=="head-yaw-left"||pose.name=="head-yaw-right",
            "unknown_hidden_proof_pose");
    const float head_yaw=pose.name=="head-yaw-left"?45.f:pose.name=="head-yaw-right"?-45.f:0.f;
    pose.head=proof_axis_rotation(1,head_yaw);
    double relative_error=0;
    for(int side=0;side<2;++side) {
        M local=cinema_placement::identity();
        if(pose.name=="yaw")local=proof_axis_rotation(1,side?-55.f:55.f);
        if(pose.name=="pitch")local=proof_axis_rotation(0,side?35.f:-50.f);
        if(pose.name=="roll")local=proof_axis_rotation(2,side?60.f:-60.f);
        local.m[0][3]=side?.22f:-.22f;local.m[1][3]=-.25f;local.m[2][3]=-.55f;
        pose.hands[side]=cinema_placement::multiply(pose.head,local);
        require(cinema_placement::rigid(pose.hands[side]),"hidden_proof_rigid_hand");
        const M relative=cinema_placement::multiply(cinema_placement::inverse(pose.head),pose.hands[side]);
        for(int r=0;r<3;++r)for(int c=0;c<4;++c)
            relative_error=std::max(relative_error,double(std::abs(relative.m[r][c]-local.m[r][c])));
    }
    require(cinema_placement::rigid(pose.head)&&relative_error<2e-6,"hidden_proof_rigid_head_relative");
    std::printf("{\"hidden_pose\":\"%s\",\"head_yaw_degrees\":%.0f,\"relative_transform_error\":%.9g}\n",
        pose.name.c_str(),head_yaw,relative_error);
    return pose;
}

int main(int argc,char**argv){
    const bool proof=argc==2 && std::string(argv[1])=="--hidden-proof";
    const char* ipc_value=std::getenv("FRAME_CINEMA_IPC"),*session_value=std::getenv("FRAME_CINEMA_SESSION"),*scene_value=std::getenv("FRAME_CINEMA_SCENE_PID");
    if(!proof&&(!ipc_value||!session_value||!scene_value))return 2;
    const std::string ipc=ipc_value?ipc_value:"",session=session_value?session_value:"";
    const auto scene_pid=scene_value?std::strtoul(scene_value,nullptr,10):0;
    std::signal(SIGTERM,stop);std::signal(SIGINT,stop);
    const auto parent=getppid();prctl(PR_SET_PDEATHSIG,SIGKILL);if(getppid()!=parent)return 0;
    EGLDisplay display=EGL_NO_DISPLAY;EGLContext context=EGL_NO_CONTEXT;EGLSurface surface=EGL_NO_SURFACE;
    bool vr_ready=false;int result=1;std::vector<vr::VROverlayHandle_t> overlays;
    auto publish_state=[&](bool presenting,bool left,bool right,uint64_t frames,double render_ms){
        if(proof||ipc.empty())return true;
        std::ofstream state(ipc+"/controller-layer.tmp");
        state<<std::setprecision(17)<<"{\"session\":\""<<session<<"\",\"scene_pid\":"<<scene_pid
            <<",\"updated\":"<<epoch()<<",\"active\":"<<(presenting?"true":"false")
            <<",\"left\":"<<(presenting&&left?"true":"false")<<",\"right\":"<<(presenting&&right?"true":"false")
            <<",\"frames\":"<<frames<<",\"cpu_submit_ms\":"<<render_ms<<"}";
        state.close();return bool(state)&&std::rename((ipc+"/controller-layer.tmp").c_str(),(ipc+"/controller-layer.json").c_str())==0;
    };
    try {
        require(publish_state(false,false,false,0,0),"controller_state_startup");
        HiddenProofPose proof_pose;
        if(proof)proof_pose=hidden_proof_pose();
        vr::EVRInitError error{};vr::VR_Init(&error,vr::VRApplication_Overlay);require(!error,"openvr_init");vr_ready=true;
        auto platform=(PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
        require(platform,"egl_platform");display=platform(EGL_PLATFORM_SURFACELESS_MESA,EGL_DEFAULT_DISPLAY,nullptr);
        require(eglInitialize(display,nullptr,nullptr),"egl_initialize");require(eglBindAPI(EGL_OPENGL_ES_API),"gles_bind");
        const EGLint attributes[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT,EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_DEPTH_SIZE,24,EGL_NONE};
        EGLConfig config;EGLint count;require(eglChooseConfig(display,attributes,&config,1,&count)&&count,"egl_config");
        const EGLint size[]={EGL_WIDTH,1,EGL_HEIGHT,1,EGL_NONE},version[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE};
        surface=eglCreatePbufferSurface(display,config,size);context=eglCreateContext(display,config,EGL_NO_CONTEXT,version);
        require(eglMakeCurrent(display,surface,surface,context),"egl_current");
        std::printf("{\"renderer\":\"%s\"}\n",glGetString(GL_RENDERER));
        const char* vertex=R"SHADER(#version 300 es
layout(location=0) in vec3 pos;
layout(location=1) in vec2 uv;
layout(location=2) in vec3 normal;
uniform mat4 projection;
uniform mat4 model;
out vec2 tex;
out vec3 eyeNormal;
out vec3 eyePosition;
void main(){
    tex=uv;
    vec4 p=model*vec4(pos,1.0);
    eyePosition=p.xyz;
    eyeNormal=mat3(model)*normal;
    gl_Position=projection*p;
})SHADER";
        const char* fragment=R"SHADER(#version 300 es
precision highp float;
in vec2 tex;
in vec3 eyeNormal;
in vec3 eyePosition;
uniform sampler2D image;
uniform float shadeStrength;
uniform float proofFlat;
uniform vec3 proofTint;
uniform vec3 keyDirection;
uniform vec3 fillDirection;
out vec4 color;
vec3 decodeSRGB(vec3 c){return mix(c/12.92,pow((c+0.055)/1.055,vec3(2.4)),step(vec3(0.04045),c));}
vec3 encodeSRGB(vec3 c){c=max(c,vec3(0));return mix(c*12.92,1.055*pow(c,vec3(1.0/2.4))-0.055,step(vec3(0.0031308),c));}
void main(){
    if(proofFlat>0.5){color=vec4(proofTint,1.0);return;}
    vec3 original=texture(image,tex).rgb;
    if(shadeStrength<0.5){color=vec4(original,1.0);return;}
    vec3 n=normalize(eyeNormal),v=normalize(-eyePosition),l=normalize(keyDirection);
    vec3 h=normalize(v+l);
    float nl=max(dot(n,l),0.0),nv=max(dot(n,v),0.001),nh=max(dot(n,h),0.0),vh=max(dot(v,h),0.0);
    // Broad dielectric plastic highlight. No normal map or invented detail.
    float roughness=0.72,a2=pow(roughness,4.0);
    float denominator=nh*nh*(a2-1.0)+1.0;
    float d=a2/(3.14159265*denominator*denominator);
    float k=pow(roughness+1.0,2.0)/8.0;
    float geometry=(nv/(nv*(1.0-k)+k))*(nl/(nl*(1.0-k)+k));
    float fresnel=0.04+0.96*pow(1.0-vh,5.0);
    float specular=d*geometry*fresnel/(4.0*nv*max(nl,0.001));
    float fill=max(dot(n,normalize(fillDirection)),0.0);
    // Neutral studio fill retains black plastic while making curvature legible.
    vec3 linear=decodeSRGB(original)*(0.55+1.35*nl+0.70*fill)+vec3(specular*nl*0.85);
    color=vec4(encodeSRGB(clamp(linear,vec3(0.0),vec3(1.0))),1.0);
})SHADER";
        GLuint vs=shader(GL_VERTEX_SHADER,vertex),fs=shader(GL_FRAGMENT_SHADER,fragment),program=glCreateProgram();glAttachShader(program,vs);glAttachShader(program,fs);glLinkProgram(program);
        GLint linked;glGetProgramiv(program,GL_LINK_STATUS,&linked);require(linked,"shader_link");glUseProgram(program);
        const GLint projection_loc=glGetUniformLocation(program,"projection"),model_loc=glGetUniformLocation(program,"model");
        const GLint key_loc=glGetUniformLocation(program,"keyDirection"),fill_loc=glGetUniformLocation(program,"fillDirection");
        const char* shade_value=std::getenv("FRAME_CINEMA_CONTROLLER_SHADE");
        const bool shaded=shade_value?std::string(shade_value)!="0":!proof;
        glUniform1f(glGetUniformLocation(program,"shadeStrength"),shaded?1.f:0.f);
        struct Model{GLuint vao=0,vertex=0,index=0,texture=0;int count=0;std::array<float,3> low{{1e9f,1e9f,1e9f}},high{{-1e9f,-1e9f,-1e9f}};};std::array<Model,2> models;
        for(int side=0;side<2;++side){
            vr::RenderModel_t* model=nullptr;vr::EVRRenderModelError e=vr::VRRenderModelError_Loading;
            const char* name=side?"{frame_controller}frame_controller_right":"{frame_controller}frame_controller_left";
            for(int i=0;i<100&&e==vr::VRRenderModelError_Loading;++i){e=vr::VRRenderModels()->LoadRenderModel_Async(name,&model);if(e==vr::VRRenderModelError_Loading)std::this_thread::sleep_for(std::chrono::milliseconds(20));}
            if(e!=vr::VRRenderModelError_None)std::printf("{\"model_error\":%d}\n",int(e));
            require(e==vr::VRRenderModelError_None&&model,"load_model");
            auto&m=models[side];for(uint32_t v=0;v<model->unVertexCount;++v)for(int axis=0;axis<3;++axis){m.low[axis]=std::min(m.low[axis],model->rVertexData[v].vPosition.v[axis]);m.high[axis]=std::max(m.high[axis],model->rVertexData[v].vPosition.v[axis]);}m.count=model->unTriangleCount*3;glGenVertexArrays(1,&m.vao);glBindVertexArray(m.vao);
            glGenBuffers(1,&m.vertex);glBindBuffer(GL_ARRAY_BUFFER,m.vertex);glBufferData(GL_ARRAY_BUFFER,model->unVertexCount*sizeof(vr::RenderModel_Vertex_t),model->rVertexData,GL_STATIC_DRAW);
            glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(vr::RenderModel_Vertex_t),(void*)offsetof(vr::RenderModel_Vertex_t,vPosition));glEnableVertexAttribArray(0);
            glVertexAttribPointer(1,2,GL_FLOAT,GL_FALSE,sizeof(vr::RenderModel_Vertex_t),(void*)offsetof(vr::RenderModel_Vertex_t,rfTextureCoord));glEnableVertexAttribArray(1);
            glVertexAttribPointer(2,3,GL_FLOAT,GL_FALSE,sizeof(vr::RenderModel_Vertex_t),(void*)offsetof(vr::RenderModel_Vertex_t,vNormal));glEnableVertexAttribArray(2);
            glGenBuffers(1,&m.index);glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,m.index);glBufferData(GL_ELEMENT_ARRAY_BUFFER,m.count*sizeof(uint16_t),model->rIndexData,GL_STATIC_DRAW);
            vr::RenderModel_TextureMap_t* tex=nullptr;e=vr::VRRenderModelError_Loading;
            for(int i=0;i<100&&e==vr::VRRenderModelError_Loading;++i){e=vr::VRRenderModels()->LoadTexture_Async(model->diffuseTextureId,&tex);if(e==vr::VRRenderModelError_Loading)std::this_thread::sleep_for(std::chrono::milliseconds(20));}
            require(e==vr::VRRenderModelError_None&&tex,"load_model_texture");
            // LoadTexture_Async returns RGBA8 for these installed Frame models.
            std::printf("{\"hand\":%d,\"triangles\":%u,\"texture_format\":%d,\"texture\":[%u,%u]}\n",side,model->unTriangleCount,int(tex->format),tex->unWidth,tex->unHeight);
            require(int(tex->format)==0,"unsupported_model_texture_format");
            glGenTextures(1,&m.texture);glBindTexture(GL_TEXTURE_2D,m.texture);glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,tex->unWidth,tex->unHeight,0,GL_RGBA,GL_UNSIGNED_BYTE,tex->rubTextureMapData);
            glGenerateMipmap(GL_TEXTURE_2D);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR_MIPMAP_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
            vr::VRRenderModels()->FreeTexture(tex);vr::VRRenderModels()->FreeRenderModel(model);
        }

        // One explicit square plane, rendered from physical per-eye origins.
        // SBS physical aspect remains a runtime acceptance check, not inferred
        // from GetTransformForOverlayCoordinates (the runtime returned stale data).
        constexpr int W=2160,H=2160;constexpr float QUAD_WIDTH=3.6f,QUAD_HEIGHT=3.6f,QUAD_DISTANCE=1.f;
        // DesktopPlus uses aspect1 for full SBS, aspect2 for half SBS.
        // This is implementation evidence; actual Frame capture remains required.
        float texel_aspect=1.f;
        if(const char* value=std::getenv("FRAME_CINEMA_CONTROLLER_SBS_TEXEL_ASPECT")){
            require(std::string(value)=="0.5"||std::string(value)=="1","sbs_aspect_choice");
            texel_aspect=std::string(value)=="1"?1.f:.5f;
        }
        const GLint proof_flat_loc=glGetUniformLocation(program,"proofFlat"),proof_tint_loc=glGetUniformLocation(program,"proofTint");
        glUniform1f(proof_flat_loc,0.f);
        struct EyeImage{GLuint texture=0,fbo=0,msaa=0,color=0,depth=0,resolve_texture=0,resolve_fbo=0;vr::VROverlayHandle_t overlay=0;};
        std::array<EyeImage,2> images;
        auto* overlay_api=vr::VROverlay();
        auto& target=images[0];
        GLint max_texture=0;glGetIntegerv(GL_MAX_TEXTURE_SIZE,&max_texture);require(max_texture>=2*W,"sbs_texture_capacity");
        glGenTextures(1,&target.texture);glBindTexture(GL_TEXTURE_2D,target.texture);
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,2*W,H,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
        glGenFramebuffers(1,&target.fbo);glBindFramebuffer(GL_FRAMEBUFFER,target.fbo);
        glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,target.texture,0);
        require(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,"resolve_framebuffer");
        glClearColor(0,0,0,0);glClear(GL_COLOR_BUFFER_BIT);
        glGenFramebuffers(1,&target.msaa);glBindFramebuffer(GL_FRAMEBUFFER,target.msaa);
        glGenRenderbuffers(1,&target.color);glBindRenderbuffer(GL_RENDERBUFFER,target.color);
        glRenderbufferStorageMultisample(GL_RENDERBUFFER,4,GL_RGBA8,W,H);glFramebufferRenderbuffer(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_RENDERBUFFER,target.color);
        glGenRenderbuffers(1,&target.depth);glBindRenderbuffer(GL_RENDERBUFFER,target.depth);
        glRenderbufferStorageMultisample(GL_RENDERBUFFER,4,GL_DEPTH_COMPONENT24,W,H);glFramebufferRenderbuffer(GL_FRAMEBUFFER,GL_DEPTH_ATTACHMENT,GL_RENDERBUFFER,target.depth);
        require(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,"msaa_framebuffer");
        // GLES multisample resolve requires identical source/destination bounds,
        // so resolve at (0,0) first, then copy the single-sample eye into SBS.
        glGenTextures(1,&target.resolve_texture);glBindTexture(GL_TEXTURE_2D,target.resolve_texture);
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,W,H,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        glGenFramebuffers(1,&target.resolve_fbo);glBindFramebuffer(GL_FRAMEBUFFER,target.resolve_fbo);
        glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,target.resolve_texture,0);
        require(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,"eye_resolve_framebuffer");
        glcheck("sbs_target_setup");
        const std::string key="frame-lab.cinema.controllers.sbs."+std::to_string(getpid());
        require(!overlay_api->CreateOverlay(key.c_str(),"Frame Cinema controller quad trial",&target.overlay),"create_overlay");overlays.push_back(target.overlay);
        require(!overlay_api->SetOverlayInputMethod(target.overlay,vr::VROverlayInputMethod_None),"overlay_input");
        require(!overlay_api->SetOverlayFlag(target.overlay,vr::VROverlayFlags_SortWithNonSceneOverlays,true),"overlay_sort_group");
        require(!overlay_api->SetOverlayFlag(target.overlay,vr::VROverlayFlags_IsPremultiplied,true),"overlay_premultiplied");
        require(!overlay_api->SetOverlayFlag(target.overlay,vr::VROverlayFlags_SideBySide_Parallel,true),"overlay_sbs");
        require(!overlay_api->SetOverlayWidthInMeters(target.overlay,QUAD_WIDTH),"overlay_width");
        require(!overlay_api->SetOverlayTexelAspect(target.overlay,texel_aspect),"overlay_aspect");
        require(!overlay_api->SetOverlaySortOrder(target.overlay,40),"overlay_sort");
        images[1]=target; // Aliases: each eye resolves into its own half of one texture.
        std::printf("{\"sbs_quad\":true,\"texture\":[4320,2160],\"plane_m\":[3.6,3.6],\"distance_m\":1,\"texel_aspect\":%.1f,\"physical_aspect_verified\":false}\n",texel_aspect);
        glViewport(0,0,W,H);glEnable(GL_DEPTH_TEST);glDisable(GL_CULL_FACE);

        auto render_eye=[&](int eye,const vr::HmdMatrix44_t& projection,const M& inverse_eye,
                            const std::array<M,2>& local,const std::array<bool,2>& draw,
                            bool flat,bool reverse){
            glUseProgram(program);
            std::array<float,16> p{};for(int r=0;r<4;++r)for(int c=0;c<4;++c)p[c*4+r]=projection.m[r][c];
            glUniformMatrix4fv(projection_loc,1,GL_FALSE,p.data());
            const float light[3]{.35f,.8f,.45f},fill[3]{-.65f,.5f,.6f};float eye_light[3]{},eye_fill[3]{};
            for(int r=0;r<3;++r)for(int c=0;c<3;++c){eye_light[r]+=inverse_eye.m[r][c]*light[c];eye_fill[r]+=inverse_eye.m[r][c]*fill[c];}
            glUniform3fv(key_loc,1,eye_light);glUniform3fv(fill_loc,1,eye_fill);glUniform1f(proof_flat_loc,flat?1.f:0.f);
            auto& target=images[eye];glBindFramebuffer(GL_FRAMEBUFFER,target.msaa);
            glClearColor(0,0,0,0);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
            for(int index=0;index<2;++index){const int side=reverse?1-index:index;if(!draw[side])continue;
                const auto transform=matrix(local[side]);glUniformMatrix4fv(model_loc,1,GL_FALSE,transform.data());
                glUniform3f(proof_tint_loc,side?0.f:1.f,side?1.f:0.f,0.f);
                glBindVertexArray(models[side].vao);glBindTexture(GL_TEXTURE_2D,models[side].texture);
                glDrawElements(GL_TRIANGLES,models[side].count,GL_UNSIGNED_SHORT,0);
            }
            glcheck("sbs_eye_draw");
            glBindFramebuffer(GL_READ_FRAMEBUFFER,target.msaa);glBindFramebuffer(GL_DRAW_FRAMEBUFFER,target.resolve_fbo);
            glBlitFramebuffer(0,0,W,H,0,0,W,H,GL_COLOR_BUFFER_BIT,GL_NEAREST);glcheck("sbs_msaa_resolve");
            glBindFramebuffer(GL_READ_FRAMEBUFFER,target.resolve_fbo);glBindFramebuffer(GL_DRAW_FRAMEBUFFER,target.fbo);
            glBlitFramebuffer(0,0,W,H,eye*W,0,(eye+1)*W,H,GL_COLOR_BUFFER_BIT,GL_NEAREST);glcheck("sbs_eye_copy");
        };
        auto read_eye=[&](int eye){
            std::vector<unsigned char> rgba(W*H*4);glBindFramebuffer(GL_FRAMEBUFFER,images[eye].fbo);
            glReadPixels(eye*W,0,W,H,GL_RGBA,GL_UNSIGNED_BYTE,rgba.data());require(glGetError()==GL_NO_ERROR,"proof_readback");return rgba;
        };
        std::array<bool,3> published_ownership{{false,false,false}};
        uint64_t frames=0,visible_frames=0;auto next_report=std::chrono::steady_clock::now();
        std::vector<GLuint> timer_queries;std::vector<double> cpu_samples;
        auto query_time=(PFNGLGETQUERYOBJECTUI64VEXTPROC)eglGetProcAddress("glGetQueryObjectui64vEXT");
        const bool timer_available=proof&&query_time&&std::string(reinterpret_cast<const char*>(glGetString(GL_EXTENSIONS))).find("GL_EXT_disjoint_timer_query")!=std::string::npos;
        while(active && getppid()==parent && (!proof||frames<90)){
            overlay_api->WaitFrameSync(20);
            const auto begin=std::chrono::steady_clock::now();const double now=epoch();
            cinema_placement::Packet packet;std::ifstream input(ipc+"/placement.txt");
            bool allowed=!proof && cinema_placement::read(input,packet)&&packet.session==session&&packet.tracked&&now>=packet.created&&now-packet.created<.2;
			std::ifstream focus_input(ipc+"/controller-focus.txt");
			allowed=allowed&&cinema_controller::focused(focus_input,session,scene_pid,now);
            allowed=allowed&&scene_pid&&vr::VRApplications()->GetCurrentSceneProcessId()==scene_pid&&!overlay_api->IsDashboardVisible();
            float prediction=0;
            if(allowed){double dt=double(packet.pose_time_ns-monotonic())*1e-9;if(dt<-.05||dt>.08||!packet.pose_time_ns)allowed=false;else prediction=std::max(0.f,float(dt));}
            vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount]{};
            vr::VRSystem()->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,prediction,poses,vr::k_unMaxTrackedDeviceCount);
            bool head_ok=cinema_controller_stereo::tracked_pose(poses[0]);
            std::array<M,2> hands{{cinema_placement::identity(),cinema_placement::identity()}};std::array<bool,2> tracked{};
            for(int side=0;side<2;++side){
                auto id=vr::VRSystem()->GetTrackedDeviceIndexForControllerRole(side?vr::TrackedControllerRole_RightHand:vr::TrackedControllerRole_LeftHand);
                tracked[side]=allowed&&head_ok&&id<vr::k_unMaxTrackedDeviceCount&&cinema_controller_stereo::tracked_pose(poses[id]);
                if(tracked[side])hands[side]=poses[id].mDeviceToAbsoluteTracking;
                if(proof){tracked[side]=true;hands[side]=proof_pose.hands[side];}
            }
            const M head=proof?proof_pose.head:head_ok?poses[0].mDeviceToAbsoluteTracking:cinema_placement::identity();

            M quad_local=cinema_placement::identity();quad_local.m[2][3]=-QUAD_DISTANCE;
            const M quad_pose=cinema_placement::multiply(head,quad_local);
            using cinema_controller_quad::transform;
            const auto lower_left=transform(quad_pose,{-QUAD_WIDTH*.5,-QUAD_HEIGHT*.5,0});
            const auto lower_right=transform(quad_pose,{QUAD_WIDTH*.5,-QUAD_HEIGHT*.5,0});
            const auto upper_left=transform(quad_pose,{-QUAD_WIDTH*.5,QUAD_HEIGHT*.5,0});
            std::array<M,2> eye_poses{},inverse_eyes{};
            std::array<vr::HmdMatrix44_t,2> projections{};
            std::array<std::array<M,2>,2> locals{};
            bool views_valid=cinema_placement::rigid(quad_pose);
            std::array<bool,2> hand_valid=tracked;
            for(int eye=0;eye<2;++eye){
                const auto eye_to_head=vr::VRSystem()->GetEyeToHeadTransform(vr::EVREye(eye));
                if(!cinema_placement::rigid(eye_to_head)){views_valid=false;continue;}
                eye_poses[eye]=cinema_placement::multiply(head,eye_to_head);
                if(!cinema_placement::rigid(eye_poses[eye])){views_valid=false;continue;}
                cinema_controller_quad::View view;
                if(!cinema_controller_quad::derive(lower_left,lower_right,upper_left,
                    cinema_controller_quad::origin(eye_poses[eye]),.03,30,view)){views_valid=false;continue;}
                inverse_eyes[eye]=view.inverse;projections[eye]=view.projection;
                for(int side=0;side<2;++side)if(tracked[side]){
                    locals[eye][side]=cinema_placement::multiply(inverse_eyes[eye],hands[side]);
                    if(!cinema_controller_stereo::model_pose_valid(locals[eye][side],projections[eye],models[side].low,models[side].high))
                        hand_valid[side]=false;
                }
            }
            if(!views_valid)hand_valid={{false,false}};
            // Both eyes are one submission; no partially owned hand/eye pair.
            int rendered=0;bool submitted=false;
            for(int eye=0;eye<2;++eye){
                if(!(hand_valid[0]||hand_valid[1]))continue;
                if(timer_available){GLuint query=0;glGenQueries(1,&query);glBeginQuery(GL_TIME_ELAPSED_EXT,query);timer_queries.push_back(query);}
                render_eye(eye,projections[eye],inverse_eyes[eye],locals[eye],hand_valid,false,false);
                if(timer_available)glEndQuery(GL_TIME_ELAPSED_EXT);
                require(glGetError()==GL_NO_ERROR,"controller_render");++rendered;
            }
            if(rendered==2){
                glFlush();vr::Texture_t texture{reinterpret_cast<void*>(uintptr_t(images[0].texture)),vr::TextureType_OpenGL,vr::ColorSpace_Gamma};
                submitted=!overlay_api->SetOverlayTransformAbsolute(images[0].overlay,vr::TrackingUniverseStanding,&quad_pose)
                    &&!overlay_api->SetOverlayTexture(images[0].overlay,&texture);
            }
            if(proof&&frames==0&&submitted){
                M stored{};vr::ETrackingUniverseOrigin space{};uint32_t width=0,height=0,flags=0;float stored_aspect=0;
                require(!overlay_api->GetOverlayTransformAbsolute(images[0].overlay,&space,&stored),"quad_pose_readback");
                require(!overlay_api->GetOverlayTextureSize(images[0].overlay,&width,&height),"quad_texture_readback");
                require(!overlay_api->GetOverlayTexelAspect(images[0].overlay,&stored_aspect),"quad_aspect_readback");
                require(!overlay_api->GetOverlayFlags(images[0].overlay,&flags),"quad_flags_readback");
                float max_pose_error=0;for(int r=0;r<3;++r)for(int c=0;c<4;++c)max_pose_error=std::max(max_pose_error,std::abs(stored.m[r][c]-quad_pose.m[r][c]));
                require(max_pose_error<1e-5&&space==vr::TrackingUniverseStanding,"quad_pose_state");
                require(width==2*W&&height==H&&std::abs(stored_aspect-texel_aspect)<1e-6
                    &&(flags&vr::VROverlayFlags_SideBySide_Parallel),"quad_texture_state");
                std::printf("{\"quad_state_readback\":true,\"pose_error\":%.9g,\"texture\":[%u,%u],\"texel_aspect\":%.1f,\"flags\":%u,\"rendered_geometry_verified\":false}\n",max_pose_error,width,height,stored_aspect,flags);
            }
            const std::array<bool,2> pair_ready{{hand_valid[0]&&rendered==2&&submitted,hand_valid[1]&&rendered==2&&submitted}};
            const auto ownership=cinema_controller_quad::present(allowed&&head_ok&&views_valid&&!proof,hand_valid,submitted,
                [&](){return !overlay_api->ShowOverlay(images[0].overlay);},
                [&](){return !overlay_api->HideOverlay(images[0].overlay);},
                [&](){return !overlay_api->ClearOverlayTexture(images[0].overlay);});
            require(ownership.cleanup_ok,"controller_quad_cleanup");
            const bool presenting=ownership.active;
            if(proof)cpu_samples.push_back(std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count());
            ++frames;if(rendered==2&&pair_ready[0]&&pair_ready[1])++visible_frames;
            if(proof&&frames==90){
                const char* output=std::getenv("FRAME_CINEMA_CONTROLLER_PROOF_OUT");
                for(int index=0;index<2;++index){
                    const auto rgba=read_eye(index);
                    require(glGetError()==GL_NO_ERROR,"proof_readback");
                    int opaque=0,clear=0,edge=0;
                    for(int i=0;i<W*H;++i){int alpha=rgba[i*4+3];opaque+=alpha==255;clear+=alpha==0;edge+=alpha>0&&alpha<255;}
                    require(opaque>1000&&clear>1000&&edge>10,"proof_transparent_msaa_edges");
                    std::printf("{\"image\":%d,\"opaque_pixels\":%d,\"clear_pixels\":%d,\"antialiased_pixels\":%d}\n",index,opaque,clear,edge);
                    if(output){
                        std::ofstream out(std::string(output)+"/controller-"+std::to_string(index)+".ppm",std::ios::binary);out<<"P6\n"<<W<<' '<<H<<"\n255\n";
                        for(int y=H-1;y>=0;--y)for(int x=0;x<W;++x){const auto i=(y*W+x)*4;const float alpha=rgba[i+3]/255.f;const int bg=((x/48+y/48)%2)?90:150;for(int c=0;c<3;++c)out.put(char(std::clamp(int(rgba[i+c]+bg*(1-alpha)),0,255)));}
                        require(bool(out),"proof_image_write");
                    }
                }
            }

            if(proof&&frames==90){
                for(int eye=0;eye<2;++eye){
                    for(int side=0;side<2;++side){
                        const std::array<bool,2> only{{side==0,side==1}};
                        render_eye(eye,projections[eye],inverse_eyes[eye],locals[eye],only,true,false);
                        const auto rgba=read_eye(eye);int occupied=0;
                        for(int i=0;i<W*H;++i)occupied+=rgba[i*4+3]>250;
                        require(occupied>1000,"proof_both_hands_occupy_each_eye");
                        std::printf("{\"eye\":%d,\"hand\":%d,\"occupied_pixels\":%d}\n",eye,side,occupied);
                    }
                    for(int front=0;front<2;++front){
                        std::array<M,2> crossing;
                        for(int side=0;side<2;++side){
                            crossing[side]=cinema_placement::identity();
                            const float z=side==front?-.55f:-1.f;
                            for(int axis=0;axis<3;++axis)crossing[side].m[axis][3]=-(models[side].low[axis]+models[side].high[axis])*.5f;
                            crossing[side].m[1][3]+=z*.25f;crossing[side].m[2][3]+=z;
                        }
                        // Entire near model is in front, so isolated opaque
                        // coverage overlap is an independent per-pixel oracle.
                        const int back=1-front;
                        require(crossing[front].m[2][3]+models[front].low[2]>
                                crossing[back].m[2][3]+models[back].high[2],"proof_depth_separation");
                        const auto proof_view=cinema_placement::identity();
                        std::array<std::vector<unsigned char>,2> masks;
                        for(int side=0;side<2;++side){
                            render_eye(eye,projections[eye],proof_view,crossing,{{side==0,side==1}},true,false);masks[side]=read_eye(eye);
                        }
                        render_eye(eye,projections[eye],proof_view,crossing,{{true,true}},true,false);const auto forward=read_eye(eye);
                        render_eye(eye,projections[eye],proof_view,crossing,{{true,true}},true,true);const auto reverse=read_eye(eye);
                        int overlap=0,max_difference=0,incorrect_front=0;
                        for(int i=0;i<W*H;++i){
                            for(int c=0;c<4;++c)max_difference=std::max(max_difference,std::abs(int(forward[i*4+c])-int(reverse[i*4+c])));
                            if(masks[0][i*4+3]>250&&masks[1][i*4+3]>250){
                                ++overlap;incorrect_front+=forward[i*4+front]<250||forward[i*4+back]>5;
                            }
                        }
                        require(overlap>100&&incorrect_front==0&&max_difference<=1,"proof_shared_depth_crossing");
                        std::printf("{\"depth_eye\":%d,\"front_hand\":%d,\"overlap_pixels\":%d,\"incorrect_front\":%d,\"draw_order_max_difference\":%d}\n",
                            eye,front,overlap,incorrect_front,max_difference);
                    }
                }
                std::printf("{\"sbs_eye_images\":2,\"texture_width\":4320,\"texture_height\":2160,\"msaa_samples\":4,\"shared_msaa_scratch\":true}\n");
            }
            const std::array<bool,3> current_ownership{{presenting,ownership.hand[0],ownership.hand[1]}};
            if(begin>=next_report||current_ownership!=published_ownership){
                const double render_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count();
                require(publish_state(presenting,ownership.hand[0],ownership.hand[1],frames,render_ms),"controller_state_publish");
                published_ownership=current_ownership;
                next_report=begin+std::chrono::milliseconds(40);
            }
        }
        if(proof){
            std::printf("{\"hidden_frames\":%llu,\"rendered_frames\":%llu}\n",(unsigned long long)frames,(unsigned long long)visible_frames);require(frames==90&&visible_frames==90,"hidden_projection_frames");
            std::sort(cpu_samples.begin(),cpu_samples.end());
            std::printf("{\"cpu_submit_ms_median\":%.3f,\"cpu_submit_ms_p95\":%.3f}\n",cpu_samples[cpu_samples.size()/2],cpu_samples[cpu_samples.size()*95/100]);
            if(timer_available){
                glFinish();GLint disjoint=1;glGetIntegerv(GL_GPU_DISJOINT_EXT,&disjoint);require(!disjoint,"gpu_timer_disjoint");
                require(timer_queries.size()==90*2,"gpu_timer_samples");
                std::vector<double> samples;for(size_t i=10*2;i<timer_queries.size();i+=2){double total=0;for(size_t j=0;j<2;++j){GLuint64 ns=0;query_time(timer_queries[i+j],GL_QUERY_RESULT,&ns);total+=ns*1e-6;}samples.push_back(total);}
                std::sort(samples.begin(),samples.end());
                std::printf("{\"gpu_draw_ms_median\":%.3f,\"gpu_draw_ms_p95\":%.3f,\"samples\":%zu}\n",samples[samples.size()/2],samples[samples.size()*95/100],samples.size());
                glDeleteQueries(timer_queries.size(),timer_queries.data());
            }else std::printf("{\"gpu_timer_available\":false}\n");
        }
        result=0;
    }catch(const std::exception&e){std::printf("{\"error\":\"%s\"}\n",e.what());}
    for(auto h:overlays){
        // Attempt every operation even if a previous one fails. Destroy is the
        // final stale-image barrier when the runtime refuses Hide or Clear.
        const auto hidden=vr::VROverlay()->HideOverlay(h);
        const auto cleared=vr::VROverlay()->ClearOverlayTexture(h);
        const auto destroyed=vr::VROverlay()->DestroyOverlay(h);
        if(hidden||cleared||destroyed)result=1;
    }
    if(!publish_state(false,false,false,0,0))result=1;
    if(vr_ready)vr::VR_Shutdown();
    if(display!=EGL_NO_DISPLAY){eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);if(context!=EGL_NO_CONTEXT)eglDestroyContext(display,context);if(surface!=EGL_NO_SURFACE)eglDestroySurface(display,surface);eglTerminate(display);}
    std::printf("{\"controller_layer_candidate\":%s}\n",result?"false":"true");return result;
}
