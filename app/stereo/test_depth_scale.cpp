#include "stereo_depth.h"
#include <cassert>
#include <cstdio>
using namespace cinema_stereo;
int main(){
    DepthScale s;std::vector<float> a(400),b(400);
    for(int i=0;i<400;++i){a[i]=float(i)/399;b[i]=1-a[i];}
    s.normalize(a,1,10,20,20);s.normalize(b,1,10+1./30,20,20);
    assert(a.front()==0&&a.back()==1&&b.front()==1&&b.back()==0);
    // Same-frame geometry reverses immediately; no old silhouette is blended.
    assert(a[100]<.3&&b[100]>.7);
    std::vector<float> uncertain(400,5);s.normalize(uncertain,1,10+2./30,20,20);
    for(float v:uncertain)assert(v==.5f);
    std::vector<float> flat(400,5);s.normalize(flat,2,11,20,20);
    for(float v:flat)assert(v==.5f);
    std::vector<float> cropped(400,1000);
    for(int y=5;y<15;++y)for(int x=0;x<20;++x)cropped[y*20+x]=float(x)/19;
    s.normalize(cropped,3,12,20,20,1,.5);
    assert(cropped[10*20]==0&&cropped[10*20+19]==1);
    bool rejected=false;cropped[0]=NAN;try{s.normalize(cropped,4,13,20,20);}catch(...){rejected=true;}assert(rejected);
    std::vector<unsigned char> blue(128),green(128);
    for(int i=0;i<128;i+=4){blue[i+2]=255;green[i+1]=255;blue[i+3]=green[i+3]=255;}
    assert(frame_difference(blue,green)>.6&&frame_difference(blue,blue)==0);
    puts("depth scale: current geometry, cut reset, padding exclusion and nonfinite rejection passed");
}
