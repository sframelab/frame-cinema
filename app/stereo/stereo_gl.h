#pragma once
#include "stereo_config.h"
#include "texture_capture.h"
#include <string>
#include <vector>
#include <algorithm>
#include <cstdint>
namespace cinema_stereo {
inline GLuint shader(GLenum type,const char* source){GLuint s=glCreateShader(type);glShaderSource(s,1,&source,nullptr);glCompileShader(s);GLint ok=0;glGetShaderiv(s,GL_COMPILE_STATUS,&ok);if(!ok){char log[2048];glGetShaderInfoLog(s,sizeof(log),nullptr,log);throw std::runtime_error(log);}return s;}
inline GLuint program(const char* fragment){
    const char* vertex="#version 330\n out vec2 uv;void main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);uv=p;gl_Position=vec4(p*2.-1.,0,1);}";
    GLuint v=shader(GL_VERTEX_SHADER,vertex),f=shader(GL_FRAGMENT_SHADER,fragment),p=glCreateProgram();glAttachShader(p,v);glAttachShader(p,f);glLinkProgram(p);glDeleteShader(v);glDeleteShader(f);GLint ok;glGetProgramiv(p,GL_LINK_STATUS,&ok);if(!ok)throw std::runtime_error("stereo_link");return p;
}
// Our own depth-image rendering shader. Horizontal inverse mapping with a
// bounded foreground search; no Moonlight rendering or export code is used.
static const char* stereo_fragment=R"GLSL(#version 330
in vec2 uv;out vec4 color;uniform sampler2D source;uniform sampler2D depth;
uniform float inverted;uniform float amount;uniform float eye;uniform float sampleOnly;
uniform vec2 sampleScale;uniform float crop;uniform vec2 modelSize;uniform float modelFilter;uniform float protectEdges;uniform float hasGradient;
vec2 imageUV(vec2 p){return vec2(p.x,inverted>.5?p.y:1.-p.y);}
float z(vec2 p){return texture(depth,p).r;}
void main(){
    if(sampleOnly>1.5){color=texture(source,imageUV(uv));return;}
    if(sampleOnly>.5){
        vec2 q=(vec2(uv.x,1.-uv.y)-.5)/sampleScale+.5;q=clamp(q,0.,1.);q.y=crop+q.y*(1.-2.*crop);
        if(modelFilter<.5){color=texture(source,imageUV(q));return;}
        // Integrate the input pixel's footprint directly in this small pass.
        // No full-resolution mip chain or extra GPU render passes are needed.
        vec2 footprint=vec2(1.,1.-2.*crop)/(modelSize*sampleScale);
        vec4 sum=vec4(0.);
        for(int y=0;y<4;++y)for(int x=0;x<4;++x){
            vec2 offset=(vec2(x,y)+.5)/4.-.5;
            sum+=texture(source,imageUV(clamp(q+offset*footprint,0.,1.)));
        }
        color=sum/16.;return;
    }
    vec2 p=uv;float edge=smoothstep(0.,.035,min(p.x,1.-p.x));float shift=amount*eye*edge;
    float best=p.x-shift*(z(p)-.5);float nearest=-2.;bool found=false;
    float background=best,backgroundDistance=2.;
    // Bracket the inverse mapping, then interpolate its crossing. Selecting
    // the discrete search point itself quantizes smooth depth into 13 planes.
    float x0=p.x-amount*.5;vec2 s0=texture(depth,vec2(x0,p.y)).rg;float d0=s0.r;float m0=x0+shift*(d0-.5);
    for(int i=1;i<=12;i++){
        float x1=p.x+amount*(float(i)/12.-.5);vec2 s1=texture(depth,vec2(x1,p.y)).rg;float d1=s1.r;
        float m1=x1+shift*(d1-.5);float span=m1-m0;
        // A large depth jump is a silhouette, not a sloping rubber sheet.
        // Newly revealed strips extend the background endpoint only; never
        // interpolate foreground color across the invisible background.
        if(abs(span)>1e-7 && p.x>=min(m0,m1) && p.x<=max(m0,m1)){
            float t=clamp((p.x-m0)/span,0.,1.);float d=mix(d0,d1,t);
            float at=mix(x0,x1,t);bool boundary=false;
            if(protectEdges>.5){
                float texel=1./float(textureSize(depth,0).x);
                // Classify the actual inverse-search segment. A wider gradient
                // band also marks valid foreground pixels beside the contour,
                // which used to carve away their silhouette in one eye.
                boundary=abs(d1-d0)>.065;
                if(boundary && abs(d-.5)<backgroundDistance){
                    backgroundDistance=abs(d-.5);
                    background=(d0<d1?x0:x1)-sign(d1-d0)*texel*.5;
                }
            }
            if(!boundary && d>nearest){best=at;nearest=d;found=true;}
        }
        x0=x1;d0=d1;m0=m1;s0=s1;
    }
    if(!found){
        if(backgroundDistance<1.)best=background;
        else for(int j=0;j<3;j++)best=p.x-shift*(z(vec2(best,p.y))-.5);
    }
    color=texture(source,imageUV(vec2(clamp(best,.0003,.9997),p.y)));
    color.a=1.;
})GLSL";
// Current-color guidance is bounded by the supporting depth structure.
// Fine color texture cannot arbitrarily pull a surface toward another plane.
static const char* refine_fragment=R"GLSL(#version 330
in vec2 uv;out vec2 value;uniform sampler2D source;uniform sampler2D depth;
uniform vec2 sampleScale;uniform float crop;uniform vec2 modelSize;uniform vec2 refineSize;
void main(){
    vec2 picture=vec2(uv.x,(uv.y-crop)/(1.-2.*crop));
    vec2 q=(picture-.5)*sampleScale+.5;
    vec2 base=floor(q*modelSize);vec3 center=texture(source,uv).rgb;
    float sum=0.,weight=0.,spatialSum=0.,spatialWeight=0.;
    float original=texture(depth,q).r,lo=original,hi=original;
    // A model-cell footprint can straddle two surfaces. Use the immutable
    // current picture to find supporting samples on the same side of its
    // outline, rather than limiting every correction to 0.025 depth units.
    for(int y=-1;y<=1;++y)for(int x=-2;x<=2;++x){
        vec2 at=(base+vec2(x,y)+.5)/modelSize;
        vec2 src=(at-.5)/sampleScale+.5;src.y=crop+src.y*(1.-2.*crop);
        vec3 d=texture(source,clamp(src,0.,1.)).rgb-center;
        float z=texture(depth,at).r;lo=min(lo,z);hi=max(hi,z);
        vec2 offset=at*modelSize-q*modelSize;
        float spatial=exp(-dot(offset,offset)*.45);
        float colorDistance=dot(d,d)*80.;
        float w=spatial/(1.+colorDistance*colorDistance);
        sum+=z*w;weight+=w;
        // Preserve meaningful depth steps while reducing isolated map noise.
        float dz=(z-original)/.055;float range=1./(1.+dz*dz*dz*dz);
        spatialSum+=z*spatial*range;spatialWeight+=spatial*range;
    }
    float smoothDepth=spatialSum/max(spatialWeight,.00001);
    float support=smoothstep(.06,.20,hi-lo);
    float correction=sum/max(weight,.00001)-smoothDepth;
    value=vec2(clamp(smoothDepth+support*correction,lo,hi),0.);
})GLSL";
struct FrozenColor {GLuint texture=0;int width=0,height=0;bool y_inverted=true;};
struct StereoGL {
    GLuint pipeline=0,refiner=0,vao=0,fbo=0,output[2]{},small=0,depth=0,refined=0,pbo=0;
    FrozenColor frozen;int mw,mh,rw=0,rh=0;float sx=1,sy=1,picture_crop=0;bool model_filter=true;
    GLsync pending=nullptr;int output_index=0,w=0,h=0;uint64_t pending_rev=0,pending_seq=0;double pending_time=0;
    StereoGL(int width=model_width,int height=model_height):mw(width),mh(height){pipeline=program(stereo_fragment);refiner=program(refine_fragment);glGenVertexArrays(1,&vao);glBindVertexArray(vao);glGenFramebuffers(1,&fbo);glGenTextures(2,output);glGenTextures(1,&small);glGenTextures(1,&depth);glGenTextures(1,&refined);glGenTextures(1,&frozen.texture);glGenBuffers(1,&pbo);
        allocate(small,mw,mh,GL_RGBA8,GL_RGBA,GL_UNSIGNED_BYTE);allocate(depth,mw,mh,GL_R32F,GL_RED,GL_FLOAT);
        std::vector<float> neutral(mw*mh,.5);glBindTexture(GL_TEXTURE_2D,depth);glTexSubImage2D(GL_TEXTURE_2D,0,0,0,mw,mh,GL_RED,GL_FLOAT,neutral.data());
        glBindBuffer(GL_PIXEL_PACK_BUFFER,pbo);glBufferData(GL_PIXEL_PACK_BUFFER,mw*mh*4,nullptr,GL_STREAM_READ);glBindBuffer(GL_PIXEL_PACK_BUFFER,0);
    }
    static void allocate(GLuint t,int x,int y,GLenum internal,GLenum format,GLenum type){glBindTexture(GL_TEXTURE_2D,t);glTexImage2D(GL_TEXTURE_2D,0,internal,x,y,0,format,type,nullptr);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);}
    void target(GLuint t,int x,int y){glBindFramebuffer(GL_FRAMEBUFFER,fbo);glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,t,0);if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)throw std::runtime_error("stereo_framebuffer");glViewport(0,0,x,y);}
    template<class Image> void setup(const Image& capture){glUseProgram(pipeline);glBindVertexArray(vao);glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,capture.texture);glUniform1i(glGetUniformLocation(pipeline,"source"),0);glActiveTexture(GL_TEXTURE1);glBindTexture(GL_TEXTURE_2D,depth);glUniform1i(glGetUniformLocation(pipeline,"depth"),1);glUniform1f(glGetUniformLocation(pipeline,"inverted"),capture.y_inverted?1:0);glUniform2f(glGetUniformLocation(pipeline,"sampleScale"),sx,sy);glUniform1f(glGetUniformLocation(pipeline,"crop"),picture_crop);glUniform2f(glGetUniformLocation(pipeline,"modelSize"),mw,mh);glUniform1f(glGetUniformLocation(pipeline,"modelFilter"),model_filter?1:0);}
    const FrozenColor& snapshot(const TextureCapture& capture,float crop=0){
        if(frozen.width!=capture.width||frozen.height!=capture.height){frozen.width=capture.width;frozen.height=capture.height;allocate(frozen.texture,frozen.width,frozen.height,GL_RGBA8,GL_RGBA,GL_UNSIGNED_BYTE);}
        picture_crop=std::clamp(crop,0.f,.4f);
        float ratio=float(capture.width)/(capture.height*(1-2*picture_crop));
        sx=std::min(1.f,ratio/(float(mw)/mh));sy=std::min(1.f,(float(mw)/mh)/ratio);
        target(frozen.texture,frozen.width,frozen.height);setup(capture);glUniform1f(glGetUniformLocation(pipeline,"sampleOnly"),2);glDrawArrays(GL_TRIANGLES,0,3);
        glFlush();return frozen;
    }
    template<class Image> void queue_sample(const Image& capture,uint64_t rev,uint64_t seq,double now){
        if(pending)return;target(small,mw,mh);setup(capture);glUniform1f(glGetUniformLocation(pipeline,"sampleOnly"),1);glDrawArrays(GL_TRIANGLES,0,3);
        glBindBuffer(GL_PIXEL_PACK_BUFFER,pbo);glReadPixels(0,0,mw,mh,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);glBindBuffer(GL_PIXEL_PACK_BUFFER,0);pending=glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);glFlush();pending_rev=rev;pending_seq=seq;pending_time=now;
    }
    std::vector<unsigned char> sample(){
        if(!pending)return {};auto state=glClientWaitSync(pending,0,0);if(state!=GL_ALREADY_SIGNALED&&state!=GL_CONDITION_SATISFIED)return {};
        glBindBuffer(GL_PIXEL_PACK_BUFFER,pbo);auto* data=(unsigned char*)glMapBufferRange(GL_PIXEL_PACK_BUFFER,0,mw*mh*4,GL_MAP_READ_BIT);if(!data)throw std::runtime_error("depth_readback");
        std::vector<unsigned char> result(data,data+mw*mh*4);glUnmapBuffer(GL_PIXEL_PACK_BUFFER);glBindBuffer(GL_PIXEL_PACK_BUFFER,0);glDeleteSync(pending);pending=nullptr;return result;
    }
    void upload_depth(const std::vector<float>& values){
        // Depth worker input is top-down; GL's scene texture is bottom-up.
        if(values.size()!=size_t(mw*mh))throw std::runtime_error("depth_upload_size");
        std::vector<float> flipped(values.size());for(int y=0;y<mh;++y)std::copy_n(values.data()+y*mw,mw,flipped.data()+((mh-1)-y)*mw);
        glBindTexture(GL_TEXTURE_2D,depth);glTexSubImage2D(GL_TEXTURE_2D,0,0,0,mw,mh,GL_RED,GL_FLOAT,flipped.data());
    }
    void refine(){
        int width=std::min(960,std::max(mw,frozen.width/2)),height=std::min(540,std::max(mh,frozen.height/2));
        if(width!=rw||height!=rh){rw=width;rh=height;allocate(refined,rw,rh,GL_RG32F,GL_RG,GL_FLOAT);}
        target(refined,rw,rh);glUseProgram(refiner);glBindVertexArray(vao);
        glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,frozen.texture);glUniform1i(glGetUniformLocation(refiner,"source"),0);
        glActiveTexture(GL_TEXTURE1);glBindTexture(GL_TEXTURE_2D,depth);glUniform1i(glGetUniformLocation(refiner,"depth"),1);
        glUniform2f(glGetUniformLocation(refiner,"sampleScale"),sx,sy);glUniform2f(glGetUniformLocation(refiner,"modelSize"),mw,mh);glUniform1f(glGetUniformLocation(refiner,"crop"),picture_crop);
        glUniform2f(glGetUniformLocation(refiner,"refineSize"),rw,rh);
        glDrawArrays(GL_TRIANGLES,0,3);
    }
    template<class Image> GLuint render(const Image& capture,float amount,bool use_refined=false,bool protect_edges=false){
        if(w!=capture.width||h!=capture.height){w=capture.width;h=capture.height;for(auto t:output)allocate(t,2*w,h,GL_RGBA8,GL_RGBA,GL_UNSIGNED_BYTE);}
        output_index=1-output_index;target(output[output_index],2*w,h);setup(capture);glUniform1f(glGetUniformLocation(pipeline,"sampleOnly"),0);glUniform1f(glGetUniformLocation(pipeline,"amount"),amount);
        glUniform1f(glGetUniformLocation(pipeline,"protectEdges"),protect_edges?1:0);
        glUniform1f(glGetUniformLocation(pipeline,"hasGradient"),use_refined?1:0);
        if(use_refined){glActiveTexture(GL_TEXTURE1);glBindTexture(GL_TEXTURE_2D,refined);}
        for(int eye=0;eye<2;++eye){glViewport(eye*w,0,w,h);glUniform1f(glGetUniformLocation(pipeline,"eye"),eye?-1.f:1.f);glDrawArrays(GL_TRIANGLES,0,3);}
        glBindFramebuffer(GL_FRAMEBUFFER,0);glFlush();if(glGetError()!=GL_NO_ERROR)throw std::runtime_error("stereo_gl_error");return output[output_index];
    }
    ~StereoGL(){glFinish();if(pending)glDeleteSync(pending);glDeleteBuffers(1,&pbo);glDeleteFramebuffers(1,&fbo);glDeleteTextures(2,output);glDeleteTextures(1,&small);glDeleteTextures(1,&depth);glDeleteTextures(1,&refined);glDeleteTextures(1,&frozen.texture);glDeleteVertexArrays(1,&vao);glDeleteProgram(pipeline);glDeleteProgram(refiner);}
};
}
