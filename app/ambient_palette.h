#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <vector>

namespace cinema_ambient {
struct RGB { double r=0,g=0,b=0; };
using Palette=std::array<RGB,12>;
constexpr int gradient_segments=64;
// Authored edge-local approximation, not a published Hue Sync constant.
constexpr double edge_fraction=.05;
using GradientPalette=std::array<RGB,gradient_segments*4>;
struct Rect { int x=0,y=0,w=0,h=0; };
inline double linear(double v) {return v<=.04045?v/12.92:std::pow((v+.055)/1.055,2.4);}
inline bool black(const RGB& p) {return std::max({p.r,p.g,p.b})<.025;}
inline Rect content(const std::vector<RGB>& p,int w,int h) {
    Rect area{0,0,w,h};if(w<8 || h<8 || p.size()!=size_t(w*h))return {};
    auto dark_row=[&](int y){int count=0;for(int x=0;x<w;++x)count+=black(p[y*w+x]);return count>=w*.96;};
    auto dark_column=[&](int x){int count=0;for(int y=0;y<h;++y)count+=black(p[y*w+x]);return count>=h*.96;};
    int top=0,bottom=0,left=0,right=0;
    while(top<h/4 && dark_row(top))++top;
    while(bottom<h/4 && dark_row(h-1-bottom))++bottom;
    while(left<w/4 && dark_column(left))++left;
    while(right<w/4 && dark_column(w-1-right))++right;
    // Symmetric bars only. Dark scenes or an edge in the picture must not
    // produce an arbitrary crop. The first non-bar row/column must be lit.
    if(top && bottom && std::abs(top-bottom)<=1 && !dark_row(top) && !dark_row(h-1-bottom)) {area.y=top;area.h-=top+bottom;}
    if(left && right && std::abs(left-right)<=1 && !dark_column(left) && !dark_column(w-1-right)) {area.x=left;area.w-=left+right;}
    return area;
}
class ContentTracker {
    struct Axis {int start=0,size=0,pending_start=0,pending_size=0,count=0;};
    Axis horizontal,vertical;int width=0,height=0;
    static void advance(Axis& axis,int start,int size) {
        if(start==axis.start && size==axis.size){axis.count=0;return;}
        if(start!=axis.pending_start || size!=axis.pending_size){axis.pending_start=start;axis.pending_size=size;axis.count=0;}
        if(++axis.count>=3){axis.start=start;axis.size=size;axis.count=0;}
    }
public:
    void reset(){horizontal={};vertical={};width=0;height=0;}
    Rect update(const std::vector<RGB>& pixels,int w,int h) {
        Rect candidate=content(pixels,w,h);
        if(candidate.w==0)return {};
        if(w!=width || h!=height){reset();width=w;height=h;horizontal.size=w;vertical.size=h;}
        auto mostly_dark=[&](int x0,int y0,int x1,int y1,bool rows){
            int dark=0,total=0;
            for(int y=y0;y<y1;++y)for(int x=x0;x<x1;++x){
                const auto& p=pixels[y*w+x];dark+=std::max({p.r,p.g,p.b})<.045;++total;
            }
            if(total==0 || dark<total*.8)return false;
            // A newly exposed picture row/column is not a localized caption.
            // This also releases one-pixel changes in otherwise wide bars.
            for(int line=rows?y0:x0;line<(rows?y1:x1);++line){
                int lit=0,count=0;
                for(int across=rows?x0:y0;across<(rows?x1:y1);++across){
                    const auto& p=pixels[(rows?line:across)*w+(rows?across:line)];
                    lit+=std::max({p.r,p.g,p.b})>=.045;++count;
                }
                if(lit>count*.5)return false;
            }
            return true;
        };
        // Hold proven bars through localized subtitles and near-black noise.
        // A real aspect change invalidates their area coverage, then changes
        // the crop after three samples. Each axis is independent.
        if(candidate.y<=vertical.start && candidate.y+candidate.h>=vertical.start+vertical.size && vertical.start>0 && vertical.start+vertical.size<h
           && mostly_dark(0,0,w,vertical.start,true) && mostly_dark(0,vertical.start+vertical.size,w,h,true)) {
            candidate.y=vertical.start;candidate.h=vertical.size;
        }
        if(candidate.x<=horizontal.start && candidate.x+candidate.w>=horizontal.start+horizontal.size && horizontal.start>0 && horizontal.start+horizontal.size<w
           && mostly_dark(0,0,horizontal.start,h,false) && mostly_dark(horizontal.start+horizontal.size,0,w,h,false)) {
            candidate.x=horizontal.start;candidate.w=horizontal.size;
        }
        advance(horizontal,candidate.x,candidate.w);advance(vertical,candidate.y,candidate.h);
        return {horizontal.start,vertical.start,horizontal.size,vertical.size};
    }
};
template<int Segments> inline std::array<RGB,Segments*4> sample_regions(const std::vector<RGB>& pixels,int w,int h,Rect area) {
    std::array<RGB,Segments*4> result{};if(area.w<1 || area.h<1 || area.x<0 || area.y<0 || area.x>w-area.w || area.y>h-area.h || pixels.size()!=size_t(w*h))return result;
    // Extend the actual picture edges. Interior subjects must not recolor an
    // unrelated border. Bar exclusion happens before choosing the shallow band.
    const double depth_x=std::max(1.0,area.w*edge_fraction),depth_y=std::max(1.0,area.h*edge_fraction);
    const int dx=std::min(area.w,int(std::ceil(depth_x))),dy=std::min(area.h,int(std::ceil(depth_y)));
    for(int zone=0;zone<Segments*4;++zone) {
        Rect r=area;const int segment=zone%Segments,side=zone/Segments;
        const bool horizontal=side%2==0;
        const int forward=side<2?segment:Segments-1-segment;
        const double low=forward*double(horizontal?area.w:area.h)/Segments;
        const double high=(forward+1)*double(horizontal?area.w:area.h)/Segments;
        if(horizontal){r.x+=int(std::floor(low));r.w=int(std::ceil(high))-int(std::floor(low));r.h=dy;if(side==2)r.y+=area.h-dy;}
        else {r.y+=int(std::floor(low));r.h=int(std::ceil(high))-int(std::floor(low));r.w=dx;if(side==1)r.x+=area.w-dx;}
        double weight_sum=0,peak_sum=0,peak_square_sum=0,chroma_sum=0;
        RGB average{},chromatic{};
        for(int y=r.y;y<r.y+r.h;++y)for(int x=r.x;x<r.x+r.w;++x) {
            const double inward=side==0?y-area.y:side==1?area.x+area.w-1-x:side==2?area.y+area.h-1-y:x-area.x;
            const double depth=horizontal?depth_y:depth_x;
            const double end=std::min(inward+1.0,depth);
            // Integrate the taper over fractional inward coverage as well:
            // the last thumbnail pixel must not expand a 5% region.
            const double inward_weight=std::max(0.0,(end-inward)*(1.0-.325*(inward+end)/depth));
            // Fractional overlap avoids empty regions and unstable rounding
            // even when a narrow active picture has fewer pixels than zones.
            const int along=horizontal?x-area.x:y-area.y;
            const double coverage=std::max(0.0,std::min(high,double(along+1))-std::max(low,double(along)));
            const double weight=inward_weight*coverage;
            const auto& encoded=pixels[y*w+x];
            const RGB p{linear(encoded.r),linear(encoded.g),linear(encoded.b)};
            const double peak=std::max({p.r,p.g,p.b});
            const double saturation=peak>1e-9?(peak-std::min({p.r,p.g,p.b}))/peak:0;
            average.r+=p.r*weight;average.g+=p.g*weight;average.b+=p.b*weight;
            chromatic.r+=p.r*weight*saturation;chromatic.g+=p.g*weight*saturation;chromatic.b+=p.b*weight*saturation;
            peak_sum+=peak*weight;peak_square_sum+=peak*peak*weight;chroma_sum+=peak*saturation*weight;weight_sum+=weight;
        }
        if(peak_sum<=1e-9)continue;
        // Continuous color confidence reduces white-caption dilution only when
        // a substantial colored area exists. Neutral scenes stay neutral; no
        // hard winning hue bin can jump as two colors exchange dominance.
        const double t=std::clamp((chroma_sum/peak_sum-.15)/.45,0.0,1.0);
        const double neutral=1-.75*t*t*(3-2*t);
        RGB color{average.r*neutral+chromatic.r*(1-neutral),average.g*neutral+chromatic.g*(1-neutral),average.b*neutral+chromatic.b*(1-neutral)};
        const double peak=std::max({color.r,color.g,color.b});
        // Bounded peak energy preserves vivid patches amongst dark pixels.
        // Uniform shades retain their original level, and a tiny highlight
        // cannot illuminate the whole border at full brightness.
        const double contrast_gain=std::min(std::sqrt(peak_square_sum/weight_sum)/(peak_sum/weight_sum),1.8);
        // Preserve the mean's peak when colors cancel. Normalizing red+cyan
        // directly to per-pixel peak energy would invent full-bright white.
        const double energy=std::max({average.r,average.g,average.b})/weight_sum*contrast_gain;
        if(peak>1e-9)result[zone]={std::clamp(color.r/peak*energy,0.0,1.0),std::clamp(color.g/peak*energy,0.0,1.0),std::clamp(color.b/peak*energy,0.0,1.0)};
    }
    return result;
}
inline Palette sample(const std::vector<RGB>& p,int w,int h,Rect r){return sample_regions<3>(p,w,h,r);}
inline GradientPalette sample_gradient(const std::vector<RGB>& p,int w,int h,Rect r){return sample_regions<gradient_segments>(p,w,h,r);}
}
