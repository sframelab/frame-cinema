#pragma once
#include "scene_placement.h"
#include "pose_history.h"
#include <time.h>
// Same timed pose/standing-space protocol as panel_host. No second scene,
// recenter implementation, or fixed-head fallback is introduced here.
struct NativePlacement {
    cinema_placement::Bridge bridge;
    cinema_placement::PoseHistory history;
    cinema_placement::Matrix raw{};
    uint64_t universe=0;bool known=false,ready=false;
    std::string ipc;
    static int64_t ns(){timespec t{};clock_gettime(CLOCK_MONOTONIC,&t);return int64_t(t.tv_sec)*1000000000+t.tv_nsec;}
    NativePlacement(const std::string& session,const std::string& location):bridge(session,location+"/placement-map.txt"),ipc(location){rebase(false);}
    bool rebase(bool changed){
        vr::ETrackedPropertyError error{};
        auto id=vr::VRSystem()->GetUint64TrackedDeviceProperty(0,vr::Prop_CurrentUniverseId_Uint64,&error);
        auto next=vr::VRSystem()->GetRawZeroPoseToStandingAbsoluteTrackingPose();
        bool valid=!error&&id&&cinema_placement::rigid(next);
        bool preserve=!changed&&known&&valid&&id==universe&&bridge.rebase(cinema_placement::multiply(next,cinema_placement::inverse(raw)));
        raw=next;universe=id;known=valid;history.clear();return preserve;
    }
    void tick(double now){
        vr::VREvent_t event{};
        while(vr::VRSystem()->PollNextEvent(&event,sizeof(event))){
            if(event.eventType==vr::VREvent_StandingZeroPoseReset || event.eventType==vr::VREvent_ChaperoneUniverseHasChanged){
                if(!rebase(event.eventType==vr::VREvent_ChaperoneUniverseHasChanged))bridge.invalidate(now);
            }
        }
        vr::TrackedDevicePose_t pose{};auto before=ns();
        vr::VRSystem()->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,0,&pose,1);auto after=ns();
        if(after-before<=2000000)history.add(before+(after-before)/2,pose);else history.clear();
        cinema_placement::Packet packet;std::ifstream file(ipc+"/placement.txt");ready=false;
        if(!cinema_placement::read(file,packet))return;
        bool synchronized=false;
        if(packet.pose_time_ns>0){
            double seconds=double(packet.pose_time_ns-ns())*1e-9;
            if(seconds>=0&&seconds<=.08){vr::VRSystem()->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,float(seconds),&pose,1);synchronized=true;}
            else synchronized=history.at(packet.pose_time_ns,pose);
            if(!synchronized)pose.bPoseIsValid=false;
        }
        ready=bridge.update(packet,pose,now,synchronized);
    }
};
