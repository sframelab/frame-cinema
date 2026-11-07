// Read-only comparison of our browser ray plane with the runtime overlay.
#include "openvr.h"
#include <cstdio>
#include <cmath>
int main() {
    vr::EVRInitError error{};vr::VR_Init(&error,vr::VRApplication_Background);
    if (error) return 2;
    auto* overlays=vr::VROverlay();vr::VROverlayHandle_t panel=0;
    if (overlays->FindOverlay("frame-lab.cinema.screen",&panel)) { vr::VR_Shutdown();return 3; }
    vr::HmdMatrix34_t transform{};vr::ETrackingUniverseOrigin origin{};
    float width=0,aspect=0;vr::HmdVector2_t mouse{};vr::VRTextureBounds_t bounds{};
    const auto transform_error=overlays->GetOverlayTransformAbsolute(panel,&origin,&transform);
    const auto width_error=overlays->GetOverlayWidthInMeters(panel,&width);
    const auto aspect_error=overlays->GetOverlayTexelAspect(panel,&aspect);
    const auto mouse_error=overlays->GetOverlayMouseScale(panel,&mouse);
    const auto bounds_error=overlays->GetOverlayTextureBounds(panel,&bounds);
    std::printf("{\"width\":%.6f,\"texel_aspect\":%.6f,\"mouse_scale\":[%.3f,%.3f],\"bounds\":[%.6f,%.6f,%.6f,%.6f],\"errors\":[%d,%d,%d,%d,%d]}\n",
        width,aspect,mouse.v[0],mouse.v[1],bounds.uMin,bounds.vMin,bounds.uMax,bounds.vMax,
        int(transform_error),int(width_error),int(aspect_error),int(mouse_error),int(bounds_error));
    if (transform_error || width_error || mouse_error || mouse.v[0]<=0 || mouse.v[1]<=0) { vr::VR_Shutdown();return 4; }
    for (float u : {.05f,.5f,.95f}) for (float v : {.05f,.5f,.95f}) {
        const float local[3]={(u-.5f)*width,(.5f-v)*width*mouse.v[1]/mouse.v[0],1.f};
        vr::VROverlayIntersectionParams_t ray{};ray.eOrigin=origin;
        for (int i=0;i<3;++i) {
            ray.vSource.v[i]=transform.m[i][3];ray.vDirection.v[i]=-transform.m[i][2];
            for (int j=0;j<3;++j) ray.vSource.v[i]+=transform.m[i][j]*local[j];
        }
        vr::VROverlayIntersectionResults_t result{};
        const bool hit=overlays->ComputeOverlayIntersection(panel,&ray,&result);
        std::printf("{\"browser_uv\":[%.4f,%.4f],\"hit\":%s,\"runtime_uv\":[%.6f,%.6f],\"distance\":%.6f}\n",
            u,v,hit?"true":"false",result.vUVs.v[0],result.vUVs.v[1],result.fDistance);
    }
    for (float u : {0.f,1.f}) for (float v : {0.f,1.f}) {
        vr::HmdMatrix34_t point{};vr::HmdVector2_t uv{{u,v}};
        const auto status=overlays->GetTransformForOverlayCoordinates(panel,origin,uv,&point);
        float local[3]{};
        for (int i=0;i<3;++i) for (int j=0;j<3;++j) local[i]+=transform.m[j][i]*(point.m[j][3]-transform.m[j][3]);
        std::printf("{\"coordinate\":[%.1f,%.1f],\"error\":%d,\"local\":[%.6f,%.6f,%.6f]}\n",u,v,int(status),local[0],local[1],local[2]);
    }
    vr::VR_Shutdown();return 0;
}
