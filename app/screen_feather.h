#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

// Experimental narrow edge treatment. This covers an opaque compositor edge
// with a neutral feather; it does not make the underlying video transparent.
namespace cinema_feather {
constexpr int content_width=2048,content_height=1152,gutter=4;
constexpr int width=content_width+2*gutter,height=content_height+2*gutter;
inline float alpha(float x,float y) {
 const float qx=std::abs(x)-content_width*.5f,qy=std::abs(y)-content_height*.5f;
 const float distance=std::hypot(std::max(qx,0.f),std::max(qy,0.f))+std::min(std::max(qx,qy),0.f);
 // Two adjacent opaque samples straddle the original hard boundary. Their
 // bilinear interpolation fully covers it; the next sample tapers to zero.
 const float t=std::clamp((std::abs(distance)-.5f)/1.5f,0.f,1.f);
 return 1-t*t*(3-2*t);
}
inline std::vector<uint8_t> pixels() {
 std::vector<uint8_t> data(size_t(width)*height*4,0);
 for(int y=0;y<height;++y)for(int x=0;x<width;++x)
  data[(size_t(y)*width+x)*4+3]=uint8_t(std::lround(255*alpha(x+.5f-width*.5f,y+.5f-height*.5f)));
 return data;
}
}

#ifdef _OPENVR_API
class CinemaScreenFeather {
public:
 vr::VROverlayHandle_t handle=0;
 int error=0,hide_error=0;
 bool visible=false;
 template<class API> void create(API* api,const std::string& key) {
  if(handle)return;
  error=api->CreateOverlay(key.c_str(),"Cinema narrow screen feather",&handle);
  if(error)return;
  auto data=cinema_feather::pixels();
  error=api->SetOverlayRaw(handle,data.data(),cinema_feather::width,cinema_feather::height,4);
  if(!error)error=api->SetOverlayInputMethod(handle,vr::VROverlayInputMethod_None);
  if(!error)error=api->SetOverlaySortOrder(handle,11);
  if(!error)error=api->SetOverlayFlag(handle,vr::VROverlayFlags_VisibleInDashboard,true);
  if(!error)error=api->SetOverlayFlag(handle,vr::VROverlayFlags_IgnoreTextureAlpha,false);
  ready=error==0;
 }
 template<class API> void update(API* api,bool show,const vr::HmdMatrix34_t& pose,
                                 float metres,float source_aspect,float acknowledged_crop) {
  if(!handle)return;
  bool finite=true;for(const auto& row:pose.m)for(float item:row)finite=finite&&std::isfinite(item);
  if(!show||!ready||!finite||!std::isfinite(metres)||metres<=0||
     !std::isfinite(source_aspect)||source_aspect<=0||
     !std::isfinite(acknowledged_crop)||acknowledged_crop<0||acknowledged_crop>.20f) {
   hide(api);return;
  }
  // Use the native acknowledged crop, including its fail-open result. The
  // vertical feather shrinks with the picture (1.2--2 reference texels), while
  // the inside edges stay exactly on both cropped video boundaries.
  const float aspect=source_aspect*float(cinema_feather::content_height)/cinema_feather::content_width/(1-2*acknowledged_crop);
  error=0;
  if(!placed||std::memcmp(&previous,&pose,sizeof(pose))||previous_width!=metres||previous_aspect!=aspect) {
   error=api->SetOverlayTransformAbsolute(handle,vr::TrackingUniverseStanding,&pose);
   if(!error)error=api->SetOverlayWidthInMeters(handle,metres*float(cinema_feather::width)/cinema_feather::content_width);
   if(!error)error=api->SetOverlayTexelAspect(handle,aspect);
   if(!error){previous=pose;previous_width=metres;previous_aspect=aspect;placed=true;}
   else placed=false;
  }
  if(!error&&!visible)error=api->ShowOverlay(handle);
  if(!error)visible=true;else hide(api);
 }
 template<class API> void destroy(API* api) {
  if(handle){hide(api);api->DestroyOverlay(handle);}handle=0;visible=false;ready=false;placed=false;
 }
private:
 bool ready=false,placed=false;
 vr::HmdMatrix34_t previous{};
 float previous_width=0,previous_aspect=0;
 template<class API> void hide(API* api) {
  if(visible){hide_error=api->HideOverlay(handle);if(!hide_error)visible=false;}
 }
};
#endif
