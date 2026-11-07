#include "stereo/stereo_gl.h"
#include <cassert>
#include <thread>
#include <cstdio>
using namespace cinema_stereo;
int main(){
    XInitThreads();auto* d=XOpenDisplay(nullptr);assert(d);constexpr int W=1920,H=1080;
    auto win=XCreateSimpleWindow(d,DefaultRootWindow(d),0,0,W,H,0,0,0);XMapWindow(d,win);XSync(d,False);
    std::this_thread::sleep_for(std::chrono::milliseconds(150));GC gc=XCreateGC(d,win,0,nullptr);
    auto* image=XCreateImage(d,DefaultVisual(d,DefaultScreen(d)),24,ZPixmap,0,(char*)calloc(W*H,4),W,H,32,0);
    double old_change=0,new_change=0;std::vector<unsigned char> prior[2];
    {
        TextureCapture capture;capture.start(win);StereoGL gpu;
        for(int t=0;t<9;++t){
            for(int y=0;y<H;++y)for(int x=0;x<W;++x){unsigned c=((x+t)/3+y/4)%2?230:25;XPutPixel(image,x,y,(c<<16)|(c<<8)|c);}
            XPutImage(d,win,gc,image,0,0,0,0,W,H);XSync(d,False);assert(capture.update());
            const auto& color=gpu.snapshot(capture);
            for(int pass=0;pass<2;++pass){
                gpu.model_filter=pass==1;
                gpu.queue_sample(color,1,t+1,1);glFinish();auto rgb=gpu.sample();assert(!rgb.empty());
                if(t)for(size_t i=0;i<rgb.size();i+=4){double change=std::abs(int(rgb[i])-int(prior[pass][i]));(pass?new_change:old_change)+=change;}
                prior[pass]=std::move(rgb);
            }
        }
    }
    XDestroyImage(image);XFreeGC(d,gc);XDestroyWindow(d,win);XCloseDisplay(d);
    assert(new_change<old_change*.4);
    std::printf("{\"sampling_pass\":true,\"fine_pattern_input_change_ratio\":%.6f}\n",new_change/old_change);
}
