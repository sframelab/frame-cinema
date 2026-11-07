#include "openvr.h"
#include <cstdio>
int main(){
    vr::EVRInitError e{};vr::VR_Init(&e,vr::VRApplication_Background);if(e)return 1;
    bool paused=vr::VRSettings()->GetBool("power","pauseCompositorOnStandby");
    std::printf("{\"steamvr\":\"%s\",\"pause_compositor_on_standby\":%s}\n",vr::VRSystem()->GetRuntimeVersion(),paused?"true":"false");
    vr::VR_Shutdown();
}
