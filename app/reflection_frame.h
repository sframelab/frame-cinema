#pragma once
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <string>
#include <vector>
namespace cinema_reflection {
// Private, volatile color transport. The source and presentation identities
// travel with the pixels; no images or provider content are saved to disk.
inline bool wanted(const std::string& ipc,const std::string& session,double now){
    std::ifstream f(ipc+"/ambient-control.txt");std::string magic,owner;double stamp=0;int on=0,reflect=0;
    return ipc.rfind("/run/user/",0)==0 && (f>>magic>>owner>>stamp>>on>>reflect)
        &&magic=="FCAC1"&&owner==session&&on==1&&reflect==1&&now-stamp>=-.01&&now-stamp<2;
}
// Godot's RGBA8 mip chain (each level halves, floored at 1, down to 1x1),
// box-filtered here so the scene thread only uploads: generating mipmaps on
// the render loop cost ~1-2 ms per video frame and delayed the reflection.
inline std::vector<unsigned char> with_mipmaps(const std::vector<unsigned char>& pixels,int w,int h){
    std::vector<unsigned char> chain(pixels);
    size_t level=0;
    while(w>1||h>1){
        const int nw=std::max(1,w/2),nh=std::max(1,h/2);
        const size_t next=chain.size();chain.resize(next+size_t(nw)*nh*4);
        for(int y=0;y<nh;++y)for(int x=0;x<nw;++x)for(int c=0;c<4;++c){
            const int x0=std::min(2*x,w-1),x1=std::min(2*x+1,w-1),y0=std::min(2*y,h-1),y1=std::min(2*y+1,h-1);
            const auto at=[&](int px,int py){return int(chain[level+(size_t(py)*w+px)*4+c]);};
            chain[next+(size_t(y)*nw+x)*4+c]=static_cast<unsigned char>((at(x0,y0)+at(x1,y0)+at(x0,y1)+at(x1,y1)+2)/4);
        }
        level=next;w=nw;h=nh;
    }
    return chain;
}
inline bool publish(const std::string& ipc,const std::string& name,const std::string& session,
    const std::string& source,double now,uint64_t sequence,unsigned long window,int viewport_w,int viewport_h,
    const std::vector<unsigned char>& pixels,int w,int h,float sx=1,float sy=1,float crop=0,double expected=0){
    if(ipc.rfind("/run/user/",0)!=0||pixels.size()!=size_t(w*h*4)||!sequence)return false;
    const auto chain=with_mipmaps(pixels,w,h);
    const auto path=ipc+"/"+name;std::ofstream f(path+".tmp",std::ios::binary);
    f<<std::setprecision(17)<<"{\"magic\":\"FCRF2\",\"session\":\""<<session<<"\",\"source\":\""<<source
     <<"\",\"updated\":"<<now<<",\"expected\":"<<expected<<",\"mipmaps\":true,\"sequence\":"<<sequence<<",\"window\":"<<window
     <<",\"viewport\":["<<viewport_w<<','<<viewport_h<<"],\"size\":["<<w<<','<<h
     <<"],\"uv\":["<<(.5f-.5f*sx)<<','<<(.5f-.5f*sy-crop*sy/(1-2*crop))<<','<<sx<<','<<sy/(1-2*crop)<<"]}\n";
    f.write(reinterpret_cast<const char*>(chain.data()),chain.size());f.close();
    return bool(f)&&std::rename((path+".tmp").c_str(),path.c_str())==0;
}
}
