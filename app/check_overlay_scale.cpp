// Check changed OpenVR dimensions on one owned, never-shown overlay.
#include "openvr.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <string>
#include <unistd.h>
int main(){
    vr::EVRInitError error{};vr::VR_Init(&error,vr::VRApplication_Overlay);assert(!error);
    auto* api=vr::VROverlay();vr::VROverlayHandle_t overlay=0;
    auto key="framecinema.scale.check."+std::to_string(getpid());
    assert(!api->CreateOverlay(key.c_str(),"Frame Cinema hidden scale check",&overlay));
    for(float width:{2560.f,3360.f,4320.f}){
        vr::HmdMatrix34_t pose{{{1,0,0,0},{0,1,0,1.65f+.45f*3600/104},{0,0,1,-3600}}},actual{};
        float measured=0;vr::ETrackingUniverseOrigin origin{};
        assert(!api->SetOverlayWidthInMeters(overlay,width));
        assert(!api->SetOverlayTransformAbsolute(overlay,vr::TrackingUniverseStanding,&pose));
        assert(!api->GetOverlayWidthInMeters(overlay,&measured)&&std::abs(width-measured)<.001);
        assert(!api->GetOverlayTransformAbsolute(overlay,&origin,&actual));
        assert(origin==vr::TrackingUniverseStanding&&std::abs(actual.m[2][3]+3600)<.001);
        assert(!api->IsOverlayVisible(overlay));
    }
    assert(!api->DestroyOverlay(overlay));vr::VR_Shutdown();
    std::puts("OPENVR_DISTANT_SCALE_OK");
}
