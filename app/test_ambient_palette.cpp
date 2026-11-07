#include "ambient_palette.h"
#include <iostream>
#include <stdexcept>
#include <iomanip>
#include <limits>
#include <sstream>
using namespace cinema_ambient;
static unsigned checks=0;
static void check(bool ok,const char* label){if(!ok)throw std::runtime_error(label);std::cout<<"PASS "<<label<<'\n';++checks;}
int main(){
    constexpr int w=96,h=54;std::vector<RGB> pixels(w*h,{1,0,0});
    auto area=content(pixels,w,h);auto colors=sample(pixels,w,h,area);
    check(area.w==w && area.h==h,"full-frame color retains full content bounds");
    check(std::all_of(colors.begin(),colors.end(),[](RGB p){return p.r==1 && p.g==0 && p.b==0;}),"solid red remains red in all twelve zones");
    for(int y=0;y<h;++y)for(int x=w/2;x<w;++x)pixels[y*w+x]={0,0,1};
    colors=sample(pixels,w,h,content(pixels,w,h));
    check(colors[0].r==1 && colors[2].b==1 && colors[4].b==1 && colors[10].r==1,"top and side zones preserve spatial color direction");
    check(colors[6].b==1 && colors[8].r==1,"bottom zones follow clockwise ordering");
    for(int y=0;y<h;++y)for(int x=0;x<w;++x)pixels[y*w+x]=(y<6 || y>=h-6)?RGB{}:RGB{0,1,0};
    area=content(pixels,w,h);colors=sample(pixels,w,h,area);
    check(area.y==6 && area.h==h-12,"symmetric letterbox bars are excluded");
    check(colors[1].g==1 && colors[7].g==1,"top and bottom glow uses picture color behind letterboxing");
    for(int y=0;y<h;++y)for(int x=0;x<w;++x)pixels[y*w+x]=(x<9 || x>=w-9)?RGB{}:RGB{0,1,0};
    area=content(pixels,w,h);check(area.x==9 && area.w==w-18,"pillarbox bars are excluded");
    pixels.assign(w*h,{});area=content(pixels,w,h);colors=sample(pixels,w,h,area);
    check(area.w==w && area.h==h && colors[0].r==0,"black scene stays black without inventing a crop or fallback color");
    pixels.assign(w*h,{.5,.5,.5});colors=sample(pixels,w,h,content(pixels,w,h));
    check(std::abs(colors[0].r-.214041)<.00001,"color averages use linear light rather than encoded sRGB");
    check(content({},w,h).w==0,"invalid pixel buffers cannot be sampled");
    pixels.assign(w*h,{});
    for(int y=h/3;y<2*h/3;++y)for(int x=w/3;x<2*w/3;++x)pixels[y*w+x]={1,0,0};
    colors=sample(pixels,w,h,{0,0,w,h});
    check(std::all_of(colors.begin(),colors.end(),[](RGB p){return p.r==0 && p.g==0 && p.b==0;}),"bright centre does not recolor unrelated dark edges");
    pixels.assign(w*h,{0,0,1});
    for(int y=0;y<10;++y)for(int x=0;x<w;++x)pixels[y*w+x]={1,0,0};
    colors=sample(pixels,w,h,{0,0,w,h});
    check(colors[1].r>.999 && colors[1].b==0 && colors[7].b>.999,"red edge remains red beside a contrasting blue interior");
    pixels.assign(w*h,{});
    for(int y=0;y<10;++y)for(int x=32;x<40;++x)pixels[y*w+x]={1,0,0};
    colors=sample(pixels,w,h,{0,0,w,h});
    check(colors[1].r>.44 && colors[1].r<.46 && colors[1].g==0 && colors[1].b==0,"quarter-zone color remains vivid with bounded dark-pixel compensation");
    pixels.assign(w*h,{1,.32,.035});
    colors=sample(pixels,w,h,{0,0,w,h});
    check(std::abs(colors[1].g-linear(.32))<1e-8 && std::abs(colors[1].b-linear(.035))<1e-8,"solid orange keeps its hue instead of per-channel RMS hue shift");
    for(int y=5;y<7;++y)for(int x=32;x<64;++x)pixels[y*w+x]={1,1,1};
    colors=sample(pixels,w,h,{0,0,w,h});
    check(colors[1].r>.999 && colors[1].g<.15 && colors[1].b<.08,"white caption stripe does not wash out a substantial orange edge");
    pixels.assign(w*h,{1,1,1});
    for(int x=32;x<36;++x)pixels[x]={1,0,0};
    colors=sample(pixels,w,h,{0,0,w,h});
    check(colors[1].g>.92 && colors[1].b>.92,"rare colored pixels do not tint a mostly neutral region strongly");
    pixels.assign(w*h,{.01,.015,.04});colors=sample(pixels,w,h,{0,0,w,h});
    check(std::abs(colors[1].b-linear(.04))<1e-8 && colors[1].b<.004,"dark uniform color receives no automatic exposure lift");
    pixels.assign(w*h,{});pixels[32]={1,1,1};colors=sample(pixels,w,h,{0,0,w,h});
    check(colors[1].r<.03 && colors[1].r==colors[1].g,"one white pixel contributes less than 3% in the smaller edge region");
    pixels.assign(w*h,{});
    for(int y=0;y<10;++y)for(int x=32;x<64;++x)pixels[y*w+x]=x<48?RGB{1,0,0}:RGB{0,1,1};
    colors=sample(pixels,w,h,{0,0,w,h});
    check(std::abs(colors[1].r-.5)<1e-8 && std::abs(colors[1].g-.5)<1e-8 && std::abs(colors[1].b-.5)<1e-8,"complementary colors mix without inventing full-bright white");
    for(int y=0;y<10;++y)for(int x=32;x<64;++x)pixels[y*w+x]=(x-32)%3==0?RGB{1,0,0}:((x-32)%3==1?RGB{0,1,0}:RGB{0,0,1});
    colors=sample(pixels,w,h,{0,0,w,h});
    check(std::abs(colors[1].r-11.0/32)<1e-8 && std::abs(colors[1].b-10.0/32)<1e-8,"mixed primaries keep their linear mean energy");
    RGB previous{};bool continuous=true;
    for(int step=0;step<=32;++step){
        for(int y=0;y<10;++y)for(int x=32;x<64;++x)pixels[y*w+x]=x-32<step?RGB{1,0,0}:RGB{0,1,1};
        colors=sample(pixels,w,h,{0,0,w,h});
        if(step)continuous=continuous && std::abs(colors[1].r-previous.r)<.04 && std::abs(colors[1].g-previous.g)<.04;
        previous=colors[1];
    }
    check(continuous,"moving complementary split changes smoothly without a winning-hue jump");
    colors=sample(pixels,w,h,{-1,0,w,h});
    check(colors[0].r==0,"out-of-buffer crop is rejected");
    for(int y=0;y<h;++y)for(int x=0;x<w;++x)pixels[y*w+x]=y<h/2?(x<w/2?RGB{1,0,0}:RGB{0,1,0}):(x<w/2?RGB{1,1,0}:RGB{0,0,1});
    colors=sample(pixels,w,h,{0,0,w,h});
    check(colors[0].r==1 && colors[2].g==1 && colors[3].g==1 && colors[5].b==1 && colors[6].b==1 && colors[8].r==1 && colors[8].g==1 && colors[9].g==1 && colors[11].g==0,"four distinct corners retain clockwise top/right/bottom/left order");
    ContentTracker tracker;
    for(int y=0;y<h;++y)for(int x=0;x<w;++x)pixels[y*w+x]=(y<6 || y>=h-6)?RGB{}:RGB{0,0,1};
    area=tracker.update(pixels,w,h);
    check(area.h==h,"a single dark-border frame does not change the crop");
    tracker.update(pixels,w,h);area=tracker.update(pixels,w,h);
    check(area.y==6 && area.h==42,"consistent letterboxing acquires after three samples");
    for(int x=32;x<64;++x)pixels[50*w+x]={1,1,1};
    for(int i=0;i<30;++i)area=tracker.update(pixels,w,h);
    colors=sample(pixels,w,h,area);
    check(area.y==6 && area.h==42 && colors[1].b>.999 && colors[7].b>.999,"localized subtitle in a proven bar does not dim the unchanged picture edges");
    for(int y=0;y<h;++y)for(int x=0;x<w;++x)pixels[y*w+x]=(y<6 || y>=h-6)?RGB{.026,.026,.026}:RGB{0,0,1};
    for(int i=0;i<30;++i)area=tracker.update(pixels,w,h);
    check(area.y==6 && area.h==42,"near-black border threshold noise does not toggle an acquired crop");
    for(int y=0;y<h;++y)for(int x=0;x<w;++x)pixels[y*w+x]=(y<6 || y>=h-6)?RGB{}:RGB{0,0,1};
    for(int x=0;x<w;++x){pixels[3*w+x]={.026,.026,.026};pixels[50*w+x]={.026,.026,.026};}
    for(int i=0;i<4;++i)area=tracker.update(pixels,w,h);
    check(area.y==6 && area.h==42,"partial crop expansion caused by dark threshold noise retains proven bars");
    for(int x=0;x<w;++x){pixels[5*w+x]={0,0,1};pixels[48*w+x]={0,0,1};pixels[3*w+x]={};pixels[50*w+x]={};}
    for(int i=0;i<3;++i)area=tracker.update(pixels,w,h);
    check(area.y==5 && area.h==44,"genuine one-row thinner bars release even when total dark coverage remains high");
    pixels.assign(w*h,{0,1,0});area=tracker.update(pixels,w,h);
    check(area.h==44,"one full-frame transition is held before changing aspect");
    tracker.update(pixels,w,h);area=tracker.update(pixels,w,h);
    check(area.h==h && area.y==0,"genuine full-frame aspect change releases old bars within three samples");
    for(int y=0;y<h;++y)for(int x=0;x<w;++x)pixels[y*w+x]=(y<6 || y>=h-6)?RGB{}:RGB{0,0,1};
    for(int i=0;i<3;++i)tracker.update(pixels,w,h);
    tracker.reset();area=tracker.update(pixels,w,h);
    check(area.h==h,"new source or window size explicitly clears previous crop history");
    tracker.reset();
    for(int y=0;y<h;++y)for(int x=0;x<w;++x)pixels[y*w+x]=(x<9 || x>=w-9)?RGB{}:RGB{0,0,1};
    for(int i=0;i<3;++i)area=tracker.update(pixels,w,h);
    for(int y=0;y<h;++y){pixels[y*w+4]={.026,.026,.026};pixels[y*w+91]={.026,.026,.026};}
    for(int i=0;i<4;++i)area=tracker.update(pixels,w,h);
    check(area.x==9 && area.w==78,"partial pillarbox expansion receives the same temporal protection");
    for(int y=0;y<h;++y){pixels[y*w+8]={0,0,1};pixels[y*w+87]={0,0,1};pixels[y*w+4]={};pixels[y*w+91]={};}
    for(int i=0;i<3;++i)area=tracker.update(pixels,w,h);
    check(area.x==8 && area.w==80,"genuine one-column thinner pillarboxing releases promptly");
    const int gw=256,gh=256;
    std::vector<RGB> fine(gw*gh);
    for(int y=0;y<gh;++y)for(int x=0;x<gw;++x)fine[y*gw+x]={double(y/4)/63.,.2,1.-double(y/4)/63.};
    const auto gradient=sample_gradient(fine,gw,gh,{0,0,gw,gh});
    check(gradient.size()==256,"gradient retains 64 independent regions per edge");
    bool ordered=true;
    for(int i=0;i<64;++i){
        const auto a=gradient[64+i],b=gradient[255-i];
        ordered=ordered&&std::abs(a.r-linear(double(i)/63.))<1e-8&&std::abs(a.b-linear(1.-double(i)/63.))<1e-8&&std::abs(a.r-b.r)<1e-8;
    }
    check(ordered,"all 64 side samples retain distinct values and clockwise orientation");
    pixels.assign(w*h,{.03,.03,.03});
    auto dark_gradient=sample_gradient(pixels,w,h,{0,0,w,h});
    check(std::all_of(dark_gradient.begin(),dark_gradient.end(),[](RGB c){return std::abs(c.r-linear(.03))<1e-8&&c.r==c.g&&c.g==c.b;}),"subpixel regions preserve dark neutral color when picture height is below64");
    for(int y=0;y<gh;++y)for(int x=0;x<gw;++x)fine[y*gw+x]={double(y%2),double(y%2),double(y%2)};
    const auto striped=sample_gradient(fine,gw,gh,{0,0,gw,gh});
    check(std::all_of(striped.begin()+64,striped.begin()+128,[](RGB c){return std::abs(c.r-std::sqrt(.5))<1e-8;}),"fine regions average all source pixels rather than aliasing alternating rows");
    auto narrow=sample_gradient(std::vector<RGB>(15,{.2,.4,.6}),5,3,{1,1,3,1});
    check(std::all_of(narrow.begin(),narrow.end(),[](RGB c){return std::abs(c.b-linear(.6))<1e-8;}),"one-row crop remains bounded and supplies every region");
    const auto sum=sample_regions<32>(fine,gw,gh,{0,0,gw,gh});
    check(std::abs(sum[32].r-striped[64].r)<1e-8,"32 and64 regions preserve equal energy on identical stripe distributions");
    for(auto dims:std::array<std::pair<int,int>,2>{{{192,108},{384,108}}}){
        const int mw=dims.first,mh=dims.second;double least=1e9,most=0;bool stable=true;
        std::vector<RGB> point(mw*mh);
        for(int y=40;y<60;++y){
            std::fill(point.begin(),point.end(),RGB{});point[y*mw+mw-1]={1,0,0};
            auto p=sample_gradient(point,mw,mh,{0,0,mw,mh});double energy=0,moment=0;
            for(int i=0;i<64;++i){energy+=p[64+i].r;moment+=p[64+i].r*(i+.5)*mh/64.;}
            least=std::min(least,energy);most=std::max(most,energy);
            stable=stable&&energy>0&&std::abs(moment/energy-(y+.5))<1.0;
        }
        check(stable&&most/least<1.06,"moving single-pixel edge highlight retains bounded energy and position across region boundaries");
    }
    std::vector<RGB> cropped(384*216);cropped[90*384+383]={0,0,1};
    double previous_energy=0;bool crop_phase=true;
    for(int top=53;top<=55;++top){
        auto p=sample_gradient(cropped,384,216,{0,top,384,108});double total=0,moment=0;
        for(int i=0;i<64;++i){total+=p[64+i].b;moment+=p[64+i].b*(top+(i+.5)*108./64.);}
        crop_phase=crop_phase&&total>0&&std::abs(moment/total-90.5)<1.0&&(!previous_energy||std::abs(total/previous_energy-1)<.06);previous_energy=total;
    }
    check(crop_phase,"one-row crop phase changes preserve a fixed highlight's energy and world-image position");
    std::stringstream wire;wire<<std::setprecision(std::numeric_limits<double>::max_digits10)<<1790630000.75;
    double timestamp=0;wire>>timestamp;
    check(timestamp==1790630000.75,"epoch timestamp retains subsecond freshness across the wire");
    std::cout<<"AMBIENT_PALETTE_OK "<<checks<<'\n';return 0;
}
