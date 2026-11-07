#include "openvr.h"
#include <cstdio>
#include <cstring>

int main(int argc, char** argv) {
    vr::EVRInitError error = vr::VRInitError_None;
    vr::VR_Init(&error, vr::VRApplication_Background);
    if (error != vr::VRInitError_None) {
        std::printf("{\"init_error\":%d}\n", int(error));
        return 1;
    }
    vr::VROverlayHandle_t panel = 0;
    auto overlay = vr::VROverlay();
    std::printf("{\"scene_pid\":%u,\"scene_state\":%d,\"dashboard_visible\":%s}\n",
        vr::VRApplications()->GetCurrentSceneProcessId(),
        int(vr::VRApplications()->GetSceneApplicationState()),
        overlay->IsDashboardVisible() ? "true" : "false");
    auto found = overlay->FindOverlay(argc == 2 && std::strcmp(argv[1], "--screen") == 0 ? "frame-lab.cinema.screen" : "frame-lab.cinema.video", &panel);
    uint32_t width = 0, height = 0, flags = 0;
    if (found == vr::VROverlayError_None) {
        const auto texture_error = overlay->GetOverlayTextureSize(panel, &width, &height);
        overlay->GetOverlayFlags(panel, &flags);
        std::printf("{\"found\":true,\"visible\":%s,\"width\":%u,\"height\":%u,\"flags\":%u,\"renderer_pid\":%u,\"texture_error\":%d}\n",
            overlay->IsOverlayVisible(panel) ? "true" : "false", width, height, flags,
            overlay->GetOverlayRenderingPid(panel), int(texture_error));
        if (argc == 2 && std::strcmp(argv[1], "--present") == 0) {
            vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount]{};
            vr::VRSystem()->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding, 0, poses, vr::k_unMaxTrackedDeviceCount);
            auto transform = poses[0].mDeviceToAbsoluteTracking;
            for (int i = 0; i < 3; ++i) transform.m[i][3] -= transform.m[i][2] * 3.5f;
            auto position = overlay->SetOverlayTransformAbsolute(panel, vr::TrackingUniverseStanding, &transform);
            auto interaction = overlay->SetOverlayFlag(panel, vr::VROverlayFlags_MakeOverlaysInteractiveIfVisible, true);
            auto shown = overlay->ShowOverlay(panel);
            std::printf("{\"position_error\":%d,\"interaction_error\":%d,\"show_error\":%d,\"visible\":%s}\n",
                        int(position), int(interaction), int(shown), overlay->IsOverlayVisible(panel) ? "true" : "false");
        }
    } else std::printf("{\"find_error\":%d}\n", int(found));
    vr::VR_Shutdown();
    return found == vr::VROverlayError_None ? 0 : 2;
}
