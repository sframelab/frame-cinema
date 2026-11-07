#include "texture_capture.h"
#include <chrono>
#include <cstdio>
#include <thread>
#include <vector>

int main(){
    Display* d=XOpenDisplay(nullptr);if(!d)return 2;
    Window w=XCreateSimpleWindow(d,DefaultRootWindow(d),0,0,1280,720,0,0,0);
    XMapWindow(d,w);XSync(d,False);std::this_thread::sleep_for(std::chrono::milliseconds(300));
    GC gc=XCreateGC(d,w,0,nullptr);int code=1;
    try{
        TextureCapture capture;capture.start(w);
        std::printf("renderer=%s inverted=%d\n",glGetString(GL_RENDERER),capture.y_inverted);
        GLuint fbo;glGenFramebuffers(1,&fbo);
        int changes=0;double total=0;unsigned previous=0;
        for(int i=0;i<32;++i){
            unsigned color=(i%2)?0xff0000:0x00ff00;
            XSetForeground(d,gc,color);XFillRectangle(d,w,gc,0,0,1280,720);XSync(d,False);
            auto begin=std::chrono::steady_clock::now();
            if(!capture.update())throw std::runtime_error("capture_update");
            glBindFramebuffer(GL_FRAMEBUFFER,fbo);
            glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,capture.texture,0);
            if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)throw std::runtime_error("read_fbo");
            unsigned char pixel[4]{};glReadPixels(32,32,1,1,GL_RGBA,GL_UNSIGNED_BYTE,pixel);
            auto value=(unsigned(pixel[0])<<16)|(unsigned(pixel[1])<<8)|pixel[2];
            if(value!=color){std::printf("mismatch expected=%06x actual=%06x\n",color,value);throw std::runtime_error("pixel_mismatch");}
            if(i&&value!=previous)++changes;previous=value;
            total+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count();
            glBindFramebuffer(GL_FRAMEBUFFER,0);
        }
        glDeleteFramebuffers(1,&fbo);
        std::printf("{\"capture_pass\":true,\"changes\":%d,\"mean_ms\":%.3f,\"width\":%d,\"height\":%d}\n",changes,total/32,capture.width,capture.height);code=0;
    }catch(const std::exception& e){std::printf("error=%s\n",e.what());}
    XFreeGC(d,gc);XDestroyWindow(d,w);XCloseDisplay(d);return code;
}
