// Development-only GPU acquisition probe; never writes a producer's image,
// changes overlay flags/visibility, posts input, or saves desktop pixels.
#include <vulkan/vulkan.h>
#include "scene_owner_contract.h"
#include <filesystem>
#include <fstream>
#include <cstdlib>
#include "openvr.h"
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

static void checked(VkResult r, const char* operation) {
    if(r!=VK_SUCCESS) throw std::runtime_error(std::string(operation)+":"+std::to_string(r));
}
static std::vector<std::string> split(const std::vector<char>& data) {
    std::istringstream in(data.empty()?"":data.data());
    std::vector<std::string> result; std::string s;
    while(in>>s) result.push_back(s);
    return result;
}
static std::vector<const char*> pointers(const std::vector<std::string>& names) {
    std::vector<const char*> result;
    for(const auto& s:names) result.push_back(s.c_str());
    return result;
}
int main(int argc,char** argv) {
    if(argc!=3)return 2;
    const auto scene_pid=uint32_t(std::strtoul(argv[2],nullptr,10));
    std::string key;
    cinema_scene_owner::Lease lease;
    for(const auto& file:std::filesystem::directory_iterator(argv[1])){
        if(file.path().extension()!=".lease")continue;
        std::ifstream input(file.path());
        if(cinema_scene_owner::read_lease(input,lease)&&lease.creator.pid==scene_pid){
            key=cinema_scene_owner::key(lease.request,cinema_scene_owner::Role::Screen);break;
        }
    }
    if(key.empty())return 2;
    VkInstance instance{}; VkDevice device{}; bool initialized=false, acquired=false;
    vr::VROverlayView_t view{};
    int result=1, nonnull=0;
    try {
        vr::EVRInitError error{};
        vr::VR_Init(&error,vr::VRApplication_Background);
        if(error!=vr::VRInitError_None) throw std::runtime_error("vr_init:"+std::to_string(error));
        initialized=true;
        if(vr::VRApplications()->GetCurrentSceneProcessId()!=scene_pid)throw std::runtime_error("scene_changed");
        auto* overlay=vr::VROverlay(); auto* viewer=vr::VROverlayView();
        if(!viewer) throw std::runtime_error("overlay_view_unavailable");
        vr::VROverlayHandle_t handle{};
        if(overlay->FindOverlay(key.c_str(),&handle)!=vr::VROverlayError_None)
            throw std::runtime_error("source_absent");
        if(handle!=lease.handles[0].value)throw std::runtime_error("lease_mismatch");
        uint32_t flags=0;
        if(overlay->GetOverlayFlags(handle,&flags)!=vr::VROverlayError_None ||
           (flags & vr::VROverlayFlags_ProtectedContent) || !viewer->IsViewingPermitted(handle))
            throw std::runtime_error("source_not_viewable");
        auto renderer=overlay->GetOverlayRenderingPid(handle);
        auto* compositor=vr::VRCompositor();
        std::vector<char> ext(compositor->GetVulkanInstanceExtensionsRequired(nullptr,0));
        if(!ext.empty()) compositor->GetVulkanInstanceExtensionsRequired(ext.data(),ext.size());
        auto names=split(ext);auto extensions=pointers(names);
        VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
        app.pApplicationName="Frame Cinema Steam view probe";app.apiVersion=VK_API_VERSION_1_1;
        VkInstanceCreateInfo ci{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
        ci.pApplicationInfo=&app;ci.enabledExtensionCount=extensions.size();ci.ppEnabledExtensionNames=extensions.data();
        checked(vkCreateInstance(&ci,nullptr,&instance),"create_instance");
        uint64_t output=0;vr::VRSystem()->GetOutputDevice(&output,vr::TextureType_Vulkan,instance);
        VkPhysicalDevice physical=reinterpret_cast<VkPhysicalDevice>(output);
        if(!physical) throw std::runtime_error("no_runtime_device");
        uint32_t count=0;vkGetPhysicalDeviceQueueFamilyProperties(physical,&count,nullptr);
        std::vector<VkQueueFamilyProperties> families(count);
        vkGetPhysicalDeviceQueueFamilyProperties(physical,&count,families.data());
        uint32_t family=0;
        while(family<count && !(families[family].queueFlags&VK_QUEUE_GRAPHICS_BIT)) ++family;
        if(family==count) throw std::runtime_error("no_graphics_queue");
        ext.resize(compositor->GetVulkanDeviceExtensionsRequired(physical,nullptr,0));
        if(!ext.empty()) compositor->GetVulkanDeviceExtensionsRequired(physical,ext.data(),ext.size());
        names=split(ext); extensions=pointers(names);
        float priority=1;
        VkDeviceQueueCreateInfo qi{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
        qi.queueFamilyIndex=family;qi.queueCount=1;qi.pQueuePriorities=&priority;
        VkDeviceCreateInfo di{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
        di.queueCreateInfoCount=1;di.pQueueCreateInfos=&qi;
        di.enabledExtensionCount=extensions.size();di.ppEnabledExtensionNames=extensions.data();
        checked(vkCreateDevice(physical,&di,nullptr,&device),"create_device");
        VkQueue queue{};vkGetDeviceQueue(device,family,0,&queue);
        vr::VRVulkanDevice_t vk{instance,device,physical,queue,family};
        vr::VRNativeDevice_t native{&vk,vr::DeviceType_Vulkan};
        for(int i=0;i<6;++i) {
            vr::VROverlayHandle_t current{};
            uint32_t currentFlags=0;
            if(vr::VRApplications()->GetCurrentSceneProcessId()!=scene_pid || overlay->FindOverlay(key.c_str(),&current)!=vr::VROverlayError_None || current!=handle ||
               overlay->GetOverlayRenderingPid(handle)!=renderer ||
               overlay->GetOverlayFlags(handle,&currentFlags)!=vr::VROverlayError_None ||
               (currentFlags&vr::VROverlayFlags_ProtectedContent) || !viewer->IsViewingPermitted(handle))
                throw std::runtime_error("source_changed_or_revoked");
            acquired=true;
            auto e=viewer->AcquireOverlayView(handle,&native,&view,sizeof(view));
            if(e!=vr::VROverlayError_None) throw std::runtime_error("acquire:"+std::to_string(e));
            if(view.texture.handle) {
                if(view.texture.eType!=vr::TextureType_Vulkan) throw std::runtime_error("unexpected_texture_type");
                auto* t=static_cast<vr::VRVulkanTextureData_t*>(view.texture.handle);
                ++nonnull;
                std::printf("{\"sample\":%d,\"width\":%u,\"height\":%u,\"format\":%u,\"non_null\":true,\"color_space\":%d,\"bounds\":[%.5f,%.5f,%.5f,%.5f]}\n",i,t->m_nWidth,t->m_nHeight,t->m_nFormat,int(view.texture.eColorSpace),view.textureBounds.uMin,view.textureBounds.vMin,view.textureBounds.uMax,view.textureBounds.vMax);
            } else std::printf("{\"sample\":%d,\"non_null\":false}\n",i);
            std::this_thread::sleep_for(std::chrono::milliseconds(160));
        }
        result=0;
    } catch(const std::exception& e) { std::printf("{\"error\":\"%s\"}\n",e.what()); }
    const VkResult idle=device?vkDeviceWaitIdle(device):VK_SUCCESS;
    const auto release=acquired?vr::VROverlayView()->ReleaseOverlayView(&view):vr::VROverlayError_None;
    if(idle!=VK_SUCCESS || release!=vr::VROverlayError_None) result=1;
    if(initialized) vr::VR_Shutdown();
    if(device) vkDestroyDevice(device,nullptr);
    if(instance) vkDestroyInstance(instance,nullptr);
    std::printf("{\"acquisition_ok\":%s,\"non_null_samples\":%d,\"pixel_advancement_tested\":false,\"cleanup\":{\"wait_idle\":%d,\"release_view\":%d}}\n",result==0?"true":"false",nonnull,int(idle),int(release));
    return result;
}
