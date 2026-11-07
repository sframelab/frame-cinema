#pragma once
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <GL/glxext.h>
#include <X11/extensions/Xcomposite.h>
#include <X11/Xutil.h>
#include <cstring>
#include <stdexcept>
#include <mutex>

// An owned browser window on Cinema's private X display. Pixels stay on GPU.
// The caller must establish window/source ownership before using this class.
struct TextureCapture {
    Display* display=nullptr;
    GLXContext context=nullptr;
    GLXPbuffer buffer=0;
    GLXFBConfig config=nullptr;
    Pixmap pixmap=0;
    GLXPixmap binding=0;
    Window window=0;
    GLuint texture=0;
    int width=0,height=0;
    bool bound=false,redirected=false,y_inverted=false;
    PFNGLXBINDTEXIMAGEEXTPROC bind=nullptr;
    PFNGLXRELEASETEXIMAGEEXTPROC release=nullptr;
    static inline thread_local int x_error=0;
    static inline thread_local Display* watched=nullptr;
    static inline XErrorHandler previous_handler=nullptr;
    static inline std::once_flag handler_once;
    static int on_error(Display* d,XErrorEvent* e){
        if(d==watched){x_error=e->error_code;return 0;}
        return previous_handler?previous_handler(d,e):0;
    }
    void start(Window target) {
        display=XOpenDisplay(nullptr);
        if(!display)throw std::runtime_error("capture_display");
        watched=display;
        std::call_once(handler_once,[]{previous_handler=XSetErrorHandler(on_error);});
        const char* ext=glXQueryExtensionsString(display,DefaultScreen(display));
        if(!ext || !std::strstr(ext,"GLX_EXT_texture_from_pixmap"))throw std::runtime_error("texture_from_pixmap_unavailable");
        bind=(PFNGLXBINDTEXIMAGEEXTPROC)glXGetProcAddressARB((const GLubyte*)"glXBindTexImageEXT");
        release=(PFNGLXRELEASETEXIMAGEEXTPROC)glXGetProcAddressARB((const GLubyte*)"glXReleaseTexImageEXT");
        if(!bind||!release)throw std::runtime_error("texture_from_pixmap_functions");
        XWindowAttributes wa{};
        if(!XGetWindowAttributes(display,target,&wa))throw std::runtime_error("capture_window");
        int count=0;
        auto configs=glXGetFBConfigs(display,DefaultScreen(display),&count);
        for(int i=0;i<count;++i){
            auto v=glXGetVisualFromFBConfig(display,configs[i]);
            int draw=0,bindrgb=0;
            glXGetFBConfigAttrib(display,configs[i],GLX_DRAWABLE_TYPE,&draw);
            glXGetFBConfigAttrib(display,configs[i],GLX_BIND_TO_TEXTURE_RGB_EXT,&bindrgb);
            if(v && v->depth==wa.depth && (draw&GLX_PIXMAP_BIT) && (draw&GLX_PBUFFER_BIT) && bindrgb)config=configs[i];
            if(v)XFree(v);
            if(config)break;
        }
        if(configs)XFree(configs);
        if(!config)throw std::runtime_error("capture_config");
        context=glXCreateNewContext(display,config,GLX_RGBA_TYPE,nullptr,True);
        const int pb[]={GLX_PBUFFER_WIDTH,1,GLX_PBUFFER_HEIGHT,1,None};
        buffer=glXCreatePbuffer(display,config,pb);
        if(!context||!buffer||!glXMakeContextCurrent(display,buffer,buffer,context))throw std::runtime_error("capture_context");
        glGenTextures(1,&texture);glBindTexture(GL_TEXTURE_2D,texture);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
        window=target;
        attach();
    }
    void detach(){
        if(!display)return;
        if(bound){release(display,binding,GLX_FRONT_LEFT_EXT);bound=false;}
        if(binding){glXDestroyPixmap(display,binding);binding=0;}
        if(pixmap){XFreePixmap(display,pixmap);pixmap=0;}
    }
    void attach(){
        detach();
        XWindowAttributes wa{};
        if(!XGetWindowAttributes(display,window,&wa)||wa.map_state!=IsViewable)throw std::runtime_error("capture_unmapped");
        if(wa.width<16||wa.height<16||wa.width>3840||wa.height>2160)throw std::runtime_error("capture_dimensions");
        x_error=0;pixmap=XCompositeNameWindowPixmap(display,window);XSync(display,False);
        if(x_error){
            pixmap=0;x_error=0;
            XCompositeRedirectWindow(display,window,CompositeRedirectAutomatic);XSync(display,False);
            if(x_error)throw std::runtime_error("capture_redirect");
            redirected=true;pixmap=XCompositeNameWindowPixmap(display,window);XSync(display,False);
        }
        if(x_error||!pixmap)throw std::runtime_error("capture_pixmap");
        const int attributes[]={GLX_TEXTURE_TARGET_EXT,GLX_TEXTURE_2D_EXT,GLX_TEXTURE_FORMAT_EXT,GLX_TEXTURE_FORMAT_RGB_EXT,None};
        binding=glXCreatePixmap(display,config,pixmap,attributes);XSync(display,False);
        if(x_error||!binding)throw std::runtime_error("capture_glx_pixmap");
        unsigned inverted=0;glXQueryDrawable(display,binding,GLX_Y_INVERTED_EXT,&inverted);
        y_inverted=inverted!=0;width=wa.width;height=wa.height;
    }
    bool update(){
        XWindowAttributes wa{};x_error=0;
        if(!XGetWindowAttributes(display,window,&wa)||wa.map_state!=IsViewable)return false;
        // Xwayland can replace the window backing buffer without a size change.
        // Name its current pixmap for each capture rather than retaining a snapshot.
        glFinish();attach();
        // Complete our reads before releasing/rebinding the producer's pixmap.
        glFinish();glBindTexture(GL_TEXTURE_2D,texture);
        if(bound)release(display,binding,GLX_FRONT_LEFT_EXT);
        glXWaitX();bind(display,binding,GLX_FRONT_LEFT_EXT,nullptr);bound=true;XSync(display,False);
        return !x_error && glGetError()==GL_NO_ERROR;
    }
    ~TextureCapture(){
        if(display){
            if(context){glFinish();detach();if(texture)glDeleteTextures(1,&texture);}
            if(redirected)XCompositeUnredirectWindow(display,window,CompositeRedirectAutomatic);
            glXMakeContextCurrent(display,None,None,nullptr);
            if(buffer)glXDestroyPbuffer(display,buffer);
            if(context)glXDestroyContext(display,context);
            XCloseDisplay(display);
            watched=nullptr;
        }
    }
};
