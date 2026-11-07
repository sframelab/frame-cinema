#pragma once
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <stdexcept>
#include <cstring>
#include <vector>
struct OverlayGL {
    EGLDisplay display=EGL_NO_DISPLAY;EGLContext context=EGL_NO_CONTEXT;EGLSurface surface=EGL_NO_SURFACE;
    GLuint texture=0;int width=0,height=0;
    std::vector<unsigned char> bottom_up;
    void start(){
        auto platform=(PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
        if(!platform)throw std::runtime_error("egl_platform");
        display=platform(EGL_PLATFORM_SURFACELESS_MESA,EGL_DEFAULT_DISPLAY,nullptr);
        if(!eglInitialize(display,nullptr,nullptr)||!eglBindAPI(EGL_OPENGL_ES_API))throw std::runtime_error("egl_init");
        EGLConfig config;EGLint count=0;
        const EGLint attr[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT,EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_NONE};
        if(!eglChooseConfig(display,attr,&config,1,&count)||!count)throw std::runtime_error("egl_config");
        const EGLint size[]={EGL_WIDTH,1,EGL_HEIGHT,1,EGL_NONE},version[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE};
        surface=eglCreatePbufferSurface(display,config,size);context=eglCreateContext(display,config,EGL_NO_CONTEXT,version);
        if(!eglMakeCurrent(display,surface,surface,context))throw std::runtime_error("egl_current");
        glGenTextures(1,&texture);glBindTexture(GL_TEXTURE_2D,texture);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
    }
    bool upload(const unsigned char* pixels,int w,int h){
        // GetOverlayImageData is top-down; OpenGL submissions use bottom-up
        // rows. Keep the owned screen's UV bounds full and uninverted.
        bottom_up.resize(size_t(w)*h*4);
        for(int y=0;y<h;++y)std::memcpy(bottom_up.data()+size_t(h-1-y)*w*4,pixels+size_t(y)*w*4,size_t(w)*4);
        glBindTexture(GL_TEXTURE_2D,texture);
        if(w!=width||h!=height){glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,w,h,0,GL_RGBA,GL_UNSIGNED_BYTE,bottom_up.data());width=w;height=h;}
        else glTexSubImage2D(GL_TEXTURE_2D,0,0,0,w,h,GL_RGBA,GL_UNSIGNED_BYTE,bottom_up.data());
        glFlush();return glGetError()==GL_NO_ERROR;
    }
    ~OverlayGL(){
        if(display!=EGL_NO_DISPLAY){
            if(texture)glDeleteTextures(1,&texture);
            eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);
            if(context!=EGL_NO_CONTEXT)eglDestroyContext(display,context);
            if(surface!=EGL_NO_SURFACE)eglDestroySurface(display,surface);
            eglTerminate(display);
        }
    }
};
