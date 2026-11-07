// Offscreen end-to-end GPU timing alongside the existing XR scene. Generated
// test window only; this is not a browser decoder or optical delivery test.
#include "stereo_gl.h"
#include <net.h>
#include <gpu.h>
#include <chrono>
#include <thread>
#include <fstream>
#include <cstdio>
using namespace cinema_stereo;
using Clock=std::chrono::steady_clock;
double elapsed(Clock::time_point from){return std::chrono::duration<double,std::milli>(Clock::now()-from).count();}
int main(int argc,char** argv){
    if(argc!=2)return 2;XInitThreads();auto* display=XOpenDisplay(nullptr);if(!display)return 3;
    Window window=XCreateSimpleWindow(display,DefaultRootWindow(display),0,0,1920,1080,0,0,0);
    XMapWindow(display,window);XSync(display,False);std::this_thread::sleep_for(std::chrono::milliseconds(200));
    GC gc=XCreateGC(display,window,0,nullptr);int code=1;
    ncnn::create_gpu_instance();
    try{
        std::string root=argv[1];ncnn::Net net;net.opt.use_vulkan_compute=true;net.opt.num_threads=2;net.opt.use_fp16_arithmetic=false;
        if(net.load_param((root+"/zipdepth.ncnn.param").c_str())||net.load_model((root+"/zipdepth.ncnn.bin").c_str()))throw std::runtime_error("model_load");
        std::vector<float> photo(model_width*model_height*3);std::ifstream f(root+"/fixture-rgb.f32",std::ios::binary);f.read((char*)photo.data(),photo.size()*4);if(!f)throw std::runtime_error("input_fixture");
        auto* bytes=(char*)std::calloc(1920*1080,4);if(!bytes)throw std::bad_alloc();
        XImage* image=XCreateImage(display,DefaultVisual(display,DefaultScreen(display)),24,ZPixmap,0,bytes,1920,1080,32,0);
        for(int y=0;y<1080;++y)for(int x=0;x<1920;++x){int i=(y*model_height/1080)*model_width+x*model_width/1920;unsigned r=photo[i]*255,g=photo[model_width*model_height+i]*255,b=photo[2*model_width*model_height+i]*255;XPutPixel(image,x,y,(r<<16)|(g<<8)|b);}
        TextureCapture capture;capture.start(window);StereoGL gl;std::vector<double> times,inference,fixture,core,warps,captures;
        for(int frame=0;frame<65;++frame){
            auto start=Clock::now();XPutImage(display,window,gc,image,0,0,0,0,1920,1080);XSync(display,False);
            double fixture_ms=elapsed(start);auto core_start=Clock::now();
            if(!capture.update())throw std::runtime_error("capture");
            gl.queue_sample(capture,1,frame+1,1);glFinish();auto rgba=gl.sample();if(rgba.size()!=model_width*model_height*4)throw std::runtime_error("readback");
            double capture_ms=elapsed(core_start);ncnn::Mat input(model_width,model_height,3);
            for(int c=0;c<3;++c){float* p=input.channel(c);for(int i=0;i<model_width*model_height;++i)p[i]=rgba[i*4+c]/255.f;}
            auto begin=Clock::now();auto ex=net.create_extractor();ncnn::Mat output;
            if(ex.input("in0",input)||ex.extract("out0",output)||output.total()!=size_t(model_width*model_height))throw std::runtime_error("inference");double infer_ms=elapsed(begin);
            std::vector<float> values((float*)output,(float*)output+model_width*model_height),sorted=values;
            std::sort(sorted.begin(),sorted.end());float lo=sorted[sorted.size()/50],hi=sorted[sorted.size()*49/50];
            for(auto& v:values)v=hi-lo>1e-5?std::clamp((v-lo)/(hi-lo),0.f,1.f):.5f;
            auto warp_start=Clock::now();gl.upload_depth(values);gl.render(capture,.018);glFinish();
            if(frame>=5){times.push_back(elapsed(start));inference.push_back(infer_ms);fixture.push_back(fixture_ms);core.push_back(elapsed(core_start));warps.push_back(elapsed(warp_start));captures.push_back(capture_ms);}
            std::this_thread::sleep_until(start+std::chrono::microseconds(33333));
        }
        XDestroyImage(image);std::sort(times.begin(),times.end());std::sort(inference.begin(),inference.end());
        auto percentile=[&](double q){return times[std::min(times.size()-1,size_t(q*times.size()))];};
        auto within=[&](double ms){return std::count_if(times.begin(),times.end(),[&](double t){return t<=ms;});};
        std::printf("{\"pipeline_pass\":true,\"depth_width\":%d,\"depth_height\":%d,\"video_width\":1920,\"video_height\":1080,\"samples\":%zu,\"median_ms\":%.3f,\"p95_ms\":%.3f,\"maximum_ms\":%.3f,\"infer_median_ms\":%.3f,\"within_24fps\":%ld,\"within_30fps\":%ld,\"within_60fps\":%ld}\n",model_width,model_height,times.size(),percentile(.5),percentile(.95),times.back(),inference[inference.size()/2],within(1000./24),within(1000./30),within(1000./60));code=0;
        for(auto* v:{&fixture,&core,&warps,&captures})std::sort(v->begin(),v->end());
        std::printf("{\"pipeline_stages\":true,\"depth_width\":%d,\"fixture_upload_median_ms\":%.3f,\"capture_and_sample_median_ms\":%.3f,\"warp_median_ms\":%.3f,\"core_median_ms\":%.3f,\"core_p95_ms\":%.3f,\"core_within_30fps\":%ld,\"core_within_24fps\":%ld}\n",model_width,fixture[30],captures[30],warps[30],core[30],core[57],std::count_if(core.begin(),core.end(),[](double t){return t<=1000./30;}),std::count_if(core.begin(),core.end(),[](double t){return t<=1000./24;}));
    }catch(const std::exception& e){std::fprintf(stderr,"pipeline_error=%s\n",e.what());}
    ncnn::destroy_gpu_instance();XFreeGC(display,gc);XDestroyWindow(display,window);XCloseDisplay(display);return code;
}
