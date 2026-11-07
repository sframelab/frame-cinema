#pragma once
#include "openvr.h"
#include "native_ui_channel.h"
#include "shortcut_edge.h"
#include <array>
#include <chrono>
#include <filesystem>
// An overlay action set keeps Cinema shortcuts available while Steam owns the
// laser. Never bind trigger/system inputs or accept held buttons on activation.
class NativeShortcuts {
    vr::VRActionSetHandle_t set=0;
    std::array<vr::VRActionHandle_t,8> actions{};
    std::array<ShortcutEdge,8> edges{};
    vr::VRInputValueHandle_t right_path=0;
    uint32_t right_device=vr::k_unTrackedDeviceIndexInvalid;
    std::string right_model;
    std::chrono::steady_clock::time_point last{};
public:
    void start(NativeUIChannel* channel){
        const auto manifest=(std::filesystem::read_symlink("/proc/self/exe").parent_path()/"actions.json").string();
        int error=int(vr::VRInput()->SetActionManifestPath(manifest.c_str()));
        if(!error)error=int(vr::VRInput()->GetActionSetHandle("/actions/cinema",&set));
        const char* names[]={"right_a","right_b","left_a","left_b","right_stick","left_stick","right_grip","left_grip"};
        for(size_t i=0;!error&&i<actions.size();++i)error=int(vr::VRInput()->GetActionHandle((std::string("/actions/cinema/in/")+names[i]).c_str(),&actions[i]));
        channel->shortcut_error.store(error,std::memory_order_release);
        if(error)set=0;
        vr::VRInput()->GetInputSourceHandle("/user/hand/right",&right_path);
    }
    void poll(NativeUIChannel* channel){
        auto now=std::chrono::steady_clock::now();if(now-last<std::chrono::milliseconds(4))return;last=now;
        const bool permitted=!vr::VROverlay()->IsDashboardVisible()&&vr::VRApplications()->GetCurrentSceneProcessId()==channel->parent;
        vr::VRActiveActionSet_t active{};active.ulActionSet=set;
        int error=set?int(vr::VRInput()->UpdateActionState(&active,sizeof(active),permitted?1:0)):int(vr::VRInputError_InvalidHandle);
        if(!permitted){for(auto& edge:edges)edge.sample(0,false);channel->shortcut_error.store(error==vr::VRInputError_NoActiveActionSet?0:error,std::memory_order_release);channel->shortcut_active.store(0,std::memory_order_release);return;}
        // Steam's native laser consumes A/Home and B/Back action states. Read
        // only those two physical button components from its installed model.
        // This neither rebinds Steam nor reads the trigger or system button.
        auto* system=vr::VRSystem();auto* models=vr::VRRenderModels();
        auto device=system->GetTrackedDeviceIndexForControllerRole(vr::TrackedControllerRole_RightHand);
        vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount]{};
        system->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,0,poses,vr::k_unMaxTrackedDeviceCount);
        const bool tracked=device<vr::k_unMaxTrackedDeviceCount&&system->GetTrackedDeviceClass(device)==vr::TrackedDeviceClass_Controller&&poses[device].bDeviceIsConnected&&poses[device].bPoseIsValid&&poses[device].eTrackingResult==vr::TrackingResult_Running_OK;
        char model[512]{};
        if(tracked)system->GetStringTrackedDeviceProperty(device,vr::Prop_RenderModelName_String,model,sizeof(model));
        if(device!=right_device||right_model!=model){right_device=device;right_model=model;edges[0].sample(0,false);edges[1].sample(0,false);}
        int first_error=error;
        unsigned mask=0,components=0;
        for(size_t i=0;i<actions.size();++i){
            vr::InputDigitalActionData_t value{};
            int read=error?error:int(vr::VRInput()->GetDigitalActionData(actions[i],&value,sizeof(value),vr::k_ulInvalidInputValueHandle));
            if(read&&!first_error)first_error=read;
            unsigned source=(!read&&value.bActive)?1:0;bool pressed=value.bState;
            if(i<2){
                vr::RenderModel_ControllerMode_State_t mode{};vr::RenderModel_ComponentState_t component{};
                if(tracked&&right_path&&model[0]&&models->GetComponentStateForDevicePath(model,i==0?"button_a":"button_b",right_path,&mode,&component)){
                    source=2;pressed=(component.uProperties&vr::VRComponentProperty_IsPressed)!=0;components|=1u<<i;
                }else if(!tracked)source=0;
            }
            if(source)mask|=1u<<i;
            if(edges[i].sample(source,pressed)&&!vr::VROverlay()->IsDashboardVisible()&&vr::VRApplications()->GetCurrentSceneProcessId()==channel->parent)
                channel->shortcuts[i].fetch_add(1,std::memory_order_release);
        }
        channel->shortcut_error.store(first_error,std::memory_order_release);
        channel->shortcut_active.store(mask,std::memory_order_release);
        channel->shortcut_components.store(components,std::memory_order_release);
    }
};
