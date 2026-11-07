#pragma once
#include "scene_placement.h"
#include "controller_stereo_contract.h"
#include <array>
#include <cmath>

namespace cinema_controller_quad {
struct Vec {double x=0,y=0,z=0;};
inline Vec add(Vec a,Vec b){return {a.x+b.x,a.y+b.y,a.z+b.z};}
inline Vec sub(Vec a,Vec b){return {a.x-b.x,a.y-b.y,a.z-b.z};}
inline Vec mul(Vec a,double s){return {a.x*s,a.y*s,a.z*s};}
inline double dot(Vec a,Vec b){return a.x*b.x+a.y*b.y+a.z*b.z;}
inline Vec cross(Vec a,Vec b){return {a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
inline double length(Vec a){return std::sqrt(dot(a,a));}
inline bool finite(Vec a){return std::isfinite(a.x)&&std::isfinite(a.y)&&std::isfinite(a.z);}
inline Vec origin(const vr::HmdMatrix34_t& m){return {m.m[0][3],m.m[1][3],m.m[2][3]};}
inline Vec transform(const vr::HmdMatrix34_t& m,Vec p){return {
 m.m[0][0]*p.x+m.m[0][1]*p.y+m.m[0][2]*p.z+m.m[0][3],
 m.m[1][0]*p.x+m.m[1][1]*p.y+m.m[1][2]*p.z+m.m[1][3],
 m.m[2][0]*p.x+m.m[2][1]*p.y+m.m[2][2]*p.z+m.m[2][3]};}
struct View {
 vr::HmdMatrix34_t pose{},inverse{};
 vr::HmdMatrix44_t projection{};
 vr::VROverlayProjection_t tangent{};
};
// Physical lower-left, lower-right, upper-left corners and an eye origin.
// View axes come from the plane, not an assumed symmetric HMD projection.
inline bool derive(Vec lower_left,Vec lower_right,Vec upper_left,Vec eye,double near_z,double far_z,View& result){
 if(!finite(lower_left)||!finite(lower_right)||!finite(upper_left)||!finite(eye)
    ||!std::isfinite(near_z)||!std::isfinite(far_z)||near_z<=0||far_z<=near_z)return false;
 Vec right=sub(lower_right,lower_left),up=sub(upper_left,lower_left);
 const double width=length(right),height=length(up);
 if(width<1e-5||height<1e-5)return false;
 right=mul(right,1/width);up=mul(up,1/height);
 if(std::abs(dot(right,up))>1e-5)return false;
 const Vec normal=cross(right,up),a=sub(lower_left,eye),b=sub(lower_right,eye),c=sub(upper_left,eye);
 const double distance=-dot(a,normal);
 if(!std::isfinite(distance)||distance<near_z)return false;
 const double left=dot(right,a)/distance,right_t=dot(right,b)/distance;
 const double bottom=dot(up,a)/distance,top=dot(up,c)/distance;
 result={};result.pose={{{float(right.x),float(up.x),float(normal.x),float(eye.x)},
                       {float(right.y),float(up.y),float(normal.y),float(eye.y)},
                       {float(right.z),float(up.z),float(normal.z),float(eye.z)}}};
 result.inverse=cinema_placement::inverse(result.pose);
 auto& p=result.projection;
 p.m[0][0]=float(2/(right_t-left));p.m[0][2]=float((right_t+left)/(right_t-left));
 p.m[1][1]=float(2/(top-bottom));p.m[1][2]=float((top+bottom)/(top-bottom));
 p.m[2][2]=float(-(far_z+near_z)/(far_z-near_z));p.m[2][3]=float(-2*far_z*near_z/(far_z-near_z));p.m[3][2]=-1;
 result.tangent.fLeft=float(left);result.tangent.fRight=float(right_t);result.tangent.fTop=float(bottom);result.tangent.fBottom=float(top);
 return cinema_placement::rigid(result.pose)&&cinema_controller_stereo::projection_valid(p,result.tangent);
}
inline bool project(const View& view,Vec point,double& u,double& v){
 const Vec local=transform(view.inverse,point);if(!finite(local)||local.z>=-.03)return false;
 const auto& p=view.projection;
 const double w=-local.z;
 u=.5+.5*(p.m[0][0]*local.x+p.m[0][2]*local.z)/w;
 v=.5+.5*(p.m[1][1]*local.y+p.m[1][2]*local.z)/w;
 return std::isfinite(u)&&std::isfinite(v);
}
// One SBS overlay owns both eye images. Any failed stage revokes both hands.
template<class Show,class Hide,class Clear>
cinema_controller_stereo::Ownership present(bool eligible,const std::array<bool,2>& hands,bool submitted,Show show,Hide hide,Clear clear){
 cinema_controller_stereo::Ownership result;
 if(eligible&&(hands[0]||hands[1])&&submitted&&show()){result.active=true;result.hand=hands;return result;}
 const bool hidden=hide(),cleared=clear();result.cleanup_ok=hidden&&cleared;return result;
}
}
