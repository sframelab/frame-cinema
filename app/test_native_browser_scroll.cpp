#include "native_browser_scroll.h"
#include <cassert>
#include <limits>
#include <vector>
#include <utility>
#include <iostream>
int main(){
    NativeBrowserScroll scroll;
    std::vector<std::pair<int,int>> positions;
    std::vector<std::pair<double,double>> events;
    bool available=true;
    auto position=[&](int x,int y){positions.emplace_back(x,y);return available;};
    auto post=[&](double x,double y){events.emplace_back(x,y);};
    auto send=[&](uint64_t window,int x,int y,double dx,double dy,double age,double now){
        return scroll.send(window,x,y,1600,900,dx,dy,age,now,position,post);
    };
    assert(send(1,100,100,.01,-.1,0,1));
    assert(positions.size()==1&&events.size()==1&&events.back().first==.01);
    assert(send(1,400,100,0,-.1,.01,1.014)&&positions.size()==1);
    assert(send(1,500,100,0,.1,0,1.028)&&events.back().second==.1&&positions.size()==1);
    assert(!send(1,500,100,0,.1,.101,1.04)&&events.size()==3);
    assert(!send(1,-1,100,0,.1,0,1.05));
    assert(!send(1,100,100,std::numeric_limits<double>::quiet_NaN(),.1,0,1.05));
    assert(!send(1,100,100,0,0,0,1.05));
    assert(send(1,500,200,0,-.1,0,1.2)&&positions.back()==std::make_pair(500,200));
    scroll.cancel();assert(send(1,700,200,0,-.1,0,1.21)&&positions.back().first==700);
    assert(send(2,800,200,0,-.1,0,1.22)&&scroll.target==2&&positions.back().first==800);
    const auto sent=events.size();available=false;
    assert(!send(3,800,200,0,-.1,0,1.23)&&scroll.target==0&&events.size()==sent);
    available=true;assert(send(3,800,200,4,-4,0,1.24)&&events.back()==std::make_pair(3.,-3.));
    assert(!send(3,800,200,0,.1,-1,1.25));
    assert(send(3,850,200,0,.1,0,.5)&&positions.back().first==850);
    std::cout<<"PASS native gesture: fractional axes, jitter latch, reverse, stale/invalid events, idle, cancel, window replacement, placement failure, bounds, clock reset\n";
}
