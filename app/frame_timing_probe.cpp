// Read-only compositor timing. Does not acquire poses, submit frames or input.
#include "openvr.h"
#include <chrono>
#include <cstdio>
#include <set>
#include <thread>
#include <cstdlib>
int main(int argc,char** argv) {
    const int seconds=argc==2?std::atoi(argv[1]):20;
    if(seconds<1 || seconds>60)return 2;
    vr::EVRInitError error=vr::VRInitError_None;
    vr::VR_Init(&error,vr::VRApplication_Background);
    if(error!=vr::VRInitError_None){std::printf("{\"init_error\":%d}\n",int(error));return 1;}
    const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(seconds);
    std::set<uint32_t> seen;
    while(std::chrono::steady_clock::now()<until) {
        vr::Compositor_FrameTiming frames[128]{};
        frames[0].m_nSize=sizeof(frames[0]);
        const auto count=vr::VRCompositor()->GetFrameTimings(frames,128);
        const bool dashboard=vr::VROverlay()->IsDashboardVisible();
        const auto scene=vr::VRApplications()->GetCurrentSceneProcessId();
        const double now=std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
        for(unsigned i=0;i<count;++i) {
            const auto& f=frames[i];if(!seen.insert(f.m_nFrameIndex).second)continue;
            std::printf("{\"observed\":%.6f,\"frame\":%u,\"time\":%.6f,\"scene_pid\":%u,\"dashboard\":%s,\"presents\":%u,\"mispresented\":%u,\"dropped\":%u,\"reprojection\":%u,\"app_gpu_ms\":%.4f,\"total_gpu_ms\":%.4f,\"compositor_gpu_ms\":%.4f,\"interval_ms\":%.4f,\"pose_valid\":%s,\"tracking\":%d}\n",now,f.m_nFrameIndex,f.m_flSystemTimeInSeconds,scene,dashboard?"true":"false",f.m_nNumFramePresents,f.m_nNumMisPresented,f.m_nNumDroppedFrames,f.m_nReprojectionFlags,f.m_flPreSubmitGpuMs,f.m_flTotalRenderGpuMs,f.m_flCompositorRenderGpuMs,f.m_flClientFrameIntervalMs,f.m_HmdPose.bPoseIsValid?"true":"false",int(f.m_HmdPose.eTrackingResult));
        }
        std::fflush(stdout);std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }
    vr::VR_Shutdown();return 0;
}
