#include "stereo/depth_temporal.h"
#include <cassert>
#include <chrono>
#include <cstdio>
using namespace cinema_stereo;
constexpr int W=384,H=224;
std::vector<unsigned char> picture(int shift=0,bool invert=false){
    std::vector<unsigned char> a(W*H*4);
    for(int y=0;y<H;++y)for(int x=0;x<W;++x){
        float u=x-shift;float l=.45f+.14f*std::sin(u*.067f)+.12f*std::cos(y*.111f)+.08f*std::sin(u*.27f+y*.09f);
        bool near=u>110&&u<190&&y>40&&y<180;
        for(int c=0;c<3;++c){float v=std::clamp(l+(near?(c==0?.3f:-.15f):0.f),.0f,1.f);a[(y*W+x)*4+c]=int((invert?1-v:v)*255);}
        a[(y*W+x)*4+3]=255;
    }
    return a;
}
std::vector<float> geometry(int shift=0){
    std::vector<float> d(W*H);
    for(int y=0;y<H;++y)for(int x=0;x<W;++x){float u=x-shift;d[y*W+x]=u>110&&u<190&&y>40&&y<180?.8f:.2f+.18f*x/W+.05f*y/H;}
    return d;
}
int main(){
    DepthTemporal filter;auto color=picture();auto truth=geometry();std::vector<float> last_raw,last_filtered;
    double raw_wobble=0,filtered_wobble=0;std::vector<double> costs;
    for(int t=0;t<28;++t){
        auto raw=truth;
        for(int y=0;y<H;++y)for(int x=0;x<W;++x){int i=y*W+x;raw[i]=raw[i]*(1+.04f*std::sin(t*1.3f))+.018f*std::cos(t*.9f)+.022f*std::sin(x*.047f+y*.071f+t*1.9f);}
        auto result=raw;auto begin=std::chrono::steady_clock::now();filter.apply(result,color,W,H,1,10+t/30.);
        costs.push_back(std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count());
        if(t>5)for(int y=16;y<H-16;++y)for(int x=16;x<W-16;++x){int i=y*W+x;raw_wobble+=std::abs(raw[i]-last_raw[i]);filtered_wobble+=std::abs(result[i]-last_filtered[i]);}
        last_raw=raw;last_filtered=result;
    }
    assert(filtered_wobble<raw_wobble*.65);
    assert(filter.stats.history_fraction>.5f);
    // Current color/depth move together; revealed background must not retain
    // the foreground silhouette. No stationary-pixel temporal averaging.
    DepthTemporal moving;double edge_error=0;
    for(int t=0;t<9;++t){
        auto rgb=picture(4*t);auto expected=geometry(4*t),result=expected;
        moving.apply(result,rgb,W,H,2,20+t/30.);
        for(int y=48;y<172;++y)for(int x=108+4*t;x<114+4*t;++x)edge_error=std::max(edge_error,double(std::abs(result[y*W+x]-expected[y*W+x])));
    }
    assert(edge_error<.055);
    auto cut=truth;for(auto& v:cut)v=1-v;auto expected=cut;
    moving.apply(cut,picture(0,true),W,H,3,21);assert(cut==expected&&moving.stats.reset);
    auto flat=std::vector<float>(W*H,.5f);moving.apply(flat,color,W,H,3,21+1./30);for(float v:flat)assert(v==.5f);
    auto gap=truth;moving.apply(gap,color,W,H,3,22);assert(gap==truth&&moving.stats.reset);
    auto rewind=truth;moving.apply(rewind,color,W,H,3,21);assert(rewind==truth&&moving.stats.reset);
    std::sort(costs.begin()+1,costs.end());
    std::printf("{\"temporal_pass\":true,\"static_wobble_ratio\":%.6f,\"moving_edge_max_error\":%.6f,\"median_ms\":%.3f,\"p95_ms\":%.3f}\n",filtered_wobble/raw_wobble,edge_error,costs[14],costs[26]);
}
