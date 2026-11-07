#include <net.h>
#include <gpu.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <vector>

int main(int argc,char** argv){
    if(argc<3)return 2;
    const std::string root=argv[1];const bool gpu=std::atoi(argv[2])!=0;
    const int w=argc>3?std::atoi(argv[3]):512,h=argc>4?std::atoi(argv[4]):288;
    ncnn::create_gpu_instance();
    int result=1;
    {
        ncnn::Net net;net.opt.use_vulkan_compute=gpu;net.opt.num_threads=2;
        net.opt.use_fp16_arithmetic=false;
        if(gpu&&ncnn::get_gpu_count()<1)return 3;
        if(net.load_param((root+"/zipdepth.ncnn.param").c_str()) || net.load_model((root+"/zipdepth.ncnn.bin").c_str()))return 4;
        ncnn::Mat input(w,h,3);std::ifstream f(root+"/fixture-rgb.f32",std::ios::binary);
        for(int c=0;c<3;++c)f.read((char*)(float*)input.channel(c),w*h*4);
        if(!f)return 5;
        std::vector<float> reference(w*h);std::ifstream r(root+"/fixture-depth.f32",std::ios::binary);
        r.read((char*)reference.data(),reference.size()*4);if(!r)return 6;
        std::vector<double> times;double maximum=0,mean=0;bool finite=true;
        for(int i=0;i<25;++i){
            auto start=std::chrono::steady_clock::now();auto ex=net.create_extractor();
            ncnn::Mat depth;if(ex.input("in0",input)||ex.extract("out0",depth))return 7;
            double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
            if(i>=5)times.push_back(ms);
            if(i==24){
                if(depth.total()!=reference.size())return 8;
                for(size_t j=0;j<reference.size();++j){double error=std::abs(((float*)depth)[j]-reference[j]);finite=finite&&std::isfinite(error);maximum=std::max(maximum,error);mean+=error;}
                mean/=reference.size();
            }
        }
        std::sort(times.begin(),times.end());
        const auto limits=std::minmax_element(reference.begin(),reference.end());
        const double rel=maximum/std::max(.0001f,*limits.second-*limits.first);
        result=finite&&rel<.025?0:9;
        printf("{\"gpu\":%s,\"width\":%d,\"height\":%d,\"median_ms\":%.3f,\"p95_ms\":%.3f,\"max_error\":%.8f,\"mean_error\":%.8f,\"relative_max\":%.6f,\"pass\":%s}\n",gpu?"true":"false",w,h,times[times.size()/2],times[18],maximum,mean,rel,result?"false":"true");
    }
    ncnn::destroy_gpu_instance();return result;
}
