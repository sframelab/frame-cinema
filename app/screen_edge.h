#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace cinema_edge {
constexpr int content_width=2048, content_height=1152, gutter=8;
constexpr int width=content_width+2*gutter, height=content_height+2*gutter;
inline float smooth(float a,float b,float x) {
    const float t=std::clamp((x-a)/(b-a),0.f,1.f);
    return t*t*(3.f-2.f*t);
}
inline float alpha(float x,float y) {
    const float qx=std::abs(x)-content_width*.5f;
    const float qy=std::abs(y)-content_height*.5f;
    const float d=std::hypot(std::max(qx,0.f),std::max(qy,0.f))+std::min(std::max(qx,qy),0.f);
    // Cover the opaque compositor boundary; feather into the image and into
    // the scenery. The centre stays transparent and input geometry is unchanged.
    return smooth(-6.f,-2.f,d)*(1.f-smooth(2.f,6.f,d));
}
inline std::vector<uint8_t> pixels() {
    std::vector<uint8_t> result(size_t(width)*height*4,0);
    for(int y=0;y<height;++y)for(int x=0;x<width;++x)
        result[(size_t(y)*width+x)*4+3]=uint8_t(std::lround(255*alpha(x+.5f-width*.5f,y+.5f-height*.5f)));
    return result;
}
}

#ifdef _OPENVR_API
class CinemaScreenEdge {
public:
    vr::VROverlayHandle_t handle=0;
    int error=0;
    int hide_error=0;
    bool visible=false;
    void create(vr::IVROverlay* api,const std::string& key) {
        error=api->CreateOverlay(key.c_str(),"Cinema screen edge",&handle);
        if(error)return;
        auto data=cinema_edge::pixels();
        error=api->SetOverlayRaw(handle,data.data(),cinema_edge::width,cinema_edge::height,4);
        if(!error)error=api->SetOverlayInputMethod(handle,vr::VROverlayInputMethod_None);
        if(!error)error=api->SetOverlaySortOrder(handle,11);
        if(!error)error=api->SetOverlayFlag(handle,vr::VROverlayFlags_VisibleInDashboard,true);
        ready=error==0;
    }
    template<class Api> void update(Api* api,bool show,const vr::HmdMatrix34_t& pose,float metres) {
        if(!handle)return;
        if(!show || !ready) { hide(api);return; }
        error=0;
        if(!placed || std::memcmp(&previous,&pose,sizeof(pose)) || previous_width!=metres) {
            error=api->SetOverlayTransformAbsolute(handle,vr::TrackingUniverseStanding,&pose);
            if(!error)error=api->SetOverlayWidthInMeters(handle,metres*float(cinema_edge::width)/cinema_edge::content_width);
            if(!error){previous=pose;previous_width=metres;placed=true;}
            else placed=false;
        }
        if(!error && !visible)error=api->ShowOverlay(handle);
        if(!error)visible=true;
        else hide(api);
    }
    void destroy(vr::IVROverlay* api) { if(handle)api->DestroyOverlay(handle);handle=0;visible=false; }
private:
    vr::HmdMatrix34_t previous{};
    float previous_width=0;
    bool placed=false;
    bool ready=false;
    template<class Api> void hide(Api* api) {
        if(visible){hide_error=api->HideOverlay(handle);if(!hide_error)visible=false;}
    }
};
#endif
