#pragma once
#include "overlay_gl.h"
#include "openvr.h"
#include <memory>

// Keep the compositor's backing image alive through hover redraws. Raw image
// loading is asynchronous and may temporarily remove the previously shown image.
// This context is independent of Godot's Vulkan renderer; restore any caller EGL
// binding after every operation, including partial initialization failures.
class NativeUITexture {
    friend struct NativeUITextureTestAccess;
    struct RestoreContext {
        EGLenum api=eglQueryAPI();
        EGLDisplay display=eglGetCurrentDisplay();
        EGLContext context=eglGetCurrentContext();
        EGLSurface draw=eglGetCurrentSurface(EGL_DRAW),read=eglGetCurrentSurface(EGL_READ);
        ~RestoreContext(){
            auto current=eglGetCurrentDisplay();
            if(current!=EGL_NO_DISPLAY)eglMakeCurrent(current,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);
            eglBindAPI(api);
            if(display!=EGL_NO_DISPLAY)eglMakeCurrent(display,draw,read,context);
        }
    };
    std::unique_ptr<OverlayGL> gpu;
public:
    int error=0;
    uint64_t submissions=0,allocations=0;
    bool submit(vr::IVROverlay* overlay,vr::VROverlayHandle_t handle,const unsigned char* pixels,int width,int height){
        RestoreContext restore;
        error=0;
        try {
            if(!gpu){gpu=std::make_unique<OverlayGL>();gpu->start();}
            else if(!eglBindAPI(EGL_OPENGL_ES_API)||!eglMakeCurrent(gpu->display,gpu->surface,gpu->surface,gpu->context)){
                error=-2;return false;
            }
            const bool resize=gpu->width!=width||gpu->height!=height;
            // The 2D viewport supplies display-encoded RGBA. Keep the image's
            // sRGB format explicit through GL/Vulkan import, not only in the
            // overlay's Gamma hint. Do not gamma-convert or tint its bytes.
            gpu->bottom_up.resize(size_t(width)*height*4);
            for(int y=0;y<height;++y)std::memcpy(gpu->bottom_up.data()+size_t(height-1-y)*width*4,pixels+size_t(y)*width*4,size_t(width)*4);
            glBindTexture(GL_TEXTURE_2D,gpu->texture);
            if(resize){glTexImage2D(GL_TEXTURE_2D,0,GL_SRGB8_ALPHA8,width,height,0,GL_RGBA,GL_UNSIGNED_BYTE,gpu->bottom_up.data());gpu->width=width;gpu->height=height;}
            else glTexSubImage2D(GL_TEXTURE_2D,0,0,0,width,height,GL_RGBA,GL_UNSIGNED_BYTE,gpu->bottom_up.data());
            if(glGetError()!=GL_NO_ERROR){error=-3;return false;}
            // Complete the upload before OpenVR copies/imports the texture.
            glFinish();
            if(glGetError()!=GL_NO_ERROR){error=-4;return false;}
            allocations+=resize;
            vr::Texture_t texture{reinterpret_cast<void*>(uintptr_t(gpu->texture)),vr::TextureType_OpenGL,vr::ColorSpace_Gamma};
            error=int(overlay->SetOverlayTexture(handle,&texture));
            if(error)return false;
            ++submissions;return true;
        }catch(const std::exception&){error=-1;gpu.reset();return false;}
    }
    void close(){
        if(!gpu)return;
        RestoreContext restore;
        eglBindAPI(EGL_OPENGL_ES_API);
        eglMakeCurrent(gpu->display,gpu->surface,gpu->surface,gpu->context);
        gpu.reset();
    }
    ~NativeUITexture(){close();}
};
