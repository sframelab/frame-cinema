#pragma once
#include "stereo_config.h"
#include "depth_temporal.h"
#include <net.h>
#include <gpu.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <mutex>
#include <thread>
#include <vector>
#include <cmath>
#include <stdexcept>
namespace cinema_stereo {
inline double wall(){return std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();}
struct DepthFrame {std::vector<float> values;uint64_t revision=0,sequence=0;double captured=0,cost_ms=0,post_ms=0;};
inline double frame_difference(const std::vector<unsigned char>& a,const std::vector<unsigned char>& b){
    if(a.size()!=b.size()||a.empty())return 0;
    double sum=0;size_t samples=0;
    for(size_t i=0;i+2<a.size();i+=64){for(int c=0;c<3;++c)sum+=std::abs(int(a[i+c])-int(b[i+c]));++samples;}
    return samples?sum/(samples*3.*255.):0;
}
// Establish the current frame's robust range. Temporal affine alignment and
// correspondence validation happen afterward in DepthTemporal.
struct DepthScale {
    uint64_t revision=0;double then=0;float low=0,high=1;
    void normalize(std::vector<float>& values,uint64_t rev,double stamp,int w,int h,float sx=1,float sy=1){
        // Global percentiles need a representative range, not a full-resolution
        // sort. Validate every value, then average 2x2 cells before selection;
        // area sampling avoids making the calibration sensitive to fine grids.
        for(float v:values)if(!std::isfinite(v))throw std::runtime_error("nonfinite_depth");
        std::vector<float> range;range.reserve(values.size()/4);
        for(int y=0;y<h;y+=2)for(int x=0;x<w;x+=2){
            float sum=0;int count=0;
            for(int j=y;j<std::min(y+2,h);++j)for(int i=x;i<std::min(x+2,w);++i){
                if(std::abs((i+.5f)/w-.5f)<=sx*.5f&&std::abs((j+.5f)/h-.5f)<=sy*.5f){sum+=values[j*w+i];++count;}
            }
            if(count)range.push_back(sum/count);
        }
        if(range.empty())throw std::runtime_error("depth_region");
        auto a=range.begin()+range.size()/50,b=range.begin()+range.size()*49/50;
        std::nth_element(range.begin(),a,range.end());float lo=*a;
        std::nth_element(range.begin(),b,range.end());float hi=*b;
        // No measurable current depth range: use the screen plane immediately.
        // A previous shot's range must not turn a flat estimate into a near slab.
        if(hi-lo<1e-5f){std::fill(values.begin(),values.end(),.5f);then=0;revision=rev;return;}
        low=lo;high=hi;
        revision=rev;then=stamp;
        for(auto& v:values)v=high-low<1e-5f?.5f:std::clamp((v-low)/(high-low),0.f,1.f);
    }
};
// Only the dedicated stereo worker calls inference. Color remains immutable
// until the corresponding map has produced both eye images.
class DepthEstimator {
    ncnn::Net net;DepthScale scale;DepthTemporal temporal;
public:
    int width,height;
    DepthEstimator(const std::string& directory,int w=model_width,int h=model_height):width(w),height(h){
        static std::once_flag initialized;
        std::call_once(initialized,[]{ncnn::create_gpu_instance();});
        if(ncnn::get_gpu_count()<1)throw std::runtime_error("no_gpu");
        net.opt.use_vulkan_compute=true;net.opt.num_threads=2;net.opt.use_fp16_arithmetic=false;
        net.opt.openmp_blocktime=0;
        if(net.load_param((directory+"/zipdepth.ncnn.param").c_str())||net.load_model((directory+"/zipdepth.ncnn.bin").c_str()))throw std::runtime_error("model_load");
    }
    DepthFrame infer(const std::vector<unsigned char>& rgba,uint64_t rev,uint64_t seq,double captured,float sx=1,float sy=1,int strength=1){
        if(rgba.size()!=size_t(width*height*4))throw std::runtime_error("model_input_size");
        ncnn::Mat input(width,height,3);
        for(int c=0;c<3;++c){float* channel=input.channel(c);for(int i=0;i<width*height;++i)channel[i]=rgba[4*i+c]/255.f;}
        auto begin=std::chrono::steady_clock::now();ncnn::Mat result;auto ex=net.create_extractor();
        if(ex.input("in0",input)||ex.extract("out0",result)||result.total()!=size_t(width*height))throw std::runtime_error("model_inference");
        DepthFrame frame;frame.revision=rev;frame.sequence=seq;frame.captured=captured;
        frame.cost_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count();
        auto post_begin=std::chrono::steady_clock::now();
        frame.values.assign((float*)result,(float*)result+width*height);
        scale.normalize(frame.values,rev,captured,width,height,sx,sy);
        temporal.apply(frame.values,rgba,width,height,rev,captured,sx,sy,strength);
        frame.post_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-post_begin).count();
        return frame;
    }
};
}
