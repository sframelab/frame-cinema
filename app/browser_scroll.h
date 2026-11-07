#pragma once
#include "scene_owner_adapter.h"
#include <algorithm>
#include <cmath>
struct SmoothBrowserScroll {
    double total_x=0,total_y=0,x=0,y=0;
    uint64_t sequence=0,epoch=0;
    bool dirty=false,active=false;
    void cancel(){if(!active)return;active=false;total_x=total_y=0;++epoch;dirty=true;}
    void add(double dx,double dy,int px,int py,int width,int height){
        if(!std::isfinite(dx)||!std::isfinite(dy)||width<1||height<1||px<0||py<0||px>=width||py>=height)return;
        total_x+=std::clamp(dx,-3.,3.)*120.;total_y-=std::clamp(dy,-3.,3.)*120.;
        x=(px+.5)/width;y=(py+.5)/height;dirty=true;active=true;
    }
    void flush(const std::string& ipc){
        if(!dirty)return;
        dirty=false;
        std::ostringstream out;out.precision(17);
        out<<"{\"producer\":"<<getpid()<<",\"sequence\":"<<++sequence<<",\"created\":"<<cinema_scene_owner::wall_now()
           <<",\"epoch\":"<<epoch<<",\"cancelled\":"<<(active?"false":"true")
           <<",\"x\":"<<x<<",\"y\":"<<y<<",\"total_x\":"<<total_x<<",\"total_y\":"<<total_y<<"}";
        cinema_scene_owner::private_write(ipc+"/browser-scroll.json",out.str());
    }
};
