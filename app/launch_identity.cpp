#include "openvr.h"
#include <cstdio>

// Read only: current scene identity, without changing SteamVR registration.
int main() {
    vr::EVRInitError error{};
    vr::VR_Init(&error, vr::VRApplication_Background);
    if (error != vr::VRInitError_None) return 2;
    auto *apps = vr::VRApplications();
    const auto pid = apps->GetCurrentSceneProcessId();
    char key[vr::k_unMaxApplicationKeyLength]{};
    const auto result = apps->GetApplicationKeyByProcessId(pid, key, sizeof(key));
    std::printf("scene_pid=%u\nkey_status=%d\nkey=%s\n", pid, int(result), key);
    if (result == vr::VRApplicationError_None) {
        char value[4096]{};
        vr::EVRApplicationError property{};
        apps->GetApplicationPropertyString(key, vr::VRApplicationProperty_Name_String, value, sizeof(value), &property);
        std::printf("name_status=%d\nname=%s\n", int(property), value);
        apps->GetApplicationPropertyString(key, vr::VRApplicationProperty_BinaryPath_String, value, sizeof(value), &property);
        std::printf("binary_status=%d\nbinary=%s\n", int(property), value);
    }
    vr::VR_Shutdown();
    return 0;
}
