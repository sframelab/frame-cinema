#pragma once
#include "ambient_palette.h"

namespace cinema_picture {
// known permits acquisition; safe_top bounds retention even when a dark scene
// has too little lit area to identify a new cinematic aspect ratio.
struct Analysis { double top=0; bool dark=false; bool known=false; double safe_top=0; };
struct BoundaryBand { int start=0, rows=0; };
inline BoundaryBand boundary_band(Analysis coarse,int source_height,int reduced_height) {
    if(coarse.dark || coarse.safe_top<=0 || coarse.safe_top>.20 || source_height<reduced_height || reduced_height<32)return {};
    const int start=int(std::floor(coarse.safe_top*source_height));
    return {start,std::min(int(std::ceil(3.0*source_height/reduced_height))+2,source_height/5+2-start)};
}
// Read full-width source strips only near the coarse boundaries. Coarse analysis
// still checks the excluded bands; refinement reduces its multi-pixel margin.
template<class Pixel> inline Analysis refine(Analysis coarse,int w,int h,BoundaryBand band,Pixel pixel) {
    if(w<32 || band.start<0 || band.rows<=0 || band.start+band.rows>=h/2)return coarse;
    int first[2]={band.rows,band.rows};
    for(int side=0;side<2;++side)for(int y=0;y<band.rows;++y) {
        bool lit=false;
        for(int x=0;x<w;++x){auto p=pixel(side,x,y);if(std::max({p.r,p.g,p.b})>=.025){lit=true;break;}}
        if(lit){first[side]=y;break;}
    }
    // An unlit strip proves additional clear rows, but cannot identify a new
    // aspect ratio. Retain only the measured safe area, with one source-row
    // guard. This also bounds sparse scenes and asymmetrical caption frames.
    const double safe=std::clamp(double(band.start+std::min(first[0],first[1])-1)/h,0.,.20);
    const bool known=coarse.known && first[0]>0 && first[1]>0 &&
        first[0]<band.rows && first[1]<band.rows && std::abs(first[0]-first[1])<=2;
    return {known?safe:0,false,known,safe};
}
inline Analysis analyze(const std::vector<cinema_ambient::RGB>& pixels,int w,int h) {
    if(w<32 || h<32 || pixels.size()!=size_t(w*h))return {};
    auto lit=[](const auto& p){return std::max({p.r,p.g,p.b})>=.025;};
    int bright=0;for(const auto& p:pixels)bright+=lit(p);
    if(bright==0)return {0,true,false,.20};
    // Every sampled pixel in excluded rows must be dark. The color sampler's
    // 96% rule and subtitle hysteresis are inappropriate for visible cropping.
    auto clear=[&](int y){for(int x=0;x<w;++x)if(lit(pixels[y*w+x]))return false;return true;};
    int top=0,bottom=0;
    while(top<h/5 && clear(top))++top;
    while(bottom<h/5 && clear(h-1-bottom))++bottom;
    // Keep one complete reduced row as a guard against filtering/crop error.
    const double safe=double(std::max(0,std::min(top,bottom)-1))/h;
    const bool known=top>=2 && bottom>=2 && std::abs(top-bottom)<=1 && bright>=w*h*.10;
    return {known?safe:0,false,known,safe};
}
}
