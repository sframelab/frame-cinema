#include "scene_placement.h"
#include "screen_layout.h"
#include <cassert>
#include <cmath>
#include <iostream>
using namespace cinema_placement;
bool decode(float width){
    std::ostringstream wire;wire<<"FCPL2 distant-test 1 2 3 100.5 1 "<<width<<" 0 0 1";
    auto m=identity();write_matrix(wire,m);write_matrix(wire,m);Packet p;std::istringstream in(wire.str());return read(in,p);
}
int main(){
    assert(cinema_layout::pointer_reach(5600)==5600&&cinema_layout::pointer_reach(8000)==5600&&cinema_layout::pointer_reach(10)==10);
    for(float nominal:{3.2f,4.2f,5.4f}){
        const float centre=std::hypot(3600.f,.45f*3600/104),seated=std::hypot(4.5f,.45f);
        float width=nominal*centre/seated;
        assert(decode(width));assert(std::abs(width/centre-nominal/seated)<1e-6);
        auto screen=identity();screen.m[1][3]=1.65f+.45f*3600/104;screen.m[2][3]=-3600;
        assert(screen.m[1][3]-width*9/32>-1280);
        assert(std::abs((screen.m[1][3]-1.65f)/3600-.45f/104)<1e-6);
        assert(std::hypot(3600.f,std::hypot(width*.5f,width*9/32))<cinema_layout::pointer_reach(5600));
        auto keyboard=cinema_layout::keyboard_pose(screen,width);
        assert(std::abs(keyboard.m[1][3]-1.05)<.001&&std::abs(keyboard.m[2][3]+1.7)<.001);
        auto seat=identity();float a=.73f;seat.m[0][0]=seat.m[2][2]=std::cos(a);seat.m[0][2]=std::sin(a);seat.m[2][0]=-std::sin(a);seat.m[0][3]=2.8f;
        auto actual=cinema_layout::keyboard_pose(multiply(seat,screen),width),near=identity();near.m[1][3]=1.05f;near.m[2][3]=-1.7f;
        assert(distance(actual,multiply(seat,near))<.001);
    }
    assert(decode(3.2)&&decode(4.2)&&decode(5.4)&&!decode(5000.1)&&!decode(1.9)&&!decode(INFINITY));
    std::cout<<"PASS distant screen projection ratio, water clearance, keyboard for all sizes\n";
}
