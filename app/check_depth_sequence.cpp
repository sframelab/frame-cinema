#include "stereo/stereo_depth.h"
#include <fstream>
#include <cstdio>
#include <cassert>
using namespace cinema_stereo;
struct OriginalScale {
    float lo=0,hi=1;bool first=true;
    void apply(std::vector<float>& v){
        auto sorted=v;std::sort(sorted.begin(),sorted.end());float a=sorted[v.size()/50],b=sorted[v.size()*49/50];
        float alpha=first?1:float(1-std::exp(-(1./30)/.35));lo+=alpha*(a-lo);hi+=alpha*(b-hi);first=false;
        for(float& x:v)x=std::clamp((x-lo)/(hi-lo),0.f,1.f);
    }
};
int main(int argc,char** argv){
    assert(argc==3);std::ifstream file(argv[1],std::ios::binary);assert(file);uint32_t header[4]{};file.read((char*)header,sizeof(header));assert(file);
    int w=header[0],h=header[1],count=header[2],pan=header[3];assert(w==384&&h==224&&count>=16&&count<=120);
    ncnn::create_gpu_instance();ncnn::Net net;net.opt.use_vulkan_compute=true;net.opt.num_threads=2;net.opt.use_fp16_arithmetic=false;
    assert(!net.load_param((std::string(argv[2])+"/zipdepth.ncnn.param").c_str()));assert(!net.load_model((std::string(argv[2])+"/zipdepth.ncnn.bin").c_str()));
    OriginalScale original;DepthScale current_scale;DepthTemporal temporal;std::vector<float> old_previous,new_previous;
    double old_variation=0,new_variation=0;float last_range=0,old_range=0;std::vector<double> costs;
    for(int t=0;t<count;++t){
        std::vector<unsigned char> rgb(w*h*4);file.read((char*)rgb.data(),rgb.size());assert(file);
        ncnn::Mat input(w,h,3);for(int c=0;c<3;++c){float* p=input.channel(c);for(int i=0;i<w*h;++i)p[i]=rgb[i*4+c]/255.f;}
        auto ex=net.create_extractor();ncnn::Mat map;assert(!ex.input("in0",input)&&!ex.extract("out0",map));assert(map.total()==size_t(w*h));
        std::vector<float> before((float*)map,(float*)map+w*h),after=before;original.apply(before);
        auto start=std::chrono::steady_clock::now();current_scale.normalize(after,1,100+t/30.,w,h);temporal.apply(after,rgb,w,h,1,100+t/30.);
        if(t>4)costs.push_back(std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count());
        if(t>5)for(int y=20;y<h-20;++y)for(int x=40+pan*t;x<w-20;++x){int i=y*w+x,p=i-pan;old_variation+=std::abs(before[i]-old_previous[p]);new_variation+=std::abs(after[i]-new_previous[p]);}
        auto a=std::minmax_element(after.begin(),after.end()),b=std::minmax_element(before.begin(),before.end());last_range=*a.second-*a.first;old_range=*b.second-*b.first;
        old_previous=before;new_previous=after;
    }
    std::sort(costs.begin(),costs.end());
    std::printf("{\"inference_sequence_pass\":true,\"motion_pixels_per_frame\":%d,\"temporal_change_ratio\":%.6f,\"depth_range_ratio\":%.6f,\"postprocess_median_ms\":%.3f,\"postprocess_p95_ms\":%.3f}\n",pan,new_variation/old_variation,last_range/old_range,costs[costs.size()/2],costs[size_t(costs.size()*.95)]);
    assert(new_variation<old_variation*.85&&last_range>old_range*.65);
}
