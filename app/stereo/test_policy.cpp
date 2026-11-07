#include "stereo_policy.h"
#include <cassert>
#include <sstream>
#include <cstdio>
using namespace cinema_stereo;
int main(){
    auto read=[](const char* text){std::istringstream s(text);return Control::read(s,"scene","source",100);};
    auto c=read("FCST1 scene source 100 2 1 7");assert(c.eligible&&c.revision==7);
    for(auto text:{"FCST1 wrong source 100 2 1 7","FCST1 scene wrong 100 2 1 7","FCST1 scene source 99 2 1 7","FCST1 scene source 101 2 1 7","FCST1 scene source 100 4 1 7","FCST1 scene source 100 2 2 7","FCST1 scene source 100 2 1 7 trailing","FCST1 scene source 100 0 1 7"})assert(!read(text).eligible);
    assert(present(c,true,true,false,false,7,7,99.9,100));
    assert(!present(c,false,true,false,false,7,7,99.9,100));
    assert(!present(c,true,false,false,false,7,7,99.9,100));
    assert(!present(c,true,true,true,false,7,7,99.9,100));
    assert(!present(c,true,true,false,true,7,7,99.9,100));
    assert(!present(c,true,true,false,false,8,7,99.9,100));
    assert(!present(c,true,true,false,false,7,7,99.7,100));
    assert(!fresh(NAN,100,1));assert(!fresh(100,INFINITY,1));
    assert(disparity(0)==0&&disparity(1)<disparity(2)&&disparity(2)<disparity(3));
    for(float width:{3.2f,4.2f,5.4f})for(float ipd:{.05f,.064f,.085f})for(int mode:{1,2,3}){
        const float amount=safe_disparity(mode,width,ipd);
        assert(amount<=disparity(mode)&&amount*width<=.85f*ipd+.000001f);
    }
    assert(safe_disparity(2,NAN,.064f)==0&&safe_disparity(2,0,.064f)==0);
    assert(safe_disparity(3,5.4f,NAN)*5.4f<=.85f*.05f+.000001f);
    auto video=[](const char* text){std::istringstream in(text);return VideoFrame::read(in,"scene","source",100);};
    assert(video("FCVF1 scene source 100 123:1 2 8 4.2 99.99 0 0").sequence==2);
    assert(video("FCVF1 scene source 100 123:1 2 8 4.2 95 1 0").paused);
    for(auto text:{"FCVF1 other source 100 123:1 2 8 4.2 99.99 0 0","FCVF1 scene wrong 100 123:1 2 8 4.2 99.99 0 0","FCVF1 scene source 98 123:1 2 8 4.2 99.99 0 0","FCVF1 scene source 100 123:1 0 8 4.2 99.99 0 0","FCVF1 scene source 100 invalid 2 8 4.2 99.99 0 0","FCVF1 scene source 100 123:1 2 8 4.2 99.99 2 0","FCVF1 scene source 100 123:1 2 8 4.2 99.99 0 0 extra"})assert(!video(text).sequence);
    puts("stereo policy: ownership, freshness, focus, dashboard, revision and strength passed");
}
