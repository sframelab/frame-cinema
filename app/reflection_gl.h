#pragma once
#include "stereo/texture_capture.h"
#include <algorithm>
#include <cstdint>
#include <vector>

// Alpine lake reflection from the GPU: the owned browser window as a texture
// (texture-from-pixmap, as Dark Room 3D captures it), box-halved on the GPU to
// 192x108 and read back through a fenced PBO one frame later. The X server's
// XRender reduction + XGetImage took 70-300 ms per capture on Frame (0.4.47).
struct ReflectionGL {
    static constexpr int W=192,H=108;
    TextureCapture capture;
    GLuint fbo[2]{},pbo=0;
    std::vector<GLuint> levels;std::vector<int> lw,lh;int source_w=0,source_h=0;
    GLsync pending=nullptr;uint64_t pending_sequence=0;double pending_expected=0;
    bool started=false;
    void start(Window window){
        capture.start(window);
        glGenFramebuffers(2,fbo);glGenBuffers(1,&pbo);
        glBindBuffer(GL_PIXEL_PACK_BUFFER,pbo);glBufferData(GL_PIXEL_PACK_BUFFER,W*H*4,nullptr,GL_STREAM_READ);glBindBuffer(GL_PIXEL_PACK_BUFFER,0);
        started=true;
    }
    void build_levels(int w,int h){
        if(w==source_w&&h==source_h&&!levels.empty())return;
        if(!levels.empty())glDeleteTextures(GLsizei(levels.size()),levels.data());
        levels.clear();lw.clear();lh.clear();source_w=w;source_h=h;
        // Halve while more than twice the target, then one final step.
        while(w>2*W||h>2*H){w=std::max(W,(w+1)/2);h=std::max(H,(h+1)/2);lw.push_back(w);lh.push_back(h);}
        lw.push_back(W);lh.push_back(H);
        levels.resize(lw.size());glGenTextures(GLsizei(levels.size()),levels.data());
        for(size_t i=0;i<levels.size();++i){
            glBindTexture(GL_TEXTURE_2D,levels[i]);
            glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,lw[i],lh[i],0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        }
    }
    // Capture the window's current contents for `sequence`. One in flight.
    bool queue(uint64_t sequence,double expected){
        if(!started||pending)return false;
        if(!capture.update())return false;
        build_levels(capture.width,capture.height);
        int sw=capture.width,sh=capture.height;GLuint source=capture.texture;
        for(size_t i=0;i<levels.size();++i){
            glBindFramebuffer(GL_READ_FRAMEBUFFER,fbo[0]);glFramebufferTexture2D(GL_READ_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,source,0);
            glBindFramebuffer(GL_DRAW_FRAMEBUFFER,fbo[1]);glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,levels[i],0);
            // Rows leave top-first: flip once on the first pass when the pixmap
            // texture is bottom-up.
            const bool flip=i==0&&!capture.y_inverted;
            glBlitFramebuffer(0,0,sw,sh,0,flip?lh[i]:0,lw[i],flip?0:lh[i],GL_COLOR_BUFFER_BIT,GL_LINEAR);
            source=levels[i];sw=lw[i];sh=lh[i];
        }
        glBindFramebuffer(GL_READ_FRAMEBUFFER,fbo[0]);glFramebufferTexture2D(GL_READ_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,levels.back(),0);
        glBindBuffer(GL_PIXEL_PACK_BUFFER,pbo);glReadPixels(0,0,W,H,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);glBindBuffer(GL_PIXEL_PACK_BUFFER,0);
        glBindFramebuffer(GL_FRAMEBUFFER,0);
        pending=glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);glFlush();
        pending_sequence=sequence;pending_expected=expected;
        return glGetError()==GL_NO_ERROR;
    }
    // Non-blocking: the previous capture's pixels once the GPU has finished.
    bool collect(std::vector<unsigned char>& pixels,uint64_t& sequence,double& expected){
        if(!pending)return false;
        const auto state=glClientWaitSync(pending,0,0);
        if(state!=GL_ALREADY_SIGNALED&&state!=GL_CONDITION_SATISFIED)return false;
        glDeleteSync(pending);pending=nullptr;
        glBindBuffer(GL_PIXEL_PACK_BUFFER,pbo);
        auto* data=static_cast<const unsigned char*>(glMapBufferRange(GL_PIXEL_PACK_BUFFER,0,W*H*4,GL_MAP_READ_BIT));
        if(!data){glBindBuffer(GL_PIXEL_PACK_BUFFER,0);return false;}
        pixels.assign(data,data+W*H*4);
        glUnmapBuffer(GL_PIXEL_PACK_BUFFER);glBindBuffer(GL_PIXEL_PACK_BUFFER,0);
        for(size_t i=3;i<pixels.size();i+=4)pixels[i]=255;
        sequence=pending_sequence;expected=pending_expected;
        return true;
    }
    ~ReflectionGL(){
        if(!started)return;
        if(pending)glDeleteSync(pending);
        if(!levels.empty())glDeleteTextures(GLsizei(levels.size()),levels.data());
        glDeleteBuffers(1,&pbo);glDeleteFramebuffers(2,fbo);
    }
};
