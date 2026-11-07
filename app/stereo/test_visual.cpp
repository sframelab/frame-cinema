// Visual QA of the same unified path on an upstream reference photo.
#include "stereo_gl.h"
#include "stereo_depth.h"
#include <fstream>
#include <thread>
#include <cstdio>
using namespace cinema_stereo;
void save(GLuint texture,StereoGL& gpu,int w,int h,const std::string& path,bool scalar=false){
    gpu.target(texture,w,h);std::vector<unsigned char> pixels(w*h*4);
    if(scalar){std::vector<float> values(w*h);glReadPixels(0,0,w,h,GL_RED,GL_FLOAT,values.data());for(int i=0;i<w*h;++i)for(int c=0;c<3;++c)pixels[i*4+c]=std::clamp(values[i]*255.f,0.f,255.f);}
    else glReadPixels(0,0,w,h,GL_RGBA,GL_UNSIGNED_BYTE,pixels.data());
    std::ofstream out(path,std::ios::binary);out<<"P6\n"<<w<<' '<<h<<"\n255\n";
    for(int y=h-1;y>=0;--y)for(int x=0;x<w;++x)out.write((char*)pixels.data()+(y*w+x)*4,3);
}
int main(int argc,char** argv){
    if(argc!=4)return 2;XInitThreads();std::ifstream in(argv[1],std::ios::binary);std::string magic;int w,h,max;
    in>>magic>>w>>h>>max;in.get();if(magic!="P6"||w<1||h<1||w>3840||h>2160||max!=255)return 3;
    std::vector<unsigned char> rgb(w*h*3);in.read((char*)rgb.data(),rgb.size());if(!in)return 4;
    auto* d=XOpenDisplay(nullptr);if(!d)return 5;auto win=XCreateSimpleWindow(d,DefaultRootWindow(d),0,0,w,h,0,0,0);
    XMapWindow(d,win);XSync(d,False);std::this_thread::sleep_for(std::chrono::milliseconds(200));GC gc=XCreateGC(d,win,0,nullptr);
    auto* image=XCreateImage(d,DefaultVisual(d,DefaultScreen(d)),24,ZPixmap,0,(char*)calloc(w*h,4),w,h,32,0);
    for(int y=0;y<h;++y)for(int x=0;x<w;++x){auto* p=&rgb[(y*w+x)*3];XPutPixel(image,x,y,(p[0]<<16)|(p[1]<<8)|p[2]);}
    XPutImage(d,win,gc,image,0,0,0,0,w,h);XSync(d,False);
    int code=1;
    try{
        TextureCapture capture;capture.start(win);StereoGL gpu;DepthEstimator model(argv[2]);
        if(!capture.update())throw std::runtime_error("capture");const auto& color=gpu.snapshot(capture);
        gpu.queue_sample(color,1,1,wall());glFinish();auto sample=gpu.sample();
        auto depth=model.infer(sample,1,1,wall(),gpu.sx,gpu.sy);gpu.upload_depth(depth.values);gpu.refine();
        std::string dir=argv[3];save(gpu.refined,gpu,gpu.rw,gpu.rh,dir+"/depth.ppm",true);
        auto eyes=gpu.render(color,.018,true);save(eyes,gpu,2*w,h,dir+"/stereo.ppm");
        save(color.texture,gpu,w,h,dir+"/color.ppm");
        std::printf("visual pass: %dx%d source, %dx%d depth, aspect scales %.5f %.5f\n",w,h,gpu.mw,gpu.mh,gpu.sx,gpu.sy);code=0;
    }catch(const std::exception& e){std::fprintf(stderr,"visual_error=%s\n",e.what());}
    XDestroyImage(image);XFreeGC(d,gc);XDestroyWindow(d,win);XCloseDisplay(d);return code;
}
