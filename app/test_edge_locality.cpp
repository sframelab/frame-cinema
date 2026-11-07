#include "ambient_palette.h"
#include <iostream>
#include <stdexcept>
using namespace cinema_ambient;
int main(){
    unsigned checks=0;
    auto check=[&](bool ok,const char* label){++checks;std::cout<<(ok?"PASS ":"FAIL ")<<label<<std::endl;if(!ok)throw std::runtime_error(label);};
    constexpr int w=400,h=200;
    std::vector<RGB> pixels(w*h,{0,0,1});
    for(int y=0;y<h;++y)for(int x=0;x<w;++x)
        if(x<20||x>=w-20||y<10||y>=h-10)pixels[y*w+x]={1,0,0};
    auto p=sample_gradient(pixels,w,h,{0,0,w,h});
    std::cout<<"TOP_MIDDLE red="<<p[32].r<<" blue="<<p[32].b<<std::endl;
    check(std::all_of(p.begin(),p.end(),[](RGB c){return c.r>.999999&&c.g==0&&c.b==0;}),"all four edges reject a contrasting interior beyond 5%");
    std::fill(pixels.begin(),pixels.end(),RGB{});
    for(int y=12;y<h-12;++y)for(int x=24;x<w-24;++x)pixels[y*w+x]={1,1,1};
    p=sample_gradient(pixels,w,h,{0,0,w,h});
    check(std::all_of(p.begin(),p.end(),[](RGB c){return c.r==0&&c.g==0&&c.b==0;}),"bright objects 6% inward cannot light a dark edge");
    std::fill(pixels.begin(),pixels.end(),RGB{});
    Rect active{40,20,320,160};
    for(int y=20;y<180;++y)for(int x=40;x<360;++x)
        pixels[y*w+x]=(x<56||x>=344||y<28||y>=172)?RGB{0,1,0}:RGB{1,0,1};
    ContentTracker tracker;Rect cropped{};for(int i=0;i<3;++i)cropped=tracker.update(pixels,w,h);
    check(cropped.x==active.x&&cropped.y==active.y&&cropped.w==active.w&&cropped.h==active.h,"combined letterbox/pillarbox acquisition retained");
    p=sample_gradient(pixels,w,h,cropped);
    check(std::all_of(p.begin(),p.end(),[](RGB c){return c.g>.999999&&c.r==0&&c.b==0;}),"5% band starts at the detected picture, not the black bars");
    for(auto size:std::array<std::pair<int,int>,3>{{{384,216},{192,108},{95,53}}}){
        const int width=size.first,height=size.second;
        std::vector<RGB> field(width*height,{.02,.04,.08});
        auto result=sample_gradient(field,width,height,{0,0,width,height});
        check(std::all_of(result.begin(),result.end(),[](RGB c){return std::abs(c.r-linear(.02))<1e-9&&std::abs(c.g-linear(.04))<1e-9&&std::abs(c.b-linear(.08))<1e-9;}),"fractional band depths preserve dark uniform RGB without gain");
    }
    std::cout<<"EDGE_LOCALITY_OK "<<checks<<std::endl;
}
