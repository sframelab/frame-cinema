#include "stereo_gl.h"
#include <cstdio>
#include <thread>
#include <chrono>
using namespace cinema_stereo;
void check(bool ok,const char* reason){if(!ok)throw std::runtime_error(reason);}
int main(){
    XInitThreads();auto* display=XOpenDisplay(nullptr);if(!display)return 2;
    Window window=XCreateSimpleWindow(display,DefaultRootWindow(display),0,0,1280,720,0,0,0);
    XMapWindow(display,window);XSync(display,False);std::this_thread::sleep_for(std::chrono::milliseconds(300));
    GC gc=XCreateGC(display,window,0,nullptr);int code=1;
    try{
        TextureCapture capture;capture.start(window);StereoGL gl;
        XSetForeground(display,gc,0xff0000);XFillRectangle(display,window,gc,0,0,1280,360);
        XSetForeground(display,gc,0x0000ff);XFillRectangle(display,window,gc,0,360,1280,360);XSync(display,False);
        check(capture.update(),"capture");gl.queue_sample(capture,7,9,1);glFinish();auto rgb=gl.sample();
        check(rgb.size()==model_width*model_height*4,"async_readback");
        std::printf("inverted=%d first=%d,%d,%d last=%d,%d,%d\n",capture.y_inverted,rgb[0],rgb[1],rgb[2],rgb[((model_height-1)*model_width)*4],rgb[((model_height-1)*model_width)*4+1],rgb[((model_height-1)*model_width)*4+2]);
        check(rgb[0]>250&&rgb[2]<5&&rgb[((model_height-1)*model_width)*4]<5&&rgb[((model_height-1)*model_width)*4+2]>250,"model_input_top_down");
        check(gl.pending_rev==7&&gl.pending_seq==9,"sample_identity");
        auto texture=gl.render(capture,0);gl.target(texture,2560,720);
        unsigned char top[4]{},bottom[4]{};glReadPixels(16,700,1,1,GL_RGBA,GL_UNSIGNED_BYTE,top);glReadPixels(16,16,1,1,GL_RGBA,GL_UNSIGNED_BYTE,bottom);
        check(top[0]>250&&top[2]<5&&bottom[0]<5&&bottom[2]>250,"display_top_down");
        // Freeze before inference, then change the producer. Both sample and
        // final eye colors must still refer to the retained red/blue frame.
        const auto& frozen=gl.snapshot(capture);
        check(std::abs(gl.sx/gl.sy-(1280.f/720)/(float(gl.mw)/gl.mh))<.0001,"preserved_aspect");
        XSetForeground(display,gc,0x00ff00);XFillRectangle(display,window,gc,0,0,1280,720);XSync(display,False);
        check(capture.update(),"changed_producer");
        gl.queue_sample(frozen,8,10,2);glFinish();auto retained=gl.sample();
        check(retained[0]>250&&retained[1]<5,"immutable_inference_input");
        gl.upload_depth(std::vector<float>(gl.mw*gl.mh,.5f));gl.refine();
        texture=gl.render(frozen,0,true);gl.target(texture,2560,720);
        glReadPixels(16,700,1,1,GL_RGBA,GL_UNSIGNED_BYTE,top);
        glReadPixels(16,16,1,1,GL_RGBA,GL_UNSIGNED_BYTE,bottom);
        check(top[0]>250&&top[1]<5&&bottom[2]>250,"immutable_pair_after_producer_changes");
        // Color detail must not manufacture relief when the model says flat.
        // This is also the negative control for text/texture-guided refinement.
        gl.target(gl.refined,gl.rw,gl.rh);
        std::vector<float> flat_pixels(gl.rw*gl.rh);
        glReadPixels(0,0,gl.rw,gl.rh,GL_RED,GL_FLOAT,flat_pixels.data());
        for(float d:flat_pixels)check(std::abs(d-.5f)<.00001f,"color_texture_does_not_invent_depth");
        gl.sx=1;gl.sy=1;gl.picture_crop=0;
        XSetForeground(display,gc,0);XFillRectangle(display,window,gc,0,0,1280,720);
        XSetForeground(display,gc,0xffffff);XFillRectangle(display,window,gc,639,0,3,720);XSync(display,False);check(capture.update(),"stripe_capture");
        std::vector<unsigned char> row(2560*4);double centers[3][2]{};
        for(int z=0;z<3;++z){
            gl.upload_depth(std::vector<float>(model_width*model_height,z*.5f));texture=gl.render(capture,.018);gl.target(texture,2560,720);glReadPixels(0,360,2560,1,GL_RGBA,GL_UNSIGNED_BYTE,row.data());
            for(int eye=0;eye<2;++eye){double sum=0,weighted=0;for(int x=0;x<1280;++x){double v=row[(eye*1280+x)*4];sum+=v;weighted+=v*x;}check(sum>200,"stripe_missing");centers[z][eye]=weighted/sum;}
        }
        check(std::abs(centers[1][0]-640)<1&&std::abs(centers[1][1]-640)<1,"neutral_identity");
        check(centers[2][0]>centers[2][1]+15,"near_parallel_eye_order");
        check(centers[0][0]<centers[0][1]-15,"far_parallel_eye_order");
        // A smooth ground-depth gradient must not snap into a stack of planes.
        std::vector<float> gradient(model_width*model_height);
        for(int y=0;y<model_height;++y)for(int x=0;x<model_width;++x)gradient[y*model_width+x]=float(y)/(model_height-1);
        gl.upload_depth(gradient);texture=gl.render(capture,.018);gl.target(texture,2560,720);
        double maximum_gradient_error=0,maximum_gradient_step=0,prior=0;
        for(int y=72;y<=648;y+=12){
            glReadPixels(0,y,1280,1,GL_RGBA,GL_UNSIGNED_BYTE,row.data());double sum=0,weighted=0;
            for(int x=0;x<1280;++x){double v=row[x*4];sum+=v;weighted+=v*x;}
            check(sum>200,"gradient_stripe_missing");double center=weighted/sum;
            double d=1.-((y+.5)/720.*model_height-.5)/(model_height-1);
            maximum_gradient_error=std::max(maximum_gradient_error,std::abs(center-(640.+.018*1280*(d-.5))));
            if(y>72)maximum_gradient_step=std::max(maximum_gradient_step,std::abs(center-prior));prior=center;
        }
        std::printf("gradient_max_error=%.4f gradient_max_step=%.4f\n",maximum_gradient_error,maximum_gradient_step);
        check(maximum_gradient_error<.15&&maximum_gradient_step<.55,"continuous_depth_gradient");
        check(glGetError()==GL_NO_ERROR,"gl_error");
        std::printf("{\"pass\":true,\"top_down\":true,\"neutral\":[%.2f,%.2f],\"near\":[%.2f,%.2f],\"far\":[%.2f,%.2f]}\n",centers[1][0],centers[1][1],centers[2][0],centers[2][1],centers[0][0],centers[0][1]);code=0;
    }catch(const std::exception& e){std::fprintf(stderr,"error=%s\n",e.what());}
    XFreeGC(display,gc);XDestroyWindow(display,window);XCloseDisplay(display);return code;
}
