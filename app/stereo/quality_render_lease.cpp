// Bound an off-head browser refresh; restore the runtime setting on EOF or timeout.
#include "openvr.h"
#include <chrono>
#include <csignal>
#include <cstdio>
#include <poll.h>
#include <unistd.h>
#include <cstdlib>
#include <fstream>
#include <iomanip>

static volatile std::sig_atomic_t stopped=0;
static void stop(int) {stopped=1;}

int main() {
    std::signal(SIGINT,stop);std::signal(SIGTERM,stop);std::signal(SIGHUP,stop);
    vr::EVRInitError init{};
    vr::VR_Init(&init,vr::VRApplication_Background);
    if(init) return 2;
    auto* settings=vr::VRSettings();
    vr::EVRSettingsError error{};
    const bool original=settings->GetBool("power","pauseCompositorOnStandby",&error);
    if(error) {vr::VR_Shutdown();return 3;}
    settings->SetBool("power","pauseCompositorOnStandby",false,&error);
    if(error) {vr::VR_Shutdown();return 4;}
    std::printf("{\"lease_started\":true,\"original_pause\":%s}\n",original?"true":"false");
    std::fflush(stdout);
    std::ofstream metrics;
    if(const char* path=std::getenv("FRAME_CINEMA_XR_METRICS")){metrics.open(path);metrics<<"time,frame,presents,mis_presents,dropped,reprojection,scene_gpu_ms,compositor_gpu_ms,display_hz\n";}
    uint32_t previous_frame=0;
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(1300);
    while(!stopped && std::chrono::steady_clock::now()<deadline) {
        pollfd input{STDIN_FILENO,POLLIN|POLLHUP,0};
        if(poll(&input,1,5)>0) break; // Release message or owning process exited.
        if(metrics){vr::Compositor_FrameTiming t{};t.m_nSize=sizeof(t);
            if(vr::VRCompositor()->GetFrameTiming(&t)&&t.m_nFrameIndex!=previous_frame){
                previous_frame=t.m_nFrameIndex;
                double now=std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
                metrics<<std::setprecision(17)<<now<<','<<t.m_nFrameIndex<<','<<t.m_nNumFramePresents<<','<<t.m_nNumMisPresented<<','<<t.m_nNumDroppedFrames<<','<<t.m_nReprojectionFlags<<','<<t.m_flPreSubmitGpuMs<<','<<t.m_flCompositorRenderGpuMs<<','<<vr::VRSystem()->GetFloatTrackedDeviceProperty(0,vr::Prop_DisplayFrequency_Float)<<'\n';metrics.flush();
            }
        }
    }
    settings->SetBool("power","pauseCompositorOnStandby",original,&error);
    const bool restored=!error && settings->GetBool("power","pauseCompositorOnStandby")==original;
    std::printf("{\"restored\":%s,\"pause_on_standby\":%s}\n",restored?"true":"false",original?"true":"false");
    vr::VR_Shutdown();return restored?0:5;
}

