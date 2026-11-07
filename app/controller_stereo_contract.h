#pragma once
#include "scene_placement.h"
#include <array>
#include <cmath>

namespace cinema_controller_stereo {
using Matrix=vr::HmdMatrix34_t;
inline bool tracked_pose(const vr::TrackedDevicePose_t& pose) {
    return pose.bPoseIsValid&&pose.bDeviceIsConnected&&pose.eTrackingResult==vr::TrackingResult_Running_OK
        &&cinema_placement::rigid(pose.mDeviceToAbsoluteTracking);
}
inline bool projection_valid(const vr::HmdMatrix44_t& matrix,const vr::VROverlayProjection_t& raw) {
    for(const auto& row:matrix.m)for(float value:row)if(!std::isfinite(value))return false;
    if(!std::isfinite(raw.fLeft)||!std::isfinite(raw.fRight)||!std::isfinite(raw.fTop)||!std::isfinite(raw.fBottom))return false;
    return raw.fRight-raw.fLeft>1e-5f&&raw.fBottom-raw.fTop>1e-5f
        &&std::abs(matrix.m[0][0])>1e-6f&&std::abs(matrix.m[1][1])>1e-6f&&std::abs(matrix.m[3][2])>1e-6f;
}
inline bool model_pose_valid(const Matrix& local,const vr::HmdMatrix44_t& projection,
                             const std::array<float,3>& low,const std::array<float,3>& high) {
    if(!cinema_placement::rigid(local))return false;
    for(int axis=0;axis<3;++axis)if(!std::isfinite(low[axis])||!std::isfinite(high[axis])||low[axis]>high[axis])return false;
    for(int corner=0;corner<8;++corner){
        float point[4]{local.m[0][3],local.m[1][3],local.m[2][3],1},w=0;
        for(int r=0;r<3;++r)for(int axis=0;axis<3;++axis)
            point[r]+=local.m[r][axis]*((corner&(1<<axis))?high[axis]:low[axis]);
        for(int c=0;c<4;++c)w+=projection.m[3][c]*point[c];
        if(!std::isfinite(w)||w<.035f)return false;
    }
    return true;
}
struct Ownership {
    bool active=false;
    std::array<bool,2> hand{{false,false}};
    bool cleanup_ok=true;
};
// Callbacks return success. Always attempt cleanup for both eyes, including
// when an earlier Hide or Clear fails. The caller tears down on cleanup failure.
template<class Show,class Hide,class Clear>
Ownership present_pair(bool eligible,const std::array<bool,2>& hand,const std::array<bool,2>& submitted,
                       Show show,Hide hide,Clear clear) {
    Ownership result;
    if(eligible&&(hand[0]||hand[1])&&submitted[0]&&submitted[1]&&show(0)&&show(1)){
        result.active=true;result.hand=hand;return result;
    }
    for(int eye=0;eye<2;++eye){
        const bool hidden=hide(eye);
        const bool cleared=clear(eye);
        result.cleanup_ok=hidden&&cleared&&result.cleanup_ok;
    }
    return result;
}
}
