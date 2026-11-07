#include <tuple>
#include "overlay_projection.h"
#include "screen_layout.h"
#include <cassert>
#include <cstdio>
#include <iostream>
int main(){
 using namespace cinema_placement;
 for(float range:{250.f,1800.f,3600.f})for(float yaw:{0.f,.9f,-2.f})for(float width:{2560.f,3360.f,4320.f}){
  auto room=identity();room.m[0][0]=room.m[2][2]=std::cos(yaw);room.m[0][2]=std::sin(yaw);room.m[2][0]=-std::sin(yaw);
  room.m[0][3]=2;room.m[1][3]=.3f;room.m[2][3]=-1;
  auto local=identity();local.m[1][3]=1.65f+.45f*3600.f/104.f;local.m[2][3]=-3600;
  auto screen=multiply(room,local);auto rendered=cinema_projection::browser(screen,width,range);
  auto seated=identity();seated.m[1][3]=1.65f;auto eye=multiply(room,seated);
  assert(rendered.projected&&std::abs(rendered.width/range-width/3600)<1e-6);
  for(int i=0;i<3;++i)assert(std::abs((rendered.pose.m[i][3]-eye.m[i][3])-(screen.m[i][3]-eye.m[i][3])*range/3600)<.01);
  if(range==3600.f)assert(distance(rendered.pose,screen)<.01);
  auto keyboard=cinema_layout::keyboard_pose(screen,width);auto key=identity();key.m[1][3]=1.05f;key.m[2][3]=-1.7f;
  assert(distance(keyboard,multiply(room,key))<.001);
 }
 auto ordinary=identity();ordinary.m[2][3]=-4.5f;
 for(float w:{3.2f,4.2f,5.4f}){auto p=cinema_projection::browser(ordinary,w);assert(!p.projected&&p.width==w&&distance(p.pose,ordinary)==0);}
 // The device file tunes the range; missing or out-of-bounds values keep 3600 m.
 assert(cinema_projection::range_from("/nonexistent/overlay-distance.txt")==3600.f);
 for(auto [text,expected]:{std::pair{"2400\n",2400.f},{"100",100.f},{"50",50.f},{"40",3600.f},{"9000",3600.f},{"far",3600.f}}){
  std::FILE* f=std::fopen("range-test.txt","w");std::fputs(text,f);std::fclose(f);
  assert(cinema_projection::range_from("range-test.txt")==expected);
 }
 std::remove("range-test.txt");
 // Scene debug row: "<distance> <size>"; invalid values are ignored.
 for(auto [text,ok,distance,size]:{std::tuple{"600 0.25",true,600.f,.25f},{"3600 1",true,3600.f,1.f},{"600 2",false,0.f,0.f},{"20 1",false,0.f,0.f},{"far",false,0.f,0.f}}){
  std::FILE* f=std::fopen("debug-test.txt","w");std::fputs(text,f);std::fclose(f);
  cinema_projection::Tuning value{0,0};
  assert(cinema_projection::debug_from("debug-test.txt",value)==ok);
  if(ok)assert(value.distance==distance&&value.size==size);
 }
 std::remove("debug-test.txt");
 {auto local=identity();local.m[1][3]=1.65f+.45f*3600.f/104.f;local.m[2][3]=-3600;
  auto half=cinema_projection::browser(local,3360,600,.25f);assert(std::abs(half.width-3360*600/3600*.25f)<1e-3);}

 std::cout<<"PROJECTION_OK range "<<cinema_projection::range()<<" m; angular size, direction, recenter, near keyboard, ordinary rooms, range file\n";
}
