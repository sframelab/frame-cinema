#include "scene_placement.h"
#include "stereo/stereo_policy.h"
#include "screen_layout.h"
#include <cassert>
#include <iostream>
using namespace cinema_placement;
static bool decode(float width){
    std::ostringstream wire;wire<<"FCPL2 alpine-test 1 2 3 100.5 1 "<<width<<" 0 0 1";
    auto h=identity(),s=identity();h.m[1][3]=1.65;s.m[1][3]=5;s.m[2][3]=-26;
    write_matrix(wire,h);write_matrix(wire,s);Packet p;std::istringstream in(wire.str());return read(in,p);
}
int main(){
    assert(decode(3.2)&&decode(4.2)&&decode(5.4));
    assert(decode(3.2f*50/7)&&decode(30)&&decode(5.4f*50/7));
    assert(!decode(40.01)&&!decode(1.9)&&!decode(INFINITY));
    for(float width:{3.2f,4.2f,5.4f,22.857f,30.f,38.571f})
        for(int mode:{1,2,3})assert(cinema_stereo::safe_disparity(mode,width,.064f)*width<=.064f*.851f);
    auto near_screen=identity(),far_screen=identity();near_screen.m[1][3]=2.1;near_screen.m[2][3]=-4.5;
    far_screen.m[1][3]=5;far_screen.m[2][3]=-26;
    auto a=cinema_layout::keyboard_pose(near_screen,4.2),b=cinema_layout::keyboard_pose(far_screen,30);
    assert(distance(a,b)<.00001 && std::abs(b.m[1][3]-1.05)<.00001 && std::abs(b.m[2][3]+1.7)<.00001);
    std::cout<<"PASS near and far screen wire bounds; excessive/nonfinite sizes rejected\n";
}
