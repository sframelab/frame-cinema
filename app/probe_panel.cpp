#include "openvr.h"
#include "scene_owner_contract.h"
#include <filesystem>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <vector>
#include <thread>
#include <chrono>
int main(int argc,char**argv){
 if(argc!=4)return 2;
 vr::EVRInitError e{};vr::VR_Init(&e,vr::VRApplication_Background);if(e)return 3;
 auto*o=vr::VROverlay();auto*c=vr::VRCompositor();
 const auto pid=uint32_t(std::strtoul(argv[1],nullptr,10));
 if(vr::VRApplications()->GetCurrentSceneProcessId()!=pid){vr::VR_Shutdown();return 4;}
 vr::VROverlayHandle_t p=0;
 for(const auto& file:std::filesystem::directory_iterator(argv[3])){
  if(file.path().extension()!=".lease")continue;
  std::ifstream input(file.path());cinema_scene_owner::Lease lease;
  if(cinema_scene_owner::read_lease(input,lease)&&lease.creator.pid==pid){
   auto key=cinema_scene_owner::key(lease.request,cinema_scene_owner::Role::Screen);
   if(!o->FindOverlay(key.c_str(),&p)&&p==lease.handles[0].value)break;p=0;
  }
 }
 if(!p){vr::VR_Shutdown();return 5;}
 float width=0;vr::HmdMatrix34_t pose{};vr::ETrackingUniverseOrigin origin{};uint32_t w=0,h=0;
 auto ew=o->GetOverlayWidthInMeters(p,&width);auto ep=o->GetOverlayTransformAbsolute(p,&origin,&pose);auto et=o->GetOverlayTextureSize(p,&w,&h);
 std::printf("{\"width\":%.6f,\"position\":[%.6f,%.6f,%.6f],\"visible\":%s,\"errors\":[%d,%d,%d],\"texture\":[%u,%u],",width,pose.m[0][3],pose.m[1][3],pose.m[2][3],o->IsOverlayVisible(p)?"true":"false",int(ew),int(ep),int(et),w,h);
 std::printf("\"mirror_used\":false,\"mirror_restored\":true}\n");
 vr::VR_Shutdown();return ew||ep?6:0;
}
