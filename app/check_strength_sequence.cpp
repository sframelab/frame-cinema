#include "stereo/stereo_depth.h"
#include <fstream>
#include <cstdio>
#include <cassert>
using namespace cinema_stereo;
int main(int argc,char** argv){
    assert(argc==3);std::ifstream file(argv[1],std::ios::binary);assert(file);
    uint32_t header[4]{};file.read((char*)header,sizeof(header));assert(file);
    int w=header[0],h=header[1],count=header[2],pan=header[3];assert(w==384&&h==224&&count>=16&&count<=120);
    ncnn::create_gpu_instance();ncnn::Net net;net.opt.use_vulkan_compute=true;net.opt.num_threads=2;net.opt.use_fp16_arithmetic=false;net.opt.openmp_blocktime=0;
    assert(!net.load_param((std::string(argv[2])+"/zipdepth.ncnn.param").c_str()));assert(!net.load_model((std::string(argv[2])+"/zipdepth.ncnn.bin").c_str()));
    DepthScale scale;DepthTemporal temporal[3];std::vector<float> previous[3];double variation[3]{};float range[3]{};
    for(int t=0;t<count;++t){
        std::vector<unsigned char> rgb(w*h*4);file.read((char*)rgb.data(),rgb.size());assert(file);
        ncnn::Mat input(w,h,3);for(int c=0;c<3;++c){float* p=input.channel(c);for(int i=0;i<w*h;++i)p[i]=rgb[i*4+c]/255.f;}
        auto ex=net.create_extractor();ncnn::Mat map;assert(!ex.input("in0",input)&&!ex.extract("out0",map));assert(map.total()==size_t(w*h));
        std::vector<float> raw((float*)map,(float*)map+w*h);scale.normalize(raw,1,100+t/30.,w,h);
        for(int mode=1;mode<=3;++mode){
            auto v=raw;temporal[mode-1].apply(v,rgb,w,h,1,100+t/30.,1,1,mode);
            if(t>5)for(int y=20;y<h-20;++y)for(int x=40+pan*t;x<w-20;++x){int i=y*w+x,p=i-pan;variation[mode-1]+=std::abs(v[i]-previous[mode-1][p]);}
            auto bounds=std::minmax_element(v.begin(),v.end());range[mode-1]=*bounds.second-*bounds.first;previous[mode-1]=std::move(v);
        }
    }
    printf("{\"mode\":\"actual ZipDepth photo perturbation proxy\",\"pan_pixels_per_frame\":%d,\"medium_variation_ratio\":%.6f,\"strong_variation_ratio\":%.6f,\"medium_range_ratio\":%.6f,\"strong_range_ratio\":%.6f}\n",pan,variation[1]/variation[0],variation[2]/variation[0],range[1]/range[0],range[2]/range[0]);
    assert(variation[1]<variation[0] && variation[2]<variation[0]);
    assert(range[1]>range[0]*.9 && range[2]>range[0]*.9);
}
